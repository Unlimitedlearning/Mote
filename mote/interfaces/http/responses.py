"""HTTP 响应与请求参数的公共实现。

只负责「协议 ↔ Python 值」的翻译：状态码、Content-Type、下载头、JSON 请求体。
会话怎么读、设置怎么写，分别由路由与 `mote.services` 决定。
"""

import json
import re
import urllib.parse

# 路径与请求体里的 ID 只接受这些字符：日志会以 ID 作为目录名，不能让路径穿越
SID = re.compile(r"[A-Za-z0-9_-]{1,80}")
NODE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def query(path):
    """把 URL 的查询串解析成 {键: [值, ...]}。"""
    return urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)


def decode_sid(match):
    return urllib.parse.unquote(match.group(1))


def attachment(name):
    """下载文件名：ASCII 回退名 + RFC 5987 的 UTF-8 名。"""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, "txt"
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "mote"
    return (f"attachment; filename=\"{fallback}.{ext}\"; "
            f"filename*=UTF-8''{urllib.parse.quote(name)}")


class ResponseMixin:
    """JSON / HTML / 文件下载的写出，以及请求体与来源判断。"""

    def _respond(self, code, body, ctype, headers=None):
        data = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.close_connection = True

    def _json(self, code, payload):
        self._respond(code, json.dumps(payload, ensure_ascii=False),
                      "application/json; charset=utf-8")

    def _html(self, text):
        self._respond(200, text, "text/html; charset=utf-8")

    @staticmethod
    def _result_payload(result):
        """把 Agent 的返回值裁成前端需要的字段（不外泄内部结构）。"""
        return {
            "reply": result["text"], "session": result["session"],
            "turn": result["turn"], "node": result.get("node"),
            "parent": result.get("parent"), "steps": result["steps"],
            "tools": result["tools"], "lenses": result["lenses"],
            "route": result.get("route"), "mode": result.get("mode"),
            "worker": result.get("worker"),
            "model": result.get("model"), "thinking": result.get("thinking") or "",
            "saved_chars": result.get("saved_chars", 0),
            "context_chars": result.get("context_chars", 0),
            "fallback": bool(result.get("fallback")),
            "stopped": bool(result.get("stopped")),
            "interrupted": bool(result.get("interrupted")),
        }

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _local_only(self):
        """配置里有 API key，只允许回环地址读写；把服务开到 0.0.0.0 时不会连 key 一起暴露。"""
        addr = (self.client_address or ("",))[0]
        return addr in ("127.0.0.1", "::1", "localhost")
