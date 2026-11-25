# 配置

## 三种改法，按推荐顺序

1. **网页面板**（推荐）：右上角「⚙ 设置」。填完点「测试连接」会真的发一次极短请求验证，
   保存后立刻重建 agent，下一条消息就按新端点走，不用重启。
2. **环境变量**：`api_key` 支持 `${ENV_NAME}` 引用，密钥可以不落盘。
3. **直接编辑 `config.json`**：适合批量改或脚本化部署。

配置来源依次是 `config.json` → `config.example.json` → 代码内默认值。
没有 `config.json` 时直接用示例配置，所以 clone 下来不建配置也能跑。

`config.json` 已加入 `.gitignore`。面板保存时只写**改动过的字段**，其余继续走默认值，
这样升级后能拿到新的默认配置；没有 `config.json` 会在项目根新建，**绝不覆盖 `config.example.json`**。

## 环境变量

```bash
export DEEPSEEK_API_KEY=sk-xxx      # cloud profile 的 api_key 默认引用它
export DASHSCOPE_API_KEY=sk-xxx     # qwen-cloud profile
export MOTE_NO_BROWSER=1            # serve 时不自动开浏览器
```

## profiles：模型端点

一个 profile 就是一套 OpenAI 兼容端点。默认给了三个：`local`（Ollama）、
`cloud`（DeepSeek）、`qwen-cloud`（DashScope），填了 key 就能用，不用改代码。

| 字段 | 含义 |
|---|---|
| `base_url` | OpenAI 兼容接口地址，如 `https://api.deepseek.com/v1` |
| `model` | 模型名，如 `deepseek-chat` / `qwen3.5:4b` |
| `api_key` | 密钥，可写 `${ENV_NAME}` 引用环境变量；本地 Ollama 随便填 |
| `temperature` | 采样温度，默认 0.3 |
| `thinking` | 开启思考模式（DeepSeek 才会返回 `reasoning_content`） |
| `max_tokens` | 单次输出上限，思考模式建议 8192（推理也占预算） |
| `timeout` | 单次请求超时秒数 |

`default_profile` 决定 `--no-hybrid` 与直连时用哪个 profile，默认 `cloud`。
新用户没有 Ollama 也能跑起来，这是刻意的。

## agent：agent 行为

| 字段 | 默认 | 含义 |
|---|---|---|
| `tools` | `["now","use_lens"]` | 启用的工具白名单 |
| `lenses_per_turn` | `5` | 单轮加载思维镜头上限 |
| `max_steps` | `12` | 单轮最多工具调用步数 |
| `state_card_chars` | `1600` | 状态卡长度，也是路由器看到的历史长度 |
| `system_prompt` | `prompts/system.md` | 系统提示文件 |
| `memory_dir` | `memory` | 事件日志目录 |
| `default_session` | `main` | CLI 默认会话 id |
| `resume_messages` | `8` | CLI `--resume` 回填的消息数 |
| `compact_context_chars` | `24000` | legacy 上下文压缩阈值 |
| `compact_keep_turns` / `compact_keep_tool_turns` | `2` / `3` | 压缩时保留的完整问答 / 工具轮数 |
| `compact_keep_msg_chars` | `3000` | 单条保留消息的字数上限 |
| `compact_thoughts` / `compact_thought_chars` | `3` / `1200` | 保留的思考段数与每段字数 |

## hybrid：问答方式与本地前置

| 字段 | 默认 | 含义 |
|---|---|---|
| `mode` | `hybrid` | `hybrid` 本地先判断再决定；`direct` 每条直连云端；`local` 只用本地端点 |
| `enabled` | `true` | 旧字段，等同 `mode == "hybrid"`；单独改它时 `mode` 跟着同步 |
| `router_profile` | `local` | 本地路由器端点；`mode=local` 时也是唯一的回答端点 |
| `worker_profile` | `cloud` | 复杂请求交给谁（`hybrid` / `direct` 用） |
| `fallback_worker` | `local` | 云端 key 缺失时回退到谁 |
| `context_chars` | `700` | 喂给云端的压缩上下文上限 |
| `router_max_tokens` | `2048` | 路由器 JSON 预算（512 不够，4B 推理会吃光） |
| `local_answer_max_tokens` | `2048` | `mode=local` 时的回答预算 |

`mode=local` 时不需要云端 key，也不需要 `worker_profile` 可解析；
`/health` 的 `needs_setup` 会因此返回 `false`，首次打开不会再弹设置面板。

## server：监听

| 字段 | 默认 | 含义 |
|---|---|---|
| `host` | `127.0.0.1` | 默认只听回环 |
| `port` | `9000` | 端口占用会直接报错并提示换端口 |

命令行可覆盖：`--host`、`--port`。`serve` 默认自动打开浏览器，
`--no-browser` 或 `MOTE_NO_BROWSER=1` 关闭（适合跑在服务器上）。

## 设置面板背后的接口

| 路径 | 作用 |
|---|---|
| `GET /settings` | 当前配置：key 只回 `sk-a…f9c2` 这类掩码 + `has_key`；`config_path` 只回项目内相对路径 |
| `POST /settings` | `{"profiles":{...},"hybrid":{...},"default_profile":"..."}`，只写改动字段；空 `api_key` 不覆盖已有值 |
| `POST /settings/test` | 用给定地址/模型/key 真发一次 64 token 请求，返回连通性与错误原因 |

## 密钥安全

- `config.json` 权限写成 `0600`，只在本地磁盘；
- 写盘用"临时文件 + `os.replace`"，避免半截配置；
- `GET /settings` 永不回显明文 key；
- 设置接口**只允许回环地址**访问，服务开到 `0.0.0.0` 时别人也改不了你的配置、看不到 key；
- 面板输入为空时表示"不修改"，避免误清空。

## 端口与浏览器

默认 **9000**（避开本机 Nanobot 常用端口）。端口被占用时会直接 `SystemExit` 并提示
换一个端口，而不是静默失败。启动后 `webbrowser.open` 会延时 0.4 秒打开页面，
此时服务已经就绪，不会出现"打开是空白"。
