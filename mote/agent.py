"""Agent loop：通用「模型 ↔ 工具」循环。核心不认识任何具体业务。

双轨运行：
- legacy：注入 llm_client 或关闭 hybrid 时，沿用完整历史 + 尾部状态卡；
- hybrid：本地 qwen 先路由/压缩/预选，简单问题本地直答，复杂问题只把压缩上下文交给 worker。
"""

from . import config as config_mod
from . import context
from . import llm as llm_mod
from . import memory as memory_mod
from . import preprocess
from . import tools as tools_mod

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

        worker_name = profile_name or (hybrid_cfg.get("worker_profile")
                                       if self.hybrid_enabled else None)
        self.profile = self._resolve_profile(worker_name)
        self.llm = llm_client or self._build_llm(self.profile)
        self.router = None
        if self.hybrid_enabled:
            try:
                router_profile = config_mod.profile(
                    cfg, hybrid_cfg.get("router_profile") or "local")
                self.router = router_client or self._build_llm(router_profile, role="router")
            except config_mod.ConfigError:
                self.router = None
                self.hybrid_enabled = False
        self.router_model = getattr(self.router, "model", "local") if self.router else "local"
        self.worker_model = self.profile["model"]

        self.tool_names = tools_mod.enabled(cfg)
        self.memory_root = memory_root or config_mod.memory_root(cfg)
        self.memory = memory or memory_mod.Memory(
            self.memory_root, session_id or self.agent_cfg.get("default_session"))
        self.system_prompt = system_prompt or config_mod.system_prompt(cfg)
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
                               "mode": "hybrid" if self.hybrid_enabled else "direct"})

    def _resolve_profile(self, name):
        try:
            profile = config_mod.profile(self.cfg, name)
        except config_mod.ConfigError:
            return config_mod.profile(self.cfg)
        if not self.hybrid_enabled or not name:
            return profile
        url = profile.get("base_url", "")
        if url.startswith(("http://localhost", "http://127.0.0.1")) or profile.get("api_key"):
            return profile
        fallback = self.hybrid_cfg.get("fallback_worker")
        if fallback:
            try:
                return config_mod.profile(self.cfg, fallback)
            except config_mod.ConfigError:
                pass
        return profile

    def _build_llm(self, profile, role="worker"):
        if role == "router":
            max_tokens = int(self.hybrid_cfg.get("router_max_tokens") or 512)
            temperature = 0
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
        if mode is not None and mode not in ("direct", "hybrid"):
            raise ValueError("对话模式只能是 direct 或 hybrid")
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
        node = memory_mod.new_node_id()
        self.turn += 1
        self.memory.user(self.turn, text, node=node, parent=parent)
        self.messages.append({"role": "user", "content": text})
        self.current_node, self.current_parent = node, parent

        previous_hybrid = self.hybrid_enabled
        self._stop_requested = False
        if mode == "direct":
            self.hybrid_enabled = False
        elif mode == "hybrid":
            self.hybrid_enabled = bool(self.router)
        effective = "hybrid" if self.hybrid_enabled and self.router else "direct"
        try:
            result = (self._ask_hybrid(text, stream) if effective == "hybrid"
                      else self._ask_legacy(text, stream))
        except Exception:
            # 失败的中断不留空问答：删掉本轮节点并回退上下文
            self._discard_node(node)
            raise
        finally:
            self.hybrid_enabled = previous_hybrid
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
        prep = preprocess.prepare(self.cfg, text, history, self.router,
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
        base = [{"role": "system", "content": self.system_prompt},
                {"role": "system", "content": "[压缩上下文]\n" + context_text}]
        specs = tools_mod.specs(prep["tools"] or self.tool_names)
        lens_state = tools_mod.new_lens_state(self.agent_cfg.get("lenses_per_turn", 5))
        max_steps = int(self.agent_cfg.get("max_steps", 12))
        used, answer, steps, tail, thinking_all = [], "", 0, [], ""

        for step in range(max_steps):
            steps = step + 1
            reply = self._chat(base + tail, specs, stream)
            if reply.reasoning:
                thinking_all += reply.reasoning
                self.memory.note_think(self.turn, reply.reasoning, node=self.current_node)
            stopped_now = self._stop_requested
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
                "model": self.profile["model"], "stopped": self._stop_requested,
                "context_chars": len(context_text), "saved_chars": prep["saved"],
                "thinking": thinking_all, "fallback": prep["fallback"]}

    def _ask_legacy(self, text, stream):
        """兼容路径：完整历史 + 稳定前缀 + 尾部状态卡。"""
        max_steps = int(self.agent_cfg.get("max_steps", 12))
        lens_state = tools_mod.new_lens_state(self.agent_cfg.get("lenses_per_turn", 5))
        used, answer, steps, thinking_all = [], "", 0, ""
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
            stopped_now = self._stop_requested
            self.memory.assistant(self.turn, reply.content, reply.tool_calls,
                                  model=self.profile["model"], route="direct",
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
                "route": "direct", "worker": self.profile["name"],
                "model": self.profile["model"], "thinking": thinking_all,
                "stopped": self._stop_requested}

    def state_card(self):
        return self.memory.state_card(self.agent_cfg.get("state_card_chars", 1600))

    def force_compact(self):
        return self._compact(context.context_chars(self.messages), "手动触发")

    def reset(self):
        self.memory = memory_mod.Memory(self.memory_root, memory_mod.new_session_id())
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
        self.profile = config_mod.profile(self.cfg, name)
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
