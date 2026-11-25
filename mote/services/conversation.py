"""会话门面：把「追加事件」与「从事件重建视图」合成一个对象。

写操作（提问、回答、工具、压缩、切换分支、删除）落成事件追加；
读操作委托 `mote.core.events` 的纯函数。组件本身不解析日志格式，
那是 `mote.infra.store` 的职责。

事件日志保持 append-only。问答按节点组织：user 事件带 node/parent，
legacy 日志没有这两个字段时按出现顺序生成稳定节点 ID。删除与切换分支
也以事件形式追加，重建历史时只读取当前路径。
"""

import datetime

from ..core import events as events_mod
from ..core import export as export_mod
from ..core.ids import DEFAULT_SESSION
from ..core.text import clip, filename
from ..infra.store import EventStore


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class Conversation:
    """一条会话：事件流 + 分支视图。"""

    def __init__(self, root, session_id=None):
        self.root = root
        self.session_id = session_id or DEFAULT_SESSION
        self.store = EventStore(root, self.session_id)
        self.home = self.store.home
        self.events_path = self.store.events_path
        self.thoughts_path = self.store.thoughts_path

    # ---- 写入 ----------------------------------------------------------

    def ensure(self, **meta):
        self.store.ensure()
        if not self.store.exists():
            self.record("session", **meta)

    def record(self, kind, **fields):
        return self.store.append({"t": kind, "ts": _now(), **fields})

    def user(self, turn, text, node=None, parent=None):
        fields = {}
        if node:
            fields["node"] = node
            # 显式写出 parent（可为 None）：根级兄弟分支不能退化成「接在上一条之后」
            fields["parent"] = parent
        event = self.record("user", turn=turn, text=text, **fields)
        # 在主分支末端继续提问时主分支跟着前移，树上那条标记才不会停在旧位置
        if node and parent and events_mod.pinned(self.events()) == parent:
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
                           calls=[{"name": call.get("name"),
                                   "arguments": clip(call.get("arguments"), 500)}
                                  for call in (calls or [])], **extra)

    def rename(self, title):
        """标题以事件形式追加，不新增文件，保持会话目录只有两个日志。"""
        title = clip(title, 80)
        if not title:
            return None
        return self.record("title", title=title)

    def tool(self, turn, name, arguments, result, ok=True):
        return self.record("tool", turn=turn, name=name, arguments=clip(arguments, 300),
                           result=clip(result, 1200), ok=bool(ok))

    def compact(self, turn, from_chars, to_chars, dropped, summary):
        return self.record("compact", turn=turn, from_chars=from_chars,
                           to_chars=to_chars, dropped=dropped, summary=summary)

    def note_think(self, turn, text, node=None):
        text = (text or "").strip()
        if not text:
            return None
        event = {"t": "thought", "ts": _now(), "turn": turn, "text": text}
        if node:
            event["node"] = node
        self.store.append_thought(event)
        return text

    def set_cursor(self, node):
        """切换当前分支；后续提问以该节点为父节点。"""
        if not self.is_active_node(node):
            return None
        return self.record("cursor", node=node)

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
        rows = events_mod.node_rows(events)
        lookup = {row["id"]: row for row in rows}
        deleted = events_mod.deleted_nodes(events)
        if node not in lookup or node in deleted:
            return None

        # tip 是界面正在显示的链路末端：主分支存在时不能拿它当删除范围
        path = events_mod.path_ids(events, tip or None)
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
        if events_mod.main_node(events) in removed:
            self.record("main", node=None)
        if node in path:
            ancestor = next((item for item in reversed(path[:path.index(node)])
                             if item not in removed), None)
            if ancestor:
                self.record("cursor", node=ancestor)
        return removed

    # ---- 读取 ----------------------------------------------------------

    def events(self):
        return self.store.events()

    def thoughts(self, limit=3, node=None):
        events = self.events()
        notes = self.store.thoughts()
        rows = events_mod.node_rows(events)
        if rows:
            path = set(events_mod.path_ids(events, node))
            path_turns = {row["event"].get("turn") for row in rows if row["id"] in path}
            notes = [note for note in notes
                     if note.get("node") in path
                     or (not note.get("node") and note.get("turn") in path_turns)]
        return notes[-limit:] if limit and limit > 0 else notes

    def turns(self):
        return sum(1 for event in self.events() if event["t"] == "user")

    def active_node(self):
        return events_mod.active_node(self.events())

    def has_node(self, node):
        return events_mod.has_node(self.events(), node)

    def is_active_node(self, node):
        return events_mod.is_active_node(self.events(), node)

    def parent_of(self, node):
        return events_mod.parent_of(self.events(), node)

    def main_node(self, events=None):
        return events_mod.main_node(self.events() if events is None else events)

    def branch_tree(self, events=None, node=None):
        return events_mod.branch_tree(self.events() if events is None else events, node)

    def conversation(self, limit=None, node=None, events=None):
        """按指定分支从根到叶还原网页消息，并标出节点 ID 供菜单操作。"""
        return events_mod.conversation(self.events() if events is None else events,
                                       limit=limit, node=node)

    def path_events(self, node=None):
        return events_mod.path_events(self.events(), node)

    def thinking_for(self, node):
        return events_mod.thinking_for(self.events(), node)

    def state_card(self, max_chars=1600, node=None):
        return events_mod.state_card(self.events(), self.session_id,
                                     max_chars=max_chars, node=node)

    def digest(self, limit=8, node=None):
        return events_mod.digest(self.events(), limit=limit, node=node)

    def rebuild_messages(self, limit=8, node=None):
        return events_mod.rebuild_messages(self.events(), limit=limit, node=node)

    def title(self):
        return events_mod.title(self.events())

    def export_filename(self, ext="md"):
        return filename(self.title(), ext)

    def export_markdown(self, node=None, with_thinking=True, events=None):
        return export_mod.markdown(self.events() if events is None else events,
                                   self.session_id, node=node, with_thinking=with_thinking)

    def export_payload(self, node=None, events=None):
        return export_mod.payload(self.events() if events is None else events,
                                  self.session_id, node=node)

    # ---- 兼容旧调用点的视图辅助（供会话列表与测试复用） ------------------

    def _node_rows(self, events=None):
        return events_mod.node_rows(self.events() if events is None else events)

    def _deleted_nodes(self, events=None):
        return events_mod.deleted_nodes(self.events() if events is None else events)

    def _pinned(self, events=None):
        return events_mod.pinned(self.events() if events is None else events)

    def _path_ids(self, node=None, events=None):
        return events_mod.path_ids(self.events() if events is None else events, node)

    def _groups(self, events=None):
        return events_mod.groups(self.events() if events is None else events)

    def _active_node(self, events, rows, deleted):
        return events_mod.active_node(events, rows, deleted)
