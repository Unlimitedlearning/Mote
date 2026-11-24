"""Mote · memory

事件日志保持 append-only。问答按节点组织：user 事件带 node/parent，
legacy 日志没有这两个字段时按出现顺序生成稳定节点 ID。删除与切换分支
也以事件形式追加，重建历史时只读取当前路径。
"""


import datetime
import json
import os
import random
import re
import threading
from collections import Counter


DEFAULT_SESSION = "main"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _clip(text, limit):
    """先截断再压空白：预览只取开头，不必为几百字的长回答跑整段正则。"""
    text = str(text or "")
    if limit and len(text) > limit:
        text = text[:limit] + "…"
    return re.sub(r"\s+", " ", text).strip()


def _quote(text):
    """把多行问题写成 Markdown 引用块，空行也保留引用前缀。"""
    lines = str(text or "").splitlines() or [""]
    return "\n".join("> " + line if line.strip() else ">" for line in lines)


def new_session_id():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"s-{stamp}-{random.randrange(0x1000, 0xFFFF):04x}"


def new_node_id():
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    return f"n-{stamp}-{random.randrange(0x1000, 0xFFFF):04x}"


class Memory:

    def __init__(self, root, session_id=None):
        self.root = root
        self.session_id = session_id or DEFAULT_SESSION
        self.home = os.path.join(root, "sessions", self.session_id)
        self.events_path = os.path.join(self.home, "events.jsonl")
        self.thoughts_path = os.path.join(self.home, "thoughts.jsonl")


    def ensure(self, **meta):
        os.makedirs(self.home, exist_ok=True)
        if not os.path.exists(self.events_path):
            self.record("session", **meta)

    def record(self, kind, **fields):
        os.makedirs(self.home, exist_ok=True)
        event = {"t": kind, "ts": _now(), **fields}
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event


    def user(self, turn, text, node=None, parent=None):
        fields = {}
        if node:
            fields["node"] = node
            # 显式写出 parent（可为 None）：根级兄弟分支不能退化成「接在上一条之后」
            fields["parent"] = parent
        event = self.record("user", turn=turn, text=text, **fields)
        # 在主分支末端继续提问时主分支跟着前移，树上那条标记才不会停在旧位置
        if node and parent and self._pinned() == parent:
            self.record("main", node=node)
        return event

    def assistant(self, turn, text, calls=None, model=None, route=None, thinking=None,
                  node=None, stopped=False):
        extra = {}
        if node:
            extra["node"] = node
        if model:
            extra["model"] = model
        if route:
            extra["route"] = route
        if thinking:
            extra["thinking"] = thinking
        if stopped:
            extra["stopped"] = True
        return self.record("assistant", turn=turn, text=text or "",
                           calls=[{"name": c.get("name"),
                                   "arguments": _clip(c.get("arguments"), 500)}
                                  for c in (calls or [])], **extra)

    def rename(self, title):
        """标题以事件形式追加，不新增文件，保持会话目录只有两个日志。"""
        title = _clip(title, 80)
        if not title:
            return None
        return self.record("title", title=title)

    def tool(self, turn, name, arguments, result, ok=True):
        return self.record("tool", turn=turn, name=name, arguments=_clip(arguments, 300),
                           result=_clip(result, 1200), ok=bool(ok))

    def compact(self, turn, from_chars, to_chars, dropped, summary):
        return self.record("compact", turn=turn, from_chars=from_chars,
                           to_chars=to_chars, dropped=dropped, summary=summary)

    def note_think(self, turn, text, node=None):
        text = (text or "").strip()
        if not text:
            return None
        os.makedirs(self.home, exist_ok=True)
        event = {"t": "thought", "ts": _now(), "turn": turn, "text": text}
        if node:
            event["node"] = node
        with open(self.thoughts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return text


    def _read(self, path, allowed=None):
        if not os.path.exists(path):
            return []
        out = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and (allowed is None or event.get("t") in allowed):
                    out.append(event)
        return out

    def events(self):
        return self._read(self.events_path)

    def thoughts(self, limit=3, node=None):
        notes = self._read(self.thoughts_path, {"thought"})
        rows = self._node_rows()
        if rows:
            path_ids = set(self._path_ids(node))
            path_turns = {row["event"].get("turn") for row in rows
                          if row["id"] in path_ids}
            notes = [n for n in notes
                     if n.get("node") in path_ids
                     or (not n.get("node") and n.get("turn") in path_turns)]
        return notes[-limit:] if limit and limit > 0 else notes

    def turns(self):
        return sum(1 for e in self.events() if e["t"] == "user")


    def _node_rows(self, events=None):
        """把 user 事件映射成节点；legacy 节点 ID 由出现顺序决定，跨重启稳定。"""
        events = self.events() if events is None else events
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

    def _deleted_nodes(self, events=None):
        events = self.events() if events is None else events
        deleted = set()
        for event in events:
            if event.get("t") != "delete":
                continue
            if event.get("nodes"):
                deleted.update(event["nodes"])
            elif event.get("node"):
                deleted.add(event["node"])
        return deleted

    def _branch_leaf(self, node, rows, deleted):
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

    def _active_node(self, events, rows, deleted):
        alive = [row for row in rows if row["id"] not in deleted]
        if not alive:
            return None
        alive_ids = {row["id"] for row in alive}
        # 主分支是显式标记，优先于「最近一次切换的分叉点」，打开会话稳定落在同一条链路
        pinned = self._pinned(events)
        if pinned in alive_ids:
            return self._branch_leaf(pinned, rows, deleted)
        cursor_node, cursor_index = None, -1
        for index, event in enumerate(events):
            if event.get("t") == "cursor":
                cursor_node, cursor_index = event.get("node"), index
        if cursor_node in alive_ids:
            later = [row for row in alive if row["index"] > cursor_index]
            base = later[-1]["id"] if later else cursor_node
        else:
            base = alive[-1]["id"]
        return self._branch_leaf(base, rows, deleted)

    def active_node(self):
        events = self.events()
        return self._active_node(events, self._node_rows(events),
                                 self._deleted_nodes(events))

    def _path_ids(self, node=None, events=None):
        events = self.events() if events is None else events
        rows = self._node_rows(events)
        lookup = {row["id"]: row for row in rows}
        deleted = self._deleted_nodes(events)
        target = node or self._active_node(events, rows, deleted)
        path, seen = [], set()
        while target in lookup and target not in seen and target not in deleted:
            path.append(target)
            seen.add(target)
            target = lookup[target]["parent"]
        return list(reversed(path))

    def _groups(self, events=None):
        """每个 user 事件到下一个 user 之前的内容属于同一个问答节点。"""
        events = self.events() if events is None else events
        by_index = {row["index"]: row["id"] for row in self._node_rows(events)}
        groups, current = [], None
        for index, event in enumerate(events):
            kind = event.get("t")
            if kind == "user":
                current = {"node": by_index.get(index), "user": event, "items": []}
                groups.append(current)
            elif kind in ("session", "title", "cursor", "delete", "main"):
                continue
            elif current is not None:
                current["items"].append(event)
        return groups

    def path_events(self, node=None):
        events = self.events()
        path = set(self._path_ids(node, events))
        out = []
        for group in self._groups(events):
            if group["node"] in path:
                out.append(group["user"])
                out.extend(group["items"])
        return out

    def has_node(self, node):
        return bool(node) and any(row["id"] == node for row in self._node_rows())

    def is_active_node(self, node):
        return self.has_node(node) and node not in self._deleted_nodes()

    def parent_of(self, node):
        for row in self._node_rows():
            if row["id"] == node and node not in self._deleted_nodes():
                return row["parent"]
        return None

    def set_cursor(self, node):
        """切换当前分支；后续提问以该节点为父节点。"""
        if not self.is_active_node(node):
            return None
        return self.record("cursor", node=node)

    def _pinned(self, events=None):
        """最后一个 main 事件记录的节点；未设置或被取消时为 None。

        只做存在性判断，是否仍在有效集合里由调用方核对。
        """
        events = self.events() if events is None else events
        node = None
        for event in events:
            if event.get("t") == "main":
                node = event.get("node")
        return node or None

    def main_node(self, events=None):
        """会话的主分支节点；未设置、已取消或该节点已删除时为 None。"""
        events = self.events() if events is None else events
        node = self._pinned(events)
        if not node:
            return None
        alive = {row["id"] for row in self._node_rows(events)}
        alive -= self._deleted_nodes(events)
        return node if node in alive else None

    def set_main(self, node=None):
        """把一条链路设为主分支：之后打开会话优先停在这里；node 为空表示取消。"""
        if not node:
            return self.record("main", node=None)
        if not self.is_active_node(node):
            return None
        return self.record("main", node=node)

    def delete_node(self, node, tip=None):
        """删除当前路径上的问答；同层兄弟分支与其它子树保留。"""
        events = self.events()
        rows = self._node_rows(events)
        lookup = {row["id"]: row for row in rows}
        deleted = self._deleted_nodes(events)
        if node not in lookup or node in deleted:
            return None

        # tip 是界面正在显示的链路末端：主分支存在时不能拿它当删除范围
        path = self._path_ids(tip or None, events)
        if node in path:
            at = path.index(node)
            removed = [item for item in path[at:] if item not in deleted]
        else:
            # 非当前路径的节点不在界面菜单里出现，退化为该节点子树，避免误删当前分支
            children = {}
            for row in rows:
                if row["parent"] and row["parent"] not in deleted:
                    children.setdefault(row["parent"], []).append(row["id"])
            removed, stack = [], [node]
            while stack:
                current = stack.pop()
                if current in removed or current in deleted:
                    continue
                removed.append(current)
                stack.extend(children.get(current, []))

        self.record("delete", node=node, nodes=removed)
        if self.main_node(events) in removed:
            self.record("main", node=None)
        if node in path:
            ancestor = next((item for item in reversed(path[:path.index(node)])
                             if item not in removed), None)
            if ancestor:
                self.record("cursor", node=ancestor)
        return removed

    def branch_tree(self, events=None, node=None):
        events = self.events() if events is None else events
        rows = self._node_rows(events)
        deleted = self._deleted_nodes(events)
        valid = {row["id"] for row in rows if row["id"] not in deleted}
        # node 是界面当前显示的那条链：主分支只决定「打开时落在哪」，不能把跳转摁回去
        if node and node in valid:
            active = self._branch_leaf(node, rows, deleted)
        else:
            active = self._active_node(events, rows, deleted)
        path = self._path_ids(active, events)
        groups = {group["node"]: group for group in self._groups(events)}
        children = {node: [] for node in valid}
        nodes = []
        for row in rows:
            node = row["id"]
            if node not in valid:
                continue
            parent = row["parent"] if row["parent"] in valid else None
            if parent and parent != node:
                children[parent].append(node)
            group = groups.get(node, {"user": row["event"], "items": []})
            answer = next((e.get("text") for e in group["items"]
                           if e.get("t") == "assistant" and (e.get("text") or "").strip()), "")
            nodes.append({
                "id": node, "parent": parent, "children": list(children.get(node, [])),
                # 分支树只用于导航与预览，问题截断可把大会话的树体积压到十分之一
                "text": _clip(row["event"].get("text") or "", 120),
                "preview": _clip(answer, 60),
                "turn": row["event"].get("turn"), "ts": row["event"].get("ts"),
                "active": node == active, "in_path": node in path,
            })
        for item in nodes:
            item["children"] = list(children.get(item["id"], []))
        parent_of = {n["id"]: n["parent"] for n in nodes}
        pinned = self._pinned(events)
        main_path = []
        if pinned in valid:
            current, guard = pinned, set()
            while current in valid and current not in guard:
                guard.add(current)
                main_path.append(current)
                current = parent_of.get(current)
            main_path.reverse()
        return {"nodes": nodes, "active": active, "path": path,
                "main": pinned if pinned in valid else None,
                "main_path": main_path}


    def conversation(self, limit=None, node=None, events=None):
        """按指定分支从根到叶还原网页消息，并标出节点 ID 供菜单操作。

        events 可传入调用方已读好的快照，避免同一请求把大日志重复读多遍。
        """
        events = self.events() if events is None else events
        rows = self._node_rows(events)
        parent_map = {row["id"]: row["parent"] for row in rows}
        path = set(self._path_ids(node, events))
        out = []
        for group in self._groups(events):
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


    def title(self):
        """标题优先取重命名事件，其次首个问题；导出文件名也用它。"""
        events = self.events()
        titles = [event.get("title") for event in events
                  if event.get("t") == "title" and (event.get("title") or "").strip()]
        if titles:
            return _clip(titles[-1], 80)
        first = next((row["event"].get("text") for row in self._node_rows(events)
                      if (row["event"].get("text") or "").strip()), "")
        return _clip(first, 80) or "新对话"

    def export_filename(self, ext="md"):
        stem = re.sub(r"[\\/:*?\"<>|\s]+", "-", self.title()).strip("-._") or "mote"
        return f"{stem[:40]}.{ext}"

    def export_markdown(self, node=None, with_thinking=True, events=None):
        """当前分支导出为 Markdown：问题用引用块，回答保留原始 Markdown。"""
        events = self.events() if events is None else events
        messages = self.conversation(node=node, events=events)
        tree = self.branch_tree(events=events)
        meta = next((event for event in events
                     if event.get("t") == "session"), {})
        users = [item for item in messages if item["role"] == "user"]
        span = [item.get("ts") for item in messages if item.get("ts")]

        lines = [f"# {self.title()}", ""]
        lines.append(f"- 会话：`{self.session_id}`")
        if meta.get("model"):
            lines.append(f"- 模型：{meta['model']}")
        lines.append("- 导出：" + datetime.datetime.now().isoformat(sep=" ", timespec="seconds"))
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
                lines += ["---", "", f"## {turn}. 你", "", _quote(item.get("text")), ""]
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

    def export_payload(self, node=None, events=None):
        """结构化导出：当前分支的消息流 + 完整分支树 + 每个节点的问答原文。"""
        events = self.events() if events is None else events
        messages = self.conversation(node=node, events=events)
        tree = self.branch_tree(events=events)
        meta = next((event for event in events if event.get("t") == "session"), {})
        groups = {group["node"]: group for group in self._groups(events)}
        branches = {}
        for item in tree["nodes"]:
            group = groups.get(item["id"], {"items": []})
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
        return {
            "format": "mote-session/1",
            "session": self.session_id,
            "title": self.title(),
            "meta": {"profile": meta.get("profile", ""), "model": meta.get("model", "")},
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "active": tree["active"],
            "counts": {"turns": sum(1 for item in messages if item["role"] == "user"),
                       "nodes": len(tree["nodes"])},
            "messages": messages,
            "tree": tree,
            "branches": branches,
        }

    def thinking_for(self, node):
        """按节点取思考原文。思考正文不进 /messages，展开时才拉取。

        工具多步时每一步都会写一条 assistant 事件，thinking 是累计值，
        因此取最长的那条，而不是第一次出现的那条。
        """
        events = self.events()
        for group in self._groups(events):
            if group["node"] != node:
                continue
            texts = [item.get("thinking") or "" for item in group["items"]
                     if item.get("t") == "assistant" and (item.get("thinking") or "").strip()]
            return max(texts, key=len) if texts else ""
        return ""

    def state_card(self, max_chars=1600, node=None):
        events = self.path_events(node)
        raw_events = self.events()
        if not events and not any(e.get("t") == "user" for e in raw_events):
            events = raw_events
        if not events:
            return "[状态卡 · 每轮从事件日志重建] 新会话，暂无历史。"
        users = [e for e in events if e["t"] == "user"]
        tools = [e for e in events if e["t"] == "tool"]
        compacts = [e for e in events if e["t"] == "compact"]
        answers = [e for e in events if e["t"] == "assistant" and (e.get("text") or "").strip()]

        lines = [f"[状态卡 · 每轮从事件日志重建 · 压缩不影响] 会话 {self.session_id} · "
                 f"第 {users[-1].get('turn') if users else 0} 轮 · "
                 f"工具 {len(tools)} 次 · 压缩 {len(compacts)} 次"]
        if users:
            lines += ["主线（最近提问）："] + [
                f"  · 轮 {e.get('turn')}：{_clip(e.get('text'), 110)}" for e in users[-4:]]
        if compacts:
            lines.append("已归档（压缩前的早前对话）：")
            lines += [f"  · 轮 {e.get('turn')} 压缩：{_clip(e.get('summary'), 260)}"
                      for e in compacts[-2:] if e.get("summary")]
        if tools:
            last = tools[-1]
            flag = "" if last.get("ok", True) else "（失败）"
            lines.append(f"最近工具{flag}：{last.get('name')}("
                         f"{_clip(last.get('arguments'), 80)}) → {_clip(last.get('result'), 160)}")
            if len(tools) > 1:
                lines.append("工具用量：" + "、".join(
                    f"{name}×{count}" for name, count in Counter(e.get("name") for e in tools).items()))
        if answers:
            lines.append("上次回答要点：" + (_clip(answers[-1].get("text"), 200) or "（空）"))

        text = "\n".join(lines)
        if max_chars and len(text) > max_chars:
            suffix = f"\n…（状态卡截断，原长 {len(text)} 字；完整历史用 /log）"
            text = text[:max(0, max_chars - len(suffix))] + suffix
        return text


    def digest(self, limit=8, node=None):
        events = self.path_events(node)
        groups = []
        for event in events:
            if event["t"] == "compact":
                groups.append({"turn": event.get("turn"), "compact": event})
            elif event["t"] in ("user", "assistant", "tool"):
                if not groups or "items" not in groups[-1] or groups[-1]["turn"] != event.get("turn"):
                    groups.append({"turn": event.get("turn"), "items": []})
                groups[-1]["items"].append(event)

        out = []
        for group in (groups[-limit:] if limit and limit > 0 else groups):
            if "compact" in group:
                event = group["compact"]
                out.append(f"[轮 {group['turn']}] ✂️ 压缩 {event.get('from_chars')} → "
                           f"{event.get('to_chars')} 字，摘要：{_clip(event.get('summary'), 200)}")
                continue
            out.append(f"[轮 {group['turn']}]")
            for event in group["items"]:
                if event["t"] == "user":
                    out.append("  你：" + _clip(event.get("text"), 240))
                elif event["t"] == "tool":
                    out.append(f"  工具{'' if event.get('ok', True) else '（失败）'}："
                               f"{_clip(event.get('result'), 200)}")
                else:
                    out.append("  AI：" + (_clip(event.get("text"), 240) or "（只调用了工具）"))
                    out += [f"      ↳ {c.get('name')}({_clip(c.get('arguments'), 120)})"
                            for c in event.get("calls") or []]
        return "\n".join(out) if out else "暂无历史。"

    def rebuild_messages(self, limit=8, node=None):
        pairs = []
        for event in self.path_events(node):
            if event["t"] == "user":
                pairs.append({"role": "user", "content": event.get("text") or ""})
            elif event["t"] == "assistant" and (event.get("text") or "").strip():
                pairs.append({"role": "assistant", "content": event["text"]})

        tail = pairs[-limit:] if limit and limit > 0 else pairs
        while tail and tail[0]["role"] != "user":
            tail = tail[1:]
        return tail



_LIST_CACHE = {}
_LIST_LOCK = threading.Lock()
_INDEX_CACHE = {}
_INDEX_LOCK = threading.Lock()


def _session_signature(base):
    """用每个 events.jsonl 的 mtime+size 判断会话列表是否过期；只 stat，不读内容。"""
    signature = []
    try:
        names = os.listdir(base)
    except OSError:
        return None
    for name in names:
        try:
            stat = os.stat(os.path.join(base, name, "events.jsonl"))
        except OSError:
            continue
        signature.append((name, stat.st_mtime_ns, stat.st_size))
    signature.sort()
    return tuple(signature)


def _index_path(root):
    return os.path.join(root, "session_index.json")


def _load_index(root):
    """跨进程复用的会话摘要：文件没变就不解析它。"""
    with _INDEX_LOCK:
        if root in _INDEX_CACHE:
            return _INDEX_CACHE[root]
    try:
        with open(_index_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    with _INDEX_LOCK:
        _INDEX_CACHE[root] = data
    return data


def _save_index(root, index):
    path = _index_path(root)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _summarize(memory):
    events = memory.events()
    deleted = memory._deleted_nodes(events)
    users = [row["event"] for row in memory._node_rows(events)
             if row["id"] not in deleted]
    titles = [event.get("title") for event in events
              if event.get("t") == "title" and (event.get("title") or "").strip()]
    # 列表里的时间是「最后一次提问」而不是文件 mtime：切换分支、重命名、删除
    # 都会追加事件，用 mtime 会让这些操作把对话顶到最前面
    asked = [event.get("ts") for event in events
             if event.get("t") == "user" and event.get("ts")]
    return {
        "turns": len(users),
        "preview": _clip(users[0].get("text") if users else "", 40),
        "title": _clip(titles[-1] if titles else
                       next((e.get("text") for e in users if (e.get("text") or "").strip()), "")
                       or "新对话", 28) or "新对话",
        "date": asked[-1] if asked else "",
    }


def list_sessions(root):
    base = os.path.join(root, "sessions")
    if not os.path.isdir(base):
        return []

    signature = _session_signature(base)
    if signature is not None:
        with _LIST_LOCK:
            cached = _LIST_CACHE.get(root)
        if cached is not None and cached[0] == signature:
            return [dict(row) for row in cached[1]]
        signature_map = {name: (mtime, size) for name, mtime, size in signature}
    else:
        signature_map = {}

    index = _load_index(root)
    changed = False
    out = []
    try:
        names = os.listdir(base)
    except OSError:
        return []
    for name in names:
        memory = Memory(root, name)
        try:
            stat = os.stat(memory.events_path)
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
            summary = _summarize(memory)
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
            if not os.path.exists(os.path.join(base, name, "events.jsonl")):
                index.pop(name, None)
        _save_index(root, index)
    out.sort(key=lambda item: item["date"], reverse=True)

    if signature is not None:
        with _LIST_LOCK:
            _LIST_CACHE[root] = (signature, out)
    return [dict(row) for row in out]


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
        memory = Memory(root, name)
        if not os.path.exists(memory.events_path):
            continue
        events = memory.events()
        if not events:
            continue
        scanned += 1
        rows = memory._node_rows(events)
        node_of_index = {row["index"]: row["id"] for row in rows}
        deleted = memory._deleted_nodes(events)
        title = _clip(next((event.get("title") for event in reversed(events)
                            if event.get("t") == "title"
                            and (event.get("title") or "").strip()), ""), 40)
        if not title:
            first = next((row["event"].get("text") for row in rows
                          if (row["event"].get("text") or "").strip()), "")
            title = _clip(first, 40) or "新对话"

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

