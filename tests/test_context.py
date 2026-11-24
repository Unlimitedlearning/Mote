"""上下文纯函数的单测：切轮不能切出孤立 tool，裁剪不能破坏 JSON。"""

import json
import unittest

from mote import context


def assistant(content="", calls=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [
            {"id": f"c{i}", "type": "function",
             "function": {"name": name, "arguments": args}}
            for i, (name, args) in enumerate(calls)
        ]
    return msg


class SplitTurnsTest(unittest.TestCase):
    def test_prefix_and_turns(self):
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U1"},
            assistant(calls=[("now", "{}")]),
            {"role": "tool", "content": "ok"},
            assistant("A1"),
        ]
        prefix, turns = context.split_turns(messages)
        self.assertEqual([m["role"] for m in prefix], ["system", "user"])
        self.assertEqual(len(turns), 2)
        self.assertEqual(len(turns[0][1]), 1)  # 第一轮带一条 tool

    def test_leading_tool_goes_to_prefix(self):
        # 孤立的 tool 消息（前面没有 assistant）落在 prefix 里，压缩时会被整体丢掉，
        # 这正是我们要的结果：它本来就不该出现，更不能被裁进保留轮。
        messages = [{"role": "system", "content": "S"},
                    {"role": "tool", "content": "orphan"},
                    assistant("A")]
        prefix, turns = context.split_turns(messages)
        self.assertEqual([m["content"] for m in prefix], ["S", "orphan"])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0][1], [])


class KeepValuableTurnsTest(unittest.TestCase):
    def test_keeps_recent_plus_tool_turns_in_order(self):
        messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "U0"}]
        # 轮1：调工具（早期关键轮）；轮2、3：纯聊天（可丢）；轮4：调工具
        messages += [assistant("", [("now", "{}")]), {"role": "tool", "content": "r1"}]
        messages += [assistant("聊天1"), assistant("聊天2")]
        messages += [assistant("", [("now", "{}")]), {"role": "tool", "content": "r4"}]

        kept = context.keep_valuable_turns(messages, recent=2, tool_turns=2)
        contents = [m.get("content") for m in kept]
        self.assertIn("r1", contents)        # 早期决策轮被保住
        self.assertIn("r4", contents)        # 最近决策轮
        self.assertIn("聊天2", contents)      # 最近 2 轮里最近的那条
        self.assertNotIn("聊天1", contents)   # 夹在中间的纯闲聊轮被丢掉
        # 顺序必须保持原样，否则 assistant 与它的 tool 会错位
        self.assertLess(contents.index("r1"), contents.index("r4"))

    def test_no_turn_returns_empty(self):
        self.assertEqual(context.keep_valuable_turns([{"role": "user", "content": "U"}]), [])


class TrimTest(unittest.TestCase):
    def test_long_tool_output_clipped_with_marker(self):
        messages = [{"role": "tool", "content": "x" * 500}]
        trimmed = context.trim_tool_outputs(messages, 100)
        self.assertLess(len(trimmed[0]["content"]), 220)
        self.assertIn("截断", trimmed[0]["content"])
        self.assertTrue(trimmed[0]["content"].startswith("xxx"))

    def test_long_arguments_stay_valid_json(self):
        raw = json.dumps({"expression": "1+" * 200})
        messages = [assistant("", [("now", raw)])]
        trimmed = context.trim_tool_outputs(messages, 100)
        args = trimmed[0]["tool_calls"][0]["function"]["arguments"]
        parsed = json.loads(args)  # 半截 JSON 会让 provider 直接 400
        self.assertTrue(parsed["_truncated"])
        self.assertEqual(parsed["_original_chars"], len(raw))
        self.assertTrue(raw.startswith(parsed["head"]))

    def test_small_messages_untouched(self):
        messages = [{"role": "user", "content": "hi"}]
        self.assertIs(context.trim_tool_outputs(messages, 100)[0], messages[0])


class ContextCharsTest(unittest.TestCase):
    def test_counts_content_and_arguments(self):
        messages = [
            {"role": "system", "content": "12345"},
            assistant("", [("now", '{"expression":"1"}')]),
            {"role": "tool", "content": "ok"},
        ]
        expected = 5 + len('{"expression":"1"}') + 2
        self.assertEqual(context.context_chars(messages), expected)


class NoticeTest(unittest.TestCase):
    def test_thought_notice_order_and_truncation(self):
        thoughts = [{"turn": 1, "text": "a" * 50}, {"turn": 2, "text": "b" * 10}]
        text = context.thought_notice(thoughts, per_thought_chars=20)
        self.assertIn("[轮 1]", text)
        self.assertIn("截断", text)
        self.assertLess(text.index("[轮 1]"), text.index("[轮 2]"))

    def test_empty(self):
        self.assertEqual(context.thought_notice([]), "")


class SummarizeTest(unittest.TestCase):
    def test_summary_contains_question_and_answer(self):
        text = context.summarize([
            {"role": "user", "content": "3+4 等于几"},
            {"role": "assistant", "content": "等于 7"},
        ])
        self.assertIn("3+4", text)
        self.assertIn("等于 7", text)

    def test_summary_truncated(self):
        text = context.summarize(
            [{"role": "user", "content": "问" * 500}], max_chars=50)
        self.assertLessEqual(len(text), 51)


if __name__ == "__main__":
    unittest.main()
