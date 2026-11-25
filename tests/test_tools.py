"""工具层：镜头只能按 id 加载，同轮不重复、不超量，坏参数不能带崩主循环。"""

import unittest

from mote.services import lenses
from mote.services import tools


class LensToolTest(unittest.TestCase):
    def setUp(self):
        self.state = tools.new_lens_state(3)

    def test_spec_shape_and_filter(self):
        specs = tools.specs()
        self.assertEqual(len(specs), 2)
        names = {item["function"]["name"] for item in specs}
        self.assertEqual(names, {"now", "use_lens"})
        for spec in specs:
            self.assertEqual(spec["type"], "function")
            self.assertIn("description", spec["function"])
        lens = next(item["function"] for item in specs
                    if item["function"]["name"] == "use_lens")
        self.assertEqual(lens["parameters"]["required"], ["lens"])
        schema = lens["parameters"]["properties"]["lens"]
        self.assertEqual(schema["type"], "string")
        self.assertIn("id", schema["description"])
        # 仓库只带精选镜头，不依赖任何外部数据
        self.assertGreaterEqual(len(lenses.LENSES), 30)

        picked = tools.specs(["now"])
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["function"]["name"], "now")
        self.assertIsNone(tools.specs(["nope"]))

    def test_now_tool(self):
        result = tools.run("now", "{}")
        self.assertTrue(result["ok"])
        self.assertIn("星期", result["text"])
        self.assertRegex(result["text"], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_load_lens_detail_normalises_id(self):
        result = tools.run("use_lens", '{"lens":"inversion"}',
                           ctx={"lens_state": self.state})
        self.assertTrue(result["ok"])
        self.assertIn("逆向思维", result["text"])
        self.assertIn("提问清单", result["text"])
        self.assertEqual(self.state["used"], ["inversion"])

        # 大小写与空格都按同一个 id 处理
        spaced = tools.run("use_lens", '{"lens": "  INVERSION  "}',
                           ctx={"lens_state": tools.new_lens_state(3)})
        self.assertTrue(spaced["ok"])

    def test_unknown_lens_lists_options(self):
        result = tools.run("use_lens", '{"lens":"没有这个"}',
                           ctx={"lens_state": self.state})
        self.assertFalse(result["ok"])
        self.assertIn("/lenses", result["text"])
        self.assertEqual(self.state["used"], [])

    def test_lens_limits(self):
        # 同轮重复加载被拒
        ctx = {"lens_state": self.state}
        tools.run("use_lens", '{"lens":"inversion"}', ctx=ctx)
        again = tools.run("use_lens", '{"lens":"inversion"}', ctx=ctx)
        self.assertFalse(again["ok"])
        self.assertIn("不要重复加载", again["text"])
        self.assertEqual(self.state["used"], ["inversion"])

        # 超过每轮上限被拒
        limited = {"lens_state": tools.new_lens_state(3)}
        for key in ("inversion", "first_principles", "systems"):
            self.assertTrue(tools.run("use_lens", '{"lens":"' + key + '"}',
                                      ctx=limited)["ok"])
        fourth = tools.run("use_lens", '{"lens":"gray"}', ctx=limited)
        self.assertFalse(fourth["ok"])
        self.assertIn("上限 3", fourth["text"])
        self.assertEqual(len(limited["lens_state"]["used"]), 3)

        # 上限至少为 1，未配置时给默认值
        self.assertEqual(tools.new_lens_state(0)["limit"], 1)
        self.assertEqual(tools.new_lens_state(None)["limit"], 4)

    def test_invalid_calls_are_rejected(self):
        cases = [
            ("nope", {}, "use_lens"),                 # 未知工具
            ("use_lens", "{lens: inversion}", "JSON"),  # 参数不是合法 JSON
            ("use_lens", [1, 2], None),               # 参数必须是对象
            ("use_lens", '{"city":"北京"}', "参数不匹配"),  # 未知参数名
            ("use_lens", "{}", "参数不匹配"),          # 缺少必填参数
        ]
        for name, arguments, hint in cases:
            with self.subTest(name=name, arguments=arguments):
                result = tools.run(name, arguments)
                self.assertFalse(result["ok"])
                if hint:
                    self.assertIn(hint, result["text"])


class EnabledWhitelistTest(unittest.TestCase):
    def test_empty_whitelist_means_no_tools(self):
        # 显式写 [] 是「一个都不要」，不能退化成全开
        self.assertEqual(tools.enabled({"agent": {"tools": []}}), [])
        self.assertEqual(tools.enabled({"agent": {"tools": ["now"]}}), ["now"])
        # 连键都没有才算「没配过」，此时用全部已注册工具
        self.assertTrue(tools.enabled({"agent": {}}))


if __name__ == "__main__":
    unittest.main()
