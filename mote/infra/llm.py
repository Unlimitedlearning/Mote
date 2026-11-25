"""Mote · llm"""


import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


class LLMError(Exception):
    pass


class _Retryable(Exception):
    pass


@dataclass
class Reply:

    content: str = ""
    reasoning: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    def message(self, with_reasoning=False):
        """转成请求里的 assistant 消息。

        with_reasoning 只在同一轮工具调用内为真：思考模式下 API 要求把
        reasoning_content 原样带回去，长期历史里则应该丢掉，避免白付 token。
        """
        msg = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": c["arguments"]}}
                                 for c in self.tool_calls]
        if with_reasoning and self.reasoning:
            msg["reasoning_content"] = self.reasoning
        return msg


def endpoint(base_url):
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if urllib.parse.urlsplit(base).path in ("", "/"):
        base += "/v1"
    return base + "/chat/completions"


class LLM:

    def __init__(self, base_url, model, api_key="", temperature=0.3,
                 max_tokens=1024, timeout=120, retries=2, thinking=False):
        self.url = endpoint(base_url)
        self.model = model
        # 只有配置里显式开启的 profile 才发 thinking：本地 Ollama 等端点不认识这个字段
        self.thinking = bool(thinking)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"


    def chat(self, messages, tools=None, stream=False, on_delta=None, on_thinking=None,
             should_stop=None):
        payload = {"model": self.model, "messages": messages,
                   "temperature": self.temperature, "max_tokens": self.max_tokens,
                   "stream": bool(stream)}
        if self.thinking:
            payload["thinking"] = {"type": "enabled"}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if stream:
            payload["stream_options"] = {"include_usage": True}

        state = {"emitted": False}
        for attempt in range(self.retries + 1):
            try:
                return self._send(payload, stream, on_delta, on_thinking, state,
                                  should_stop)
            except _Retryable as err:
                if state["emitted"]:
                    raise LLMError(f"{err}（已输出部分内容，不再重试）") from err
                if attempt >= self.retries:
                    raise LLMError(str(err)) from err
                time.sleep(min(2 ** attempt, 5))


    def _send(self, payload, stream, on_delta, on_thinking, state, should_stop=None):
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self.headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", "replace")[:600]
            error = _Retryable if err.code in (408, 429, 500, 502, 503, 504) else LLMError
            raise error(f"HTTP {err.code}: {body}") from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise _Retryable(f"连接 {self.url} 失败: {err}") from err

        with resp:
            if stream:
                return self._stream(resp, on_delta, on_thinking, state, should_stop)
            return self._parse(resp.read().decode("utf-8", "replace"))

    def _parse(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError as err:
            raise LLMError(f"响应不是合法 JSON: {body[:300]}") from err
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"响应里没有 choices: {body[:300]}")

        msg = choices[0].get("message") or {}
        reply = Reply(content=msg.get("content") or "",
                      reasoning=msg.get("reasoning_content") or msg.get("reasoning") or "",
                      usage=data.get("usage") or {})
        reply.tool_calls = [{
            "id": call.get("id") or f"call_{i}",
            "name": (call.get("function") or {}).get("name") or "",
            "arguments": (call.get("function") or {}).get("arguments") or "{}",
        } for i, call in enumerate(msg.get("tool_calls") or [])]
        return reply

    def _stream(self, resp, on_delta, on_thinking, state, should_stop=None):
        reply, calls = Reply(), {}
        for raw in resp:
            if should_stop and should_stop():
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":"):
                continue
            data = line[5:].strip() if line.startswith("data:") else line
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                reply.usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or choices[0].get("message") or {}

            if delta.get("content"):
                reply.content += delta["content"]
                state["emitted"] = True
                if on_delta:
                    on_delta(delta["content"])

            for key in ("reasoning_content", "reasoning", "thinking"):
                if delta.get(key):
                    reply.reasoning += delta[key]
                    if on_thinking:
                        on_thinking(delta[key])

            for item in delta.get("tool_calls") or []:
                slot = calls.setdefault(item.get("index", len(calls)),
                                        {"id": "", "name": "", "arguments": ""})
                if item.get("id"):
                    slot["id"] = item["id"]
                fn = item.get("function") or {}
                slot["name"] += fn.get("name") or ""
                args = fn.get("arguments")
                if isinstance(args, str):
                    slot["arguments"] += args
                elif args is not None:
                    slot["arguments"] += json.dumps(args, ensure_ascii=False)

        reply.tool_calls = [calls[i] for i in sorted(calls) if calls[i]["name"]]
        for i, call in enumerate(reply.tool_calls):
            call["id"] = call["id"] or f"call_{i}"
        return reply
