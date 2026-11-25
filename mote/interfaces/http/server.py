"""HTTP 服务的生命周期：会话缓存、线程服务器、启动提示。"""

import os
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from ...core.ids import DEFAULT_SESSION
from ...services.agent import Agent
from .handler import Handler


class SessionManager:
    """按会话缓存 Agent：同一会话的多条请求共用上下文与锁。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.agents = {}
        self.locks = {}
        self.guard = threading.Lock()

    def get(self, session_id=None):
        key = session_id or DEFAULT_SESSION
        with self.guard:
            agent = self.agents.get(key)
            if agent is None:
                agent = Agent(self.cfg, session_id=key)
                agent.resume()
                self.agents[key] = agent
                self.locks[key] = threading.Lock()
            return agent

    def lock(self, agent):
        return self.locks.setdefault(agent.memory.session_id, threading.Lock())

    def reset(self):
        """配置改动后丢掉缓存的 agent：下一次请求按新端点、新 key 重建。"""
        with self.guard:
            self.agents.clear()
            self.locks.clear()


class _Server(ThreadingHTTPServer):
    """浏览器关闭页面时会直接断开连接，这类断开不必打印堆栈。"""

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def browse_url(host, port):
    """监听 0.0.0.0 时浏览器不能访问这个地址，换成回环地址。"""
    target = "127.0.0.1" if host in ("0.0.0.0", "::", "", "*") else host
    return f"http://{target}:{port}/"


def serve(cfg, host="127.0.0.1", port=9000, verbose=False, open_browser=False):
    try:
        httpd = _Server((host, port), Handler)
    except OSError as err:
        raise SystemExit(f"端口 {port} 无法监听（{err}）。换一个：python -m mote serve --port {port + 1}")
    httpd.manager = SessionManager(cfg)
    httpd.cfg = cfg
    httpd.verbose = verbose
    url = browse_url(host, port)
    print(f"Mote 已启动：{url}")
    print("  首次使用点右上角「⚙ 设置」填接口地址、模型名和 API Key；Ctrl+C 停止。")
    print("  接口：POST /inbox · GET /sessions/<id>/messages · GET/POST /settings")
    if open_browser and not os.getenv("MOTE_NO_BROWSER"):
        # 先让服务进入循环再打开，避免浏览器抢在监听之前访问
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
