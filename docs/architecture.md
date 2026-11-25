# 架构：一次请求怎么走

Mote 的目标是用最小的自建框架，把「本地小模型做前置、云端大模型做回答」串成一条链，
同时不牺牲对话历史的完整性。整个运行期只依赖 Python 标准库。

## 三条路径

```
你发一个问题
  └→ 本地 qwen 一次调用，输出 JSON：route / context / tools
       ├─ route=local  → 本地直接回答，云端 0 token
       └─ route=cloud  → 只把压缩上下文 + 选中的工具给云端
                           └→ 云端按需调工具，再给最终回答
```

| 路径 | 触发条件 | 送给模型的内容 |
|---|---|---|
| **hybrid**（默认） | `hybrid.mode = hybrid` | 路由器压出的短上下文 + 工具 schema |
| **legacy（直连）** | 测试注入假模型、`--no-hybrid`、`mode=direct` | 完整历史 + 稳定 system 前缀 + 尾部状态卡 |
| **local（仅本地）** | `hybrid.mode = local`、`--local` | 完整历史 + 尾部状态卡，只发本机端点 |
| **本地直答** | 路由器判定 `route=local` | 只有状态卡，不触碰云端 |

`hybrid.mode` 取 `hybrid` / `direct` / `local`，是设置面板里「问答方式」的唯一开关；
`hybrid.enabled` 是旧字段，写入时按 `mode` 同步，读的时候两者冲突以 `enabled` 为准（兼容旧配置）。

`mode` 也可以在单次请求里覆盖全局设置（`POST /inbox` 的 `mode` 字段），网页不逐条传，
统一走设置面板。仅本地与直连共用 `_ask_legacy`，差别只在用哪一组端点：
`local` 用 `router_profile`（本地），`direct` 用 `worker_profile`（云端），回答的 `route`
分别记 `local` / `direct`，网页据此显示「本地 · 模型名」或「云端直连 · 模型名」。

仅本地模式不会建路由：省掉一次调用，也避免 4B 模型的路由判断把问题误判成"该上云"。
配置里删掉 local 端点时，构造 Agent 会直接报错，**不会**悄悄回退到云端——
那会把「不出本机」的承诺打破。

## 路由器的三件事

`mote/core/router.py` 用一次本地调用同时完成：

1. **路由**：判断这个问题要不要上云。问候、事实、时间类问题本地直答。
2. **压缩**：把状态卡和历史压成 `hybrid.context_chars` 以内的短上下文。
3. **工具预选**：从白名单里挑出这一轮可能用到的工具，云端不再盲选。

输出预算是 `hybrid.router_max_tokens`（默认 2048）。4B 模型的推理会先吃掉一部分 token，
512 时正文经常为空，这是踩过的坑。

解析失败不抛错，走规则回退：按关键词识别时间问题选 `now`，其余把截断的状态卡交给
worker。也就是说路由器挂掉只会退化成"普通对话"，不会让整个请求失败。

## token 账

每条回答都会记录并展示**实际产出它的模型**（`本地 · qwen3.5:4b` / `云端 · deepseek-chat`），
以及这一轮省下的上下文字数。模型归属写入事件日志，历史回填后仍然可见——
这样"省钱"是可核对的，而不是一句宣传。

## 思考原文

模型的多轮推理原文单独存进 `assistant.thinking`，网页里折叠成「思考过程」，
展开才拉取；这段文本不进状态卡，不增加下一轮 token。

`deepseek-chat` 默认是非思考模式，不返回 `reasoning_content`。`profiles.cloud.thinking`
为 `true` 时请求里带 `thinking: {"type": "enabled"}` 才会一起返回；关掉就没有思考过程，
但更快更省。思考模式下推理会占用输出预算，所以 `max_tokens` 放到 8192。

本地直答不经过 worker，它的「思考过程」就是路由那次调用的推理（Ollama 的 `reasoning` 字段）。
工具轮里 assistant 的 `reasoning_content` 只在本轮回传，长期历史里会丢掉，避免白付 token。

## 上下文裁剪

`mote/core/context.py` 负责 legacy 路径的超长历史：超过 `compact_context_chars` 就压缩，
保留最近 `compact_keep_turns` 轮完整问答、`compact_keep_tool_turns` 轮工具调用，
单条消息截到 `compact_keep_msg_chars`，历史思考只留最近 `compact_thoughts` 条的
前 `compact_thought_chars` 字。

## 缓存不变量

- **legacy 路径**：完整历史 + 稳定 system 前缀 + 尾部状态卡，沿用 ZeroX 式逐字节前缀缓存。
  46 个精选镜头目录常驻 system 前缀，**绝不能进入 `self.messages`**，否则前缀失效。
  随机候选之类的动态内容只能放请求尾部。
- **hybrid 路径**：同一轮内工具调用共享同一段压缩前缀，所以第 2 次云端调用仍命中缓存。

`tests/test_loop.py::test_cache_prefix_stable_across_turns` 锁住 legacy 不变量；
`tests/test_hybrid.py` 锁住"简单问题不调云端"和"云端只收压缩上下文"。

## 分层

代码按四层组织，依赖只能从上往下，同层可以互相引用。`tests/test_layers.py`
用 AST 解析每个模块的相对导入，任何向上的依赖都会让测试失败。

| 层 | 目录 | 可以依赖 | 职责 |
|---|---|---|---|
| 接入 | `mote/interfaces/` | core / infra / services / 同层 | HTTP、网页、终端 |
| 服务 | `mote/services/` | core / infra / 同层 | 会话、问答编排、设置、工具 |
| 基础设施 | `mote/infra/` | core / 同层 | 配置读写、事件日志、模型客户端 |
| 纯逻辑 | `mote/core/` | 同层 | 配置模型、上下文、事件树、导出、路由规则 |

`mote/__main__.py` 在四层之上，只做参数解析与派发。`core` 里不出现文件读写与网络调用，
所以事件树、导出、路由解析都能用纯数据构造测试，不需要临时目录。

## 模块

| 文件 | 职责 |
|---|---|
| `mote/core/config.py` | 配置模型：默认值、深合并、profile 规则、路径 |
| `mote/core/context.py` | legacy 路径的上下文裁剪与压缩 |
| `mote/core/events.py` | 事件流 → 节点 / 路径 / 分支树 / 视图 / 状态卡 |
| `mote/core/export.py` | Markdown 与结构化 JSON 导出 |
| `mote/core/router.py` | 本地路由器：路由 / 压缩 / 预选的提示词与解析 |
| `mote/infra/config_file.py` | 配置文件的查找、加载与原子写回 |
| `mote/infra/store.py` | 事件日志与会话索引的读写 |
| `mote/infra/llm.py` | OpenAI 兼容客户端（urllib + SSE） |
| `mote/services/conversation.py` | 会话门面：追加事件、重建视图、导出 |
| `mote/services/library.py` | 会话列表、全文检索、整库备份 |
| `mote/services/settings.py` | 端点选择、缺 key 判断、设置表单校验 |
| `mote/services/agent.py` | 通用 tool loop + 三条路径的分发 |
| `mote/services/tools.py` | 工具注册表（`@tool` 装饰器 + 白名单） |
| `mote/services/lenses.py` | 46 个手写思维镜头 |
| `mote/interfaces/http/` | 路由分派、SSE 输出、会话缓存与启动 |
| `mote/interfaces/web/` | 页面模板与内联的 CSS / JS 资源 |
| `mote/interfaces/cli.py` | 终端 REPL 与斜杠命令 |

工具层是插件式的：核心不认识具体业务，`@tool(name, description, schema)` 注册即可，
`agent.tools` 是白名单，传给云端的 schema 按白名单与预选结果过滤。删掉 `use_lens`
后 system 前缀里的镜头目录也会自动消失。

## 线程模型

一个 `ThreadingHTTPServer`，每个会话一把锁，同一会话的生成不并发；`Agent.request_stop()`
从另一个线程置位，`LLM.chat(..., should_stop=...)` 在流式分片之间检查，所以中断不需要等
生成结束。会话不跨线程共享，锁只保护事件写入与内存视图。
