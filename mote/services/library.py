"""会话库：跨会话的列表、全文检索与整库备份。

只读磁盘快照，不改任何事件；索引文件与内存缓存用来避免每次刷新都重解析全部日志。
"""

import datetime
import os
import re
import threading

from ..core import events as events_mod
from ..core.text import clip
from ..infra import store
from .conversation import Conversation

_LIST_CACHE = {}
_LIST_LOCK = threading.Lock()


def session_count(root):
    """只数目录，不解析日志：/health 会在每次打开页面时调用。"""
    base = os.path.join(root, "sessions")
    try:
        return sum(1 for item in os.scandir(base) if item.is_dir())
    except OSError:
        return 0


def list_sessions(root):
    """会话列表：标题、轮数、首问预览与最后一次提问时间。"""
    base = os.path.join(root, "sessions")
    if not os.path.isdir(base):
        return []

    signature = store.session_signature(base)
    if signature is not None:
        with _LIST_LOCK:
            cached = _LIST_CACHE.get(root)
        if cached is not None and cached[0] == signature:
            return [dict(row) for row in cached[1]]
        signature_map = {name: (mtime, size) for name, mtime, size in signature}
    else:
        signature_map = {}

    index = store.load_index(root)
    changed = False
    out = []
    try:
        names = os.listdir(base)
    except OSError:
        return []
    for name in names:
        conversation = Conversation(root, name)
        try:
            stat = os.stat(conversation.events_path)
        except OSError:
            continue
        stamp = signature_map.get(name)
        if stamp is None:
            stamp = (stat.st_mtime_ns, stat.st_size)
        entry = index.get(name)
        if (entry and entry.get("mtime_ns") == stamp[0]
                and entry.get("size") == stamp[1] and "date" in entry):
            turns, title, preview = entry["turns"], entry["title"], entry["preview"]
            date = entry["date"]
        else:
            summary = events_mod.summarize(conversation.events())
            turns, title, preview = (summary["turns"], summary["title"],
                                     summary["preview"])
            date = summary["date"]
            index[name] = {"mtime_ns": stamp[0], "size": stamp[1], **summary}
            changed = True
        out.append({
            "id": name,
            "turns": turns,
            # 没有提问记录的会话（刚建、或只导入过空白会话）退回建会话的时间
            "date": date or datetime.datetime.fromtimestamp(
                stat.st_mtime).isoformat(timespec="minutes"),
            "preview": preview,
            "title": title,
        })

    if changed:
        for name in list(index):
            if not os.path.exists(os.path.join(base, name, store.EVENTS_FILE)):
                index.pop(name, None)
        store.save_index(root, index)
    out.sort(key=lambda item: item["date"], reverse=True)

    if signature is not None:
        with _LIST_LOCK:
            _LIST_CACHE[root] = (signature, out)
    return [dict(row) for row in out]


def forget_cache(root=None):
    """配置或数据目录变化后清掉内存缓存。"""
    with _LIST_LOCK:
        if root is None:
            _LIST_CACHE.clear()
        else:
            _LIST_CACHE.pop(root, None)
    store.forget_index(root)


def _snippet(text, terms, width=110):
    """截取命中附近的一段正文，用 \\x01/\\x02 标出命中词，由前端替换成 <mark>。"""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    lower = text.lower()
    spots = [lower.find(term.lower()) for term in terms]
    spots = [item for item in spots if item >= 0]
    at = min(spots) if spots else 0
    start = max(0, at - width // 3)
    end = min(len(text), start + width)
    start = max(0, end - width)
    piece = text[start:end]
    pattern = re.compile("|".join(re.escape(term) for term in
                                  sorted(terms, key=len, reverse=True) if term), re.I)
    out, cursor = [], 0
    for match in pattern.finditer(piece):
        out.append(piece[cursor:match.start()])
        out.append("\x01" + match.group(0) + "\x02")
        cursor = match.end()
    out.append(piece[cursor:])
    body = "".join(out)
    return ("…" if start > 0 else "") + body + ("…" if end < len(text) else "")


def search_sessions(root, query, limit=50, per_session=4):
    """跨会话全文检索：空格分隔的多个词需同时命中，按命中次数与时间排序。

    已删除的节点不参与检索，避免搜出用户已经从界面删掉的内容。
    """
    terms = [item for item in re.split(r"\s+", str(query or "").strip()) if item]
    if not terms:
        return {"query": "", "total": 0, "sessions": 0, "results": []}
    lows = [term.lower() for term in terms]
    base = os.path.join(root, "sessions")
    if not os.path.isdir(base):
        return {"query": query, "total": 0, "sessions": 0, "results": []}

    results, total, scanned = [], 0, 0
    for name in os.listdir(base):
        conversation = Conversation(root, name)
        if not os.path.exists(conversation.events_path):
            continue
        events = conversation.events()
        if not events:
            continue
        scanned += 1
        rows = events_mod.node_rows(events)
        node_of_index = {row["index"]: row["id"] for row in rows}
        deleted = events_mod.deleted_nodes(events)
        title = clip(next((event.get("title") for event in reversed(events)
                           if event.get("t") == "title"
                           and (event.get("title") or "").strip()), ""), 40)
        if not title:
            first = next((row["event"].get("text") for row in rows
                          if (row["event"].get("text") or "").strip()), "")
            title = clip(first, 40) or "新对话"

        current, local = None, []
        for index, event in enumerate(events):
            kind = event.get("t")
            if kind == "user":
                current = node_of_index.get(index)
            if kind not in ("user", "assistant"):
                continue
            if current and current in deleted:
                continue
            text = event.get("text") or ""
            if not text:
                continue
            low = text.lower()
            if not all(term in low for term in lows):
                continue
            local.append({
                "session": name, "title": title, "node": current, "role": kind,
                "turn": event.get("turn"), "ts": event.get("ts"),
                "score": sum(low.count(term) for term in lows),
                "snippet": _snippet(text, terms),
            })
        total += len(local)
        local.sort(key=lambda item: (item["score"], str(item.get("ts") or "")),
                   reverse=True)
        results.extend(local[:per_session])

    results.sort(key=lambda item: (item["score"], str(item.get("ts") or "")),
                 reverse=True)
    return {"query": query, "total": total, "sessions": scanned,
            "results": results[:limit]}


def backup(root, at=None):
    """整库备份：每个会话一条结构化导出。"""
    sessions = [Conversation(root, row["id"]).export_payload()
                for row in list_sessions(root)]
    stamp = at or datetime.datetime.now()
    return {"format": "mote-backup/1",
            "exported_at": stamp.isoformat(timespec="seconds"),
            "count": len(sessions), "sessions": sessions}
