"""终端 REPL + 斜杠命令。"""

import os
import sys

from . import config as config_mod
from . import lenses as lenses_mod
from . import memory as memory_mod
from .llm import LLMError

HELP = """\
命令：
  /lenses [n]   列出镜头目录（n = 全部时打印每个镜头的提问清单）
  /state        看本轮注入的状态卡
  /log [n]      最近 n 轮历史（默认 8）
  /compact      立即压缩上下文
  /new          开新会话
  /sessions     列出会话
  /resume <id|序号> 接上历史会话
  /model [名字] 看或切换端点
  /tools        列出工具
  /help         本帮助
  /exit         退出"""


class Paint:
    def __init__(self, enabled=None):
        if enabled is None:
            enabled = sys.stdout.isatty() and not os.getenv("NO_COLOR")
        self.enabled = bool(enabled)

    def __call__(self, text, code):
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def dim(self, t): return self(t, "2")
    def cyan(self, t): return self(t, "36")
    def green(self, t): return self(t, "32")
    def yellow(self, t): return self(t, "33")
    def red(self, t): return self(t, "31")
    def bold(self, t): return self(t, "1")


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


class Renderer:
    def __init__(self, paint=None):
        self.paint = paint or Paint()
        self.printed = False

    def delta(self, piece):
        sys.stdout.write(piece)
        sys.stdout.flush()
        self.printed = True

    def newline(self):
        if self.printed:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.printed = False

    def event(self, kind, payload):
        p = self.paint
        if kind == "tool_start":
            self.newline()
            print(p.dim(f"  ↳ 调用 {payload['name']}({_clip(payload['arguments'], 160)})"))
        elif kind == "tool_end":
            print(p.dim(f"  {p.green('✓') if payload['ok'] else p.red('✗')} "
                        f"{_clip(payload['result'], 220)}"))
        elif kind == "compact":
            self.newline()
            print(p.yellow(f"  ✂ 压缩：{payload['before']} → {payload['after']} 字"))
        elif kind == "profile":
            print(p.cyan(f"  ⚙ 已切到 {payload['profile']} · {payload['model']}"))


def banner(agent, paint):
    p, rule = paint, "─" * 56
    print("\n".join([
        p.dim(rule),
        f"  {p.bold('Mote')} · 通用 agent（工具可插拔，本地前置省钱）",
        p.dim(f"  模型 {agent.profile['model']}  [{'本地路由' if agent.hybrid_enabled else '直连'}]   "
              f"会话 {agent.memory.session_id}"),
        p.dim(f"  已启用工具 {len(agent.tool_names)} 个：{'、'.join(agent.tool_names)}"),
        p.dim(rule),
        p.dim("  /help 看命令；网页界面：python -m mote serve"),
    ]))


def _print_sessions(root, current_id=None, paint=None):
    paint = paint or Paint()
    rows = memory_mod.list_sessions(root)
    if not rows:
        print(paint.dim("  磁盘上还没有历史会话"))
    for index, row in enumerate(rows, 1):
        mark = "*" if row["id"] == current_id else " "
        print(f"  {mark} {index:>2}. {row['id']}  {row['turns']:>3} 轮  "
              f"{row['date']}  {paint.dim(row['preview'])}")
    return rows


def _print_lenses(arg):
    if arg.lower() == "all":
        for key, item in lenses_mod.LENSES.items():
            print(f"  {key} {item['name']}  [{item['category']}]")
            print(lenses_mod.detail(key))
            print()
        return
    print(lenses_mod.catalog())
    print("  /lenses all 看每个镜头的提问清单")


def handle_command(agent, line):
    paint = Paint()
    parts = line[1:].split()
    cmd, arg = (parts[0].lower() if parts else ""), (parts[1] if len(parts) > 1 else "")

    if cmd in ("exit", "quit", "q"):
        return False
    if cmd in ("help", "h", "?"):
        print(HELP)
    elif cmd == "lenses":
        _print_lenses(arg)
    elif cmd == "state":
        print(paint.dim("─" * 56))
        print(agent.state_card())
        print(paint.dim("─" * 56))
    elif cmd in ("log", "history"):
        print(agent.memory.digest(int(arg) if arg.isdigit() else 8))
    elif cmd == "compact":
        if not agent.force_compact():
            print(paint.yellow("  当前没有可压缩的内容"))
    elif cmd == "new":
        agent.reset()
        print(paint.green(f"  已开新会话 {agent.memory.session_id}"))
    elif cmd == "sessions":
        _print_sessions(agent.memory_root, agent.memory.session_id, paint)
    elif cmd == "resume":
        if not arg:
            print(paint.yellow("  用法：/resume <id|序号>"))
            _print_sessions(agent.memory_root, agent.memory.session_id, paint)
            return True
        rows = memory_mod.list_sessions(agent.memory_root)
        target = rows[int(arg) - 1]["id"] if arg.isdigit() and 1 <= int(arg) <= len(rows) else \
            (arg if any(row["id"] == arg for row in rows) else None)
        if not target:
            print(paint.red(f"  找不到会话 {arg}"))
            return True
        agent.memory = memory_mod.Memory(agent.memory_root, target)
        print(paint.green(f"  已接上 {target}：重建 {agent.resume()} 条消息"))
    elif cmd == "model":
        if arg:
            try:
                agent.switch_profile(arg)
            except config_mod.ConfigError as err:
                print(paint.red(f"  {err}"))
        else:
            print(f"  当前 {paint.bold(agent.profile['name'])} · {agent.profile['model']}")
            print(paint.dim(f"  可切换：{', '.join(agent.cfg.get('profiles') or {})}"))
    elif cmd == "tools":
        from . import tools as tools_mod
        for item in tools_mod.REGISTRY.values():
            print(f"  {paint.cyan(item['name'])}  {_clip(item['description'], 100)}")
    else:
        print(paint.yellow(f"  未知命令 /{cmd}，试试 /help"))
    return True


def _bind(agent, renderer):
    renderer = renderer or Renderer()
    agent.on_delta = renderer.delta
    agent.on_event = renderer.event
    return renderer


def chat(agent, renderer=None):
    renderer = _bind(agent, renderer)
    paint = renderer.paint
    banner(agent, paint)
    while True:
        try:
            line = input(paint.cyan("你 › ")).strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if not handle_command(agent, line):
                break
            continue
        try:
            agent.ask(line)
        except KeyboardInterrupt:
            print(paint.yellow("  （本轮已中断）"))
        except LLMError as err:
            print(paint.red(f"  ✗ 模型调用失败：{err}"))
        finally:
            renderer.newline()
    print(paint.dim("再见。"))


def ask_once(agent, text, renderer=None):
    renderer = _bind(agent, renderer)
    try:
        result = agent.ask(text)
    except LLMError as err:
        renderer.newline()
        print(renderer.paint.red(f"✗ 模型调用失败：{err}"), file=sys.stderr)
        return 2
    renderer.newline()
    return 0 if result["text"] else 1
