"""配置模型：默认值、深合并、profile 解析规则与路径计算。

这一层只处理内存里的字典与路径，不读写文件；磁盘上的加载与保存见
`mote.infra.config_file`，设置面板的表单语义见 `mote.services.settings`。
"""

import os

from .errors import ConfigError

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
            # 思考模式：deepseek-chat 默认不返回 reasoning_content，打开后才有思考过程；
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
        # mode 是当前唯一的问答方式开关，取值 hybrid / direct / local
        # （enabled 保留为兼容字段，写入时按 mode 同步）
        "mode": "hybrid",
        "enabled": True,                 # 本地 qwen 前置，云端只处理复杂请求
        "router_profile": "local",       # 路由/压缩/预选 + 仅本地回答用的端点
        "worker_profile": "cloud",       # 复杂请求交给谁
        "fallback_worker": "local",      # 云端 key 缺失或不可用时回退
        "context_chars": 700,            # 喂给云端的压缩上下文上限
        "router_max_tokens": 2048,        # qwen3.5 推理会吃掉一部分预算，512 不够输出 JSON
        "local_answer_max_tokens": 2048, # 仅本地回答的预算
    },
    "server": {
        "host": "127.0.0.1",
        "port": 9000,
    },
}


def merge(base, override):
    """递归合并两个字典。"""
    out = dict(base)
    for key, value in (override or {}).items():
        out[key] = (merge(out[key], value)
                    if isinstance(value, dict) and isinstance(out.get(key), dict) else value)
    return out


def mode_of(hybrid_cfg):
    """问答方式：mode 优先（hybrid / direct / local），enabled 是旧字段。

    两者冲突时按 enabled 走——旧配置、旧调用方（`hybrid={"enabled": False}`）只写 enabled，
    不能让残留的 mode 把它们的意思改掉。
    """
    hybrid = hybrid_cfg or {}
    raw = str(hybrid.get("mode") or "").strip().lower()
    if raw in ("hybrid", "direct", "local"):
        if raw == "hybrid" and hybrid.get("enabled") is False:
            return "direct"
        return raw
    return "hybrid" if hybrid.get("enabled") else "direct"


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


def agent_cfg(cfg):
    return cfg.get("agent") or DEFAULT["agent"]


def memory_root(cfg):
    return resolve_path(agent_cfg(cfg).get("memory_dir") or "memory")


def server_cfg(cfg):
    return cfg.get("server") or DEFAULT["server"]


__all__ = [
    "CONFIG_FILE", "EXAMPLE_FILE", "PROJECT_ROOT", "DEFAULT", "ConfigError",
    "merge", "mode_of", "resolve_path", "config_target",
    "agent_cfg", "memory_root", "server_cfg",
]
