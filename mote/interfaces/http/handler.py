"""HTTP 请求入口：把三个动词分派给路由实现。

Handler 只做组合：响应写出（ResponseMixin）、SSE（StreamMixin）、
路径分派（RoutesMixin）。会话缓存与服务器生命周期在 `.server`。
"""

from http.server import BaseHTTPRequestHandler

from .responses import ResponseMixin
from .routes import RoutesMixin
from .stream import StreamMixin


class Handler(ResponseMixin, StreamMixin, RoutesMixin, BaseHTTPRequestHandler):
    server_version = "Mote/0.6"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)
