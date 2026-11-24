"""命令行入口：ask / chat / lenses / serve 等。"""

import argparse
import json
import sys

from . import config as config_mod
from . import memory as memory_mod
from .agent import Agent


def build_parser():
    parser = argparse.ArgumentParser(prog="mote", description="轻量思维顾问：带问题来，挑镜头给建议")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--profile", help="端点名")
    parser.add_argument("--no-hybrid", action="store_true",
                        help="关闭本地前置，直接调用默认 profile")
    sub = parser.add_subparsers(dest="cmd")

    for name, text in (("chat", "进入对话（默认行为）"), ("ask", "一次性提问")):
        cmd = sub.add_parser(name, help=text)
        if name == "ask":
            cmd.add_argument("text", nargs="+", help="要咨询的问题")
        cmd.add_argument("--session", help="会话 id，默认 main")

    lenses = sub.add_parser("lenses", help="列出镜头目录")
    lenses.add_argument("--all", action="store_true", help="同时打印每个镜头的提问清单")
    lenses.add_argument("--id", help="查看某个镜头 id 的提问清单")

    state = sub.add_parser("state", help="打印状态卡与历史")
    state.add_argument("--session", help="默认取最近一个会话")
    state.add_argument("--log", type=int, default=6, help="同时打印最近几轮（0 = 不打印）")

    sub.add_parser("sessions", help="列出磁盘上的会话")

    serve = sub.add_parser("serve", help="启动 HTTP 接口（含网页）")
    serve.add_argument("--host", help="监听地址，默认取配置 server.host")
    serve.add_argument("--port", type=int, help="监听端口，默认取配置 server.port")
    serve.add_argument("--verbose", action="store_true", help="打印访问日志")
    serve.add_argument("--no-browser", action="store_true",
                       help="启动后不自动打开浏览器（也可设 MOTE_NO_BROWSER=1）")

    sub.add_parser("tools", help="打印工具 schema")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    raw = list(sys.argv[1:] if argv is None else argv)
    # 这两个开关允许写在子命令前面（python -m mote --no-browser serve）
    no_hybrid = "--no-hybrid" in raw
    no_browser = "--no-browser" in raw
    raw = [item for item in raw if item not in ("--no-hybrid", "--no-browser")]
    if raw and raw[0] in ("-h", "--help"):
        build_parser().print_help()
        return 0
    if not raw or raw[0].startswith("-"):
        raw = ["chat"] + raw

    args = build_parser().parse_args(raw)
    args.no_hybrid = no_hybrid
    args.no_browser = no_browser
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as err:
        print(f"配置错误：{err}", file=sys.stderr)
        return 2
    if no_hybrid:
        cfg.setdefault("hybrid", {})["enabled"] = False
    cfg["_memory_root"] = root = config_mod.memory_root(cfg)

    if args.cmd == "sessions":
        from .cli import _print_sessions
        _print_sessions(root)
        return 0
    if args.cmd == "tools":
        from . import tools as tools_mod
        print(json.dumps(tools_mod.specs(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "lenses":
        from . import lenses as lenses_mod
        if args.id:
            text = lenses_mod.detail(args.id)
            if text is None:
                print(f"找不到镜头 {args.id}", file=sys.stderr)
                return 1
            print(text)
        elif args.all:
            for key, item in lenses_mod.LENSES.items():
                print(f"{key} {item['name']} [{item['category']}]")
                print(lenses_mod.detail(key))
                print()
        else:
            print(lenses_mod.catalog())
            print(f"\n精选 {len(lenses_mod.LENSES)} 个；"
                  f"--all 看提问清单，--id <id> 看单个。")
        return 0
    if args.cmd == "serve":
        from .server import serve
        srv = config_mod.server_cfg(cfg)
        host = args.host if args.host is not None else srv.get("host", "127.0.0.1")
        port = args.port if args.port is not None else int(srv.get("port", 9000))
        serve(cfg, host, port, args.verbose, open_browser=not args.no_browser)
        return 0
    if args.cmd == "state":
        rows = memory_mod.list_sessions(root)
        session = args.session or (rows[0]["id"] if rows else None)
        if not session:
            print("磁盘上还没有会话。")
            return 1
        memory = memory_mod.Memory(root, session)
        print(f"会话 {session}  {memory.home}")
        print("─" * 60)
        print(memory.state_card(int(config_mod.agent_cfg(cfg).get("state_card_chars", 1600))))
        if args.log:
            print("─" * 60)
            print(memory.digest(args.log))
        return 0

    from .cli import Renderer, ask_once, chat as chat_loop
    try:
        agent = Agent(cfg, profile_name=args.profile, session_id=args.session)
    except config_mod.ConfigError as err:
        print(f"配置错误：{err}", file=sys.stderr)
        return 2
    rebuilt = agent.resume()
    if args.session and rebuilt:
        print(f"已接上会话 {args.session}：重建 {rebuilt} 条消息，第 {agent.turn} 轮")

    if args.cmd == "ask":
        return ask_once(agent, " ".join(args.text), Renderer())
    chat_loop(agent, Renderer())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
