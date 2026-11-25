"""HTTP 接入：组合路由、流式输出与服务生命周期。"""

from .handler import Handler
from .server import SessionManager, serve

__all__ = ["Handler", "SessionManager", "serve"]
