"""Mote —— 轻量通用 agent：工具可插拔，本地 qwen 前置以省云端 token。

零第三方依赖（只用标准库），可接本地 Ollama 或任意 OpenAI 兼容云端 API。

模块速查：
  agent.py    通用 tool loop：本地直答 / 云端压缩执行
  preprocess.py 本地路由器：一次调用完成路由、压缩、工具预选
  tools.py    工具注册表：now、use_lens（插件）
  lenses.py   46 个精选镜头的提问清单与目录（可选插件）
  llm.py      OpenAI 兼容客户端（urllib + SSE）
  memory.py   对话记忆：事件流水 + 每轮重建的状态卡
  context.py  上下文裁剪的纯函数
  server.py   HTTP 接口
  web.py      网页界面：双栏会话 + Markdown 渲染
  cli.py      终端 REPL
  config.py   配置加载与 profile 切换
"""
