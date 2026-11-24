"""记忆层：事件只追加、默认共用一个会话、状态卡能重建、续跑不产生孤立 tool 消息。"""

import os
import tempfile
import unittest
import unittest.mock

from mote import memory as memory_mod


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = memory_mod.Memory(self.tmp.name, "s-test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_events_append_only(self):
        self.memory.user(1, "现在几点")
        self.memory.assistant(1, "十点整")
        self.assertEqual([e["t"] for e in self.memory.events()], ["user", "assistant"])
        # 再写一条不能让前两条消失
        self.memory.user(2, "明天呢")
        self.assertEqual(len(self.memory.events()), 3)

    def test_ensure_writes_session_event_only_once(self):
        self.memory.ensure(profile="local", model="m")
        self.memory.ensure(profile="local", model="m")
        kinds = [e["t"] for e in self.memory.events()]
        self.assertEqual(kinds.count("session"), 1)

    def test_turns_count(self):
        self.memory.user(1, "a")
        self.memory.tool(1, "now", "{}", "2026-11-22 ...")
        self.memory.user(2, "b")
        self.assertEqual(self.memory.turns(), 2)

    def test_state_card_rebuilds_from_events(self):
        self.memory.user(1, "现在几点")
        self.memory.tool(1, "now", "{}", "2026-11-22 10:09:52 星期日")
        self.memory.assistant(1, "现在是十点零九分")
        card = self.memory.state_card()
        self.assertIn("第 1 轮", card)
        self.assertIn("10:09:52", card)
        self.assertIn("上次回答要点", card)

    def test_state_card_empty(self):
        self.assertIn("新会话", self.memory.state_card())

    def test_state_card_truncated(self):
        for i in range(1, 30):
            self.memory.user(i, "问题" * 200)
        card = self.memory.state_card(max_chars=300)
        self.assertLessEqual(len(card), 300)
        self.assertIn("截断", card)

    def test_state_card_shows_compaction_summary(self):
        self.memory.user(1, "早前的问题")
        self.memory.compact(3, 9000, 2000, 5, "问「早前的问题」；答「早前的答案」")
        card = self.memory.state_card()
        self.assertIn("已归档", card)
        self.assertIn("早前的答案", card)

    def test_tool_failure_is_marked(self):
        self.memory.tool(1, "now", "{}", "参数不匹配", ok=False)
        self.assertIn("失败", self.memory.state_card())

    def test_thoughts_skip_empty_and_keep_order(self):
        self.memory.note_think(1, "先确认时区")
        self.memory.note_think(1, "   ")
        self.memory.note_think(2, "再换算星期")
        notes = self.memory.thoughts(3)
        self.assertEqual([n["text"] for n in notes], ["先确认时区", "再换算星期"])

    def test_digest_marks_compaction(self):
        self.memory.user(1, "问题")
        self.memory.assistant(1, "回答")
        self.memory.compact(2, 100, 20, 3, "摘要内容")
        text = self.memory.digest()
        self.assertIn("轮 1", text)
        self.assertIn("压缩", text)

    def test_rebuild_messages_drops_tool_and_leading_assistant(self):
        self.memory.assistant(0, "上一轮残留")
        self.memory.user(1, "问 1")
        self.memory.assistant(1, "", [{"name": "now", "arguments": "{}"}])
        self.memory.tool(1, "now", "{}", "2026-11-22 10:09:52")
        self.memory.assistant(2, "答 2")
        rebuilt = self.memory.rebuild_messages(10)
        self.assertEqual([m["role"] for m in rebuilt], ["user", "assistant"])
        self.assertEqual(rebuilt[1]["content"], "答 2")
        # 绝不能出现孤立 tool 消息
        self.assertFalse(any(m["role"] == "tool" for m in rebuilt))

    def test_broken_line_does_not_break_history(self):
        self.memory.user(1, "好的一行")
        with open(self.memory.events_path, "a", encoding="utf-8") as f:
            f.write('{"t":"user","ts":"2026-01-01T00:00:00","text":"被截断的一')  # 进程被杀留下的半行
        self.assertEqual(len(self.memory.events()), 1)


class SessionDirTest(unittest.TestCase):
    """这几条盯着一个用户体感问题：不该每问一句就多一个文件夹。"""

    def test_default_session_is_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = memory_mod.Memory(tmp)
            second = memory_mod.Memory(tmp)
            self.assertEqual(first.session_id, memory_mod.DEFAULT_SESSION)
            self.assertEqual(first.session_id, second.session_id)

            first.user(1, "第一次")
            second.user(2, "第二次")
            rows = memory_mod.list_sessions(tmp)
            self.assertEqual(len(rows), 1)          # 只有一个目录
            self.assertEqual(rows[0]["turns"], 2)   # 两次都在里面

    def test_session_has_only_two_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = memory_mod.Memory(tmp)
            memory.ensure(profile="local", model="m")
            memory.user(1, "你好")
            memory.assistant(1, "你好")
            memory.note_think(1, "想一下")
            names = sorted(os.listdir(memory.home))
            self.assertEqual(names, ["events.jsonl", "thoughts.jsonl"])

    def test_new_session_id_is_unique(self):
        self.assertNotEqual(memory_mod.new_session_id(), memory_mod.new_session_id())


class SessionListTest(unittest.TestCase):
    def test_list_sessions_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = memory_mod.Memory(tmp, "s-1")
            second = memory_mod.Memory(tmp, "s-2")
            with unittest.mock.patch.object(
                    memory_mod, "_now",
                    side_effect=["2026-01-02T09:00:00", "2026-02-03T09:00:00"]):
                first.user(1, "第一个会话")
                second.user(1, "第二个会话")
            rows = memory_mod.list_sessions(tmp)
            self.assertEqual([r["id"] for r in rows], ["s-2", "s-1"])
            self.assertEqual(rows[0]["preview"], "第二个会话")

    def test_date_follows_last_question_not_log_mtime(self):
        """切分支、重命名都会追加事件；日期只认最后一次提问，不能被这些操作顶到最新。"""
        with tempfile.TemporaryDirectory() as tmp:
            memory = memory_mod.Memory(tmp, "s-date")
            with unittest.mock.patch.object(memory_mod, "_now",
                                            return_value="2026-03-05T10:00:00"):
                memory.user(1, "老问题", node="n-1")
            memory.set_cursor("n-1")
            memory.rename("改个名字")
            os.utime(memory.events_path, (2_000_000_000, 2_000_000_000))
            row = memory_mod.list_sessions(tmp)[0]
            self.assertEqual(row["date"], "2026-03-05T10:00:00")

            with unittest.mock.patch.object(memory_mod, "_now",
                                            return_value="2026-04-06T11:22:33"):
                memory.user(2, "新问题", node="n-2", parent="n-1")
            self.assertEqual(memory_mod.list_sessions(tmp)[0]["date"],
                             "2026-04-06T11:22:33")


class ConversationTest(unittest.TestCase):
    """网页要能按会话把整段历史读回来，并标出每轮真实加载过的镜头。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = memory_mod.Memory(self.tmp.name, "s-web")

    def tearDown(self):
        self.tmp.cleanup()

    def test_conversation_rebuilds_pairs_and_lenses(self):
        self.memory.user(1, "问题一")
        self.memory.tool(1, "use_lens", '{"lens":"inversion"}', "清单")
        self.memory.tool(1, "use_lens", '{"lens":"first_principles"}', "清单")
        self.memory.assistant(1, "**结论**：先做小实验。")
        self.memory.user(2, "问题二")
        self.memory.assistant(2, "")

        rows = self.memory.conversation()
        self.assertEqual([(r["role"], r["text"]) for r in rows], [
            ("user", "问题一"), ("assistant", "**结论**：先做小实验。"), ("user", "问题二")])
        self.assertEqual(rows[1]["lenses"], ["inversion", "first_principles"])

    def test_rename_adds_event_without_new_file(self):
        self.memory.user(1, "问题")
        self.memory.rename("新标题")
        row = memory_mod.list_sessions(self.tmp.name)[0]
        self.assertEqual(row["title"], "新标题")
        self.assertEqual(sorted(os.listdir(self.memory.home)), ["events.jsonl"])

    def test_list_sessions_exposes_title(self):
        self.memory.user(1, "该不该现在换工作")
        row = memory_mod.list_sessions(self.tmp.name)[0]
        self.assertEqual(row["title"], "该不该现在换工作")


    def test_thinking_survives_conversation_rebuild(self):
        self.memory.user(1, "怎么选")
        self.memory.assistant(1, "结论：先试一步。", model="local", route="local",
                              thinking="先拆问题，再看约束。")
        row = self.memory.conversation()[1]
        self.assertEqual(row["thinking"], "先拆问题，再看约束。")
        self.assertEqual(row["model"], "local")


class BranchTest(unittest.TestCase):
    """问答节点、编辑分叉、删除子树与当前分支指针。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = memory_mod.Memory(self.tmp.name, "s-branch")

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self):
        self.memory.user(1, "问题 A", node="n1", parent=None)
        self.memory.assistant(1, "回答 A", node="n1")
        self.memory.user(2, "问题 B", node="n2", parent="n1")
        self.memory.assistant(2, "回答 B", node="n2")
        self.memory.user(3, "问题 C", node="n3", parent="n1")
        self.memory.assistant(3, "回答 C", node="n3")

    def test_branch_tree_keeps_siblings(self):
        self._seed()
        tree = self.memory.branch_tree()
        self.assertEqual({n["id"] for n in tree["nodes"]}, {"n1", "n2", "n3"})
        by_id = {n["id"]: n for n in tree["nodes"]}
        self.assertEqual(by_id["n1"]["children"], ["n2", "n3"])
        self.assertEqual(tree["active"], "n3")

    def test_conversation_follows_cursor_branch(self):
        self._seed()
        self.memory.set_cursor("n2")
        rows = self.memory.conversation()
        self.assertEqual([r["text"] for r in rows],
                         ["问题 A", "回答 A", "问题 B", "回答 B"])
        self.assertEqual(rows[-1]["node"], "n2")
        self.assertNotIn("问题 C", [r["text"] for r in rows])

    def test_main_branch_wins_over_cursor_on_reopen(self):
        self._seed()
        self.memory.set_cursor("n3")
        self.assertEqual(self.memory.active_node(), "n3")
        self.memory.set_main("n2")
        # 主分支优先：即便游标停在 C，打开会话仍落在 B 链路
        self.assertEqual(self.memory.active_node(), "n2")
        reopened = memory_mod.Memory(self.memory.root, self.memory.session_id)
        self.assertEqual(reopened.active_node(), "n2")
        self.assertEqual([r["text"] for r in reopened.conversation()][-1], "回答 B")
        # 之后又在别处切换分支（写新游标），主分支依然生效
        reopened.set_cursor("n3")
        self.assertEqual(reopened.active_node(), "n2")

    def test_main_branch_can_be_cleared(self):
        self._seed()
        self.memory.set_main("n2")
        self.memory.set_cursor("n3")
        self.assertEqual(self.memory.active_node(), "n2")
        self.memory.set_main(None)
        self.assertEqual(self.memory.active_node(), "n3")

    def test_main_branch_dropped_when_node_deleted(self):
        self._seed()
        self.memory.set_main("n3")
        self.assertEqual(self.memory.branch_tree()["main"], "n3")
        self.memory.delete_node("n3")
        self.assertIsNone(self.memory.main_node())
        self.assertEqual(self.memory.active_node(), "n2")
        # 已删除的节点不能再被设为主分支
        self.assertIsNone(self.memory.set_main("n3"))

    def test_branch_view_can_follow_any_chain(self):
        self._seed()
        self.memory.set_main("n3")
        # 显式指定节点时按该节点出树，主分支只作为标记一起返回
        tree = self.memory.branch_tree(node="n2")
        self.assertEqual(tree["active"], "n2")
        self.assertEqual(tree["main"], "n3")
        self.assertEqual(tree["main_path"], ["n1", "n3"])
        self.assertEqual([r["text"] for r in self.memory.conversation(node="n2")][-1],
                         "回答 B")
        # 打开会话仍落在主分支
        self.assertEqual(self.memory.active_node(), "n3")

    def test_main_branch_moves_with_new_turn(self):
        self._seed()
        self.memory.set_main("n2")
        self.memory.user(4, "接着问", node="n4", parent="n2")
        self.memory.assistant(4, "答四", node="n4")
        self.assertEqual(self.memory.main_node(), "n4")
        # 从分叉点另起的提问不算主分支的延续
        self.memory.user(5, "分叉问", node="n5", parent="n1")
        self.assertEqual(self.memory.main_node(), "n4")

    def test_main_event_does_not_leak_into_messages(self):
        self._seed()
        self.memory.set_main("n2")
        rows = self.memory.conversation()
        self.assertEqual([r["text"] for r in rows],
                         ["问题 A", "回答 A", "问题 B", "回答 B"])
        self.assertEqual(self.memory.turns(), 3)
        self.assertNotIn("main", self.memory.export_markdown())
        self.assertEqual(self.memory.branch_tree()["main"], "n2")

    def test_delete_node_removes_subtree_from_context(self):
        self._seed()
        self.memory.user(4, "问题 D", node="n4", parent="n3")
        self.memory.assistant(4, "回答 D", node="n4")
        removed = self.memory.delete_node("n3")
        self.assertEqual(set(removed), {"n3", "n4"})
        # 删掉当前分支后回退到剩下的兄弟分支，而不是停在分叉点
        self.assertEqual(self.memory.active_node(), "n2")
        self.assertNotIn("问题 C", self.memory.state_card())
        self.assertNotIn("问题 D", self.memory.state_card())
        tree = self.memory.branch_tree()
        self.assertEqual({n["id"] for n in tree["nodes"]}, {"n1", "n2"})

    def test_delete_is_append_only(self):
        self._seed()
        before = len(self.memory.events())
        self.memory.delete_node("n2")
        events = self.memory.events()
        self.assertEqual([e["t"] for e in events[before:]], ["delete"])
        self.assertEqual([e["t"] for e in events[:before]],
                         [e["t"] for e in events[:before]])

    def test_delete_only_current_branch_keeps_siblings(self):
        self.memory.user(1, "问题 A", node="n1", parent=None)
        self.memory.assistant(1, "回答 A", node="n1")
        self.memory.user(2, "问题 B", node="n2", parent="n1")
        self.memory.assistant(2, "回答 B", node="n2")
        self.memory.user(3, "问题 C", node="n3", parent="n2")
        self.memory.assistant(3, "回答 C", node="n3")
        self.memory.user(4, "问题 D", node="n4", parent="n2")
        self.memory.assistant(4, "回答 D", node="n4")
        self.memory.user(5, "问题 E", node="n5", parent="n4")
        self.memory.assistant(5, "回答 E", node="n5")
        self.memory.set_cursor("n3")

        removed = self.memory.delete_node("n2")
        self.assertEqual(set(removed), {"n2", "n3"})
        tree = self.memory.branch_tree()
        self.assertEqual({item["id"] for item in tree["nodes"]}, {"n1", "n4", "n5"})
        self.assertEqual(self.memory.active_node(), "n1")
        self.assertNotIn("问题 D", self.memory.state_card())

    def test_switch_to_fork_shows_branch_continuation(self):
        self._seed()
        self.memory.user(4, "问题 D", node="n4", parent="n3")
        self.memory.assistant(4, "回答 D", node="n4")

        self.memory.set_cursor("n2")
        self.assertEqual(self.memory.active_node(), "n2")
        self.assertEqual([m["text"] for m in self.memory.conversation()],
                         ["问题 A", "回答 A", "问题 B", "回答 B"])

        self.memory.set_cursor("n3")
        self.assertEqual(self.memory.active_node(), "n4")
        self.assertEqual([m["text"] for m in self.memory.conversation()],
                         ["问题 A", "回答 A", "问题 C", "回答 C", "问题 D", "回答 D"])

    def test_root_level_fork_keeps_siblings(self):
        self.memory.user(1, "问题 A", node="n1", parent=None)
        self.memory.assistant(1, "回答 A", node="n1")
        self.memory.user(2, "问题 A 改", node="n2", parent=None)
        self.memory.assistant(2, "回答 A 改", node="n2")

        tree = self.memory.branch_tree()
        self.assertEqual({n["id"] for n in tree["nodes"]}, {"n1", "n2"})
        self.assertEqual([n["parent"] for n in tree["nodes"]], [None, None])

        self.memory.set_cursor("n1")
        self.assertEqual([m["text"] for m in self.memory.conversation()],
                         ["问题 A", "回答 A"])

    def test_legacy_log_infers_linear_nodes(self):
        self.memory.user(1, "旧问题")
        self.memory.assistant(1, "旧回答")
        self.assertEqual([n["id"] for n in self.memory.branch_tree()["nodes"]],
                         ["legacy-1"])
        self.assertEqual([m["text"] for m in self.memory.conversation()],
                         ["旧问题", "旧回答"])

    def test_branch_tree_clips_long_questions(self):
        self.memory.user(1, "长" * 400, node="n1", parent=None)
        node = self.memory.branch_tree()["nodes"][0]
        self.assertLessEqual(len(node["text"]), 121)
        # 完整问题仍保留在历史与导出里
        self.assertEqual(self.memory.conversation()[0]["text"], "长" * 400)


class ExportTest(unittest.TestCase):
    """导出要能脱离 Mote 阅读：标题、问题、回答、模型来源都在。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = memory_mod.Memory(self.tmp.name, "s-export")
        self.memory.ensure(profile="local", model="deepseek-chat")
        self.memory.rename("换工作判断")
        self.memory.user(1, "该不该换工作\n第二行", node="n1", parent=None)
        self.memory.assistant(1, "先做**小实验**。", node="n1", model="deepseek-chat",
                              route="cloud", thinking="先拆约束")
        self.memory.user(2, "怎么找隐患", node="n2", parent="n1")
        self.memory.assistant(2, "反向清单。", node="n2", model="qwen3.5:4b", route="local")

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown_keeps_question_answer_and_source(self):
        text = self.memory.export_markdown()
        self.assertIn("# 换工作判断", text)
        self.assertIn("> 该不该换工作", text)
        self.assertIn("> 第二行", text)
        self.assertIn("## 1. 你", text)
        self.assertIn("## 2. 你", text)
        self.assertIn("先做**小实验**。", text)
        self.assertIn("云端 · deepseek-chat", text)
        self.assertIn("本地 · qwen3.5:4b", text)
        self.assertIn("思考过程（4 字）", text)
        self.assertIn("`s-export`", text)

    def test_markdown_can_skip_thinking(self):
        text = self.memory.export_markdown(with_thinking=False)
        self.assertNotIn("思考过程", text)
        self.assertNotIn("先拆约束", text)

    def test_payload_carries_all_branches(self):
        self.memory.user(3, "怎么找隐患（改）", node="n3", parent="n1")
        self.memory.assistant(3, "另一条回答。", node="n3", model="deepseek-chat",
                              route="cloud")
        self.memory.set_cursor("n2")
        payload = self.memory.export_payload()
        self.assertEqual(payload["format"], "mote-session/1")
        self.assertEqual(payload["title"], "换工作判断")
        self.assertEqual(payload["active"], "n2")
        self.assertEqual(payload["counts"], {"turns": 2, "nodes": 3})
        self.assertEqual(set(payload["branches"]), {"n1", "n2", "n3"})
        self.assertEqual(payload["branches"]["n1"]["answer"], "先做**小实验**。")
        self.assertEqual(payload["branches"]["n1"]["thinking"], "先拆约束")
        # 当前分支是 n2，兄弟分支只出现在树与 branches 里
        self.assertNotIn("另一条回答。", [m.get("text") for m in payload["messages"]])
        self.assertIn("另一条回答。", payload["branches"]["n3"]["answer"])

    def test_filename_is_safe(self):
        self.memory.rename('a/b:c "d"')
        self.assertEqual(self.memory.export_filename("md"), "a-b-c-d.md")

    def test_thinking_for_node(self):
        self.assertEqual(self.memory.thinking_for("n1"), "先拆约束")
        self.assertEqual(self.memory.thinking_for("n2"), "")
        self.assertEqual(self.memory.thinking_for("nope"), "")


class SearchTest(unittest.TestCase):
    """跨会话检索：多词需同时命中，删除的节点不再出现。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.first = memory_mod.Memory(self.tmp.name, "s-a")
        self.first.user(1, "工作太累", node="n1", parent=None)
        self.first.assistant(1, "先看约束再决定。", node="n1")
        self.second = memory_mod.Memory(self.tmp.name, "s-b")
        self.second.user(1, "阳台光照不够", node="n1", parent=None)
        self.second.assistant(1, "下午搬到西边。", node="n1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_matching_session_is_returned(self):
        data = memory_mod.search_sessions(self.tmp.name, "约束")
        self.assertEqual(data["total"], 1)
        hit = data["results"][0]
        self.assertEqual((hit["session"], hit["role"], hit["node"]), ("s-a", "assistant", "n1"))
        self.assertIn("\x01约束\x02", hit["snippet"])
        self.assertEqual(hit["title"], "工作太累")

    def test_all_terms_must_match(self):
        self.assertEqual(memory_mod.search_sessions(self.tmp.name, "约束 决定")["total"], 1)
        self.assertEqual(memory_mod.search_sessions(self.tmp.name, "约束 光照")["total"], 0)

    def test_deleted_node_disappears_from_search(self):
        self.first.delete_node("n1")
        self.assertEqual(memory_mod.search_sessions(self.tmp.name, "工作")["total"], 0)

    def test_empty_query_returns_nothing(self):
        self.assertEqual(memory_mod.search_sessions(self.tmp.name, "  ")["results"], [])

    def test_limit_is_respected(self):
        for index in range(2, 10):
            self.first.user(index, "重复的约束问题 %d" % index,
                            node="n%d" % index, parent="n1")
        data = memory_mod.search_sessions(self.tmp.name, "约束", limit=3)
        self.assertEqual(len(data["results"]), 3)
        self.assertGreater(data["total"], 3)


class SessionListCacheTest(unittest.TestCase):
    """会话列表按 mtime+size 缓存：没写盘就不重复解析 50MB 事件日志。"""

    def test_reuses_cache_until_log_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = memory_mod.Memory(tmp, "s-cache")
            memory.user(1, "第一条")
            first = memory_mod.list_sessions(tmp)
            self.assertEqual(first[0]["turns"], 1)

            with unittest.mock.patch.object(
                    memory_mod.Memory, "events",
                    side_effect=AssertionError("不应重新读取事件日志")):
                second = memory_mod.list_sessions(tmp)
            self.assertEqual(second, first)

            memory.user(2, "第二条")
            self.assertEqual(memory_mod.list_sessions(tmp)[0]["turns"], 2)

    def test_different_roots_do_not_share_rows(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            memory_mod.Memory(one, "s-a").user(1, "甲")
            memory_mod.Memory(two, "s-b").user(1, "乙")
            self.assertEqual(memory_mod.list_sessions(one)[0]["title"], "甲")
            self.assertEqual(memory_mod.list_sessions(two)[0]["title"], "乙")

    def test_cache_rows_are_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_mod.Memory(tmp, "s-copy").user(1, "标题")
            rows = memory_mod.list_sessions(tmp)
            rows[0]["title"] = "被改掉"
            self.assertEqual(memory_mod.list_sessions(tmp)[0]["title"], "标题")

    def test_index_survives_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_mod.Memory(tmp, "s-index").user(1, "持久标题")
            memory_mod.list_sessions(tmp)
            self.assertTrue(os.path.exists(os.path.join(tmp, "session_index.json")))
            memory_mod._LIST_CACHE.clear()
            memory_mod._INDEX_CACHE.clear()
            with unittest.mock.patch.object(
                    memory_mod.Memory, "events",
                    side_effect=AssertionError("索引命中时不应读日志")):
                rows = memory_mod.list_sessions(tmp)
            self.assertEqual(rows[0]["title"], "持久标题")
            self.assertEqual(rows[0]["turns"], 1)


if __name__ == "__main__":
    unittest.main()
