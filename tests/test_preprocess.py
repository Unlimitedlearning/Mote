"""本地路由器：JSON 路由、压缩、工具白名单，以及解析失败时的回退。"""

import copy
import unittest

from mote import config as config_mod
from mote import preprocess
from mote.llm import Reply


class StubRouter:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, messages, tools=None, stream=False, on_delta=None):
        self.calls.append(messages)
        return Reply(content=self.content)


class BrokenRouter(StubRouter):
    def chat(self, messages, tools=None, stream=False, on_delta=None):
        raise RuntimeError("本地模型没起来")


class PreprocessTest(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(config_mod.DEFAULT)

    def test_local_route_keeps_answer(self):
        router = StubRouter('{"route":"local","answer":"现在是本地直接回答。","context":"","tools":[]}')
        result = preprocess.prepare(self.cfg, "在吗", "历史", router,
                                    allowed=["now", "use_lens"])
        self.assertEqual(result["route"], "local")
        self.assertEqual(result["answer"], "现在是本地直接回答。")
        self.assertFalse(result["fallback"])
        self.assertEqual(len(router.calls), 1)

    def test_cloud_route_filters_tools_and_truncates_context(self):
        router = StubRouter(
            '```json\n{"route":"cloud","context":"压缩背景和当前问题",'
            '"tools":["now","nope"]}\n```')
        result = preprocess.prepare(self.cfg, "问题", "历史" * 100, router,
                                    allowed=["now", "use_lens"], limit=40)
        self.assertEqual(result["route"], "cloud")
        self.assertEqual(result["tools"], ["now"])
        self.assertLessEqual(len(result["context"]), 40)
        self.assertIn("当前问题", result["context"])

    def test_bad_json_falls_back(self):
        router = StubRouter("我没有输出 JSON")
        result = preprocess.prepare(self.cfg, "关键问题", "历史", router,
                                    allowed=["now"], limit=100)
        self.assertEqual(result["route"], "cloud")
        self.assertTrue(result["fallback"])
        self.assertIn("关键问题", result["context"])

    def test_router_exception_falls_back(self):
        result = preprocess.prepare(self.cfg, "关键问题", "历史",
                                    BrokenRouter(""), allowed=["now"], limit=100)
        self.assertEqual(result["route"], "cloud")
        self.assertTrue(result["fallback"])

    def test_fallback_detects_time_question(self):
        result = preprocess.prepare(self.cfg, "现在几点", "历史", None,
                                    allowed=["now", "use_lens"], limit=100)
        self.assertEqual(result["tools"], ["now"])

    def test_no_router_uses_rules(self):
        result = preprocess.prepare(self.cfg, "关键问题", "历史", None,
                                    allowed=["now"], limit=100)
        self.assertEqual(result["route"], "cloud")
        self.assertTrue(result["fallback"])
        self.assertIn("关键问题", result["context"])


if __name__ == "__main__":
    unittest.main()
