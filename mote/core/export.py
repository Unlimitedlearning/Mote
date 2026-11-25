"""导出：把一条分支渲染成 Markdown 或结构化 JSON。

输入只有事件快照，输出是字符串/字典，便于直接比对与测试。
"""

import datetime

from .events import branch_tree, conversation, groups, title
from .text import quote


def markdown(events, session_id, node=None, with_thinking=True, at=None):
    """当前分支导出为 Markdown：问题用引用块，回答保留原始 Markdown。"""
    messages = conversation(events, node=node)
    tree = branch_tree(events, node=node)
    meta = next((event for event in events if event.get("t") == "session"), {})
    users = [item for item in messages if item["role"] == "user"]
    span = [item.get("ts") for item in messages if item.get("ts")]
    stamp = at or datetime.datetime.now()

    lines = [f"# {title(events)}", ""]
    lines.append(f"- 会话：`{session_id}`")
    if meta.get("model"):
        lines.append(f"- 模型：{meta['model']}")
    lines.append("- 导出：" + stamp.isoformat(sep=" ", timespec="seconds"))
    lines.append(f"- 轮数：{len(users)}")
    if len(tree["nodes"]) > len(users):
        lines.append(f"- 分支：共 {len(tree['nodes'])} 个问答节点，"
                     f"此处只导出当前分支的 {len(users)} 轮")
    if span:
        lines.append(f"- 时间：{span[0]} → {span[-1]}")
    lines.append("")

    turn = 0
    for item in messages:
        if item["role"] == "user":
            turn += 1
            lines += ["---", "", f"## {turn}. 你", "", quote(item.get("text")), ""]
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        thinking = (item.get("thinking") or "").strip()
        if with_thinking and thinking:
            lines += ["<details>", f"<summary>思考过程（{len(thinking)} 字）</summary>", "",
                      thinking, "", "</details>", ""]
        lines += [text, ""]
        notes = []
        route, model = item.get("route"), item.get("model")
        if route == "local":
            notes.append("本地 · " + (model or "qwen"))
        elif route in ("cloud", "direct"):
            notes.append("云端 · " + (model or "worker"))
        elif model:
            notes.append(model)
        if item.get("stopped"):
            notes.append("已停止生成")
        if notes:
            lines += ["*" + " · ".join(notes) + "*", ""]
    return "\n".join(lines).rstrip() + "\n"


def payload(events, session_id, node=None, at=None):
    """结构化导出：当前分支的消息流 + 完整分支树 + 每个节点的问答原文。"""
    messages = conversation(events, node=node)
    tree = branch_tree(events, node=node)
    meta = next((event for event in events if event.get("t") == "session"), {})
    by_node = {group["node"]: group for group in groups(events)}
    branches = {}
    for item in tree["nodes"]:
        group = by_node.get(item["id"], {"items": []})
        answer = next((event for event in group["items"]
                       if event.get("t") == "assistant"
                       and (event.get("text") or "").strip()), {})
        branches[item["id"]] = {
            "parent": item["parent"],
            "question": item["text"],
            "answer": answer.get("text") or "",
            "thinking": answer.get("thinking") or "",
            "model": answer.get("model") or "",
            "route": answer.get("route") or "",
            "stopped": bool(answer.get("stopped")),
            "turn": item.get("turn"), "ts": item.get("ts"),
        }
    stamp = at or datetime.datetime.now()
    return {
        "format": "mote-session/1",
        "session": session_id,
        "title": title(events),
        "meta": {"profile": meta.get("profile", ""), "model": meta.get("model", "")},
        "exported_at": stamp.isoformat(timespec="seconds"),
        "active": tree["active"],
        "counts": {"turns": sum(1 for item in messages if item["role"] == "user"),
                   "nodes": len(tree["nodes"])},
        "messages": messages,
        "tree": tree,
        "branches": branches,
    }
