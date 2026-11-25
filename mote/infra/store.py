"""会话日志的磁盘层：追加事件、读取快照、维护跨进程的会话索引。

这一层只负责「字节到字典」的搬运，不判断分支、不拼状态卡；
所有语义计算在 `mote.core.events`，门面在 `mote.services.conversation`。
"""

import json
import os
import shutil
import threading

EVENTS_FILE = "events.jsonl"
THOUGHTS_FILE = "thoughts.jsonl"
INDEX_FILE = "session_index.json"


def session_dir(root, session_id):
    return os.path.join(root, "sessions", session_id)


class EventStore:
    """一条会话的日志文件：events.jsonl 是正式事件流，thoughts.jsonl 存思考原文。"""

    def __init__(self, root, session_id):
        self.root = root
        self.session_id = session_id
        self.home = session_dir(root, session_id)
        self.events_path = os.path.join(self.home, EVENTS_FILE)
        self.thoughts_path = os.path.join(self.home, THOUGHTS_FILE)

    def ensure(self):
        os.makedirs(self.home, exist_ok=True)

    def exists(self):
        return os.path.isfile(self.events_path)

    def append(self, event):
        self.ensure()
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def append_thought(self, event):
        self.ensure()
        with open(self.thoughts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    @staticmethod
    def read(path, allowed=None):
        """逐行解析；损坏的行直接跳过，不让一条坏记录挡住整个会话。"""
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
        return self.read(self.events_path)

    def thoughts(self):
        return self.read(self.thoughts_path, {"thought"})

    def remove(self):
        shutil.rmtree(self.home, ignore_errors=True)


_INDEX_CACHE = {}
_INDEX_LOCK = threading.Lock()


def session_signature(base):
    """用每个 events.jsonl 的 mtime+size 判断会话列表是否过期；只 stat，不读内容。"""
    signature = []
    try:
        names = os.listdir(base)
    except OSError:
        return None
    for name in names:
        try:
            stat = os.stat(os.path.join(base, name, EVENTS_FILE))
        except OSError:
            continue
        signature.append((name, stat.st_mtime_ns, stat.st_size))
    signature.sort()
    return tuple(signature)


def index_path(root):
    return os.path.join(root, INDEX_FILE)


def load_index(root):
    """跨进程复用的会话摘要：文件没变就不解析它。"""
    with _INDEX_LOCK:
        if root in _INDEX_CACHE:
            return _INDEX_CACHE[root]
    try:
        with open(index_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    with _INDEX_LOCK:
        _INDEX_CACHE[root] = data
    return data


def save_index(root, index):
    path = index_path(root)
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


def forget_index(root=None):
    """测试与设置变更后清掉内存缓存，下次重新从磁盘读。"""
    with _INDEX_LOCK:
        if root is None:
            _INDEX_CACHE.clear()
        else:
            _INDEX_CACHE.pop(root, None)
