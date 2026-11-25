"""事件流的纯计算：节点、路径、分支树、视图与状态卡。

所有函数只接收 `events` 列表（append-only 的事件字典），不读写文件、不持有状态，
因此可以直接用构造好的事件列表做单元测试。磁盘部分见 `mote.infra.store`。
"""

import json
from collections import Counter

from .text import clip

# 事件类型里不产生对话内容、只影响视图的几种
META_EVENTS = ("session", "title", "cursor", "delete", "main")


def node_rows(events):
    """把 user 事件映射成节点；legacy 节点 ID 由出现顺序决定，跨重启稳定。"""
    rows, known = [], set()
    for index, event in enumerate(events):
        if event.get("t") != "user":
            continue
        previous = rows[-1]["id"] if rows else None
        node = event.get("node") or f"legacy-{len(rows) + 1}"
        if node in known:
            node = f"{node}-{index}"
        if "parent" in event:
            parent = event.get("parent")
        else:
            parent = previous
        if parent is not None and parent not in known:
            parent = previous
        known.add(node)
        rows.append({"id": node, "parent": parent, "event": event, "index": index})
    return rows


def deleted_nodes(events):
    deleted = set()
    for event in events:
        if event.get("t") != "delete":
            continue
        if event.get("nodes"):
            deleted.update(event["nodes"])
        elif event.get("node"):
            deleted.add(event["node"])
    return deleted


def pinned(events):
    """最后一个 main 事件记录的节点；未设置或被取消时为 None。

    只做存在性判断，是否仍在有效集合里由调用方核对。
    """
    node = None
    for event in events:
        if event.get("t") == "main":
            node = event.get("node")
    return node or None


def branch_leaf(node, rows, deleted):
    """从切换点沿子节点走到该分支末端，避免只显示到分叉那一轮。"""
    children = {}
    for row in rows:
        if row["parent"] and row["id"] not in deleted:
            children.setdefault(row["parent"], []).append(row["id"])
    current, seen = node, {node}
    while True:
        options = [item for item in children.get(current, []) if item not in seen]
        if not options:
            return current
        current = options[-1]
        seen.add(current)


def active_node(events, rows=None, deleted=None):
    """打开会话时应当显示的节点：主分支优先，其次最近一次 cursor。"""
    rows = node_rows(events) if rows is None else rows
    deleted = deleted_nodes(events) if deleted is None else deleted
    alive = [row for row in rows if row["id"] not in deleted]
    if not alive:
        return None
    alive_ids = {row["id"] for row in alive}
    # 主分支是显式标记，优先于「最近一次切换的分叉点」，打开会话稳定落在同一条链路
    pinned_node = pinned(events)
    if pinned_node in alive_ids:
        return branch_leaf(pinned_node, rows, deleted)
    cursor_node, cursor_index = None, -1
    for index, event in enumerate(events):
        if event.get("t") == "cursor":
            cursor_node, cursor_index = event.get("node"), index
    if cursor_node in alive_ids:
        later = [row for row in alive if row["index"] > cursor_index]
        base = later[-1]["id"] if later else cursor_node
    else:
        base = alive[-1]["id"]
    return branch_leaf(base, rows, deleted)


def path_ids(events, node=None):
    """从根到 node（默认当前节点）的节点链，已删除节点不进入路径。"""
    rows = node_rows(events)
    lookup = {row["id"]: row for row in rows}
    deleted = deleted_nodes(events)
    target = node or active_node(events, rows, deleted)
    path, seen = [], set()
    while target in lookup and target not in seen and target not in deleted:
        path.append(target)
        seen.add(target)
        target = lookup[target]["parent"]
    return list(reversed(path))


def groups(events):
    """每个 user 事件到下一个 user 之前的内容属于同一个问答节点。"""
    by_index = {row["index"]: row["id"] for row in node_rows(events)}
    out, current = [], None
    for index, event in enumerate(events):
        kind = event.get("t")
        if kind == "user":
            current = {"node": by_index.get(index), "user": event, "items": []}
            out.append(current)
        elif kind in META_EVENTS:
            continue
        elif current is not None:
            current["items"].append(event)
    return out


def path_events(events, node=None):
    """当前路径上的事件，按原始顺序（含 user 与其后的回答、工具、压缩）。"""
    path = set(path_ids(events, node))
    out = []
    for group in groups(events):
        if group["node"] in path:
            out.append(group["user"])
            out.extend(group["items"])
    return out


def has_node(events, node):
    return bool(node) and any(row["id"] == node for row in node_rows(events))


def is_active_node(events, node):
    return has_node(events, node) and node not in deleted_nodes(events)


def parent_of(events, node):
    for row in node_rows(events):
        if row["id"] == node and node not in deleted_nodes(events):
            return row["parent"]
    return None


def main_node(events):
    """会话的主分支节点；未设置、已取消或该节点已删除时为 None。"""
    node = pinned(events)
    if not node:
        return None
    alive = {row["id"] for row in node_rows(events)} - deleted_nodes(events)
    return node if node in alive else None


def title(events, fallback="新对话"):
    """标题优先取重命名事件，其次首个问题；导出文件名也用它。"""
    titles = [event.get("title") for event in events
              if event.get("t") == "title" and (event.get("title") or "").strip()]
    if titles:
        return clip(titles[-1], 80)
    first = next((row["event"].get("text") for row in node_rows(events)
                  if (row["event"].get("text") or "").strip()), "")
    return clip(first, 80) or fallback


def branch_tree(events, node=None):
    """分支树：节点、父子关系、当前链路、主分支链路。"""
    rows = node_rows(events)
    deleted = deleted_nodes(events)
    valid = {row["id"] for row in rows if row["id"] not in deleted}
    # node 是界面当前显示的那条链：主分支只决定「打开时落在哪」，不能把跳转摁回去
    if node and node in valid:
        active = branch_leaf(node, rows, deleted)
    else:
        active = active_node(events, rows, deleted)
    path = path_ids(events, active)
    by_node = {group["node"]: group for group in groups(events)}
    children = {item: [] for item in valid}
    nodes = []
    for row in rows:
        node_id = row["id"]
        if node_id not in valid:
            continue
        parent = row["parent"] if row["parent"] in valid else None
        if parent and parent != node_id:
            children[parent].append(node_id)
        group = by_node.get(node_id, {"user": row["event"], "items": []})
        answer = next((event.get("text") for event in group["items"]
                       if event.get("t") == "assistant" and (event.get("text") or "").strip()), "")
        nodes.append({
            "id": node_id, "parent": parent, "children": children.get(node_id, []),
            # 分支树只用于导航与预览，问题截断可把大会话的树体积压到十分之一
            "text": clip(row["event"].get("text") or "", 120),
            "preview": clip(answer, 60),
            "turn": row["event"].get("turn"), "ts": row["event"].get("ts"),
            "active": node_id == active, "in_path": node_id in path,
        })
    for item in nodes:
        item["children"] = list(children.get(item["id"], []))
    parent_map = {item["id"]: item["parent"] for item in nodes}
    pinned_node = pinned(events)
    main_path = []
    if pinned_node in valid:
        current, guard = pinned_node, set()
        while current in valid and current not in guard:
            guard.add(current)
            main_path.append(current)
            current = parent_map.get(current)
        main_path.reverse()
    return {"nodes": nodes, "active": active, "path": path,
            "main": pinned_node if pinned_node in valid else None,
            "main_path": main_path}


def conversation(events, limit=None, node=None):
    """按指定分支从根到叶还原网页消息，并标出节点 ID 供菜单操作。"""
    parent_map = {row["id"]: row["parent"] for row in node_rows(events)}
    path = set(path_ids(events, node))
    out = []
    for group in groups(events):
        node_id = group["node"]
        if node_id not in path:
            continue
        user_event = group["user"]
        parent = parent_map.get(node_id)
        out.append({"role": "user", "text": user_event.get("text") or "",
                    "turn": user_event.get("turn"), "ts": user_event.get("ts"),
                    "node": node_id, "parent": parent})
        lenses = []
        for item in group["items"]:
            if item.get("t") == "tool" and item.get("name") == "use_lens":
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                key = args.get("lens") if isinstance(args, dict) else None
                if key and key not in lenses:
                    lenses.append(key)
            elif item.get("t") == "assistant" and (item.get("text") or "").strip():
                out.append({"role": "assistant", "text": item["text"],
                            "turn": item.get("turn"), "ts": item.get("ts"),
                            "node": node_id, "parent": parent,
                            "model": item.get("model") or "",
                            "route": item.get("route") or "",
                            "thinking": item.get("thinking") or "", "lenses": lenses,
                            "stopped": bool(item.get("stopped"))})
    return out[-limit:] if limit and limit > 0 else out


def thinking_for(events, node):
    """按节点取思考原文。

    工具多步时每一步都会写一条 assistant 事件，thinking 是累计值，
    因此取最长的那条，而不是第一次出现的那条。
    """
    for group in groups(events):
        if group["node"] != node:
            continue
        texts = [item.get("thinking") or "" for item in group["items"]
                 if item.get("t") == "assistant" and (item.get("thinking") or "").strip()]
        return max(texts, key=len) if texts else ""
    return ""


def state_card(events, session_id, max_chars=1600, node=None):
    """每轮重建的状态卡：主线、已归档摘要、最近工具结果、上次回答要点。"""
    path = path_events(events, node)
    if not path and not any(event.get("t") == "user" for event in events):
        path = events
    if not path:
        return "[状态卡 · 每轮从事件日志重建] 新会话，暂无历史。"
    users = [event for event in path if event["t"] == "user"]
    tools = [event for event in path if event["t"] == "tool"]
    compacts = [event for event in path if event["t"] == "compact"]
    answers = [event for event in path
               if event["t"] == "assistant" and (event.get("text") or "").strip()]

    lines = [f"[状态卡 · 每轮从事件日志重建 · 压缩不影响] 会话 {session_id} · "
             f"第 {users[-1].get('turn') if users else 0} 轮 · "
             f"工具 {len(tools)} 次 · 压缩 {len(compacts)} 次"]
    if users:
        lines += ["主线（最近提问）："] + [
            f"  · 轮 {event.get('turn')}：{clip(event.get('text'), 110)}" for event in users[-4:]]
    if compacts:
        lines.append("已归档（压缩前的早前对话）：")
        lines += [f"  · 轮 {event.get('turn')} 压缩：{clip(event.get('summary'), 260)}"
                  for event in compacts[-2:] if event.get("summary")]
    if tools:
        last = tools[-1]
        flag = "" if last.get("ok", True) else "（失败）"
        lines.append(f"最近工具{flag}：{last.get('name')}("
                     f"{clip(last.get('arguments'), 80)}) → {clip(last.get('result'), 160)}")
        if len(tools) > 1:
            lines.append("工具用量：" + "、".join(
                f"{name}×{count}" for name, count in
                Counter(event.get("name") for event in tools).items()))
    if answers:
        lines.append("上次回答要点：" + (clip(answers[-1].get("text"), 200) or "（空）"))

    text = "\n".join(lines)
    if max_chars and len(text) > max_chars:
        suffix = f"\n…（状态卡截断，原长 {len(text)} 字；完整历史用 /log）"
        text = text[:max(0, max_chars - len(suffix))] + suffix
    return text


def digest(events, limit=8, node=None):
    """最近几轮的可读摘要，供 /log 与调试输出使用。"""
    rows = []
    for event in path_events(events, node):
        if event["t"] == "compact":
            rows.append({"turn": event.get("turn"), "compact": event})
        elif event["t"] in ("user", "assistant", "tool"):
            if not rows or "items" not in rows[-1] or rows[-1]["turn"] != event.get("turn"):
                rows.append({"turn": event.get("turn"), "items": []})
            rows[-1]["items"].append(event)

    out = []
    for group in (rows[-limit:] if limit and limit > 0 else rows):
        if "compact" in group:
            event = group["compact"]
            out.append(f"[轮 {group['turn']}] ✂️ 压缩 {event.get('from_chars')} → "
                       f"{event.get('to_chars')} 字，摘要：{clip(event.get('summary'), 200)}")
            continue
        out.append(f"[轮 {group['turn']}]")
        for event in group["items"]:
            if event["t"] == "user":
                out.append("  你：" + clip(event.get("text"), 240))
            elif event["t"] == "tool":
                out.append(f"  工具{'' if event.get('ok', True) else '（失败）'}："
                           f"{clip(event.get('result'), 200)}")
            else:
                out.append("  AI：" + (clip(event.get("text"), 240) or "（只调用了工具）"))
                out += [f"      ↳ {call.get('name')}({clip(call.get('arguments'), 120)})"
                        for call in event.get("calls") or []]
    return "\n".join(out) if out else "暂无历史。"


def rebuild_messages(events, limit=8, node=None):
    """把当前路径还原成 LLM 消息（只保留问答文本，不含工具细节）。"""
    pairs = []
    for event in path_events(events, node):
        if event["t"] == "user":
            pairs.append({"role": "user", "content": event.get("text") or ""})
        elif event["t"] == "assistant" and (event.get("text") or "").strip():
            pairs.append({"role": "assistant", "content": event["text"]})

    tail = pairs[-limit:] if limit and limit > 0 else pairs
    while tail and tail[0]["role"] != "user":
        tail = tail[1:]
    return tail


def summarize(events):
    """会话列表用的一行摘要：轮数、首问预览、标题、最后一次提问时间。"""
    deleted = deleted_nodes(events)
    users = [row["event"] for row in node_rows(events) if row["id"] not in deleted]
    titles = [event.get("title") for event in events
              if event.get("t") == "title" and (event.get("title") or "").strip()]
    # 列表里的时间是「最后一次提问」而不是文件 mtime：切换分支、重命名、删除
    # 都会追加事件，用 mtime 会让这些操作把对话顶到最前面。
    # 必须只算还活着的节点，否则删掉最新一问后，列表时间还停在那条已删除的提问上。
    asked = [event.get("ts") for event in users if event.get("ts")]
    return {
        "turns": len(users),
        "preview": clip(users[0].get("text") if users else "", 40),
        "title": clip(titles[-1] if titles else
                      next((event.get("text") for event in users
                            if (event.get("text") or "").strip()), "")
                      or "新对话", 28) or "新对话",
        "date": asked[-1] if asked else "",
    }
