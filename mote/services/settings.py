"""配置的语义层：选哪个端点、缺没缺 key、设置面板收什么、存什么。

磁盘读写委托 `mote.infra.config_file`，路径与默认值来自 `mote.core.config`。
"""

import os

from ..core.config import ConfigError, PROJECT_ROOT, agent_cfg, config_target, mode_of
from . import lenses


def expand(value):
    """把 ${ENV} 占位符换成环境变量；没设置时返回空串。"""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value


def profile(cfg, name=None):
    """取一个端点配置：显式名字 > MOTE_PROFILE > default_profile。

    返回的字典带 `name`，并把 base_url / model / api_key 展开成真实值。
    """
    chosen = name or os.getenv("MOTE_PROFILE") or cfg.get("default_profile")
    profiles = cfg.get("profiles") or {}
    if chosen not in profiles:
        raise ConfigError(f"没有名为 {chosen!r} 的 profile，可用：{', '.join(profiles) or '（无）'}")

    item = dict(profiles[chosen], name=chosen)
    for field in ("base_url", "model", "api_key"):
        item[field] = os.getenv(f"MOTE_{field.upper()}") or expand(item.get(field, ""))
    for field in ("base_url", "model"):
        if not item[field]:
            raise ConfigError(f"profile {chosen!r} 缺少 {field}")
    return item


def mode(cfg):
    """问答方式：hybrid / direct / local。"""
    return mode_of(cfg.get("hybrid") or {})


def profile_info(cfg, name=None):
    try:
        item = profile(cfg, name)
        return {"name": item["name"], "model": item["model"]}
    except ConfigError:
        return None


def _usable(cfg, name=None):
    """这个端点能不能直接用：存在、字段齐全，且本机端点不要求 key。"""
    try:
        item = profile(cfg, name)
    except ConfigError:
        return False
    base_url = str(item.get("base_url") or "")
    local = "localhost" in base_url or "127.0.0.1" in base_url or "::1" in base_url
    return local or bool((item.get("api_key") or "").strip())


def needs_setup(cfg):
    """还没配好端点：首次打开就该把设置面板弹出来。

    要按**当前方式实际会用的端点**判断。hybrid 回答的是 worker_profile，
    只看 default_profile 会在 worker 缺 key 时误判成「配好了」，
    用户于是每问一句都拿到一条生成失败。
    """
    hybrid = cfg.get("hybrid") or {}
    current = mode(cfg)
    if current == "local":
        # 只用本地时不碰云端，只要 local 端点还在就不需要 key
        return not _usable(cfg, hybrid.get("router_profile") or "local")
    if current == "hybrid":
        # worker 缺 key 时还能退回 fallback_worker（通常是本地），两边都不可用才算没配好
        names = [hybrid.get("worker_profile") or "cloud"]
        if hybrid.get("fallback_worker"):
            names.append(hybrid["fallback_worker"])
        return not any(_usable(cfg, name) for name in names)
    return not _usable(cfg)


def system_prompt(cfg):
    """系统提示词 + 镜头目录；目录是常量，注入后仍是稳定前缀。"""
    try:
        with open(os.path.join(PROJECT_ROOT, agent_cfg(cfg).get("system_prompt")
                               or "prompts/system.md"), encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        text = "你是一个轻量思维顾问。挑 3-4 个镜头后再给建议。"
    # 详细提问清单不进这里，避免每轮都付一份大前缀
    tools = agent_cfg(cfg).get("tools") or []
    catalog = (lenses.catalog() if "use_lens" in tools
               else "（当前未启用镜头插件）")
    return text.replace("{{LENS_CATALOG}}", catalog)


def mask_key(key):
    """只回显首尾几位：设置页需要让用户确认「填过」，但不该把 key 明文送进浏览器。"""
    if not key:
        return ""
    if len(key) <= 10:
        return "*" * len(key)
    return key[:4] + "…" + key[-4:]


def key_of(item):
    """profile 里的 api_key 可能是 ${ENV} 占位符，取真正生效的值。"""
    raw = str((item or {}).get("api_key") or "")
    if raw.startswith("${") and raw.endswith("}"):
        return os.getenv(raw[2:-1], ""), raw[2:-1]
    return raw, ""


def display_path(path):
    """面板只展示项目内的相对路径：绝对路径会把本机目录带进截图和分享画面。"""
    if not path:
        return ""
    try:
        rel = os.path.relpath(path, PROJECT_ROOT)
    except ValueError:  # Windows 上跨盘符
        return os.path.basename(path)
    return os.path.basename(path) if rel.startswith("..") else rel.replace(os.sep, "/")


def settings_payload(cfg):
    """设置面板要的完整快照：端点列表（key 只给掩码）、问答方式、配置文件位置。"""
    profiles = []
    for name, item in (cfg.get("profiles") or {}).items():
        key, env = key_of(item)
        profiles.append({
            "name": name,
            "base_url": item.get("base_url") or "",
            "model": item.get("model") or "",
            "thinking": bool(item.get("thinking")),
            "max_tokens": item.get("max_tokens"),
            "has_key": bool(key),
            "key_hint": mask_key(key),
            "key_env": env,
        })
    hybrid = cfg.get("hybrid") or {}
    target = config_target(cfg)
    return {
        "config_path": display_path(target),
        "config_exists": os.path.exists(target),
        "default_profile": cfg.get("default_profile") or "local",
        "profiles": profiles,
        "hybrid": {"mode": mode(cfg),
                   "enabled": bool(hybrid.get("enabled")),
                   "router_profile": hybrid.get("router_profile") or "local",
                   "worker_profile": hybrid.get("worker_profile") or "cloud"},
    }


def settings_patch(cfg, data):
    """校验设置表单，返回要写进配置文件的片段；不合法时抛 ValueError。"""
    profiles = cfg.get("profiles") or {}
    patch = {}

    if "default_profile" in data:
        name = str(data["default_profile"] or "")
        if name not in profiles:
            raise ValueError(f"没有名为 {name!r} 的端点")
        patch["default_profile"] = name

    incoming = data.get("profiles")
    if incoming is not None:
        if not isinstance(incoming, dict):
            raise ValueError("profiles 必须是对象")
        changed = {}
        for name, item in incoming.items():
            if name not in profiles:
                raise ValueError(f"没有名为 {name!r} 的端点")
            if not isinstance(item, dict):
                raise ValueError(f"{name} 的配置必须是对象")
            entry = {}
            if "base_url" in item:
                url = str(item["base_url"] or "").strip()
                if not url.startswith(("http://", "https://")):
                    raise ValueError("接口地址要以 http:// 或 https:// 开头")
                entry["base_url"] = url
            if "model" in item:
                model = str(item["model"] or "").strip()
                if not model:
                    raise ValueError("模型名不能为空")
                entry["model"] = model
            key = str(item.get("api_key") or "").strip()
            if key:  # 留空表示保持原值，避免误清掉已保存的 key
                entry["api_key"] = key
            if "thinking" in item:
                entry["thinking"] = bool(item["thinking"])
            for field, low, high in (("max_tokens", 64, 200000), ("timeout", 5, 3600)):
                if field not in item:
                    continue
                try:
                    value = int(item[field])
                except (TypeError, ValueError):
                    raise ValueError(f"{field} 必须是整数") from None
                if not low <= value <= high:
                    raise ValueError(f"{field} 要在 {low} 到 {high} 之间")
                entry[field] = value
            if entry:  # 整组都是空值时不必写盘
                changed[name] = entry
        if changed:
            patch["profiles"] = changed

    hybrid_in = data.get("hybrid")
    if hybrid_in is not None:
        if not isinstance(hybrid_in, dict):
            raise ValueError("hybrid 必须是对象")
        hybrid = {}
        chosen = None
        if "mode" in hybrid_in:
            chosen = str(hybrid_in["mode"] or "").strip().lower()
            if chosen not in ("hybrid", "direct", "local"):
                raise ValueError("问答方式只能是 hybrid、direct 或 local")
        if "enabled" in hybrid_in and chosen is None:
            # 只给旧字段时按它推导，别让 mode 与 enabled 互相矛盾
            chosen = "hybrid" if bool(hybrid_in["enabled"]) else "direct"
        if chosen:
            hybrid["mode"] = chosen
            hybrid["enabled"] = chosen == "hybrid"
        for field in ("router_profile", "worker_profile"):
            if field not in hybrid_in:
                continue
            name = str(hybrid_in[field] or "")
            if name not in profiles:
                raise ValueError(f"没有名为 {name!r} 的端点")
            hybrid[field] = name
        if hybrid:
            patch["hybrid"] = hybrid

    return patch
