"""Mote · config"""


import json
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

CONFIG_FILE = "config.json"
EXAMPLE_FILE = "config.example.json"

DEFAULT = {
    # 面向新用户：默认走云端（hybrid 的 worker 也是它），首次打开页面会提示填 key
    "default_profile": "cloud",
    "profiles": {
        "local": {
            "base_url": "http://localhost:11434/v1",
            "model": "qwen3.5:4b",
            "api_key": "ollama",
            "temperature": 0.3,
            "max_tokens": 2048,
            "timeout": 180,
        },
        "cloud": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "${DEEPSEEK_API_KEY}",
            "temperature": 0.3,
            # 思考模式：deepseek-chat 默认不返回 reasoning_content，打开后才会有思考过程；
            # 推理会占输出预算，所以上限比纯回答时放宽
            "thinking": True,
            "max_tokens": 8192,
            "timeout": 240,
        },
    },
    "agent": {
        "default_session": "main",
        "max_steps": 12,
        "lenses_per_turn": 5,        # AI 选，合计加载上限
        "compact_context_chars": 24000,
        "compact_keep_turns": 2,
        "compact_keep_tool_turns": 3,
        "compact_keep_msg_chars": 3000,
        "compact_thoughts": 3,
        "compact_thought_chars": 1200,
        "state_card_chars": 1600,
        "resume_messages": 8,
        "tools": ["now", "use_lens"],  # 初始工具：时间 + 可选镜头插件
        "system_prompt": "prompts/system.md",
        "memory_dir": "memory",
    },
    "hybrid": {
        "enabled": True,                 # 本地 qwen 前置，云端只处理复杂请求
        "router_profile": "local",       # 路由/压缩/预选用的本地端点
        "worker_profile": "cloud",       # 复杂请求交给谁
        "fallback_worker": "local",      # 云端 key 缺失或不可用时回退
        "context_chars": 700,            # 喂给云端的压缩上下文上限
        "router_max_tokens": 2048,        # qwen3.5 推理会吃掉一部分预算，512 不够输出 JSON
        "local_answer_max_tokens": 1024, # 本地直答的预算
    },
    "server": {
        "host": "127.0.0.1",
        "port": 9000,
    },
}


class ConfigError(Exception):
    pass


def _expand(value):
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value


def _merge(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        out[key] = (_merge(out[key], value)
                    if isinstance(value, dict) and isinstance(out.get(key), dict) else value)
    return out


def resolve_path(path):
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def config_target(cfg):
    """设置面板写盘的位置：已有 config.json 就用它，否则在项目根新建。

    示例文件只作模板，永远不覆盖——否则一次保存就把带注释的样板改花了，
    下次升级也看不到新的默认值。
    """
    path = cfg.get("_config_path") or ""
    name = os.path.basename(path).lower()
    if path and not (name == EXAMPLE_FILE or name.startswith("config.example")):
        return path
    return os.path.join(PROJECT_ROOT, CONFIG_FILE)


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
    merged = _merge(raw, patch or {})
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
    return {**_merge(DEFAULT, raw), "_config_path": path}


def profile(cfg, name=None):
    chosen = name or os.getenv("MOTE_PROFILE") or cfg.get("default_profile")
    profiles = cfg.get("profiles") or {}
    if chosen not in profiles:
        raise ConfigError(f"没有名为 {chosen!r} 的 profile，可用：{', '.join(profiles) or '（无）'}")

    item = dict(profiles[chosen], name=chosen)
    for field in ("base_url", "model", "api_key"):
        item[field] = os.getenv(f"MOTE_{field.upper()}") or _expand(item.get(field, ""))
    for field in ("base_url", "model"):
        if not item[field]:
            raise ConfigError(f"profile {chosen!r} 缺少 {field}")
    return item


def agent_cfg(cfg):
    return cfg.get("agent") or DEFAULT["agent"]


def memory_root(cfg):
    return resolve_path(agent_cfg(cfg).get("memory_dir") or "memory")


def server_cfg(cfg):
    return cfg.get("server") or DEFAULT["server"]


def system_prompt(cfg):
    try:
        with open(resolve_path(agent_cfg(cfg).get("system_prompt") or "prompts/system.md"),
                  encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        text = "你是一个轻量思维顾问。挑 3-4 个镜头后再给建议。"
    # 目录是常量，注入后仍是稳定前缀；详细提问清单不进这里。
    from . import lenses
    tools = agent_cfg(cfg).get("tools") or []
    catalog = (lenses.catalog() if "use_lens" in tools
               else "（当前未启用镜头插件）")
    return text.replace("{{LENS_CATALOG}}", catalog)
