"""Mote · context"""


import json




def _role(msg):
    return msg.get("role") if isinstance(msg, dict) else ""


def _arguments(call):
    fn = call.get("function") if isinstance(call, dict) else None
    args = fn.get("arguments") if isinstance(fn, dict) else None
    return args if isinstance(args, str) else ""


def split_turns(messages):
    prefix, turns = [], []
    for msg in messages:
        if _role(msg) == "assistant":
            turns.append((msg, []))
        elif turns:
            turns[-1][1].append(msg)
        else:
            prefix.append(msg)
    return prefix, turns


def turn_is_tool(turn):
    return bool(turn[0].get("tool_calls"))


def keep_valuable_turns(messages, recent=2, tool_turns=3):
    _, turns = split_turns(messages)
    if not turns:
        return []

    chosen = set(range(max(0, len(turns) - max(0, recent)), len(turns)))

    tool_idx = [i for i, turn in enumerate(turns) if turn_is_tool(turn)]
    chosen.update(tool_idx[-max(0, tool_turns):] if tool_turns else [])

    out = []
    for index in sorted(chosen):
        assistant, tools = turns[index]
        out.append(assistant)
        out.extend(tools)
    return out


def _clip_arguments(args, limit):
    if not isinstance(args, str) or len(args) <= limit:
        return args
    head_len = limit * 2 // 3
    return json.dumps({"_truncated": True, "_original_chars": len(args),
                       "head": args[:head_len],
                       "tail": args[-(limit - head_len):] if limit > head_len else ""},
                      ensure_ascii=False)


def trim_tool_outputs(messages, limit):
    out = []
    for msg in messages:
        if _role(msg) == "tool":
            content = msg.get("content")
            if isinstance(content, str) and len(content) > limit:
                head = content[: limit * 2 // 3]
                tail = content[len(head):][-(limit - len(head)):] if limit > len(head) else ""
                msg = dict(msg, content=f"{head}\n…（截断，原长 {len(content)} 字）…\n{tail}")
            out.append(msg)
            continue

        calls = msg.get("tool_calls") if _role(msg) == "assistant" else None
        if not calls or not any(len(_arguments(c)) > limit for c in calls):
            out.append(msg)
            continue
        out.append(dict(msg, tool_calls=[
            dict(call, function=dict(call.get("function") or {},
                                     arguments=_clip_arguments(_arguments(call), limit)))
            if len(_arguments(call)) > limit else call
            for call in calls]))
    return out


def context_chars(messages):
    total = 0
    for msg in messages:
        content = msg.get("content")
        total += len(content) if isinstance(content, str) else len(str(content or ""))
        total += sum(len(_arguments(call)) for call in msg.get("tool_calls") or [])
    return total


THOUGHT_HEADER = "--- 压缩前你的思考原文（由旧到新，逐字保留）---"
THOUGHT_FOOTER = "--- 思考原文结束 ---"


def thought_notice(thoughts, per_thought_chars=1200):
    blocks = []
    for event in thoughts or []:
        raw = (event.get("text") or "").strip() if isinstance(event, dict) else str(event).strip()
        if not raw:
            continue
        if len(raw) > per_thought_chars:
            raw = raw[:per_thought_chars] + f"\n…（截断，原长 {len(raw)} 字；完整见 thoughts.jsonl）"
        turn = event.get("turn") if isinstance(event, dict) else ""
        blocks.append(f"[轮 {turn}]\n{raw}")
    return "\n\n".join([THOUGHT_HEADER] + blocks + [THOUGHT_FOOTER]) if blocks else ""


def summarize(messages, max_chars=400):
    parts = []
    for msg in messages:
        text = " ".join(str(msg.get("content") or "").split())
        if not text:
            continue
        if _role(msg) == "user":
            parts.append("问「" + text[:60] + "」")
        elif _role(msg) == "assistant":
            parts.append("答「" + text[:60] + "」")
    text = "；".join(parts)
    return text[:max_chars] + "…" if len(text) > max_chars else text
