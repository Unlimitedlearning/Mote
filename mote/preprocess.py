"""本地前置路由器：一次 qwen 调用完成「路由 + 压缩 + 工具预选」。

输出严格 JSON；解析失败或字段缺失时回退到规则，不让云端链路因为格式问题挂掉。
这个模块不知道任何具体业务，工具白名单由调用方传入。
"""

import json


def router_prompt(limit, tools):
    return f"""你是 Mote 的成本路由器。只输出一个 JSON 对象，不要 Markdown，不要解释文字。

格式：
{{"route":"local|cloud","answer":"...","context":"...","tools":["工具名"]}}

规则：
- 问候、简单事实、三句话内能答完的问题：route=local，把简短回答写进 answer，context 留空。
- 问当前时间/日期/星期必须交给工具：route=cloud，tools 只选 now，context 写当前问题。
- 需要判断、分析、权衡、多步推理的问题：route=cloud，answer 留空，把历史背景和当前问题压成不超过 {limit} 字的 context，只保留影响判断的事实。
- tools 只能从 {tools} 里选需要的子集；用不到就给空数组。问时间只选 now，需要多视角判断才选 use_lens。
- 不确定时 route=cloud，tools 给空数组。
"""


def fallback_context(history, question, limit):
    """保证当前问题一定在上下文里，历史从尾部取，避免长历史把问题挤掉。"""
    tail = "当前问题：" + (question or "")
    if len(tail) >= limit:
        return tail[:max(1, limit)]
    room = limit - len(tail) - 1
    head = (history or "").strip()
    if len(head) > room:
        head = "…" + head[-max(0, room - 1):]
    return (head + "\n" + tail).strip()[:max(1, limit)]


def _extract_json(text):
    """从可能带 ``` 围栏或前后废话的输出里截出第一个完整 JSON 对象。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start = raw.find("{")
    if start < 0:
        return None
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return None
                return value if isinstance(value, dict) else None
    return None


def prepare(cfg, question, history=None, router=None, allowed=None, limit=None):
    """返回 {route, answer, context, tools, saved, fallback, raw, thinking}。"""
    hybrid = cfg.get("hybrid") or {}
    limit = max(120, int(limit or hybrid.get("context_chars") or 700))
    allowed = list(allowed or [])
    question = (question or "").strip()
    full = fallback_context(history, question, 100000)
    fallback = {"route": "cloud", "answer": "", "context": fallback_context(history, question, limit),
                "tools": [], "saved": max(0, len(full) - limit), "fallback": True,
                "raw": "", "thinking": ""}
    if "now" in allowed and any(word in question for word in
                                ("几点", "时间", "今天", "现在", "日期", "星期", "几月", "哪天")):
        fallback["tools"] = ["now"]

    if router is None:
        return fallback
    try:
        reply = router.chat([
            {"role": "system", "content": router_prompt(
                limit, "、".join(allowed) or "（无）")},
            {"role": "user", "content": (f"历史背景：{history or '无'}\n当前问题：{question}")},
        ], stream=False)
        data = _extract_json(reply.content)
        thought = getattr(reply, "reasoning", "") or ""
    except Exception:
        return fallback
    if not data:
        return fallback

    answer = str(data.get("answer") or "").strip()
    route = str(data.get("route") or "").strip().lower()
    picked = data.get("tools")
    tools = [str(x) for x in picked if str(x) in allowed] if isinstance(picked, list) else []
    context = str(data.get("context") or "").strip()[:limit]

    if route == "local" and answer:
        # 本地直答没有单独的 worker 调用，它的推理就是这次路由调用的 reasoning
        return {"route": "local", "answer": answer, "context": "", "tools": [],
                "saved": len(full), "fallback": False, "raw": reply.content,
                "thinking": thought}
    if not context:
        context = fallback["context"]
    return {"route": "cloud", "answer": "", "context": context, "tools": tools,
            "saved": max(0, len(full) - len(context)), "fallback": False,
            "raw": reply.content, "thinking": ""}
