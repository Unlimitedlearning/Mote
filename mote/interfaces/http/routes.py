"""HTTP 路由：URL → 服务调用 → JSON。

这一层只做参数校验与状态码翻译；会话读写走 `mote.services.conversation`，
列表与检索走 `mote.services.library`，设置表单走 `mote.services.settings`。
"""

import datetime
import json
import os
import re
import time
import urllib.parse

from ...core import config as config_mod
from ...core.ids import DEFAULT_SESSION, new_session_id
from ...infra import config_file
from ...infra import llm as llm_mod
from ...services import lenses as lenses_mod
from ...services import library
from ...services import settings as settings_mod
from ...services import tools as tools_mod
from ...services.conversation import Conversation
from ..web.page import PAGE
from .responses import NODE_ID, SID, attachment, decode_sid, query
from .stream import chat_params

MESSAGES_PATH = re.compile(r"/sessions/([^/]+)/messages")
TREE_PATH = re.compile(r"/sessions/([^/]+)/tree")
TITLE_PATH = re.compile(r"/sessions/([^/]+)/title")
CURSOR_PATH = re.compile(r"/sessions/([^/]+)/cursor")
MAIN_PATH = re.compile(r"/sessions/([^/]+)/main")
STOP_PATH = re.compile(r"/sessions/([^/]+)/stop")
NODE_PATH = re.compile(r"/sessions/([^/]+)/nodes/([^/]+)")
THINK_PATH = re.compile(r"/sessions/([^/]+)/thinking/([^/]+)")
EXPORT_PATH = re.compile(r"/sessions/([^/]+)/export")
SESSION_PATH = re.compile(r"/sessions/([^/]+)")


def root_of(cfg):
    return cfg.get("_memory_root") or config_mod.memory_root(cfg)


def session_view(conversation, node=None):
    """一次读盘产出消息流与分支树；思考原文不下发，展开时按节点取。

    node 非空时按该节点所在链路出视图（点分支树、删除时的当前视图），
    为空则按主分支/游标（打开会话）。
    """
    events = conversation.events()
    messages = []
    for item in conversation.conversation(node=node, events=events):
        row = dict(item)
        thinking = row.pop("thinking", "") or ""
        row["thinking_chars"] = len(thinking)
        messages.append(row)
    return {"messages": messages,
            "tree": conversation.branch_tree(events=events, node=node)}


class RoutesMixin:
    """三个 HTTP 动词的分派。"""

    # ---- 公共辅助 ------------------------------------------------------

    def _known_session(self, session_id):
        """只查目录，不扫全部会话：这个判断在每个请求上都跑，必须 O(1)。"""
        path = os.path.join(root_of(self.server.cfg), "sessions", session_id,
                            "events.jsonl")
        return os.path.isfile(path)

    def _conversation(self, session_id):
        return Conversation(root_of(self.server.cfg), session_id)

    def _reload_config(self):
        """从磁盘重新读配置并清空 agent 缓存，设置保存后立即生效。"""
        target = config_mod.config_target(self.server.cfg)
        try:
            cfg = config_file.load(target)
        except config_mod.ConfigError as err:
            return str(err)
        cfg["_memory_root"] = (self.server.cfg.get("_memory_root")
                               or config_mod.memory_root(cfg))
        self.server.cfg = cfg
        # manager 自己握着 cfg 的引用：不一起换掉，设置保存后新建的 Agent 仍读旧配置
        self.server.manager.cfg = cfg
        self.server.manager.reset()
        library.forget_cache()
        return ""

    def _test_profile(self, data):
        """用表单里的参数发一次极短请求：地址、模型名、key 有一个不对就能立刻看出来。"""
        cfg = self.server.cfg
        name = str(data.get("profile") or cfg.get("default_profile") or "local")
        saved = (cfg.get("profiles") or {}).get(name) or {}
        saved_key, _ = settings_mod.key_of(saved)
        base_url = str(data.get("base_url") or saved.get("base_url") or "").strip()
        model = str(data.get("model") or saved.get("model") or "").strip()
        key = str(data.get("api_key") or "").strip() or saved_key
        thinking = data.get("thinking")
        thinking = bool(saved.get("thinking")) if thinking is None else bool(thinking)
        if not base_url.startswith(("http://", "https://")):
            return self._json(400, {"error": "接口地址要以 http:// 或 https:// 开头"})
        if not model:
            return self._json(400, {"error": "模型名不能为空"})
        client = llm_mod.LLM(base_url=base_url, model=model, api_key=key,
                             temperature=0, max_tokens=64, timeout=20,
                             retries=0, thinking=thinking)
        started = time.time()
        try:
            reply = client.chat([{"role": "user", "content": "ping，只回两个字：可用"}])
        except llm_mod.LLMError as err:
            return self._json(200, {"ok": False, "error": str(err)[:400]})
        return self._json(200, {"ok": True, "model": model,
                                "ms": int((time.time() - started) * 1000),
                                "reply": (reply.content or "").strip()[:80],
                                "thinking_chars": len(reply.reasoning or "")})

    # ---- GET -----------------------------------------------------------

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        manager = self.server.manager
        cfg = self.server.cfg
        if path in ("/", "/index.html"):
            return self._html(PAGE)
        if path == "/health":
            mode = settings_mod.mode(cfg)
            hybrid = mode == "hybrid"
            profile = settings_mod.profile_info(cfg)
            if mode == "local":
                # 顶栏要显示真正回答的端点，而不是 default_profile 指的那朵云
                local_name = (cfg.get("hybrid") or {}).get("router_profile") or "local"
                profile = settings_mod.profile_info(cfg, local_name) or profile
            if manager.agents:
                agent = next(iter(manager.agents.values()))
                mode, hybrid = agent.default_mode, agent.hybrid_enabled
                profile = {"name": agent.profile["name"], "model": agent.profile["model"]}
            return self._json(200, {
                "ok": True, "profile": profile, "hybrid": hybrid, "mode": mode,
                "tools": tools_mod.enabled(cfg),
                "default_session": DEFAULT_SESSION,
                "needs_setup": settings_mod.needs_setup(cfg),
                "lenses": len(lenses_mod.LENSES),
                "sessions": library.session_count(root_of(cfg)),
            })
        if path == "/sessions":
            return self._json(200, {"sessions": library.list_sessions(root_of(cfg))})
        if path == "/search":
            params = query(self.path)
            text = (params.get("q") or [""])[0].strip()
            if not text:
                return self._json(400, {"error": "缺少 q"})
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            limit = max(1, min(200, limit))
            return self._json(200, library.search_sessions(root_of(cfg), text, limit=limit))
        if path == "/export":
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
            payload = library.backup(root_of(cfg))
            return self._respond(
                200, json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "application/json; charset=utf-8",
                {"Content-Disposition": attachment(f"mote-backup-{stamp}.json")})
        if path == "/settings":
            if not self._local_only():
                return self._json(403, {"error": "设置只允许在本机修改"})
            return self._json(200, settings_mod.settings_payload(cfg))
        if path == "/lenses":
            return self._json(200, {"count": len(lenses_mod.LENSES),
                                    "catalog": lenses_mod.catalog(),
                                    "lenses": lenses_mod.LENSES})
        if path == "/lens-names":
            return self._json(200, {"names": {key: item["name"]
                                              for key, item in lenses_mod.LENSES.items()}})

        match = MESSAGES_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            conversation = self._conversation(session_id)
            node = (query(self.path).get("node") or [""])[0]
            if node and not NODE_ID.fullmatch(node):
                node = ""
            view = session_view(conversation, node=node or None)
            return self._json(200, {"session": session_id, "messages": view["messages"],
                                    "tree": view["tree"]})
        match = THINK_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            node = urllib.parse.unquote(match.group(2))
            if not SID.fullmatch(session_id) or not NODE_ID.fullmatch(node):
                return self._json(400, {"error": "id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            conversation = self._conversation(session_id)
            if not conversation.has_node(node):
                return self._json(404, {"error": "分支节点不存在"})
            text = conversation.thinking_for(node)
            return self._json(200, {"session": session_id, "node": node,
                                    "text": text, "chars": len(text)})
        match = TREE_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            conversation = self._conversation(session_id)
            node = (query(self.path).get("node") or [""])[0]
            if node and not NODE_ID.fullmatch(node):
                node = ""
            return self._json(200, {"session": session_id,
                                    "tree": conversation.branch_tree(node=node or None)})
        match = EXPORT_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            params = query(self.path)
            fmt = (params.get("format") or ["md"])[0].lower()
            with_thinking = (params.get("thinking") or ["1"])[0].lower() \
                not in ("0", "false", "no")
            conversation = self._conversation(session_id)
            if fmt in ("md", "markdown"):
                return self._respond(
                    200, conversation.export_markdown(with_thinking=with_thinking),
                    "text/markdown; charset=utf-8",
                    {"Content-Disposition": attachment(conversation.export_filename("md"))})
            if fmt == "json":
                return self._respond(
                    200, json.dumps(conversation.export_payload(), ensure_ascii=False, indent=2),
                    "application/json; charset=utf-8",
                    {"Content-Disposition": attachment(conversation.export_filename("json"))})
            return self._json(400, {"error": "format 只能是 md 或 json"})
        return self._json(404, {"error": "not found"})

    # ---- POST ----------------------------------------------------------

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        manager = self.server.manager
        data = self._body()
        if data is None:
            return self._json(400, {"error": "body 必须是 JSON"})
        if not isinstance(data, dict):
            # JSON 数组或字符串也能解析成功，但后续都按对象取值，先挡住
            return self._json(400, {"error": "body 必须是 JSON 对象"})

        if path in ("/settings", "/settings/test"):
            if not self._local_only():
                return self._json(403, {"error": "设置只允许在本机修改"})
            if path == "/settings/test":
                return self._test_profile(data)
            try:
                patch = settings_mod.settings_patch(self.server.cfg, data)
            except ValueError as err:
                return self._json(400, {"error": str(err)})
            target = config_mod.config_target(self.server.cfg)
            try:
                config_file.update(target, patch)
            except (config_mod.ConfigError, OSError) as err:
                return self._json(500, {"error": f"写入配置失败：{err}"})
            problem = self._reload_config()
            if problem:
                return self._json(500, {"error": f"配置已写入但重载失败：{problem}"})
            payload = settings_mod.settings_payload(self.server.cfg)
            payload["ok"] = True
            payload["saved"] = sorted(patch)
            return self._json(200, payload)

        if path == "/sessions":
            session_id = str(data.get("id") or new_session_id()).strip()
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if self._known_session(session_id):
                return self._json(409, {"error": "会话已存在", "session": session_id})
            profile = settings_mod.profile_info(self.server.cfg) or {}
            conversation = self._conversation(session_id)
            conversation.ensure(profile=profile.get("name", ""), model=profile.get("model", ""))
            return self._json(200, {"session": session_id})

        match = TITLE_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            title = str(data.get("title") or "").strip()
            if not title:
                return self._json(400, {"error": "标题不能为空"})
            self._conversation(session_id).rename(title)
            return self._json(200, {"session": session_id, "title": title[:28]})

        match = CURSOR_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            node = str(data.get("node") or "")
            if not NODE_ID.fullmatch(node):
                return self._json(400, {"error": "分支节点 id 不合法"})
            conversation = self._conversation(session_id)
            if not conversation.set_cursor(node):
                return self._json(404, {"error": "分支节点不存在或已删除"})
            agent = manager.agents.get(session_id)
            if agent is not None and hasattr(agent, "resume"):
                with manager.lock(agent):
                    agent.resume(node)
            view = session_view(conversation, node=node)
            return self._json(200, {"session": session_id, "node": node,
                                    "messages": view["messages"], "tree": view["tree"]})

        match = MAIN_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            node = str(data.get("node") or "")
            conversation = self._conversation(session_id)
            if node:
                if not NODE_ID.fullmatch(node):
                    return self._json(400, {"error": "分支节点 id 不合法"})
                if not conversation.set_main(node):
                    return self._json(404, {"error": "分支节点不存在或已删除"})
            else:
                conversation.set_main(None)
            # tip 是界面正在看的链路：主分支只决定打开时落在哪，不能把当前视图拽走
            tip = str(data.get("tip") or "")
            if tip and not NODE_ID.fullmatch(tip):
                tip = ""
            view = session_view(conversation, node=tip or None)
            # 主分支不影响当前视图，因此不下发 messages
            return self._json(200, {"session": session_id, "main": conversation.main_node(),
                                    "tree": view["tree"]})

        match = STOP_PATH.fullmatch(path)
        if match:
            session_id = decode_sid(match)
            if not SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            agent = manager.agents.get(session_id)
            if agent is not None and hasattr(agent, "request_stop"):
                # 不取会话锁：正在进行的流持有该锁，取锁会一直等到生成结束
                agent.request_stop()
            return self._json(202, {"session": session_id, "stopping": True})

        if path == "/inbox/stream":
            return self._stream_chat(data)
        if path not in ("/chat", "/inbox"):
            return self._json(404, {"error": "not found"})
        params, error = chat_params(data)
        if error:
            return self._json(400, {"error": error})

        agent = manager.get(params["session"])
        with manager.lock(agent):
            try:
                result = agent.ask(params["message"], stream=False, parent=params["parent"],
                                   mode=params["mode"], fork=params["fork"])
            except Exception as err:
                return self._json(502, {"error": f"{type(err).__name__}: {err}"})
        return self._json(200, self._result_payload(result))

    # ---- DELETE --------------------------------------------------------

    def do_DELETE(self):
        path = urllib.parse.urlsplit(self.path).path
        node_match = NODE_PATH.fullmatch(path)
        if node_match:
            session_id = decode_sid(node_match)
            node = urllib.parse.unquote(node_match.group(2))
            if not SID.fullmatch(session_id) or not NODE_ID.fullmatch(node):
                return self._json(400, {"error": "id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            conversation = self._conversation(session_id)
            tip = (query(self.path).get("tip") or [""])[0]
            if tip and not NODE_ID.fullmatch(tip):
                tip = ""
            removed = conversation.delete_node(node, tip=tip or None)
            if removed is None:
                return self._json(404, {"error": "分支节点不存在或已删除"})
            agent = self.server.manager.agents.get(session_id)
            if agent is not None and hasattr(agent, "resume"):
                with self.server.manager.lock(agent):
                    agent.resume()
            view = session_view(conversation, node=tip or None)
            return self._json(200, {"ok": True, "session": session_id,
                                    "nodes": removed, "messages": view["messages"],
                                    "tree": view["tree"]})

        match = SESSION_PATH.fullmatch(path)
        if not match:
            return self._json(404, {"error": "not found"})
        session_id = decode_sid(match)
        if not SID.fullmatch(session_id):
            return self._json(400, {"error": "会话 id 不合法"})
        if not self._known_session(session_id):
            return self._json(404, {"error": "找不到这个会话"})
        self._conversation(session_id).store.remove()
        manager = self.server.manager
        with manager.guard:
            manager.agents.pop(session_id, None)
            manager.locks.pop(session_id, None)
        library.forget_cache()
        return self._json(200, {"ok": True, "session": session_id})
