"""Loop 端到端（不联网）：用脚本化假模型驱动 Agent，检查镜头链路与记忆。

Agent 唯一的外部依赖是 self.llm.chat(...)。换成按剧本返回的假客户端，
整个 loop 就能离线跑完——包括工具调用、压缩、续跑这些路径。
断言看 client.calls：那是模型实际收到的 messages，比只看最终文本更可复现。
"""

import copy
import tempfile
import unittest

from mote.core import config as config_mod
from mote.core.ids import DEFAULT_SESSION
from mote.services import library
from mote.services import settings as settings_mod
from mote.services.conversation import Conversation
from mote.services.agent import Agent
from mote.infra.llm import Reply


class ScriptedLLM:
    """按剧本返回 Reply 的假客户端，记录每次收到的 messages 快照。"""

    def __init__(self, replies, stream_pieces=None):
        self.replies = list(replies)
        self.calls = []
        self.deltas = []
        self.max_tokens = 2048

    def chat(self, messages, tools=None, stream=False, on_delta=None):
        self.calls.append(copy.deepcopy(messages))
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        if on_delta and reply.content:
            on_delta(reply.content)
        return reply


def make_cfg(memory_dir, **overrides):
    """测试配置：base_url 指向 discard 端口，漏注入假客户端会立刻失败。"""
    cfg = copy.deepcopy(config_mod.DEFAULT)
    cfg["profiles"]["local"]["base_url"] = "http://127.0.0.1:9/v1"
    cfg["agent"].update(overrides)
    cfg["_memory_root"] = memory_dir
    return cfg


def lens_call(index, key="inversion"):
    return {"id": f"c{index}", "name": "use_lens", "arguments": '{"lens":"' + key + '"}'}


class AgentLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, replies, **agent_cfg):
        client = ScriptedLLM(replies)
        agent = Agent(make_cfg(self.tmp.name, **agent_cfg), llm_client=client,
                      memory_root=self.tmp.name, system_prompt="SYS")
        return agent, client

    def test_tool_round_trip(self):
        agent, client = self.build([
            Reply(tool_calls=[lens_call(1)]),
            Reply(content="建议：先定义失败条件，再倒推今天能做的预防。"),
        ])
        result = agent.ask("这个项目怎么推进")
        self.assertIn("倒推", result["text"])
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["tools"], [{"name": "use_lens", "ok": True}])
        self.assertEqual(result["lenses"], ["inversion"])

        second = client.calls[1]
        tool_msgs = [m for m in second if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn("提问清单", tool_msgs[0]["content"])
        self.assertEqual(tool_msgs[0]["tool_call_id"], "c1")

        self.assertEqual(second[-1]["role"], "system")
        self.assertIn("状态卡", second[-1]["content"])
        self.assertFalse(any("状态卡" in (m.get("content") or "") for m in agent.messages))

        kinds = [e["t"] for e in agent.memory.events()]
        self.assertEqual(kinds, ["session", "user", "assistant", "tool", "assistant"])

    def test_lens_state_guards(self):
        # 同一轮内重复加载：工具层拒绝，镜头只算一次
        agent, _ = self.build([
            Reply(tool_calls=[lens_call(1)]),
            Reply(tool_calls=[lens_call(2)]),
            Reply(content="基于已加载的镜头作答。"),
        ])
        result = agent.ask("换个角度")
        self.assertEqual(result["lenses"], ["inversion"])
        tool_events = [e for e in agent.memory.events() if e["t"] == "tool"]
        self.assertFalse(tool_events[1]["ok"])
        self.assertIn("不要重复加载", tool_events[1]["result"])

        # 每轮总量上限：第四个镜头被截断
        agent, _ = self.build([
            Reply(tool_calls=[lens_call(i, key) for i, key in
                              enumerate(("inversion", "first_principles", "systems", "gray"), 1)]),
            Reply(content="四个镜头已经到上限。"),
        ], lenses_per_turn=3)
        self.assertEqual(agent.ask("复杂问题")["lenses"],
                         ["inversion", "first_principles", "systems"])

        # 状态按轮重置：下一轮仍能加载同一个镜头
        agent, _ = self.build([
            Reply(tool_calls=[lens_call(1)]),
            Reply(content="第一轮"),
            Reply(tool_calls=[lens_call(2)]),
            Reply(content="第二轮"),
        ], lenses_per_turn=1)
        agent.ask("第一轮问题")
        self.assertEqual(agent.ask("第二轮问题")["lenses"], ["inversion"])

    def test_answer_without_tool(self):
        agent, _ = self.build([Reply(content="你好")])
        pieces = []
        agent.on_delta = pieces.append
        result = agent.ask("在吗")
        self.assertEqual(result["text"], "你好")
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["lenses"], [])
        self.assertEqual("".join(pieces), "你好")

    def test_max_steps_guard(self):
        replies = [Reply(tool_calls=[lens_call(i, key)]) for i, key in
                   enumerate(("inversion", "first_principles", "systems"), 1)]
        agent, _ = self.build(replies, max_steps=2)
        result = agent.ask("一直加载镜头")
        self.assertIn("上限", result["text"])

    def test_empty_question_rejected(self):
        agent, _ = self.build([])
        with self.assertRaises(ValueError):
            agent.ask("   ")

    def test_system_prompt_carries_catalog(self):
        cfg = make_cfg(self.tmp.name)
        prompt = settings_mod.system_prompt(cfg)
        self.assertIn("[元认知]", prompt)
        self.assertIn("inversion 逆向思维", prompt)
        self.assertNotIn("提问清单：", prompt)  # 详细清单按需加载，不进固定前缀

    def test_state_card_feeds_next_turn(self):
        agent, client = self.build([Reply(content="第一个答案")], state_card_chars=1600)
        agent.ask("第一个问题")
        client.replies = [Reply(content="第二个答案")]
        agent.ask("第二个问题")
        card = client.calls[1][-1]["content"]
        self.assertIn("第一个问题", card)
        self.assertIn("第一个答案", card)

    def test_cache_prefix_stable_across_turns(self):
        """缓存不变量：system + 历史是稳定前缀，只有末尾状态卡每轮变化。"""
        agent, client = self.build([Reply(content="答案一"), Reply(content="答案二")],
                                   state_card_chars=2000)
        agent.ask("问题一")
        agent.ask("问题二")
        first, second = client.calls[0], client.calls[1]
        self.assertEqual(first[0], second[0])
        stable = first[:-1]
        self.assertEqual(second[:len(stable)], stable)
        self.assertGreater(len(second), len(first))
        self.assertNotEqual(first[-1], second[-1])
        self.assertEqual(first[-1]["role"], "system")
        self.assertIn("状态卡", first[-1]["content"])


class CompactionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_compaction_keeps_state_and_replays_thoughts(self):
        replies = [
            Reply(content="甲" * 400, reasoning="先把括号里的先算"),
            Reply(content="乙" * 400, reasoning="再乘 5"),
            Reply(content="丙" * 400, reasoning="最后核对单位"),
            Reply(content="丁" * 400),
        ]
        agent = Agent(
            make_cfg(self.tmp.name, compact_context_chars=400, compact_keep_turns=1,
                     compact_keep_tool_turns=1, compact_keep_msg_chars=100,
                     compact_thoughts=3),
            llm_client=ScriptedLLM(replies), memory_root=self.tmp.name, system_prompt="SYS")
        for text in ("一", "二", "三", "四"):
            agent.ask(text)

        compacts = [e for e in agent.memory.events() if e["t"] == "compact"]
        self.assertTrue(compacts)
        event = compacts[0]
        self.assertGreater(event["from_chars"], event["to_chars"])
        self.assertTrue(event["summary"])

        notices = [m["content"] for m in agent.messages
                   if isinstance(m.get("content"), str) and "SYSTEM NOTICE" in m["content"]]
        self.assertTrue(notices)
        self.assertIn("状态卡", notices[-1])
        self.assertIn("压缩前你的思考原文", notices[-1])
        self.assertIn("先把括号里的先算", notices[-1])
        self.assertLessEqual(len(agent.messages), 6)
        self.assertIn("已归档", agent.state_card())

    def test_compaction_skipped_when_it_would_grow(self):
        replies = [Reply(content="短答案") for _ in range(3)]
        agent = Agent(make_cfg(self.tmp.name, compact_context_chars=1,
                               compact_keep_turns=1, compact_keep_tool_turns=0),
                      llm_client=ScriptedLLM(replies), memory_root=self.tmp.name,
                      system_prompt="SYS")
        for text in ("一", "二", "三"):
            agent.ask(text)
        self.assertFalse([e for e in agent.memory.events() if e["t"] == "compact"])

    def test_force_compact_without_history(self):
        agent = Agent(make_cfg(self.tmp.name), llm_client=ScriptedLLM([]),
                      memory_root=self.tmp.name, system_prompt="SYS")
        self.assertFalse(agent.force_compact())
        self.assertEqual(len(agent.messages), 1)


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_reset_and_resume(self):
        client = ScriptedLLM([Reply(content="答案一"), Reply(content="答案二")])
        agent = Agent(make_cfg(self.tmp.name), llm_client=client,
                      memory_root=self.tmp.name, system_prompt="SYS")
        first_session = agent.memory.session_id
        self.assertEqual(first_session, DEFAULT_SESSION)
        agent.ask("问题一")

        agent.reset()
        self.assertNotEqual(agent.memory.session_id, first_session)
        self.assertEqual(agent.turn, 0)
        self.assertEqual(len(agent.messages), 1)
        agent.ask("问题二")

        agent.memory = Conversation(self.tmp.name, first_session)
        count = agent.resume()
        self.assertEqual(count, 2)
        self.assertEqual(agent.messages[1]["content"], "问题一")
        self.assertEqual(agent.turn, 1)

    def test_two_runs_share_one_folder(self):
        for text in ("第一次问", "第二次问"):
            agent = Agent(make_cfg(self.tmp.name),
                          llm_client=ScriptedLLM([Reply(content="好")]),
                          memory_root=self.tmp.name, system_prompt="SYS")
            agent.resume()
            agent.ask(text)
        rows = library.list_sessions(self.tmp.name)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["turns"], 2)


class BranchAgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_edit_from_earlier_node_starts_new_branch(self):
        replies = [Reply(content="甲"), Reply(content="乙"), Reply(content="丙")]
        client = ScriptedLLM(replies)
        agent = Agent(make_cfg(self.tmp.name), llm_client=client,
                      memory_root=self.tmp.name, system_prompt="SYS")
        first = agent.ask("主线一")
        agent.ask("主线二")
        branch = agent.ask("改成分支", parent=first["node"])

        self.assertNotEqual(branch["node"], first["node"])
        self.assertEqual(branch["parent"], first["node"])
        third_call = client.calls[2]
        contents = [m["content"] for m in third_call]
        self.assertIn("主线一", contents)
        self.assertIn("甲", contents)
        self.assertIn("改成分支", contents)
        self.assertNotIn("主线二", contents)
        self.assertNotIn("乙", contents)

        tree = agent.memory.branch_tree()
        by_id = {item["id"]: item for item in tree["nodes"]}
        self.assertIn(branch["node"], by_id[first["node"]]["children"])
        self.assertEqual(tree["active"], branch["node"])



class StopLLM(ScriptedLLM):
    """第一次调用只吐一半正文就触发停止，模拟用户在流式中途点停止。"""

    agent = None
    partial_ratio = 0.5

    def chat(self, messages, tools=None, stream=False, on_delta=None,
             should_stop=None):
        self.calls.append(copy.deepcopy(messages))
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        if not reply.content:
            if self.agent is not None:
                self.agent.request_stop()
            return Reply(content="")
        cut = max(1, int(len(reply.content) * self.partial_ratio))
        piece = reply.content[:cut]
        if on_delta:
            on_delta(piece)
        if self.agent is not None:
            self.agent.request_stop()
        return Reply(reasoning=reply.reasoning, content=piece)


class StopAndRetryTest(unittest.TestCase):
    """中断要留下已生成的一半，失败要清掉残缺节点。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, client):
        agent = Agent(make_cfg(self.tmp.name), llm_client=client,
                      memory_root=self.tmp.name, system_prompt="SYS")
        if hasattr(client, "agent"):
            client.agent = agent
        return agent

    def test_stop_keeps_partial_answer(self):
        client = StopLLM([Reply(content="先定义失败条件，再倒推今天能做的预防。")])
        agent = self.build(client)
        result = agent.ask("怎么开始？")

        self.assertTrue(result["stopped"])
        self.assertEqual(result["text"], "先定义失败条件，再")
        messages = agent.memory.conversation()
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertEqual(messages[-1]["text"], "先定义失败条件，再")
        self.assertIn(result["node"],
                      {item["id"] for item in agent.memory.branch_tree()["nodes"]})
        self.assertTrue(messages[-1]["stopped"])

    def test_empty_or_failed_turn_leaves_nothing(self):
        # 一个 delta 都没有就停止：整轮节点撤销，历史里不留空问答
        agent = self.build(StopLLM([Reply(content="")]))
        result = agent.ask("这个问题没有任何输出")
        self.assertTrue(result["stopped"])
        self.assertEqual(result["text"], "")
        self.assertIsNone(result["node"])
        self.assertEqual(agent.memory.branch_tree()["nodes"], [])
        self.assertEqual(agent.memory.conversation(), [])

        # 调用抛错同样撤销，不把残缺节点留在树上
        class Boom(ScriptedLLM):
            def chat(self, messages, tools=None, stream=False, on_delta=None,
                     should_stop=None):
                raise RuntimeError("连接断开")

        failed = self.build(Boom([]))
        with self.assertRaises(RuntimeError):
            failed.ask("会失败的问题")
        self.assertEqual(failed.memory.branch_tree()["nodes"], [])

    def test_stop_flag_resets_between_turns(self):
        client = StopLLM([Reply(content="前半段内容比较长一些。")])
        agent = self.build(client)
        agent.ask("第一次")
        self.assertTrue(agent._stop_requested)

        agent.llm = ScriptedLLM([Reply(content="第二次完整回答")])
        result = agent.ask("第二次")
        self.assertFalse(result["stopped"])
        self.assertEqual(result["text"], "第二次完整回答")


if __name__ == "__main__":
    unittest.main()
