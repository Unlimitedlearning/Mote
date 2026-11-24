"""工具层：镜头只能按 id 加载，同轮不重复、不超量，坏参数不能带崩主循环。"""

import unittest

from mote import lenses
from mote import tools


class LensToolTest(unittest.TestCase):
    def setUp(self):
        self.state = tools.new_lens_state(3)

    def test_spec_shape(self):
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

    def test_specs_can_be_filtered(self):
        picked = tools.specs(["now"])
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["function"]["name"], "now")
        self.assertIsNone(tools.specs(["nope"]))

    def test_now_tool(self):
        result = tools.run("now", "{}")
        self.assertTrue(result["ok"])
        self.assertIn("星期", result["text"])
        self.assertRegex(result["text"], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_load_returns_detail(self):
        result = tools.run("use_lens", '{"lens":"inversion"}',
                           ctx={"lens_state": self.state})
        self.assertTrue(result["ok"])
        self.assertIn("逆向思维", result["text"])
        self.assertIn("提问清单", result["text"])
        self.assertEqual(self.state["used"], ["inversion"])

    def test_case_and_space_in_lens_id(self):
        result = tools.run("use_lens", '{"lens": "  INVERSION  "}',
                           ctx={"lens_state": self.state})
        self.assertTrue(result["ok"])
        self.assertEqual(self.state["used"], ["inversion"])

    def test_unknown_lens_lists_options(self):
        result = tools.run("use_lens", '{"lens":"没有这个"}',
                           ctx={"lens_state": self.state})
        self.assertFalse(result["ok"])
        self.assertIn("/lenses", result["text"])
        self.assertEqual(self.state["used"], [])

    def test_duplicate_lens_blocked(self):
        ctx = {"lens_state": self.state}
        tools.run("use_lens", '{"lens":"inversion"}', ctx=ctx)
        again = tools.run("use_lens", '{"lens":"inversion"}', ctx=ctx)
        self.assertFalse(again["ok"])
        self.assertIn("不要重复加载", again["text"])
        self.assertEqual(self.state["used"], ["inversion"])

    def test_turn_limit_blocked(self):
        ctx = {"lens_state": self.state}
        for key in ("inversion", "first_principles", "systems"):
            self.assertTrue(tools.run("use_lens", '{"lens":"' + key + '"}', ctx=ctx)["ok"])
        fourth = tools.run("use_lens", '{"lens":"gray"}', ctx=ctx)
        self.assertFalse(fourth["ok"])
        self.assertIn("上限 3", fourth["text"])
        self.assertEqual(len(self.state["used"]), 3)

    def test_state_limit_is_at_least_one(self):
        self.assertEqual(tools.new_lens_state(0)["limit"], 1)
        self.assertEqual(tools.new_lens_state(None)["limit"], 4)

    def test_unknown_tool(self):
        result = tools.run("nope", {})
        self.assertFalse(result["ok"])
        self.assertIn("use_lens", result["text"])

    def test_bad_json_arguments(self):
        result = tools.run("use_lens", "{lens: inversion}")
        self.assertFalse(result["ok"])
        self.assertIn("JSON", result["text"])

    def test_arguments_must_be_object(self):
        self.assertFalse(tools.run("use_lens", [1, 2])["ok"])

    def test_unknown_argument_name(self):
        result = tools.run("use_lens", '{"city":"北京"}')
        self.assertFalse(result["ok"])
        self.assertIn("参数不匹配", result["text"])

    def test_missing_argument(self):
        result = tools.run("use_lens", "{}")
        self.assertFalse(result["ok"])
        self.assertIn("参数不匹配", result["text"])


if __name__ == "__main__":
    unittest.main()
