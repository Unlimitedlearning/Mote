"""LLM 客户端：用本地假服务端验证 SSE 解析与 tool_calls 分片拼接。

为什么要专门测这个：工具调用在流里是按 index 分片下发的（名字一片、参数几片），
拼错一个字节，模型就会拿着一份坏 JSON 去调工具，然后整轮跑偏。
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mote.infra import llm as llm_mod


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.server.seen.append({"path": self.path, "payload": payload,
                                 "auth": self.headers.get("Authorization")})

        if "/bad" in self.path:
            return self._send(400, '{"error":"bad request"}')

        if not payload.get("stream"):
            return self._send(200, json.dumps({
                "choices": [{"message": {"role": "assistant", "content": "非流式回答",
                                         "tool_calls": [{"id": "c9", "type": "function",
                                                         "function": {"name": "now",
                                                                      "arguments": '{"expression":"1+1"}'}}]}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            }))

        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": "合计"}}]},
            {"choices": [{"delta": {"content": " 35"}}]},
            {"choices": [{"delta": {"reasoning_content": "先算括号"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "now", "arguments": '{"expre'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": 'ssion": "(3+4)*5"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                      "total_tokens": 15}},
        ]
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        self._send(200, body, "text/event-stream")


class LLMClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.httpd.seen = []
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def client(self, path="/v1", retries=0):
        return llm_mod.LLM(base_url=f"http://127.0.0.1:{self.port}{path}",
                           model="fake", api_key="k", retries=retries, timeout=5)

    def test_stream_stops_on_request(self):
        seen = []

        def on_delta(piece):
            seen.append(piece)

        reply = self.client().chat([{"role": "user", "content": "x"}], stream=True,
                                   on_delta=on_delta,
                                   should_stop=lambda: len(seen) >= 1)
        self.assertEqual(seen, ["合计"])
        self.assertEqual(reply.content, "合计")

    def test_endpoint_normalisation(self):
        self.assertEqual(llm_mod.endpoint("http://localhost:11434/v1"),
                         "http://localhost:11434/v1/chat/completions")
        self.assertEqual(llm_mod.endpoint("https://api.deepseek.com"),
                         "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(llm_mod.endpoint("http://x/v1/"),
                         "http://x/v1/chat/completions")
        self.assertEqual(llm_mod.endpoint("http://x/v1/chat/completions"),
                         "http://x/v1/chat/completions")

    def test_stream_assembles_tool_call_fragments(self):
        pieces = []
        reply = self.client().chat([{"role": "user", "content": "算"}],
                                   tools=[{"type": "function", "function": {"name": "now"}}],
                                   stream=True, on_delta=pieces.append)
        self.assertEqual("".join(pieces), "合计 35")
        self.assertEqual(reply.content, "合计 35")
        self.assertEqual(reply.reasoning, "先算括号")
        self.assertEqual(len(reply.tool_calls), 1)
        call = reply.tool_calls[0]
        self.assertEqual(call["name"], "now")
        self.assertEqual(json.loads(call["arguments"])["expression"], "(3+4)*5")
        self.assertEqual(reply.usage["total_tokens"], 15)

        seen = self.httpd.seen[-1]
        self.assertEqual(seen["path"], "/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer k")
        self.assertTrue(seen["payload"]["stream"])
        self.assertEqual(seen["payload"]["tools"][0]["function"]["name"], "now")

        # 思考分片单独回调，与正文分开累计
        thoughts = []
        self.client().chat([{"role": "user", "content": "算"}],
                           stream=True, on_thinking=thoughts.append)
        self.assertEqual("".join(thoughts), "先算括号")

    def test_non_stream_parse(self):
        reply = self.client().chat([{"role": "user", "content": "算"}])
        self.assertEqual(reply.content, "非流式回答")
        self.assertEqual(reply.tool_calls[0]["id"], "c9")
        self.assertEqual(reply.usage["prompt_tokens"], 3)

    def test_message_shapes(self):
        reply = llm_mod.Reply(content="", tool_calls=[{"id": "c1", "name": "now",
                                                      "arguments": "{}"}],
                              reasoning="不该回传的思考")
        msg = reply.message()
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["content"], "")  # 不能是 None
        self.assertEqual(msg["tool_calls"][0]["function"]["arguments"], "{}")
        self.assertNotIn("reasoning", msg)
        self.assertNotIn("reasoning_content", msg)  # 长期历史不带思考，省 token
        json.dumps(msg)  # 必须可直接序列化回传

        # 只在发回同一轮工具调用时带上思考，且为空时不塞空字段
        with_reasoning = reply.message(with_reasoning=True)
        self.assertEqual(with_reasoning["reasoning_content"], "不该回传的思考")
        self.assertNotIn("reasoning_content",
                         llm_mod.Reply(content="x").message(with_reasoning=True))

    def test_thinking_flag_only_when_profile_asks(self):
        plain = self.client()
        plain.chat([{"role": "user", "content": "x"}])
        self.assertNotIn("thinking", self.httpd.seen[-1]["payload"])

        thinking = llm_mod.LLM(base_url=f"http://127.0.0.1:{self.port}/v1",
                               model="fake", api_key="k", retries=0, timeout=5,
                               thinking=True)
        thinking.chat([{"role": "user", "content": "x"}])
        self.assertEqual(self.httpd.seen[-1]["payload"]["thinking"],
                         {"type": "enabled"})

    def test_errors_are_wrapped(self):
        # 4xx 不重试，直接上报
        with self.assertRaises(llm_mod.LLMError):
            self.client(path="/v1/bad").chat([{"role": "user", "content": "算"}])
        # 连不上也要包成同一种异常，调用方只处理一种错误
        offline = llm_mod.LLM(base_url="http://127.0.0.1:9/v1", model="x",
                              retries=0, timeout=1)
        with self.assertRaises(llm_mod.LLMError):
            offline.chat([{"role": "user", "content": "算"}])


if __name__ == "__main__":
    unittest.main()
