"""把 DeepSeek 导出的会话转换成 Mote 的事件日志格式。

默认导入完整分支树：DeepSeek 的 USER/ASSISTANT 树会映射成 Mote 问答节点，
current_message_id 所在路径成为当前分支。只做数据转换，不联网、不改源数据。

用法：
    python tools/import_deepseek.py --dry-run
    python tools/import_deepseek.py --limit 5
    python tools/import_deepseek.py --sync              # 升级旧导入会话
    python tools/import_deepseek.py --force --max-turns 200
    python tools/import_deepseek.py --current-only      # 旧行为：只取当前链路
"""

import argparse
import datetime
import json
import os
import re
import sys

SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def parse_args(argv=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="DeepSeek 导出数据 → Mote 会话格式")
    p.add_argument("--source", default=os.path.join(root, "deepseek_data"))
    p.add_argument("--root", default=os.path.join(root, "memory"))
    p.add_argument("--limit", type=int, default=0, help="最多转换几个会话，0 表示全部")
    p.add_argument("--max-turns", type=int, default=0, help="每个会话保留最近几轮，0 表示全部")
    p.add_argument("--include-tools", action="store_true", help="把搜索/打开网页记成 tool 事件")
    p.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    p.add_argument("--force", action="store_true", help="覆盖已存在的会话目录")
    p.add_argument("--sync", action="store_true", help="只升级旧导入格式，保留已有新对话的会话")
    p.add_argument("--current-only", action="store_true", help="只导入当前分支，不导入兄弟分支")
    return p.parse_args(argv)


def stamp(ts):
    if not isinstance(ts, str):
        return datetime.datetime.now().isoformat(timespec="seconds")
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat(timespec="seconds")
    except ValueError:
        return ts[:19]


def epoch(ts):
    try:
        return datetime.datetime.fromisoformat(stamp(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def write_jsonl(path, events):
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def active_chain(session):
    """沿 current_message_id 的 parent_id 回溯，用于 max-turns 与旧模式。"""
    by_id = {str(m["id"]): m for m in session.get("messages", [])
             if isinstance(m, dict) and "id" in m}
    if not by_id:
        return []
    chain, cursor, seen = [], str(session.get("current_message_id")), set()
    while cursor in by_id and cursor not in seen:
        seen.add(cursor)
        item = by_id[cursor]
        chain.append(item)
        parent = item.get("parent_id")
        cursor = str(parent) if parent is not None else None
    chain.reverse()
    if len(chain) < 2 or not any(m.get("role") == "USER" for m in chain):
        chain = sorted(by_id.values(), key=lambda m: (m.get("id") or 0))
    return chain


def text_of(message):
    """提取用户正文与附件占位；Mote 只处理文本，附件保留原始路径供查回。"""
    parts = []
    for frag in message.get("fragments") or []:
        kind = frag.get("type")
        if kind == "REQUEST" and isinstance(frag.get("content"), str):
            parts.append(frag["content"])
        elif kind == "FILE":
            for item in frag.get("files") or []:
                name = item.get("file_name") or "附件"
                path = item.get("export_path") or ""
                label = "图片" if item.get("is_image") else "文件"
                parts.append(f"[{label}：{name}]" + (f"（原始文件：{path}）" if path else ""))
    return "\n".join(x for x in parts if x).strip()


def answer_of(message, include_tools=False):
    thinking, response, tools = [], [], []
    for frag in message.get("fragments") or []:
        kind, content = frag.get("type"), frag.get("content")
        if kind == "THINK" and isinstance(content, str) and content.strip():
            thinking.append(content.strip())
        elif kind in ("RESPONSE", "TEMPLATE_RESPONSE") and isinstance(content, str) and content.strip():
            response.append(content.strip())
        elif include_tools and kind in ("TOOL_SEARCH", "TOOL_OPEN"):
            tools.append((kind.replace("TOOL_", "").lower(), frag))
    return "\n\n".join(thinking), "\n\n".join(response), tools


def tool_event(turn, ts, name, frag):
    if name == "search":
        queries = frag.get("queries") or []
        result = "搜索：" + "；".join(str(q) for q in queries[:8])
    else:
        result = "打开：" + str(frag.get("url") or frag.get("title") or "（无结果）")
    return {"t": "tool", "ts": ts, "turn": turn, "name": name,
            "arguments": "{}", "result": result[:1200], "ok": True}


def _sort_key(message):
    value = message.get("id")
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _build_nodes(session, args):
    """把 DeepSeek 消息树展开为 Mote 问答节点。一个 USER + 一个 ASSISTANT 子节点 = 一个节点。"""
    messages = [m for m in session.get("messages", []) if isinstance(m, dict) and "id" in m]
    by_id = {str(m["id"]): m for m in messages}
    children = {}
    for message in messages:
        parent = message.get("parent_id")
        key = str(parent) if parent is not None else None
        children.setdefault(key, []).append(message)
    for bucket in children.values():
        bucket.sort(key=_sort_key)

    nodes, by_key = [], {}

    def add_node(user, assistant, parent, depth):
        uid = str(user["id"])
        aid = str(assistant["id"]) if assistant else "x"
        node_id = f"ds-{uid}-{aid}"
        ts_user = stamp(user.get("inserted_at"))
        events = [{"t": "user", "ts": ts_user, "turn": depth,
                   "text": text_of(user), "node": node_id, "parent": parent}]
        thoughts = []
        if assistant is not None:
            ts = stamp(assistant.get("inserted_at"))
            thinking, response, tools = answer_of(assistant, args.include_tools)
            event = {"t": "assistant", "ts": ts, "turn": depth,
                     "text": response or ("（该轮没有最终回答，仅有思维过程）" if thinking else ""),
                     "calls": [], "model": "deepseek", "route": "import", "node": node_id}
            if thinking:
                event["thinking"] = thinking
                thoughts.append({"t": "thought", "ts": ts, "turn": depth,
                                 "text": thinking, "node": node_id})
            events.append(event)
            for name, frag in tools:
                events.append(tool_event(depth, ts, name, frag))
        node = {"id": node_id, "events": events, "thoughts": thoughts,
                "parent": parent, "depth": depth}
        nodes.append(node)
        by_key[(uid, aid)] = node
        return node

    def walk(message, parent, depth):
        mid = str(message["id"])
        kids = children.get(mid, [])
        if message.get("role") == "USER":
            if not text_of(message):
                for child in kids:
                    walk(child, parent, depth)
                return
            assistants = [m for m in kids if m.get("role") == "ASSISTANT"]
            created = []
            if assistants:
                for assistant in assistants:
                    created.append(add_node(message, assistant, parent, depth))
            else:
                created.append(add_node(message, None, parent, depth))
            for assistant in assistants:
                aid = str(assistant["id"])
                node = by_key[(mid, aid)]
                for child in children.get(aid, []):
                    walk(child, node["id"], depth + 1)
            regular = [m for m in kids if not (m.get("role") == "ASSISTANT")]
            for child in regular:
                walk(child, created[0]["id"], depth + 1)
        else:
            for child in kids:
                walk(child, parent, depth)

    for root in children.get(None, []):
        walk(root, None, 1)

    current = by_id.get(str(session.get("current_message_id")))
    active = None
    if current is not None:
        cid = str(current["id"])
        if current.get("role") == "ASSISTANT":
            uid = str(current.get("parent_id"))
            active = by_key.get((uid, cid))
        elif current.get("role") == "USER":
            assistants = [m for m in children.get(cid, []) if m.get("role") == "ASSISTANT"]
            if assistants:
                active = by_key.get((cid, str(assistants[0]["id"])))
            else:
                active = by_key.get((cid, "x"))
    return nodes, active


def convert(session, title, args):
    sid = str(session.get("id") or "")
    if not SAFE_ID.fullmatch(sid):
        return None, "会话 id 不合法，跳过"

    source = dict(session)
    if args.current_only:
        source["messages"] = active_chain(session)

    nodes, active = _build_nodes(source, args)
    if not nodes:
        return None, "没有可用问答，跳过"

    chain_turns = sum(1 for m in active_chain(source) if m.get("role") == "USER")
    if args.max_turns > 0 and chain_turns > args.max_turns:
        first = chain_turns - args.max_turns + 1
        nodes = [node for node in nodes if node["depth"] >= first]

    events = [{"t": "session", "ts": stamp(session.get("inserted_at")),
               "profile": "deepseek-import", "model": "deepseek"}]
    if title:
        events.append({"t": "title", "ts": stamp(session.get("updated_at")), "title": title[:80]})
    thoughts = []
    for node in nodes:
        events.extend(node["events"])
        thoughts.extend(node["thoughts"])
    if active is not None and any(node["id"] == active["id"] for node in nodes):
        events.append({"t": "cursor", "ts": stamp(session.get("updated_at")),
                       "node": active["id"]})

    turns = min(chain_turns, args.max_turns) if args.max_turns > 0 else chain_turns
    return {"id": sid, "title": title or "DeepSeek 会话", "events": events,
            "thoughts": thoughts, "target": os.path.join(args.root, "sessions", sid),
            "turns": turns}, ""


def _can_sync(existing_path):
    """仅升级纯旧导入数据；一旦有节点字段或新对话就跳过，避免覆盖用户后续工作。"""
    if not os.path.exists(existing_path):
        return True, ""
    try:
        with open(existing_path, encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return False, "现有日志无法读取"
    if any(event.get("node") for event in events):
        return False, "已是节点格式"
    if any(event.get("t") == "assistant" and event.get("route") not in ("import", None)
           for event in events):
        return False, "会话已有新对话"
    return True, ""


def main(argv=None):
    args = parse_args(argv)
    source = os.path.join(args.source, "chat_sessions")
    if not os.path.isdir(source):
        print(f"找不到会话目录：{source}", file=sys.stderr)
        return 2

    index = {}
    index_path = os.path.join(args.source, "chat_session_index.json")
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as f:
                index = {row["id"]: row.get("title") or "" for row in json.load(f)}
        except (OSError, ValueError, KeyError, TypeError):
            index = {}

    paths = sorted((os.path.join(source, name) for name in os.listdir(source)
                    if name.endswith(".json")), reverse=True)
    if args.limit > 0:
        paths = paths[:args.limit]

    imported = skipped = turns = thinking_count = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
        except (OSError, ValueError):
            skipped += 1
            continue
        target = os.path.join(args.root, "sessions", str(session.get("id") or ""))
        events_path = os.path.join(target, "events.jsonl")
        if os.path.exists(target) and not args.force:
            if args.sync:
                ok, reason = _can_sync(events_path)
                if not ok:
                    skipped += 1
                    print(f"  跳过  {os.path.basename(path)}：{reason}")
                    continue
            else:
                skipped += 1
                print(f"  跳过  {os.path.basename(path)}：已存在，跳过")
                continue

        result, reason = convert(session, index.get(session.get("id"), ""), args)
        if result is None:
            skipped += 1
            print(f"  跳过  {os.path.basename(path)}：{reason}")
            continue
        turns += result["turns"]
        thinking_count += len(result["thoughts"])
        if not args.dry_run:
            os.makedirs(result["target"], exist_ok=True)
            write_jsonl(events_path, result["events"])
            write_jsonl(os.path.join(result["target"], "thoughts.jsonl"), result["thoughts"])
            latest = epoch(result["events"][-1].get("ts"))
            if latest:
                os.utime(events_path, (latest, latest))
        imported += 1
        print(f"  {'预览' if args.dry_run else '导入'}  {result['title'][:24]:<24} "
              f"{result['turns']:>5} 轮 · {len(result['events'])} 事件")

    label = "预览" if args.dry_run else "导入"
    print(f"\n完成：{label} {imported} 个会话、{turns} 轮、{thinking_count} 段思维；"
          f"跳过 {skipped} 个。目标：{args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
