"""HTTP 层：网页双栏结构、会话创建与历史回填、镜头名接口。"""

import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from mote.core import config as config_mod
from mote.core.ids import DEFAULT_SESSION, new_node_id
from mote.infra import config_file
from mote.services import settings as settings_mod
from mote.services.conversation import Conversation
from mote.interfaces import http as server_mod


class FakeAgent:
    def __init__(self, root, session_id):
        self.root = root
        self.sid = session_id

    def ask(self, text, stream=False, parent=None, mode=None, fork=None):
        memory = Conversation(self.root, self.sid)
        if fork:
            parent = memory.parent_of(fork)
        parent = parent or memory.active_node()
        node = new_node_id()
        memory.user(1, text, node=node, parent=parent)
        memory.tool(1, "use_lens", '{"lens":"inversion"}', "清单")
        memory.assistant(1, "**结论**：先做小实验。", model="fake-cloud", route="cloud",
                         thinking="先拆约束")
        return {"text": "**结论**：先做小实验。", "session": self.sid,
                "turn": 1, "node": node, "parent": parent,
                "steps": 2, "tools": [], "lenses": ["inversion"],
                "route": "cloud", "worker": "cloud", "model": "fake-cloud",
                "saved_chars": 120, "context_chars": 80}


class StreamingFakeAgent:
    sid = "stream-session"
    on_delta = on_thinking = on_event = None
    mode = None
    fork = None

    def ask(self, text, stream=False, parent=None, mode=None, fork=None):
        self.mode = mode
        self.fork = fork
        if self.on_event:
            self.on_event("preprocess", {"route": "cloud", "fallback": False})
        if self.on_thinking:
            self.on_thinking("先看约束")
        if self.on_delta:
            self.on_delta("第一部分")
            self.on_delta("第二部分")
        return {"text": "第一部分第二部分", "session": self.sid, "turn": 1,
                "steps": 1, "tools": [], "lenses": [], "route": "cloud",
                "worker": "fake", "model": "fake-cloud", "thinking": "先看约束"}


class FakeManager:
    def __init__(self, root):
        self.root = root
        self.agents = {}
        self.locks = {}
        self.guard = threading.Lock()

    def get(self, session_id=None):
        key = session_id or DEFAULT_SESSION
        if key not in self.agents:
            self.agents[key] = FakeAgent(self.root, key)
            self.locks[key] = threading.Lock()
        return self.agents[key]

    def lock(self, agent):
        return self.locks.setdefault(agent.sid, threading.Lock())


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = copy.deepcopy(config_mod.DEFAULT)
        cfg["_memory_root"] = self.tmp.name
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
        self.httpd.cfg = cfg
        self.httpd.manager = FakeManager(self.tmp.name)
        self.httpd.verbose = False
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _raw(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8")

    def test_page_covers_ui_features(self):
        """页面是内联的单文件：这里守住「功能入口都还在」这条底线。"""
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            page = r.read().decode("utf-8")
        tokens = [
            # 双栏、Markdown、复制、状态标签
            'id="sessions"', 'id="thread"', 'id="toLatest"', 'id="status"',
            'data-act="rename"', 'data-act="delete"', '思考中',
            "'云端 · '", "'本地 · '", 'function md(', 'class="copy"',
            # 流式输出与思考折叠
            '/inbox/stream', "d.className='think'", 'function paintPending()',
            # 分支树、消息菜单、生成控制
            'id="branchBtn"', 'id="treeModal"', 'id="editModal"',
            'class="msg-more"', 'data-act="edit"', 'function renderTree(',
            'async function deleteTurn(', '⚙ 设置', 'id="setMode"',
            'data-mode="hybrid"', 'data-mode="direct"', 'function branchNavFor(',
            'function stopGenerating(', 'function regenerate(', 'function retryLast(',
            "'ans-tools'", 'AbortController', 'data-act="main"', 'function setMain(',
            'id="note"',
            # 设置面板
            'id="setBtn"', 'id="setModal"', 'function openSettings(',
            "fetch('/settings'", 'id="setCloudKey"', 'id="setTestBtn"',
            # 分支树由 JS 算坐标后画 SVG
            'class="tm-edge', 'class="tm-node', 'state.treePos',
            # 检索与导出
            'id="hits"', 'function runSearch(', 'function renderHits(',
            'function openHit(', 'data-act="export-md"', 'data-act="export-json"',
            'id="backup"', "'/search?q='", 'function download(', "'load-more'",
            'function revealNode(', '/thinking/',
        ]
        for token in tokens:
            with self.subTest(token=token):
                self.assertIn(token, page)

    def test_create_session_then_read_history(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        _, reply = self._post("/inbox", {"message": "该不该换工作", "session": sid})
        self.assertEqual(reply["reply"], "**结论**：先做小实验。")
        self.assertEqual(reply["model"], "fake-cloud")
        self.assertEqual(reply["route"], "cloud")

        _, listed = self._get("/sessions")
        self.assertEqual(listed["sessions"][0]["title"], "该不该换工作")
        _, history = self._get("/sessions/" + sid + "/messages")
        self.assertEqual([m["role"] for m in history["messages"]], ["user", "assistant"])
        self.assertEqual(history["messages"][1]["lenses"], ["inversion"])
        self.assertEqual(history["messages"][1]["model"], "fake-cloud")
        self.assertEqual(history["messages"][1]["route"], "cloud")

    def test_rename_session_keeps_history(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        self._post("/inbox", {"message": "原问题", "session": sid})
        _, renamed = self._post("/sessions/" + sid + "/title", {"title": "新标题"})
        self.assertEqual(renamed["title"], "新标题")
        _, listed = self._get("/sessions")
        self.assertEqual(listed["sessions"][0]["title"], "新标题")
        _, history = self._get("/sessions/" + sid + "/messages")
        self.assertEqual([m["role"] for m in history["messages"]], ["user", "assistant"])

    def test_delete_session(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        req = urllib.request.Request(self.base + "/sessions/" + sid, method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        self.assertTrue(data["ok"])
        _, listed = self._get("/sessions")
        self.assertNotIn(sid, [row["id"] for row in listed["sessions"]])
        with self.assertRaises(urllib.error.HTTPError) as gone:
            self._get("/sessions/" + sid + "/messages")
        self.assertEqual(gone.exception.code, 404)

    def test_lens_names_are_available(self):
        _, data = self._get("/lens-names")
        self.assertIn("inversion", data["names"])
        self.assertTrue(all(isinstance(v, str) for v in data["names"].values()))

    def test_rejects_invalid_and_unknown_session(self):
        with self.assertRaises(urllib.error.HTTPError) as bad:
            self._get("/sessions/bad.id/messages")
        self.assertEqual(bad.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self._get("/sessions/s-no-such-session/messages")
        self.assertEqual(missing.exception.code, 404)


    def test_stream_endpoint_emits_delta_thinking_and_done(self):
        agent = StreamingFakeAgent()
        self.httpd.manager.agents[agent.sid] = agent
        self.httpd.manager.locks[agent.sid] = threading.Lock()
        req = urllib.request.Request(
            self.base + "/inbox/stream",
            data=json.dumps({"message": "怎么选", "session": agent.sid}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("text/event-stream"))
            raw = r.read().decode("utf-8")
        events = {}
        for block in raw.strip().split("\n\n"):
            name, data = "", ""
            for line in block.split("\n"):
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
            if name and data:
                events.setdefault(name, []).append(json.loads(data))
        self.assertEqual([x["delta"] for x in events["delta"]], ["第一部分", "第二部分"])
        self.assertEqual(events["thinking"][0]["delta"], "先看约束")
        self.assertEqual(events["done"][0]["thinking"], "先看约束")
        self.assertIsNone(agent.on_delta)

    def test_branch_tree_edit_switch_and_delete(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        _, first = self._post("/inbox", {"message": "问题一", "session": sid})
        _, second = self._post("/inbox", {"message": "问题二", "session": sid})
        _, branch = self._post("/inbox", {"message": "问题一改", "session": sid,
                                          "parent": first["node"]})

        _, tree = self._get("/sessions/" + sid + "/tree")
        by_id = {item["id"]: item for item in tree["tree"]["nodes"]}
        self.assertIn(second["node"], by_id[first["node"]]["children"])
        self.assertIn(branch["node"], by_id[first["node"]]["children"])

        _, active = self._get("/sessions/" + sid + "/messages")
        self.assertIn("问题一改", [m["text"] for m in active["messages"]])
        self.assertNotIn("问题二", [m["text"] for m in active["messages"]])

        _, switched = self._post("/sessions/" + sid + "/cursor", {"node": second["node"]})
        self.assertIn("问题二", [m["text"] for m in switched["messages"]])
        self.assertNotIn("问题一改", [m["text"] for m in switched["messages"]])

        req = urllib.request.Request(
            self.base + "/sessions/" + sid + "/nodes/" + second["node"],
            method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            deleted = json.loads(r.read().decode("utf-8"))
        self.assertEqual(deleted["nodes"], [second["node"]])
        self.assertNotIn(second["node"],
                         [item["id"] for item in deleted["tree"]["nodes"]])
        _, history = self._get("/sessions/" + sid + "/messages")
        self.assertNotIn("问题二", [m["text"] for m in history["messages"]])

    def test_main_branch_endpoint_pins_and_clears(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        _, first = self._post("/inbox", {"message": "问题一", "session": sid})
        _, second = self._post("/inbox", {"message": "问题二", "session": sid})
        _, branch = self._post("/inbox", {"message": "问题一改", "session": sid,
                                          "parent": first["node"]})

        # 切到另一条链，再把「问题二」那条链设为主分支
        self._post("/sessions/" + sid + "/cursor", {"node": branch["node"]})
        _, pinned = self._post("/sessions/" + sid + "/main",
                               {"node": second["node"], "tip": branch["node"]})
        self.assertEqual(pinned["main"], second["node"])
        self.assertEqual(pinned["tree"]["main"], second["node"])
        # 当前视图（tip）不被主分支带走
        self.assertEqual(pinned["tree"]["active"], branch["node"])

        # 打开会话（/messages）落在主分支，而不是最后切换的 cursor
        _, opened = self._get("/sessions/" + sid + "/messages")
        texts = [m["text"] for m in opened["messages"]]
        self.assertIn("问题二", texts)
        self.assertNotIn("问题一改", texts)
        self.assertEqual(opened["tree"]["active"], second["node"])

        # 取消后回到跟随 cursor 的行为
        _, cleared = self._post("/sessions/" + sid + "/main", {})
        self.assertIsNone(cleared["main"])
        self.assertIsNone(cleared["tree"]["main"])
        _, back = self._get("/sessions/" + sid + "/messages")
        self.assertIn("问题一改", [m["text"] for m in back["messages"]])

        # 不存在的节点要拒绝
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/sessions/" + sid + "/main", {"node": "no-such-node"})
        self.assertEqual(ctx.exception.code, 404)

    def test_jump_off_main_branch_is_not_pulled_back(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        _, first = self._post("/inbox", {"message": "问题一", "session": sid})
        _, second = self._post("/inbox", {"message": "问题二", "session": sid})
        _, branch = self._post("/inbox", {"message": "问题一改", "session": sid,
                                          "parent": first["node"]})
        self._post("/sessions/" + sid + "/main", {"node": second["node"]})

        # 在主分支之外点分支树：视图跟着走，不被主分支摁住
        _, jumped = self._post("/sessions/" + sid + "/cursor", {"node": branch["node"]})
        texts = [m["text"] for m in jumped["messages"]]
        self.assertIn("问题一改", texts)
        self.assertNotIn("问题二", texts)
        self.assertEqual(jumped["tree"]["active"], branch["node"])
        self.assertEqual(jumped["tree"]["main"], second["node"])
        self.assertEqual(jumped["tree"]["main_path"], [first["node"], second["node"]])

        # 重新打开会话（不带 node）仍落在主分支
        _, opened = self._get("/sessions/" + sid + "/messages")
        self.assertIn("问题二", [m["text"] for m in opened["messages"]])

        # 打开分支树时带上当前节点，当前位置不会被主分支改写
        _, tree = self._get("/sessions/" + sid + "/tree?node=" + branch["node"])
        self.assertEqual(tree["tree"]["active"], branch["node"])

    def test_delete_follows_current_view_not_main(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        _, first = self._post("/inbox", {"message": "问题一", "session": sid})
        _, a1 = self._post("/inbox", {"message": "A 一", "session": sid,
                                      "parent": first["node"]})
        _, a2 = self._post("/inbox", {"message": "A 二", "session": sid,
                                      "parent": a1["node"]})
        self._post("/sessions/" + sid + "/cursor", {"node": first["node"]})
        _, b1 = self._post("/inbox", {"message": "B 一", "session": sid,
                                      "parent": first["node"]})
        self._post("/sessions/" + sid + "/main", {"node": b1["node"]})

        # 界面切到 A 链，删除 A 的第一问：应删掉 A 的整段下游，而不是按主分支判范围
        self._post("/sessions/" + sid + "/cursor", {"node": a2["node"]})
        req = urllib.request.Request(
            self.base + "/sessions/" + sid + "/nodes/" + a1["node"] +
            "?tip=" + a2["node"], method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            deleted = json.loads(r.read().decode("utf-8"))
        self.assertEqual(set(deleted["nodes"]), {a1["node"], a2["node"]})
        self.assertEqual(deleted["tree"]["main"], b1["node"])

        # 主分支原样保留，重新打开仍落在 B 链
        _, opened = self._get("/sessions/" + sid + "/messages")
        texts = [m["text"] for m in opened["messages"]]
        self.assertIn("B 一", texts)
        self.assertNotIn("A 一", texts)

    def test_edit_fork_creates_sibling_branch(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        _, first = self._post("/inbox", {"message": "问题一", "session": sid})
        _, second = self._post("/inbox", {"message": "问题二", "session": sid})
        _, forked = self._post("/inbox", {"message": "问题二改", "session": sid,
                                          "fork": second["node"]})

        self.assertEqual(forked["parent"], first["node"])
        _, tree = self._get("/sessions/" + sid + "/tree")
        by_id = {item["id"]: item for item in tree["tree"]["nodes"]}
        self.assertEqual(set(by_id[first["node"]]["children"]),
                         {second["node"], forked["node"]})

        _, active = self._get("/sessions/" + sid + "/messages")
        texts = [m["text"] for m in active["messages"]]
        self.assertIn("问题二改", texts)
        self.assertNotIn("问题二", texts)
        self.assertEqual(active["tree"]["active"], forked["node"])

    def test_stop_endpoint_sets_flag_without_lock(self):
        class StoppableAgent:
            sid = "stop-session"
            on_delta = on_thinking = on_event = None
            stopped = False

            def request_stop(self):
                self.stopped = True

        agent = StoppableAgent()
        self.httpd.manager.agents[agent.sid] = agent
        self.httpd.manager.locks[agent.sid] = threading.Lock()
        req = urllib.request.Request(
            self.base + "/sessions/" + agent.sid + "/stop", data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 202)
            body = json.loads(r.read().decode("utf-8"))
        self.assertTrue(body["stopping"])
        self.assertTrue(agent.stopped)

    def test_stream_mode_is_forwarded(self):
        agent = StreamingFakeAgent()
        self.httpd.manager.agents[agent.sid] = agent
        self.httpd.manager.locks[agent.sid] = threading.Lock()
        req = urllib.request.Request(
            self.base + "/inbox/stream",
            data=json.dumps({"message": "怎么选", "session": agent.sid,
                             "mode": "direct"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        self.assertEqual(agent.mode, "direct")

    def test_export_markdown_and_json(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        self._post("/inbox", {"message": "该不该换工作", "session": sid})

        status, headers, body = self._raw("/sessions/" + sid + "/export?format=md")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/markdown"))
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("# 该不该换工作", body)
        self.assertIn("> 该不该换工作", body)
        self.assertIn("**结论**：先做小实验。", body)
        self.assertIn("云端 · fake-cloud", body)

        _, payload = self._get("/sessions/" + sid + "/export?format=json")
        self.assertEqual(payload["format"], "mote-session/1")
        self.assertEqual(payload["counts"]["turns"], 1)
        self.assertEqual(payload["branches"][payload["active"]]["answer"],
                         "**结论**：先做小实验。")

    def test_export_rejects_bad_format_and_unknown_session(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        with self.assertRaises(urllib.error.HTTPError) as bad:
            self._get("/sessions/" + sid + "/export?format=pdf")
        self.assertEqual(bad.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self._get("/sessions/s-no-such/export?format=md")
        self.assertEqual(missing.exception.code, 404)

    def test_backup_exports_every_session(self):
        for text in ("第一个会话", "第二个会话"):
            _, created = self._post("/sessions", {})
            self._post("/inbox", {"message": text, "session": created["session"]})
        status, headers, body = self._raw("/export")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(data["format"], "mote-backup/1")
        self.assertEqual(data["count"], 2)
        self.assertEqual({item["title"] for item in data["sessions"]},
                         {"第一个会话", "第二个会话"})

    def test_search_endpoint_finds_messages(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        self._post("/inbox", {"message": "先做小实验", "session": sid})
        _, data = self._get("/search?q=" + urllib.parse.quote("小实验"))
        self.assertEqual(data["total"], 2)          # 问题与回答都含这三个字
        self.assertTrue(all(item["session"] == sid for item in data["results"]))
        self.assertIn("\x01小实验\x02", data["results"][0]["snippet"])
        with self.assertRaises(urllib.error.HTTPError) as bad:
            self._get("/search?q=")
        self.assertEqual(bad.exception.code, 400)

    def test_messages_defer_thinking_to_lazy_endpoint(self):
        _, created = self._post("/sessions", {})
        sid = created["session"]
        _, reply = self._post("/inbox", {"message": "该不该换工作", "session": sid})
        _, history = self._get("/sessions/" + sid + "/messages")
        answer = history["messages"][1]
        self.assertNotIn("thinking", answer)
        self.assertEqual(answer["thinking_chars"], 4)

        _, think = self._get("/sessions/" + sid + "/thinking/" + answer["node"])
        self.assertEqual(think["text"], "先拆约束")
        self.assertEqual(think["chars"], 4)
        _, tree = self._get("/sessions/" + sid + "/tree")
        node = tree["tree"]["nodes"][0]
        self.assertEqual(node["text"], "该不该换工作")

        with self.assertRaises(urllib.error.HTTPError) as missing:
            self._get("/sessions/" + sid + "/thinking/n-nope")
        self.assertEqual(missing.exception.code, 404)


class SettingsTest(unittest.TestCase):
    """设置面板：读配置要藏住 key，写完要落盘并让运行中的服务立即换配置。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp.name, "config.json")
        cfg = copy.deepcopy(config_mod.DEFAULT)
        cfg["_memory_root"] = self.tmp.name
        cfg["_config_path"] = self.config_path
        cfg["profiles"]["cloud"]["api_key"] = "sk-original-0001"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
        self.httpd.cfg = cfg
        self.httpd.manager = server_mod.SessionManager(cfg)
        self.httpd.verbose = False
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _config_file(self):
        with open(self.config_path, encoding="utf-8") as f:
            return json.load(f)

    def _post(self, path, payload, expect=None):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            body = json.loads(err.read().decode("utf-8"))
            if expect and err.code == expect:
                return err.code, body
            raise

    def test_get_never_returns_plaintext_key(self):
        _, data = self._get("/settings")
        cloud = next(item for item in data["profiles"] if item["name"] == "cloud")
        self.assertTrue(cloud["has_key"])
        self.assertEqual(cloud["key_hint"], "sk-o…0001")
        self.assertNotIn("sk-original-0001", json.dumps(data, ensure_ascii=False))
        self.assertEqual(data["default_profile"], "cloud")
        self.assertFalse(data["config_exists"])
        # 面板只显示相对路径，避免把本机目录带进界面
        self.assertEqual(data["config_path"], "config.json")

    def test_post_writes_file_and_reloads_runtime(self):
        _, saved = self._post("/settings", {
            "default_profile": "cloud",
            "profiles": {"cloud": {"base_url": "https://api.example.com/v1",
                                   "model": "deepseek-reasoner",
                                   "api_key": "sk-brand-new-9",
                                   "thinking": False, "max_tokens": 4096}},
            "hybrid": {"enabled": False}})
        self.assertTrue(saved["ok"])
        raw = self._config_file()
        self.assertEqual(raw["profiles"]["cloud"]["model"], "deepseek-reasoner")
        self.assertEqual(raw["profiles"]["cloud"]["api_key"], "sk-brand-new-9")
        self.assertEqual(raw["profiles"]["cloud"]["max_tokens"], 4096)
        self.assertFalse(raw["hybrid"]["enabled"])
        # 没提到的字段不会被写死，仍走默认值
        self.assertNotIn("local", raw.get("profiles", {}))
        self.assertEqual(self.httpd.cfg["profiles"]["local"]["model"], "qwen3.5:4b")
        # 运行中的服务立即换配置，并丢掉缓存的 agent
        self.assertEqual(self.httpd.cfg["profiles"]["cloud"]["model"], "deepseek-reasoner")
        self.assertEqual(self.httpd.cfg["default_profile"], "cloud")
        self.assertEqual(len(self.httpd.manager.agents), 0)

    def test_blank_key_keeps_saved_one(self):
        self._post("/settings", {"profiles": {"cloud": {"api_key": "sk-keep-me-1"}}})
        self._post("/settings", {"profiles": {"cloud": {"model": "m2", "api_key": "   "}}})
        raw = self._config_file()
        self.assertEqual(raw["profiles"]["cloud"]["api_key"], "sk-keep-me-1")
        self.assertEqual(raw["profiles"]["cloud"]["model"], "m2")

    def test_invalid_input_is_rejected(self):
        code, body = self._post("/settings",
                                {"profiles": {"cloud": {"base_url": "ftp://x"}}}, expect=400)
        self.assertIn("http", body["error"])
        code, body = self._post("/settings", {"profiles": {"nope": {}}}, expect=400)
        self.assertIn("nope", body["error"])
        code, body = self._post("/settings",
                                {"profiles": {"cloud": {"max_tokens": 1}}}, expect=400)
        self.assertIn("max_tokens", body["error"])
        self.assertFalse(os.path.exists(self.config_path))

    def test_config_target_skips_example_file(self):
        cfg = copy.deepcopy(config_mod.DEFAULT)
        cfg["_config_path"] = os.path.join(config_mod.PROJECT_ROOT, "config.example.json")
        self.assertTrue(config_mod.config_target(cfg).endswith("config.json"))
        cfg["_config_path"] = self.config_path
        self.assertEqual(config_mod.config_target(cfg), self.config_path)

    def test_mode_local_persists_and_needs_no_cloud_key(self):
        _, data = self._get("/settings")
        self.assertEqual(data["hybrid"]["mode"], "hybrid")

        _, saved = self._post("/settings", {"hybrid": {"mode": "local"}})
        self.assertTrue(saved["ok"])
        raw = self._config_file()
        self.assertEqual(raw["hybrid"]["mode"], "local")
        # 旧字段跟着同步，两份表示不会互相矛盾
        self.assertFalse(raw["hybrid"]["enabled"])
        self.assertEqual(self._get("/settings")[1]["hybrid"]["mode"], "local")
        # 只用本地不碰云端，首次打开不该再弹设置面板
        self.assertFalse(settings_mod.needs_setup(self.httpd.cfg))

    def test_legacy_enabled_syncs_mode(self):
        self._post("/settings", {"hybrid": {"enabled": False}})
        raw = self._config_file()
        self.assertFalse(raw["hybrid"]["enabled"])
        self.assertEqual(raw["hybrid"]["mode"], "direct")

    def test_mode_rejects_unknown_value(self):
        code, body = self._post("/settings", {"hybrid": {"mode": "offline"}}, expect=400)
        self.assertIn("hybrid", body["error"])
        self.assertFalse(os.path.exists(self.config_path))

    def test_update_keeps_unrelated_sections(self):
        config_file.update(self.config_path, {"profiles": {"cloud": {"model": "m1"}}})
        config_file.update(self.config_path, {"hybrid": {"enabled": False}})
        raw = self._config_file()
        self.assertEqual(raw["profiles"]["cloud"]["model"], "m1")
        self.assertFalse(raw["hybrid"]["enabled"])


if __name__ == "__main__":
    unittest.main()
