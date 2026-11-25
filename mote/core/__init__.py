"""L0 · 纯逻辑层：只吃字典与列表，不碰磁盘、网络和全局状态。

- text      文本裁剪、引用块、文件名
- ids       会话与节点 ID
- errors    跨层共用的错误类型
- config    配置模型（默认值、合并、profile 取值规则、路径）
- context   上下文裁剪与压缩摘要
- events    事件流 → 节点 / 路径 / 分支树 / 视图 / 状态卡
- export    导出 Markdown 与结构化 JSON
- router    本地路由的提示词与 JSON 解析
"""
