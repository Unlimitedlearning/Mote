"""跨层共用的错误类型。

放在 core 是因为 infra 读写配置时要抛它，services 与 interfaces 只负责翻译成提示或状态码。
"""


class ConfigError(Exception):
    """配置缺失或不合法：端点不存在、字段为空、文件读不出来。"""
