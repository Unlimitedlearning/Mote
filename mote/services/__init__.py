"""L2 · 服务层：把 core 的纯逻辑与 infra 的 IO 组合成用例。

- conversation  会话门面：写事件、读视图、导出
- library       会话库：列表、检索、整库备份
- settings      配置语义：选端点、缺 key 判断、设置表单校验
- agent         问答编排：路由、工具循环、压缩、端点切换
- tools         工具注册表与内置工具
- lenses        精选镜头目录（可选插件）
"""
