"""混合链路：本地直答不调云端，云端只收压缩上下文，模型名写进每条回答。"""

import copy
import tempfile
import unittest

from mote.core import config as config_mod
from mote.infra.llm import Reply
from mote.services.agent import Agent


class RecordingLLM:
    def __init__(self, replies, model="deepseek-chat"):
        self.replies = list(replies)
        self.model = model
        self.calls = []
        self.tools_seen = []

    def chat(self, messages, tools=None, stream=False, on_delta=None):
        self.calls.append(copy.deepcopy(messages))
        self.tools_seen.append(copy.deepcopy(tools))
        reply = self.replies.pop(0)
        if on_delta and reply.content:
            on_delta(reply.content)
        return reply


class Router:
    def __init__(self, content, model="qwen-local", reasoning=""):
        self.content = content
        self.model = model
        self.reasoning = reasoning
        self.calls = []

    def chat(self, messages, tools=None, stream=False, on_delta=None):
        self.calls.append(messages)
        return Reply(content=self.content, reasoning=self.reasoning)


class HybridTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self):
        cfg = copy.deepcopy(config_mod.DEFAULT)
        cfg["profiles"]["cloud"]["api_key"] = "sk-test"
        cfg["profiles"]["local"]["base_url"] = "http://127.0.0.1:9/v1"
        cfg["hybrid"]["enabled"] = True
        cfg["hybrid"]["worker_profile"] = "cloud"
        cfg["hybrid"]["context_chars"] = 120
        cfg["_memory_root"] = self.tmp.name
        return cfg

    def build(self, router_content, worker_replies):
        router = Router(router_content)
        worker = RecordingLLM(worker_replies)
        agent = Agent(self.cfg(), llm_client=worker, router_client=router,
                      hybrid={"enabled": True}, memory_root=self.tmp.name,
                      system_prompt="SYS")
        return agent, router, worker

    def test_local_answer_never_calls_worker(self):
        agent, router, worker = self.build(
            '{"route":"local","answer":"这是本地回答","context":"","tools":[]}', [])
        router.reasoning = "只是打招呼，走本地直答就够了"
        result = agent.ask("在吗")
        self.assertEqual(result["route"], "local")
        self.assertEqual(result["model"], "qwen-local")
        self.assertEqual(result["worker"], "local")
        self.assertEqual(len(worker.calls), 0)
        self.assertEqual(len(router.calls), 1)
        # 本地直答没有 worker 调用，思考过程来自路由那次调用
        self.assertEqual(result["thinking"], "只是打招呼，走本地直答就够了")
        event = [e for e in agent.memory.events() if e["t"] == "assistant"][0]
        self.assertEqual(event["model"], "qwen-local")
        self.assertEqual(event["route"], "local")
        self.assertEqual(event["thinking"], "只是打招呼，走本地直答就够了")
        self.assertEqual(agent.memory.thinking_for(result["node"]),
                         "只是打招呼，走本地直答就够了")

    def test_cloud_gets_compressed_context_and_filtered_tools(self):
        agent, router, worker = self.build(
            '{"route":"cloud","context":"压缩背景","tools":["now","use_lens"]}',
            [Reply(tool_calls=[{"id": "c1", "name": "now", "arguments": "{}"}]),
             Reply(content="最终回答")])
        result = agent.ask("这个方案有什么隐患")
        self.assertEqual(result["route"], "cloud")
        self.assertEqual(result["model"], "deepseek-chat")
        self.assertEqual(result["tools"], [{"name": "now", "ok": True}])
        self.assertEqual(len(worker.calls), 2)
        self.assertIn("[压缩上下文]\n压缩背景", worker.calls[0][1]["content"])
        self.assertFalse(any("状态卡" in (m.get("content") or "")
                             for m in worker.calls[0]))
        names = {item["function"]["name"] for item in worker.tools_seen[0]}
        self.assertEqual(names, {"now", "use_lens"})
        # 第二轮请求必须同时带上一条 tool_calls 与它的结果，缺一条接口会拒
        second = worker.calls[1]
        self.assertIn("assistant", [m["role"] for m in second])
        self.assertEqual(len([m for m in second if m["role"] == "tool"]), 1)
        history = agent.memory.conversation()
        self.assertEqual(history[-1]["model"], "deepseek-chat")
        self.assertEqual(history[-1]["route"], "cloud")

    def test_second_turn_carries_recent_exchanges(self):
        """多轮是主路径：压缩背景之外必须带上近几轮原文，否则「刚才那段」不存在。"""
        agent, router, worker = self.build(
            '{"route":"cloud","context":"背景","tools":[]}',
            [Reply(content="第一轮回答"), Reply(content="第二轮问题接着答")])
        agent.ask("第一轮问题")
        agent.ask("第二轮问题")

        second = worker.calls[1]
        contents = [msg.get("content") or "" for msg in second]
        self.assertEqual([msg["role"] for msg in second[:2]], ["system", "system"])
        self.assertIn("[压缩上下文]\n背景", contents[1])
        # 上一轮的问答原文按顺序出现在请求里
        self.assertIn("第一轮问题", contents)
        self.assertIn("第一轮回答", contents)
        self.assertLess(contents.index("第一轮问题"), contents.index("第一轮回答"))
        # 当前问题必须是最后一条，且是原文而不是压缩后的概述
        self.assertEqual(second[-1]["role"], "user")
        self.assertEqual(second[-1]["content"], "第二轮问题")

    def test_mode_override_picks_path(self):
        # 单轮指定 hybrid：本地路由器参与，简单问题本地直答
        agent, router, worker = self.build(
            '{"route":"local","answer":"先本地处理","context":"","tools":[]}', [])
        result = agent.ask("在吗", mode="hybrid")
        self.assertEqual(result["mode"], "hybrid")
        self.assertEqual(result["route"], "local")
        self.assertEqual(len(router.calls), 1)
        self.assertEqual(len(worker.calls), 0)

        # 单轮指定 direct：完全跳过本地路由器
        agent, router, worker = self.build(
            '{"route":"local","answer":"不应出现","context":"","tools":[]}',
            [Reply(content="直接问云端")])
        result = agent.ask("这个方案有什么隐患", mode="direct")
        self.assertEqual(result["mode"], "direct")
        self.assertEqual(result["route"], "direct")
        self.assertEqual(result["text"], "直接问云端")
        self.assertEqual(len(router.calls), 0)
        self.assertEqual(len(worker.calls), 1)

    def test_bad_router_json_falls_back(self):
        agent, _, worker = self.build("模型没有输出 JSON", [Reply(content="兜底回答")])
        result = agent.ask("关键问题")
        self.assertEqual(result["route"], "cloud")
        self.assertTrue(result["fallback"])
        self.assertTrue(any("关键问题" in (m.get("content") or "")
                            for m in worker.calls[0]))
        self.assertEqual(len(worker.calls), 1)


class LocalOnlyTest(unittest.TestCase):
    """仅本地：不建路由、不碰云端，回答由本地端点直接产出。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, mode):
        cfg = copy.deepcopy(config_mod.DEFAULT)
        cfg["profiles"]["cloud"]["api_key"] = "sk-test"
        cfg["profiles"]["local"]["base_url"] = "http://127.0.0.1:9/v1"
        cfg["hybrid"]["mode"] = mode
        cfg["hybrid"]["enabled"] = mode == "hybrid"
        cfg["_memory_root"] = self.tmp.name
        return cfg

    def test_local_mode_never_builds_router(self):
        local = RecordingLLM([Reply(content="本地算出来的答案")], model="qwen3.5:4b")
        agent = Agent(self.cfg("local"), llm_client=local, memory_root=self.tmp.name,
                      system_prompt="SYS")
        self.assertEqual(agent.default_mode, "local")
        self.assertIsNone(agent.router)
        result = agent.ask("一加一")
        self.assertEqual(result["route"], "local")
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["model"], "qwen3.5:4b")
        self.assertEqual(result["steps"], 1)
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(agent.memory.conversation()[-1]["route"], "local")

    def test_switch_to_local_from_cloud_mode(self):
        router = Router('{"route":"cloud","answer":"","context":"压缩过的问题","tools":[]}')
        worker = RecordingLLM([Reply(content="云端回答")])
        agent = Agent(self.cfg("hybrid"), llm_client=worker, router_client=router,
                      hybrid={"mode": "hybrid", "enabled": True},
                      memory_root=self.tmp.name, system_prompt="SYS")
        local = RecordingLLM([Reply(content="本地回答")], model="qwen3.5:4b")
        agent._pairs["local"] = (dict(agent._resolve_profile("local"), model="qwen3.5:4b"), local)

        result = agent.ask("这个问题", mode="local")
        self.assertEqual(result["route"], "local")
        self.assertEqual(result["model"], "qwen3.5:4b")
        self.assertEqual(len(local.calls), 1)
        # 路由与云端一次都没被调用
        self.assertEqual(worker.calls, [])
        self.assertEqual(router.calls, [])
        # 单轮覆盖不外溢：下一轮仍按配置的方式走
        self.assertEqual(agent.default_mode, "hybrid")

    def test_mode_rules_and_missing_local(self):
        self.assertEqual(config_mod.mode_of({"mode": "local", "enabled": False}), "local")
        # 旧字段说不要本地前置时，残留的 mode=hybrid 不能把它改回来
        self.assertEqual(config_mod.mode_of({"mode": "hybrid", "enabled": False}), "direct")
        self.assertEqual(config_mod.mode_of({"enabled": False}), "direct")
        self.assertEqual(config_mod.mode_of({"enabled": True}), "hybrid")
        self.assertEqual(config_mod.mode_of({}), "direct")

        # 仅本地缺端点必须报错，不能悄悄退回云端
        cfg = self.cfg("local")
        del cfg["profiles"]["local"]
        cfg["default_profile"] = "cloud"
        with self.assertRaises(config_mod.ConfigError) as ctx:
            Agent(cfg, memory_root=self.tmp.name, system_prompt="SYS")
        self.assertIn("local", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
