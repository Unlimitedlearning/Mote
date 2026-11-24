"""HTTP 接口：文字问题 → 镜头 → 建议。零第三方依赖。"""

import datetime
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config as config_mod
from . import lenses as lenses_mod
from . import llm as llm_mod
from . import memory as memory_mod
from . import tools as tools_mod
from .agent import Agent
from .web import PAGE

_SID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_NODE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_MESSAGES_PATH = re.compile(r"/sessions/([^/]+)/messages")
_TREE_PATH = re.compile(r"/sessions/([^/]+)/tree")
_TITLE_PATH = re.compile(r"/sessions/([^/]+)/title")
_CURSOR_PATH = re.compile(r"/sessions/([^/]+)/cursor")
_MAIN_PATH = re.compile(r"/sessions/([^/]+)/main")
_STOP_PATH = re.compile(r"/sessions/([^/]+)/stop")
_NODE_PATH = re.compile(r"/sessions/([^/]+)/nodes/([^/]+)")
_THINK_PATH = re.compile(r"/sessions/([^/]+)/thinking/([^/]+)")
_EXPORT_PATH = re.compile(r"/sessions/([^/]+)/export")
_SESSION_PATH = re.compile(r"/sessions/([^/]+)")


def _query(path):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)


def _attachment(name):
    """下载文件名：ASCII 回退名 + RFC 5987 的 UTF-8 名。"""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, "txt"
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "mote"
    return (f"attachment; filename=\"{fallback}.{ext}\"; "
            f"filename*=UTF-8''{urllib.parse.quote(name)}")



def _decode_sid(match):
    return urllib.parse.unquote(match.group(1))


def _root(cfg):
    return cfg.get("_memory_root") or config_mod.memory_root(cfg)


def _session_count(cfg):
    """只数目录，不解析日志：/health 会在每次打开页面时调用。"""
    base = os.path.join(_root(cfg), "sessions")
    try:
        return sum(1 for item in os.scandir(base) if item.is_dir())
    except OSError:
        return 0


def _needs_setup(cfg):
    """还没配好端点：默认 profile 指向云端却没有 key，首次打开就该把设置面板弹出来。"""
    try:
        item = config_mod.profile(cfg)
    except config_mod.ConfigError:
        return True
    base_url = str(item.get("base_url") or "")
    local = "localhost" in base_url or "127.0.0.1" in base_url or "::1" in base_url
    return not local and not (item.get("api_key") or "").strip()


def _profile_info(cfg):
    try:
        item = config_mod.profile(cfg)
        return {"name": item["name"], "model": item["model"]}
    except config_mod.ConfigError:
        return None


def _mask_key(key):
    """只回显首尾几位：设置页需要让用户确认「填过」，但不该把 key 明文送进浏览器。"""
    if not key:
        return ""
    if len(key) <= 10:
        return "*" * len(key)
    return key[:4] + "…" + key[-4:]


def _key_of(item):
    """profile 里的 api_key 可能是 ${ENV} 占位符，取真正生效的值。"""
    raw = str((item or {}).get("api_key") or "")
    if raw.startswith("${") and raw.endswith("}"):
        return os.getenv(raw[2:-1], ""), raw[2:-1]
    return raw, ""


def _display_path(path):
    """面板只展示项目内的相对路径：绝对路径会把本机目录带进截图和分享画面。"""
    if not path:
        return ""
    try:
        rel = os.path.relpath(path, config_mod.PROJECT_ROOT)
    except ValueError:  # Windows 上跨盘符
        return os.path.basename(path)
    return os.path.basename(path) if rel.startswith("..") else rel.replace(os.sep, "/")


def _settings_payload(cfg):
    profiles = []
    for name, item in (cfg.get("profiles") or {}).items():
        key, env = _key_of(item)
        profiles.append({
            "name": name,
            "base_url": item.get("base_url") or "",
            "model": item.get("model") or "",
            "thinking": bool(item.get("thinking")),
            "max_tokens": item.get("max_tokens"),
            "has_key": bool(key),
            "key_hint": _mask_key(key),
            "key_env": env,
        })
    hybrid = cfg.get("hybrid") or {}
    target = config_mod.config_target(cfg)
    return {
        "config_path": _display_path(target),
        "config_exists": os.path.exists(target),
        "default_profile": cfg.get("default_profile") or "local",
        "profiles": profiles,
        "hybrid": {"enabled": bool(hybrid.get("enabled")),
                   "router_profile": hybrid.get("router_profile") or "local",
                   "worker_profile": hybrid.get("worker_profile") or "cloud"},
    }


def _settings_patch(cfg, data):
    """校验设置表单，返回要写进配置文件的片段；不合法时抛 ValueError。"""
    profiles = cfg.get("profiles") or {}
    patch = {}

    if "default_profile" in data:
        name = str(data["default_profile"] or "")
        if name not in profiles:
            raise ValueError(f"没有名为 {name!r} 的端点")
        patch["default_profile"] = name

    incoming = data.get("profiles")
    if incoming is not None:
        if not isinstance(incoming, dict):
            raise ValueError("profiles 必须是对象")
        changed = {}
        for name, item in incoming.items():
            if name not in profiles:
                raise ValueError(f"没有名为 {name!r} 的端点")
            if not isinstance(item, dict):
                raise ValueError(f"{name} 的配置必须是对象")
            entry = {}
            if "base_url" in item:
                url = str(item["base_url"] or "").strip()
                if not url.startswith(("http://", "https://")):
                    raise ValueError("接口地址要以 http:// 或 https:// 开头")
                entry["base_url"] = url
            if "model" in item:
                model = str(item["model"] or "").strip()
                if not model:
                    raise ValueError("模型名不能为空")
                entry["model"] = model
            key = str(item.get("api_key") or "").strip()
            if key:  # 留空表示保持原值，避免误清掉已保存的 key
                entry["api_key"] = key
            if "thinking" in item:
                entry["thinking"] = bool(item["thinking"])
            for field, low, high in (("max_tokens", 64, 200000), ("timeout", 5, 3600)):
                if field not in item:
                    continue
                try:
                    value = int(item[field])
                except (TypeError, ValueError):
                    raise ValueError(f"{field} 必须是整数") from None
                if not low <= value <= high:
                    raise ValueError(f"{field} 要在 {low} 到 {high} 之间")
                entry[field] = value
            if entry:  # 整组都是空值时不必写盘
                changed[name] = entry
        if changed:
            patch["profiles"] = changed

    hybrid_in = data.get("hybrid")
    if hybrid_in is not None:
        if not isinstance(hybrid_in, dict):
            raise ValueError("hybrid 必须是对象")
        hybrid = {}
        if "enabled" in hybrid_in:
            hybrid["enabled"] = bool(hybrid_in["enabled"])
        for field in ("router_profile", "worker_profile"):
            if field not in hybrid_in:
                continue
            name = str(hybrid_in[field] or "")
            if name not in profiles:
                raise ValueError(f"没有名为 {name!r} 的端点")
            hybrid[field] = name
        if hybrid:
            patch["hybrid"] = hybrid

    return patch


class _ClientGone(Exception):
    pass


class SessionManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.agents = {}
        self.locks = {}
        self.guard = threading.Lock()

    def get(self, session_id=None):
        key = session_id or memory_mod.DEFAULT_SESSION
        with self.guard:
            agent = self.agents.get(key)
            if agent is None:
                agent = Agent(self.cfg, session_id=key)
                agent.resume()
                self.agents[key] = agent
                self.locks[key] = threading.Lock()
            return agent

    def lock(self, agent):
        return self.locks.setdefault(agent.memory.session_id, threading.Lock())

    def reset(self):
        """配置改动后丢掉缓存的 agent：下一次请求按新端点、新 key 重建。"""
        with self.guard:
            self.agents.clear()
            self.locks.clear()


class Handler(BaseHTTPRequestHandler):
    server_version = "Mote/0.6"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _respond(self, code, body, ctype, headers=None):
        data = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.close_connection = True

    def _json(self, code, payload):
        self._respond(code, json.dumps(payload, ensure_ascii=False),
                      "application/json; charset=utf-8")

    def _html(self, text):
        self._respond(200, text, "text/html; charset=utf-8")

    @staticmethod
    def _result_payload(result):
        return {
            "reply": result["text"], "session": result["session"],
            "turn": result["turn"], "node": result.get("node"),
            "parent": result.get("parent"), "steps": result["steps"],
            "tools": result["tools"], "lenses": result["lenses"],
            "route": result.get("route"), "mode": result.get("mode"),
            "worker": result.get("worker"),
            "model": result.get("model"), "thinking": result.get("thinking") or "",
            "saved_chars": result.get("saved_chars", 0),
            "context_chars": result.get("context_chars", 0),
            "fallback": bool(result.get("fallback")),
            "stopped": bool(result.get("stopped")),
        }

    def _sse_start(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
        except OSError as err:
            raise _ClientGone(str(err)) from err

    def _sse(self, event, payload):
        """每个 SSE 事件作为一段 chunk 写出，写完立即 flush。"""
        body = (f"event: {event}\n"
                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n").encode("utf-8")
        try:
            self.wfile.write(f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n")
            self.wfile.flush()
        except (OSError, ValueError) as err:
            raise _ClientGone(str(err)) from err

    def _sse_end(self):
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            self.close_connection = True

    def _stream_chat(self, data):
        message = (data.get("message") or data.get("content") or "").strip()
        if not message:
            return self._json(400, {"error": "缺少 message"})
        session_id = data.get("session")
        if session_id is not None and (not isinstance(session_id, str)
                                       or not _SID.fullmatch(session_id)):
            return self._json(400, {"error": "会话 id 不合法"})
        parent = data.get("parent")
        if parent is not None and (not isinstance(parent, str)
                                   or not _NODE_ID.fullmatch(parent)):
            return self._json(400, {"error": "分支节点 id 不合法"})
        fork = data.get("fork")
        if fork is not None and (not isinstance(fork, str)
                                 or not _NODE_ID.fullmatch(fork)):
            return self._json(400, {"error": "分支节点 id 不合法"})
        mode = data.get("mode")
        if mode is not None and mode not in ("direct", "hybrid"):
            return self._json(400, {"error": "对话模式不合法"})

        agent = self.server.manager.get(session_id)
        state = {"closed": False}

        def push(event, payload):
            if state["closed"]:
                return
            try:
                self._sse(event, payload)
            except _ClientGone:
                state["closed"] = True

        def on_delta(piece):
            if piece:
                push("delta", {"delta": piece})

        def on_thinking(piece):
            if piece:
                push("thinking", {"delta": piece})

        def on_event(kind, payload):
            if kind in ("preprocess", "tool_start", "tool_end"):
                push(kind, payload)

        with self.server.manager.lock(agent):
            previous = (agent.on_delta, agent.on_thinking, agent.on_event)
            agent.on_delta, agent.on_thinking, agent.on_event = on_delta, on_thinking, on_event
            try:
                self._sse_start()
                result = agent.ask(message, stream=True, parent=parent,
                                   mode=mode, fork=fork)
                push("done", self._result_payload(result))
            except Exception as err:
                push("error", {"error": f"{type(err).__name__}: {err}"})
            finally:
                if hasattr(agent, "clear_stop"):
                    agent.clear_stop()
                agent.on_delta, agent.on_thinking, agent.on_event = previous
                self._sse_end()

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _known_session(self, session_id):
        """只查目录，不扫全部会话：这个判断在每个请求上都跑，必须 O(1)。"""
        path = os.path.join(_root(self.server.cfg), "sessions", session_id,
                            "events.jsonl")
        return os.path.isfile(path)

    @staticmethod
    def _session_view(memory, node=None):
        """一次读盘产出消息流与分支树；思考原文不下发，展开时按节点取。

        node 非空时按该节点所在链路出视图（点分支树、删除时的当前视图），
        为空则按主分支/游标（打开会话）。
        """
        events = memory.events()
        messages = []
        for item in memory.conversation(node=node, events=events):
            row = dict(item)
            thinking = row.pop("thinking", "") or ""
            row["thinking_chars"] = len(thinking)
            messages.append(row)
        return {"messages": messages, "tree": memory.branch_tree(events=events, node=node)}

    def _local_only(self):
        """配置里有 API key，只允许回环地址读写；把服务开到 0.0.0.0 时不会连 key 一起暴露。"""
        addr = (self.client_address or ("",))[0]
        return addr in ("127.0.0.1", "::1", "localhost")

    def _reload_config(self):
        """从磁盘重新读配置并清空 agent 缓存，设置保存后立即生效。"""
        target = config_mod.config_target(self.server.cfg)
        try:
            cfg = config_mod.load(target)
        except config_mod.ConfigError as err:
            return str(err)
        cfg["_memory_root"] = (self.server.cfg.get("_memory_root")
                               or config_mod.memory_root(cfg))
        self.server.cfg = cfg
        self.server.manager.reset()
        return ""

    def _test_profile(self, data):
        """用表单里的参数发一次极短请求：地址、模型名、key 有一个不对就能立刻看出来。"""
        cfg = self.server.cfg
        name = str(data.get("profile") or cfg.get("default_profile") or "local")
        saved = (cfg.get("profiles") or {}).get(name) or {}
        saved_key, _ = _key_of(saved)
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

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        manager = self.server.manager
        if path in ("/", "/index.html"):
            return self._html(PAGE)
        if path == "/health":
            profile = None
            if manager.agents:
                item = next(iter(manager.agents.values())).profile
                profile = {"name": item["name"], "model": item["model"]}
            else:
                profile = _profile_info(self.server.cfg)
            hybrid = bool((self.server.cfg.get("hybrid") or {}).get("enabled"))
            if manager.agents:
                hybrid = next(iter(manager.agents.values())).hybrid_enabled
            return self._json(200, {
                "ok": True, "profile": profile, "hybrid": hybrid,
                "tools": tools_mod.enabled(self.server.cfg),
                "default_session": memory_mod.DEFAULT_SESSION,
                "needs_setup": _needs_setup(self.server.cfg),
                "lenses": len(lenses_mod.LENSES),
                "sessions": _session_count(self.server.cfg),
            })
        if path == "/sessions":
            return self._json(200, {"sessions": memory_mod.list_sessions(
                _root(self.server.cfg))})
        if path == "/search":
            query = _query(self.path)
            text = (query.get("q") or [""])[0].strip()
            if not text:
                return self._json(400, {"error": "缺少 q"})
            try:
                limit = int((query.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            limit = max(1, min(200, limit))
            return self._json(200, memory_mod.search_sessions(
                _root(self.server.cfg), text, limit=limit))
        if path == "/export":
            root = _root(self.server.cfg)
            rows = memory_mod.list_sessions(root)
            sessions = [memory_mod.Memory(root, row["id"]).export_payload()
                        for row in rows]
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
            payload = {"format": "mote-backup/1",
                       "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
                       "count": len(sessions), "sessions": sessions}
            return self._respond(
                200, json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "application/json; charset=utf-8",
                {"Content-Disposition": _attachment(f"mote-backup-{stamp}.json")})
        if path == "/settings":
            if not self._local_only():
                return self._json(403, {"error": "设置只允许在本机修改"})
            return self._json(200, _settings_payload(self.server.cfg))
        if path == "/lenses":
            return self._json(200, {"count": len(lenses_mod.LENSES),
                                    "catalog": lenses_mod.catalog(),
                                    "lenses": lenses_mod.LENSES})
        if path == "/lens-names":
            return self._json(200, {"names": {key: item["name"]
                                              for key, item in lenses_mod.LENSES.items()}})
        match = _MESSAGES_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            if not _SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            node = (_query(self.path).get("node") or [""])[0]
            if node and not _NODE_ID.fullmatch(node):
                node = ""
            view = self._session_view(memory, node=node or None)
            return self._json(200, {"session": session_id, "messages": view["messages"],
                                    "tree": view["tree"]})
        match = _THINK_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            node = urllib.parse.unquote(match.group(2))
            if not _SID.fullmatch(session_id) or not _NODE_ID.fullmatch(node):
                return self._json(400, {"error": "id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            if not memory.has_node(node):
                return self._json(404, {"error": "分支节点不存在"})
            text = memory.thinking_for(node)
            return self._json(200, {"session": session_id, "node": node,
                                    "text": text, "chars": len(text)})
        match = _TREE_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            if not _SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            node = (_query(self.path).get("node") or [""])[0]
            if node and not _NODE_ID.fullmatch(node):
                node = ""
            return self._json(200, {"session": session_id,
                                    "tree": memory.branch_tree(node=node or None)})
        match = _EXPORT_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            if not _SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            query = _query(self.path)
            fmt = (query.get("format") or ["md"])[0].lower()
            with_thinking = (query.get("thinking") or ["1"])[0].lower() \
                not in ("0", "false", "no")
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            if fmt in ("md", "markdown"):
                return self._respond(
                    200, memory.export_markdown(with_thinking=with_thinking),
                    "text/markdown; charset=utf-8",
                    {"Content-Disposition": _attachment(memory.export_filename("md"))})
            if fmt == "json":
                return self._respond(
                    200, json.dumps(memory.export_payload(), ensure_ascii=False, indent=2),
                    "application/json; charset=utf-8",
                    {"Content-Disposition": _attachment(memory.export_filename("json"))})
            return self._json(400, {"error": "format 只能是 md 或 json"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        manager = self.server.manager
        data = self._body()
        if data is None:
            return self._json(400, {"error": "body 必须是 JSON"})

        if path in ("/settings", "/settings/test"):
            if not self._local_only():
                return self._json(403, {"error": "设置只允许在本机修改"})
            if path == "/settings/test":
                return self._test_profile(data)
            try:
                patch = _settings_patch(self.server.cfg, data)
            except ValueError as err:
                return self._json(400, {"error": str(err)})
            target = config_mod.config_target(self.server.cfg)
            try:
                config_mod.update(target, patch)
            except (config_mod.ConfigError, OSError) as err:
                return self._json(500, {"error": f"写入配置失败：{err}"})
            problem = self._reload_config()
            if problem:
                return self._json(500, {"error": f"配置已写入但重载失败：{problem}"})
            payload = _settings_payload(self.server.cfg)
            payload["ok"] = True
            payload["saved"] = sorted(patch)
            return self._json(200, payload)

        if path == "/sessions":
            session_id = str(data.get("id") or memory_mod.new_session_id()).strip()
            if not _SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if self._known_session(session_id):
                return self._json(409, {"error": "会话已存在", "session": session_id})
            profile = _profile_info(self.server.cfg) or {}
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            memory.ensure(profile=profile.get("name", ""), model=profile.get("model", ""))
            return self._json(200, {"session": session_id})

        match = _TITLE_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            if not _SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            title = str(data.get("title") or "").strip()
            if not title:
                return self._json(400, {"error": "标题不能为空"})
            memory_mod.Memory(_root(self.server.cfg), session_id).rename(title)
            return self._json(200, {"session": session_id, "title": title[:28]})

        match = _CURSOR_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            if not _SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            node = str(data.get("node") or "")
            if not _NODE_ID.fullmatch(node):
                return self._json(400, {"error": "分支节点 id 不合法"})
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            if not memory.set_cursor(node):
                return self._json(404, {"error": "分支节点不存在或已删除"})
            agent = manager.agents.get(session_id)
            if agent is not None and hasattr(agent, "resume"):
                with manager.lock(agent):
                    agent.resume(node)
            view = self._session_view(memory, node=node)
            return self._json(200, {"session": session_id, "node": node,
                                    "messages": view["messages"], "tree": view["tree"]})

        match = _MAIN_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            if not _SID.fullmatch(session_id):
                return self._json(400, {"error": "会话 id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            node = str(data.get("node") or "")
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            if node:
                if not _NODE_ID.fullmatch(node):
                    return self._json(400, {"error": "分支节点 id 不合法"})
                if not memory.set_main(node):
                    return self._json(404, {"error": "分支节点不存在或已删除"})
            else:
                memory.set_main(None)
            # tip 是界面正在看的链路：主分支只决定打开时落在哪，不能把当前视图拽走
            tip = str(data.get("tip") or "")
            if tip and not _NODE_ID.fullmatch(tip):
                tip = ""
            view = self._session_view(memory, node=tip or None)
            # 主分支不影响当前视图，因此不下发 messages
            return self._json(200, {"session": session_id, "main": memory.main_node(),
                                    "tree": view["tree"]})

        match = _STOP_PATH.fullmatch(path)
        if match:
            session_id = _decode_sid(match)
            if not _SID.fullmatch(session_id):
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
        message = (data.get("message") or data.get("content") or "").strip()
        if not message:
            return self._json(400, {"error": "缺少 message"})
        session_id = data.get("session")
        if session_id is not None and (not isinstance(session_id, str)
                                       or not _SID.fullmatch(session_id)):
            return self._json(400, {"error": "会话 id 不合法"})
        parent = data.get("parent")
        if parent is not None and (not isinstance(parent, str)
                                   or not _NODE_ID.fullmatch(parent)):
            return self._json(400, {"error": "分支节点 id 不合法"})
        fork = data.get("fork")
        if fork is not None and (not isinstance(fork, str)
                                 or not _NODE_ID.fullmatch(fork)):
            return self._json(400, {"error": "分支节点 id 不合法"})
        mode = data.get("mode")
        if mode is not None and mode not in ("direct", "hybrid"):
            return self._json(400, {"error": "对话模式不合法"})

        agent = manager.get(session_id)
        with manager.lock(agent):
            try:
                result = agent.ask(message, stream=False, parent=parent,
                                   mode=mode, fork=fork)
            except Exception as err:
                return self._json(502, {"error": f"{type(err).__name__}: {err}"})
        return self._json(200, self._result_payload(result))

    def do_DELETE(self):
        path = urllib.parse.urlsplit(self.path).path
        node_match = _NODE_PATH.fullmatch(path)
        if node_match:
            session_id = _decode_sid(node_match)
            node = urllib.parse.unquote(node_match.group(2))
            if not _SID.fullmatch(session_id) or not _NODE_ID.fullmatch(node):
                return self._json(400, {"error": "id 不合法"})
            if not self._known_session(session_id):
                return self._json(404, {"error": "找不到这个会话"})
            memory = memory_mod.Memory(_root(self.server.cfg), session_id)
            tip = (_query(self.path).get("tip") or [""])[0]
            if tip and not _NODE_ID.fullmatch(tip):
                tip = ""
            removed = memory.delete_node(node, tip=tip or None)
            if removed is None:
                return self._json(404, {"error": "分支节点不存在或已删除"})
            agent = self.server.manager.agents.get(session_id)
            if agent is not None and hasattr(agent, "resume"):
                with self.server.manager.lock(agent):
                    agent.resume()
            view = self._session_view(memory, node=tip or None)
            return self._json(200, {"ok": True, "session": session_id,
                                    "nodes": removed, "messages": view["messages"],
                                    "tree": view["tree"]})

        match = _SESSION_PATH.fullmatch(path)
        if not match:
            return self._json(404, {"error": "not found"})
        session_id = _decode_sid(match)
        if not _SID.fullmatch(session_id):
            return self._json(400, {"error": "会话 id 不合法"})
        if not self._known_session(session_id):
            return self._json(404, {"error": "找不到这个会话"})
        shutil.rmtree(memory_mod.Memory(_root(self.server.cfg), session_id).home)
        manager = self.server.manager
        with manager.guard:
            manager.agents.pop(session_id, None)
            manager.locks.pop(session_id, None)
        return self._json(200, {"ok": True, "session": session_id})


class _Server(ThreadingHTTPServer):
    """浏览器关闭页面时会直接断开连接，这类断开不必打印堆栈。"""

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def _browse_url(host, port):
    """监听 0.0.0.0 时浏览器不能访问这个地址，换成回环地址。"""
    target = "127.0.0.1" if host in ("0.0.0.0", "::", "", "*") else host
    return f"http://{target}:{port}/"


def serve(cfg, host="127.0.0.1", port=9000, verbose=False, open_browser=False):
    try:
        httpd = _Server((host, port), Handler)
    except OSError as err:
        raise SystemExit(f"端口 {port} 无法监听（{err}）。换一个：python -m mote serve --port {port + 1}")
    httpd.manager = SessionManager(cfg)
    httpd.cfg = cfg
    httpd.verbose = verbose
    url = _browse_url(host, port)
    print(f"Mote 已启动：{url}")
    print("  首次使用点右上角「⚙ 设置」填接口地址、模型名和 API Key；Ctrl+C 停止。")
    print("  接口：POST /inbox · GET /sessions/<id>/messages · GET/POST /settings")
    if open_browser and not os.getenv("MOTE_NO_BROWSER"):
        # 先让服务进入循环再打开，避免浏览器抢在监听之前访问
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
