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
| **hybrid**（默认） | `hybrid.enabled = true` | 路由器压出的短上下文 + 工具 schema |
| **legacy** | 测试注入假模型、`--no-hybrid`、`mode=direct` | 完整历史 + 稳定 system 前缀 + 尾部状态卡 |
| **本地直答** | 路由器判定 `route=local` | 只有状态卡，不触碰云端 |

`mode` 可以在单次请求里覆盖全局设置（`POST /inbox` 的 `mode` 字段），网页不逐条传，
统一走设置面板里的「问答方式」。

## 路由器的三件事

`mote/preprocess.py` 用一次本地调用同时完成：

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

`mote/context.py` 负责 legacy 路径的超长历史：超过 `compact_context_chars` 就压缩，
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

## 模块

| 文件 | 职责 |
|---|---|
| `mote/agent.py` | 通用 tool loop + 三条路径的分发 |
| `mote/preprocess.py` | 本地路由器：路由 / 压缩 / 预选 + 规则回退 |
| `mote/llm.py` | OpenAI 兼容客户端（urllib + SSE） |
| `mote/context.py` | legacy 路径的上下文裁剪与压缩 |
| `mote/memory.py` | 事件流水、状态卡、分支、模型归属 |
| `mote/tools.py` | 工具注册表（`@tool` 装饰器 + 白名单） |
| `mote/lenses.py` | 46 个手写思维镜头 |
| `mote/server.py` | HTTP 接口、设置面板后端、静态页 |
| `mote/web.py` | 单文件网页（HTML/CSS/JS，无 CDN） |
| `mote/cli.py` | 终端 REPL 与斜杠命令 |

工具层是插件式的：核心不认识具体业务，`@tool(name, description, schema)` 注册即可，
`agent.tools` 是白名单，传给云端的 schema 按白名单与预选结果过滤。删掉 `use_lens`
后 system 前缀里的镜头目录也会自动消失。

## 线程模型

一个 `ThreadingHTTPServer`，每个会话一把锁，同一会话的生成不并发；`Agent.request_stop()`
从另一个线程置位，`LLM.chat(..., should_stop=...)` 在流式分片之间检查，所以中断不需要等
生成结束。会话不跨线程共享，锁只保护事件写入与内存视图。
