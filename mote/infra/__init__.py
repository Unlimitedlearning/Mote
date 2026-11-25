"""L1 · 基础设施层：只负责与外部世界交换字节。

- config_file  配置文件的查找、加载与原子写回
- store        事件日志与会话索引的读写
- llm          OpenAI 兼容客户端（urllib + SSE）
"""
