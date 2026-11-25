"""配置文件的读写：找文件、合并默认值、原子写回。

只做磁盘操作，取哪个端点、缺 key 怎么提示由 `mote.services.settings` 决定。
"""

import json
import os

from ..core.config import (
    CONFIG_FILE, DEFAULT, EXAMPLE_FILE, PROJECT_ROOT, ConfigError, merge, resolve_path,
)


def find_config(explicit=None):
    for candidate in (explicit, os.getenv("MOTE_CONFIG")):
        if candidate:
            return resolve_path(candidate)
    for name in (CONFIG_FILE, EXAMPLE_FILE):
        path = os.path.join(PROJECT_ROOT, name)
        if os.path.exists(path):
            return path
    return None


def load(explicit=None):
    path = find_config(explicit)
    if path and not os.path.exists(path):
        raise ConfigError(f"找不到配置文件：{path}")
    raw = {}
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as err:
            raise ConfigError(f"{path} 不是合法 JSON：{err}") from err
        if not isinstance(raw, dict):
            raise ConfigError(f"{path} 的顶层必须是对象")
    return {**merge(DEFAULT, raw), "_config_path": path}


def update(path, patch):
    """把 patch 深合并进磁盘上的配置（不存在则新建），返回合并后的对象。

    只 patch 用户改过的字段：默认值仍由 DEFAULT 提供，升级时能拿到新默认。
    """
    raw = {}
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, json.JSONDecodeError) as err:
            raise ConfigError(f"{path} 读取失败：{err}") from err
    merged = merge(raw, patch or {})
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        # 文件里有 API key，尽量只给当前用户读写（Windows 上是空操作）
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return merged
