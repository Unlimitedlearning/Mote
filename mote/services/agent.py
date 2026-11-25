"""Agent loop：通用「模型 ↔ 工具」循环。核心不认识任何具体业务。

三条路径（由 `hybrid.mode` 或单次请求的 `mode` 决定）：
- hybrid：本地 qwen 先路由/压缩/预选，简单问题本地直答，复杂问题只把压缩上下文交给 worker；
- direct：跳过本地路由，完整历史 + 尾部状态卡直接发给 worker；
- local：同样用完整历史与状态卡，但只发本机端点，构造时不建路由器。
"""

from ..core import config as config_mod
from ..core import context
from ..core import router as router_mod
from ..core.ids import new_node_id, new_session_id
from ..infra import llm as llm_mod
from . import settings as settings_mod
from . import tools as tools_mod
from .conversation import Conversation

COMPACT_NOTICE = (
    "SYSTEM NOTICE: 早前对话已被压缩以节省上下文。末尾的 [状态卡] 每轮从事件日志重建，"
    "已经包含主线、已归档的摘要、最近的工具结果与上次回答要点——直接接着做，"
    "不要重新问用户已经回答过的问题。下面若有「思考原文」，那是压缩前你的推理，"
    "用来接着验证当时那个假设，而不是从头推导。"
)


class Agent:
    def __init__(self, cfg, profile_name=None, session_id=None, memory=None,
                 llm_client=None, on_delta=None, on_event=None, on_thinking=None,
                 memory_root=None, system_prompt=None, router_client=None, hybrid=None):
        self.cfg = cfg
        self.agent_cfg = config_mod.agent_cfg(cfg)
        hybrid_cfg = dict(cfg.get("hybrid") or {})
        if isinstance(hybrid, dict):
            hybrid_cfg.update(hybrid)
        self.hybrid_cfg = hybrid_cfg
        # 显式传 hybrid 字典时以它为准；否则注入假客户端的测试自动走 legacy 路径。
        self.hybrid_enabled = (bool(hybrid_cfg.get("enabled"))
                               if hybrid is not None
                               else bool(hybrid_cfg.get("enabled")) and llm_client is None)
        self.default_mode = config_mod.mode_of(hybrid_cfg)

        if profile_name:
            worker_name = profile_name
        elif self.default_mode == "local":
            # 仅本地：提问与路由共用本地端点，不必要求 cloud profile 存在
            worker_name = hybrid_cfg.get("router_profile") or "local"
        else:
            worker_name = hybrid_cfg.get("worker_profile") if self.hybrid_enabled else None
        self.profile = self._resolve_profile(worker_name)
        self.llm = llm_client or self._build_llm(
            self.profile, role="local" if self.default_mode == "local" else "worker")
        self.router = None
        if self.hybrid_enabled:
            try:
                router_profile = settings_mod.profile(
                    cfg, hybrid_cfg.get("router_profile") or "local")
                self.router = router_client or self._build_llm(router_profile, role="router")
            except config_mod.ConfigError:
                self.router = None
                self.hybrid_enabled = False
        self.router_model = getattr(self.router, "model", "local") if self.router else "local"
        # 本地路由经验上比云端更脆：路由建不起来就按直连处理，别让人选到一个跑不通的方式
        if self.default_mode == "hybrid" and not self.router:
            self.default_mode = "direct"
        self.worker_model = self.profile["model"]
        # 按需缓存的「端点 + 客户端」：当前方式用 self 上的那一组，这里只存另一种
        self._pairs = {}

        self.tool_names = tools_mod.enabled(cfg)
        self.memory_root = memory_root or config_mod.memory_root(cfg)
        self.memory = memory or Conversation(
            self.memory_root, session_id or self.agent_cfg.get("default_session"))
        self.system_prompt = system_prompt or settings_mod.system_prompt(cfg)
        self.on_delta = on_delta
        self.on_thinking = on_thinking
        self.on_event = on_event
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.turn = self.memory.turns()
        self.current_node = self.memory.active_node()
        self.current_parent = self.memory.parent_of(self.current_node)
        self._stop_requested = False
        self.memory.ensure(profile=self.profile["name"], model=self.profile["model"])
        self._emit("session", {"session": self.memory.session_id,
                               "profile": self.profile["name"],
                               "model": self.profile["model"],
                               "mode": self.default_mode})

    def _resolve_profile(self, name):
        try:
            profile = settings_mod.profile(self.cfg, name)
        except config_mod.ConfigError:
            # 仅本地不能悄悄换成云端端点：那会把「不出本机」的承诺悄悄打破
            if self.default_mode == "local":
                raise
            return settings_mod.profile(self.cfg)
        if not self.hybrid_enabled or not name:
            return profile
        url = profile.get("base_url", "")
        if url.startswith(("http://localhost", "http://127.0.0.1")) or profile.get("api_key"):
            return profile
        fallback = self.hybrid_cfg.get("fallback_worker")
        if fallback:
            try:
                return settings_mod.profile(self.cfg, fallback)
            except config_mod.ConfigError:
                pass
        return profile

    def _build_llm(self, profile, role="worker"):
        if role == "router":
            max_tokens = int(self.hybrid_cfg.get("router_max_tokens") or 512)
            temperature = 0
        elif role == "local":
            # 仅本地回答：预算单独配，别被路由那份 JSON 预算限制
            max_tokens = int(self.hybrid_cfg.get("local_answer_max_tokens")
                             or profile.get("max_tokens", 2048))
            temperature = profile.get("temperature", 0.3)
        else:
            max_tokens = profile.get("max_tokens", 1024)
            temperature = profile.get("temperature", 0.3)
        # 思考模式只给 worker：router 要的是严格 JSON，多一段推理只会更慢更费
        thinking = bool(profile.get("thinking")) and role != "router"
        return llm_mod.LLM(
            base_url=profile["base_url"], model=profile["model"],
            api_key=profile.get("api_key") or "", temperature=temperature,
            max_tokens=max_tokens, timeout=profile.get("timeout", 180),
            thinking=thinking)

    def _pair_for(self, mode):
        """取某个方式要用的 (profile, llm)：worker 一组，仅本地一组，建一次就缓存。

        与当前方式同组时直接返回 self 上的引用——外部可能换过 llm（测试替身、/model 切换），
        缓存里的旧对象会把它盖掉。
        """
        group = "local" if mode == "local" else "worker"
        current = "local" if self.default_mode == "local" else "worker"
        if group == current:
            return self.profile, self.llm
        if group in self._pairs:
            return self._pairs[group]
        if group == "local":
            name = self.hybrid_cfg.get("router_profile") or "local"
            try:
                profile = settings_mod.profile(self.cfg, name)
            except config_mod.ConfigError as exc:
                raise config_mod.ConfigError(
                    f"配置里没有可用的本地端点（{name}），无法只用本地回答；"
                    "请先在 config.json 补上 local，或换回云端方式") from exc
            llm = self._build_llm(profile, role="local")
        else:
            profile = self._resolve_profile(self.hybrid_cfg.get("worker_profile") or "cloud")
            llm = self._build_llm(profile)
        self._pairs[group] = (profile, llm)
        return profile, llm

    def _chat(self, messages, specs, stream):
        """假客户端测试只接受 on_delta；有思维回调时才传新参数。"""
        kwargs = {"tools": specs, "stream": stream, "on_delta": self.on_delta,
                  "should_stop": lambda: self._stop_requested}
        if self.on_thinking:
            kwargs["on_thinking"] = self.on_thinking
        try:
            return self.llm.chat(messages, **kwargs)
        except TypeError:
            # 测试替身可能只实现了旧签名
            kwargs.pop("should_stop", None)
            return self.llm.chat(messages, **kwargs)

    def request_stop(self):
        """由另一个线程设置；正在进行的流式请求在下一个分片处收尾。"""
        self._stop_requested = True

    def clear_stop(self):
        self._stop_requested = False

    def ask(self, text, stream=True, parent=None, mode=None, fork=None):
        text = (text or "").strip()
        if not text:
            raise ValueError("提问不能为空")
        if mode is not None and mode not in ("direct", "hybrid", "local"):
            raise ValueError("对话模式只能是 direct、hybrid 或 local")
        if fork is not None:
            if not self.memory.is_active_node(fork):
                raise ValueError("分支节点不存在或已删除")
            parent = self.memory.parent_of(fork)
            self._rebuild_to(parent)
        elif parent is not None:
            if not self.memory.is_active_node(parent):
                raise ValueError("分支节点不存在或已删除")
            self._rebuild_to(parent)
        else:
            parent = self.memory.active_node()
        node = new_node_id()
        self.turn += 1
        self.memory.user(self.turn, text, node=node, parent=parent)
        self.messages.append({"role": "user", "content": text})
        self.current_node, self.current_parent = node, parent

        previous_hybrid = self.hybrid_enabled
        previous_llm, previous_profile = self.llm, self.profile
        previous_model = self.worker_model
        self._stop_requested = False
        target = mode or self.default_mode
        try:
            profile, llm = self._pair_for(target)
            self.profile, self.llm = profile, llm
            self.worker_model = profile["model"]
            if target == "hybrid" and self.router:
                self.hybrid_enabled, effective = True, "hybrid"
                result = self._ask_hybrid(text, stream)
            elif target == "local":
                self.hybrid_enabled, effective = False, "local"
                result = self._ask_legacy(text, stream, route="local")
            else:
                self.hybrid_enabled, effective = False, "direct"
                result = self._ask_legacy(text, stream, route="direct")
        except Exception:
            # 失败的中断不留空问答：删掉本轮节点并回退上下文
            self._discard_node(node)
            raise
        finally:
            self.hybrid_enabled = previous_hybrid
            self.llm, self.profile = previous_llm, previous_profile
            self.worker_model = previous_model
        result["mode"] = effective
        result["stopped"] = bool(result.get("stopped"))
        if result["stopped"] and not result.get("text"):
            self._discard_node(node)
            result["node"], result["parent"] = None, parent
        return result

    def _discard_node(self, node):
        """移除本轮节点并重建上下文，用于失败或空停止。"""
        self.memory.delete_node(node)
        self._rebuild_to(None)

    def _stop_early(self):
        """本地路由阶段就收到中断：不再请求 worker，直接返回空结果。"""
        return {"text": "", "steps": 0, "tools": [], "lenses": [], "candidates": [],
                "turn": self.turn, "session": self.memory.session_id,
                "node": self.current_node, "parent": self.current_parent,
                "route": "hybrid", "worker": "local", "model": self.router_model,
                "thinking": "", "stopped": True}

    def _ask_hybrid(self, text, stream):
        """一次本地调用决定：本地直答，还是压缩后交给 worker。"""
        if self._stop_requested:
            return self._stop_early()
        history = self.memory.state_card(self.agent_cfg.get("state_card_chars", 1600))
        prep = router_mod.prepare(self.cfg, text, history, self.router,
                                  allowed=self.tool_names,
                                  limit=self.hybrid_cfg.get("context_chars"))
        if self._stop_requested:
            return self._stop_early()
        self._emit("preprocess", {"route": prep["route"], "saved": prep["saved"],
                                  "fallback": prep["fallback"], "tools": prep["tools"]})

        if prep["route"] == "local" and prep["answer"]:
            answer = prep["answer"]
            if self.on_delta:
                self.on_delta(answer)
            self.memory.assistant(self.turn, answer, [],
                                  model=self.router_model, route="local",
                                  thinking=(prep.get("thinking") or None),
                                  node=self.current_node)
            self.messages.append({"role": "assistant", "content": answer})
            return {"text": answer, "steps": 0, "tools": [], "lenses": [],
                    "candidates": [], "turn": self.turn,
                    "session": self.memory.session_id,
                    "node": self.current_node, "parent": self.current_parent,
                    "route": "local", "worker": "local", "model": self.router_model,
                    "context_chars": 0, "saved_chars": prep["saved"],
                    "thinking": prep.get("thinking") or "", "fallback": prep["fallback"]}

        context_text = prep["context"] or ("当前问题：" + text)
        # 压缩上下文只管更早的背景；最近几轮必须给原文，否则「刚才那段」在请求里根本不存在
        # 条数为 0 表示不要原文（rebuild_messages(0) 会返回全部，所以这里显式短路）
        resume = int(self.agent_cfg.get("resume_messages", 8))
        recent = []
        if self.current_parent and resume > 0:
            recent = context.fit_tail(
                self.memory.rebuild_messages(resume, node=self.current_parent),
                int(self.agent_cfg.get("recent_chars", 6000)))
        base = [{"role": "system", "content": self.system_prompt},
                {"role": "system", "content": "[压缩上下文]\n" + context_text}]
        base += recent
        base.append({"role": "user", "content": text})
        specs = tools_mod.specs(prep["tools"] or self.tool_names)
        lens_state = tools_mod.new_lens_state(self.agent_cfg.get("lenses_per_turn", 5))
        max_steps = int(self.agent_cfg.get("max_steps", 12))
        used, answer, steps, tail, thinking_all = [], "", 0, [], ""
        stopped_any = interrupted_any = False

        for step in range(max_steps):
            steps = step + 1
            reply = self._chat(base + tail, specs, stream)
            if reply.reasoning:
                thinking_all += reply.reasoning
                self.memory.note_think(self.turn, reply.reasoning, node=self.current_node)
            # 流中途断开（interrupted）与用户点停止同样处理：已生成的正文留着收尾
            stopped_now = self._stop_requested or getattr(reply, "interrupted", False)
            stopped_any = stopped_any or stopped_now
            interrupted_any = interrupted_any or bool(getattr(reply, "interrupted", False))
            self.memory.assistant(self.turn, reply.content, reply.tool_calls,
                                  model=self.profile["model"], route="cloud",
                                  thinking=thinking_all or None, node=self.current_node,
                                  stopped=stopped_now)
            self.messages.append(reply.message())
            if stopped_now:
                answer = reply.content or ""
                break
            if not reply.tool_calls:
                answer = reply.content or ""
                break
            # 请求只带 base+tail：assistant 的 tool_calls 必须一起进 tail，
            # 否则下一轮只有 tool 结果、没有对应的调用消息，接口会拒绝
            tail.append(reply.message(with_reasoning=True))
            for call in reply.tool_calls:
                self._emit("tool_start", {"name": call["name"],
                                          "arguments": call["arguments"]})
                result = tools_mod.run(call["name"], call["arguments"],
                                       ctx={"lens_state": lens_state})
                used.append({"name": call["name"], "ok": result["ok"]})
                self.memory.tool(self.turn, call["name"], call["arguments"],
                                 result["text"], result["ok"])
                message = {"role": "tool", "tool_call_id": call["id"],
                           "name": call["name"], "content": result["text"]}
                tail.append(message)
                self.messages.append(message)
                self._emit("tool_end", {"name": call["name"], "ok": result["ok"],
                                        "result": result["text"]})
        else:
            answer = f"（工具调用达到上限 {max_steps} 轮，先停在这里。）"

        return {"text": answer, "steps": steps, "tools": used,
                "lenses": list(lens_state["used"]), "candidates": [],
                "turn": self.turn, "session": self.memory.session_id,
                "node": self.current_node, "parent": self.current_parent,
                "route": "cloud", "worker": self.profile["name"],
                "model": self.profile["model"],
                "stopped": stopped_any or self._stop_requested,
                "interrupted": interrupted_any,
                "context_chars": len(context_text), "saved_chars": prep["saved"],
                "thinking": thinking_all, "fallback": prep["fallback"]}

    def _ask_legacy(self, text, stream, route="direct"):
        """完整历史 + 稳定前缀 + 尾部状态卡；route 区分直连云端的回答与仅本地的回答。"""
        max_steps = int(self.agent_cfg.get("max_steps", 12))
        lens_state = tools_mod.new_lens_state(self.agent_cfg.get("lenses_per_turn", 5))
        used, answer, steps, thinking_all = [], "", 0, ""
        stopped_any = interrupted_any = False
        for step in range(max_steps):
            steps = step + 1
            self._maybe_compact()
            tail = [{"role": "system",
                     "content": self.memory.state_card(
                         self.agent_cfg.get("state_card_chars", 1600))}]
            reply = self._chat(self.messages + tail, tools_mod.specs(self.tool_names), stream)
            if reply.reasoning:
                thinking_all += reply.reasoning
                self.memory.note_think(self.turn, reply.reasoning, node=self.current_node)
            # 流中途断开与用户点停止同样处理：已生成的正文留着收尾
            stopped_now = self._stop_requested or getattr(reply, "interrupted", False)
            stopped_any = stopped_any or stopped_now
            interrupted_any = interrupted_any or bool(getattr(reply, "interrupted", False))
            self.memory.assistant(self.turn, reply.content, reply.tool_calls,
                                  model=self.profile["model"], route=route,
                                  thinking=thinking_all or None, node=self.current_node,
                                  stopped=stopped_now)
            self.messages.append(reply.message())

            if stopped_now:
                answer = reply.content or ""
                break
            if not reply.tool_calls:
                answer = reply.content or ""
                break

            for call in reply.tool_calls:
                self._emit("tool_start", {"name": call["name"],
                                          "arguments": call["arguments"]})
                result = tools_mod.run(call["name"], call["arguments"],
                                       ctx={"lens_state": lens_state})
                used.append({"name": call["name"], "ok": result["ok"]})
                self.memory.tool(self.turn, call["name"], call["arguments"],
                                 result["text"], result["ok"])
                self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                      "name": call["name"], "content": result["text"]})
                self._emit("tool_end", {"name": call["name"], "ok": result["ok"],
                                        "result": result["text"]})
        else:
            answer = f"（工具调用达到上限 {max_steps} 轮，先停在这里。可以把问题拆小一点再问。）"

        return {"text": answer, "steps": steps, "tools": used,
                "lenses": list(lens_state["used"]),
                "candidates": [],
                "turn": self.turn, "session": self.memory.session_id,
                "node": self.current_node, "parent": self.current_parent,
                "route": route, "worker": self.profile["name"],
                "model": self.profile["model"], "thinking": thinking_all,
                "stopped": stopped_any or self._stop_requested,
                "interrupted": interrupted_any}

    def state_card(self):
        return self.memory.state_card(self.agent_cfg.get("state_card_chars", 1600))

    def force_compact(self):
        return self._compact(context.context_chars(self.messages), "手动触发")

    def reset(self):
        self.memory = Conversation(self.memory_root, new_session_id())
        self.memory.ensure(profile=self.profile["name"], model=self.profile["model"])
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.turn = 0
        self.current_node = None
        self.current_parent = None
        self._emit("session", {"session": self.memory.session_id,
                               "profile": self.profile["name"],
                               "model": self.profile["model"]})

    def _rebuild_to(self, node):
        """把上下文重建到指定节点（None 表示空历史），用于切换分支或分叉。"""
        rebuilt = self.memory.rebuild_messages(
            int(self.agent_cfg.get("resume_messages", 8)), node=node)
        self.messages = [{"role": "system", "content": self.system_prompt}] + rebuilt
        self.turn = self.memory.turns()
        self.current_node = node
        self.current_parent = self.memory.parent_of(node) if node else None
        return len(rebuilt)

    def resume(self, node=None):
        if node is not None:
            if not self.memory.is_active_node(node):
                raise ValueError("分支节点不存在或已删除")
            self.memory.set_cursor(node)
        return self._rebuild_to(self.memory.active_node())

    def switch_profile(self, name):
        self.profile = settings_mod.profile(self.cfg, name)
        self.llm = self._build_llm(self.profile)
        self._emit("profile", {"profile": self.profile["name"], "model": self.profile["model"]})

    def _maybe_compact(self):
        before = context.context_chars(self.messages)
        threshold = int(self.agent_cfg.get("compact_context_chars", 24000))
        if before < threshold or len(self.messages) < 6:
            return False
        return self._compact(before, f"上下文 {before} 字 ≥ 阈值 {threshold}")

    def _compact(self, before, reason):
        keep_turns = int(self.agent_cfg.get("compact_keep_turns", 2))
        keep_tool_turns = int(self.agent_cfg.get("compact_keep_tool_turns", 3))
        keep_chars = int(self.agent_cfg.get("compact_keep_msg_chars", 3000))
        kept = context.keep_valuable_turns(self.messages, recent=keep_turns,
                                           tool_turns=keep_tool_turns)
        kept_ids = {id(msg) for msg in kept}
        dropped = [msg for msg in self.messages[1:] if id(msg) not in kept_ids]
        kept = context.trim_tool_outputs(kept, keep_chars)
        notice = COMPACT_NOTICE
        thoughts = self.memory.thoughts(int(self.agent_cfg.get("compact_thoughts", 3)),
                                        node=self.current_node)
        block = context.thought_notice(
            thoughts, int(self.agent_cfg.get("compact_thought_chars", 1200)))
        if block:
            notice += "\n\n" + block
        candidate = [self.messages[0], {"role": "user", "content": notice}] + kept
        after = context.context_chars(candidate)
        if after >= before:
            return False
        self.messages = candidate
        self.memory.compact(self.turn, before, after, len(dropped),
                            context.summarize(dropped))
        self._emit("compact", {"before": before, "after": after,
                               "dropped": len(dropped), "kept": len(kept), "reason": reason})
        return True

    def _emit(self, kind, payload):
        if self.on_event:
            self.on_event(kind, payload)
