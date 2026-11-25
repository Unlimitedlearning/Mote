"""DeepSeek 导出数据转换：完整分支树、当前路径、思维与标题。"""

import importlib.util
import json
import os
import pathlib
import tempfile
import unittest

from mote.services.conversation import Conversation

MODULE_PATH = pathlib.Path(__file__).resolve().parent.parent / "tools" / "import_deepseek.py"
spec = importlib.util.spec_from_file_location("import_deepseek", MODULE_PATH)
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def message(mid, parent, role, fragments, ts="2026-06-29T09:30:15.010Z"):
    return {"id": mid, "parent_id": parent, "role": role, "status": "FINISHED",
            "inserted_at": ts, "fragments": fragments}


class ImportDeepSeekTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "deepseek_data")
        self.sessions = os.path.join(self.source, "chat_sessions")
        os.makedirs(self.sessions)
        session = {
            "id": "test-session", "title": "原始标题",
            "inserted_at": "2026-06-29T09:30:00.000Z",
            "updated_at": "2026-06-29T10:00:00.000Z",
            "current_message_id": 4,
            "messages": [
                message(1, None, "USER", [{"type": "REQUEST", "content": "第一个问题"}]),
                message(2, 1, "ASSISTANT", [
                    {"type": "THINK", "content": "先看约束"},
                    {"type": "RESPONSE", "content": "回答一"},
                    {"type": "CONTENT_RISK", "content": "忽略我"}]),
                message(3, 2, "USER", [{"type": "REQUEST", "content": "第二个问题"}]),
                message(4, 3, "ASSISTANT", [
                    {"type": "RESPONSE", "content": "回答二"}]),
                message(5, 2, "USER", [{"type": "REQUEST", "content": "被舍弃的分支"}]),
            ],
        }
        with open(os.path.join(self.sessions, "test-session.json"), "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False)
        with open(os.path.join(self.source, "chat_session_index.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": "test-session", "title": "导入后的标题"}], f, ensure_ascii=False)
        self.session = session

    def tearDown(self):
        self.tmp.cleanup()

    def _events(self, root):
        path = os.path.join(root, "sessions", "test-session", "events.jsonl")
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_full_branches_thinking_and_cursor(self):
        root = os.path.join(self.tmp.name, "memory")
        code = importer.main(["--source", self.source, "--root", root])
        self.assertEqual(code, 0)
        events = self._events(root)
        kinds = [e["t"] for e in events]
        self.assertEqual(kinds, ["session", "title", "user", "assistant",
                                 "user", "assistant", "user", "cursor"])
        self.assertEqual(events[1]["title"], "导入后的标题")
        self.assertEqual(events[3]["thinking"], "先看约束")
        self.assertEqual(events[3]["route"], "import")
        self.assertEqual(events[3]["node"], "ds-1-2")
        self.assertEqual(events[6]["text"], "被舍弃的分支")
        self.assertEqual(events[7]["node"], "ds-3-4")
        self.assertNotIn("忽略我", json.dumps(events, ensure_ascii=False))

        memory = Conversation(root, "test-session")
        tree = memory.branch_tree()
        by_id = {item["id"]: item for item in tree["nodes"]}
        self.assertEqual(set(by_id), {"ds-1-2", "ds-3-4", "ds-5-x"})
        self.assertEqual(set(by_id["ds-1-2"]["children"]), {"ds-3-4", "ds-5-x"})
        self.assertEqual(tree["active"], "ds-3-4")
        self.assertIn("第二个问题", [m["text"] for m in memory.conversation()])
        self.assertNotIn("被舍弃的分支", [m["text"] for m in memory.conversation()])

        with open(os.path.join(root, "sessions", "test-session", "thoughts.jsonl"),
                  encoding="utf-8") as f:
            thoughts = [json.loads(x) for x in f]
        self.assertEqual(thoughts[0]["text"], "先看约束")
        self.assertEqual(thoughts[0]["node"], "ds-1-2")

    def test_current_only_keeps_single_branch(self):
        args = importer.parse_args(["--source", self.source, "--root", self.tmp.name,
                                    "--current-only"])
        result, reason = importer.convert(self.session, "标题", args)
        self.assertFalse(reason)
        text = json.dumps(result["events"], ensure_ascii=False)
        self.assertNotIn("被舍弃的分支", text)
        self.assertIn("回答二", text)

    def test_skip_existing_and_force(self):
        root = os.path.join(self.tmp.name, "memory")
        importer.main(["--source", self.source, "--root", root])
        events_path = os.path.join(root, "sessions", "test-session", "events.jsonl")
        before = os.path.getmtime(events_path)
        importer.main(["--source", self.source, "--root", root])
        self.assertEqual(os.path.getmtime(events_path), before)
        importer.main(["--source", self.source, "--root", root, "--force"])
        self.assertTrue(os.path.exists(events_path))

    def test_sync_upgrades_old_format_only(self):
        root = os.path.join(self.tmp.name, "memory")
        target = os.path.join(root, "sessions", "test-session")
        os.makedirs(target)
        old_events = [
            {"t": "session", "ts": "2026-06-29T09:30:00", "profile": "deepseek-import"},
            {"t": "user", "ts": "2026-06-29T09:30:15", "turn": 1, "text": "旧问题"},
            {"t": "assistant", "ts": "2026-06-29T09:30:16", "turn": 1,
             "text": "旧回答", "route": "import", "model": "deepseek"},
        ]
        with open(os.path.join(target, "events.jsonl"), "w", encoding="utf-8") as f:
            for event in old_events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

        importer.main(["--source", self.source, "--root", root, "--sync"])
        self.assertTrue(any(e.get("node") for e in self._events(root)))

        with open(os.path.join(target, "events.jsonl"), "w", encoding="utf-8") as f:
            for event in old_events + [{"t": "assistant", "ts": "2026-06-29T10:01:00",
                                        "turn": 2, "text": "新对话", "route": "local"}]:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        importer.main(["--source", self.source, "--root", root, "--sync"])
        events = self._events(root)
        self.assertFalse(any(e.get("node") for e in events))
        self.assertIn("新对话", [e.get("text") for e in events])

    def test_max_turns_keeps_recent_depth(self):
        args = importer.parse_args(["--source", self.source, "--root", self.tmp.name,
                                    "--max-turns", "1"])
        result, reason = importer.convert(self.session, "标题", args)
        self.assertFalse(reason)
        turns = [e["turn"] for e in result["events"] if e["t"] == "user"]
        self.assertEqual(turns, [2, 2])


if __name__ == "__main__":
    unittest.main()
