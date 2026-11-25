"""流式回答：SSE 写出与一次问答的完整生命周期。

浏览器关闭页面就断开，这类错误转成 `_ClientGone` 后静默收尾，
不把连接错误当成模型错误推给前端。
"""

import json

from .responses import NODE_ID, SID


class ClientGone(Exception):
    """连接已经断开：后续 SSE 写入不再尝试。"""


def chat_params(data):
    """校验聊天请求体，返回 (参数, 错误信息)。两边（一次性与流式）共用。"""
    message = (data.get("message") or data.get("content") or "").strip()
    if not message:
        return None, "缺少 message"
    session_id = data.get("session")
    if session_id is not None and (not isinstance(session_id, str)
                                   or not SID.fullmatch(session_id)):
        return None, "会话 id 不合法"
    parent = data.get("parent")
    if parent is not None and (not isinstance(parent, str)
                               or not NODE_ID.fullmatch(parent)):
        return None, "分支节点 id 不合法"
    fork = data.get("fork")
    if fork is not None and (not isinstance(fork, str)
                             or not NODE_ID.fullmatch(fork)):
        return None, "分支节点 id 不合法"
    mode = data.get("mode")
    if mode is not None and mode not in ("direct", "hybrid", "local"):
        return None, "对话模式不合法"
    return {"message": message, "session": session_id, "parent": parent,
            "fork": fork, "mode": mode}, None


class StreamMixin:
    """SSE 输出的三段式：开流、逐个事件、收尾。"""

    def _sse_start(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
        except OSError as err:
            raise ClientGone(str(err)) from err

    def _sse(self, event, payload):
        """每个 SSE 事件作为一段 chunk 写出，写完立即 flush。"""
        body = (f"event: {event}\n"
                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n").encode("utf-8")
        try:
            self.wfile.write(f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n")
            self.wfile.flush()
        except (OSError, ValueError) as err:
            raise ClientGone(str(err)) from err

    def _sse_end(self):
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            self.close_connection = True

    def _stream_chat(self, data):
        params, error = chat_params(data)
        if error:
            return self._json(400, {"error": error})

        agent = self.server.manager.get(params["session"])
        state = {"closed": False}

        def push(event, payload):
            if state["closed"]:
                return
            try:
                self._sse(event, payload)
            except ClientGone:
                state["closed"] = True

        def on_delta(piece):
            if piece:
                push("delta", {"delta": piece})

        def on_thinking(piece):
            if piece:
                push("thinking", {"delta": piece})

        def on_event(kind, payload):
            if kind in ("preprocess", "tool_start", "tool_end"):
                push(kind, payload)

        with self.server.manager.lock(agent):
            previous = (agent.on_delta, agent.on_thinking, agent.on_event)
            agent.on_delta, agent.on_thinking, agent.on_event = on_delta, on_thinking, on_event
            try:
                self._sse_start()
                result = agent.ask(params["message"], stream=True, parent=params["parent"],
                                   mode=params["mode"], fork=params["fork"])
                push("done", self._result_payload(result))
            except Exception as err:
                push("error", {"error": f"{type(err).__name__}: {err}"})
            finally:
                if hasattr(agent, "clear_stop"):
                    agent.clear_stop()
                agent.on_delta, agent.on_thinking, agent.on_event = previous
                self._sse_end()
