"""工具注册表：核心只认 REGISTRY，不认识任何具体业务。

初始插件：now（当前时间）、use_lens（思维镜头，可选）。
模型只看见 specs() 给出的 schema；调用统一走 run()，依赖通过 ctx 注入。
"""

import datetime
import json

from . import lenses

REGISTRY = {}


class ToolError(Exception):
    """工具层的业务失败：run() 转成 ok=False，把文本回给模型而不是崩掉主循环。"""


def tool(name, description, parameters):
    def wrap(fn):
        REGISTRY[name] = {"name": name, "description": description,
                          "parameters": parameters, "fn": fn}
        return fn
    return wrap


def specs(names=None):
    """默认给全部工具；传入 names 时只暴露白名单，用来压缩云端请求的 schema。"""
    if not REGISTRY:
        return None
    items = (list(REGISTRY.values()) if names is None
             else [REGISTRY[name] for name in names if name in REGISTRY])
    if not items:
        return None
    return [{"type": "function",
             "function": {k: item[k] for k in ("name", "description", "parameters")}}
            for item in items]


def run(name, arguments, ctx=None):
    item = REGISTRY.get(name)
    if item is None:
        return {"ok": False, "text": f"没有名为 {name!r} 的工具，可用：{', '.join(REGISTRY)}"}
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as err:
            return {"ok": False, "text": f"参数不是合法 JSON（{err}）"}
    else:
        args = arguments or {}
    if not isinstance(args, dict):
        return {"ok": False, "text": "参数必须是 JSON 对象"}
    try:
        return {"ok": True, "text": str(item["fn"](ctx=ctx, **args))}
    except TypeError as err:
        return {"ok": False, "text": f"参数不匹配：{err}"}
    except ToolError as err:
        return {"ok": False, "text": str(err)}
    except Exception as err:
        return {"ok": False, "text": f"{type(err).__name__}: {err}"}


def enabled(cfg):
    """配置里的 tools 是工具名白名单；键不存在时才用全部已注册工具。

    显式写 `[]` 是「一个都不要」，不能退化成全开——那会让用户关不掉工具。
    """
    agent = cfg.get("agent") or {}
    if "tools" not in agent:
        return list(REGISTRY)
    names = agent.get("tools") or []
    return [name for name in names if name in REGISTRY]


def new_lens_state(limit):
    """每轮一个独立计数，跨工具调用共用；模型不能在同轮重复或超量加载镜头。"""
    return {"limit": max(1, int(limit)) if limit is not None else 4, "used": []}


@tool("now", "获取当前本地日期、时间和星期。涉及“今天/现在/本周”等时间判断时调用，"
      "不要凭记忆猜测当前时间。无参数。",
      {"type": "object", "properties": {}, "additionalProperties": False})
def _now(ctx=None):
    now = datetime.datetime.now()
    week = "一二三四五六日"[now.weekday()]
    return f"{now:%Y-%m-%d %H:%M:%S} 星期{week}"


@tool("use_lens", "加载一个思维镜头的详细提问清单。只有需要从多个视角审视一个有实质"
      "内容的判断时才调用；回答简单问题、问事实或获取时间时不要调用。同一个镜头本轮"
      "只能加载一次，达到上限后直接作答。可用 id 见 /lenses。",
      {"type": "object", "properties": {
          "lens": {"type": "string",
                   "description": "镜头 id，例如 inversion、first_principles；"
                                  "完整列表可用 `python -m mote lenses` 查看。"}},
       "required": ["lens"]})
def _use_lens(ctx=None, lens=None):
    if not isinstance(lens, str) or not lens.strip():
        raise ToolError("参数不匹配：缺少 lens（镜头 id）")
    key = lens.strip().lower()
    text = lenses.detail(key)
    if text is None:
        raise ToolError(f"没有名为 {lens!r} 的镜头，可用 id 见 /lenses")
    display = lenses.LENSES[key]["name"]

    state = (ctx or {}).get("lens_state")
    if state is None:
        return text
    if key in state["used"]:
        raise ToolError(f"本轮已经加载过 {display} 镜头，请直接作答，不要重复加载。")
    if len(state["used"]) >= state["limit"]:
        raise ToolError(f"本轮已加载 {len(state['used'])} 个镜头（上限 {state['limit']}），"
                        "请基于已加载的镜头直接作答。")
    state["used"].append(key)
    return text
