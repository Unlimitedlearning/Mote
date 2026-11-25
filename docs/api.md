# 接口与命令行

服务默认监听 `127.0.0.1:9000`，全部接口返回 JSON（`GET /` 返回网页）。
没有鉴权，默认只听回环；要暴露到局域网请自己加反向代理与认证。

## 会话与对话

| 路径 | 作用 |
|---|---|
| `GET /` | 网页：左侧会话列表 + 右侧聊天框 |
| `POST /sessions` | 新建空会话 |
| `POST /sessions/<id>/title` | 重命名会话 |
| `DELETE /sessions/<id>` | 删除会话（不可恢复） |
| `GET /sessions` | 会话列表：标题、轮数、最后提问时间、预览 |
| `GET /sessions/<id>/messages` | 当前分支历史，含每条回答的 `model` / `route` / `node` / `thinking_chars`；`?node=` 按指定链路出视图 |
| `GET /sessions/<id>/tree` | 问答分支树（含 `main` / `main_path`）；`?node=` 指定当前位置 |
| `GET /sessions/<id>/thinking/<node>` | 按需取某轮回答的思考原文（列表不带正文） |
| `POST /sessions/<id>/cursor` | `{"node":"..."}` 切换分支，返回该分支完整历史 |
| `POST /sessions/<id>/main` | `{"node":"...","tip":"..."}` 设为主分支（`node` 为空即取消），返回更新后的树 |
| `POST /sessions/<id>/stop` | 中断正在生成的回答，已生成部分保留 |
| `DELETE /sessions/<id>/nodes/<node>?tip=...` | 软删除当前视图路径上的该问答及后续，兄弟分支保留 |

## 提问

| 路径 | 作用 |
|---|---|
| `POST /inbox` | `{"message":"...","session":"...","parent":"..."?,"fork":"..."?,"mode":"hybrid\|direct\|local"?}` |
| `POST /inbox/stream` | 同上，走 SSE |

- `parent`：把新问题接在该节点之后，成为它的子节点。
- `fork`：新问题与该节点**同级**（编辑后另开分支），原分支保持不变。
- `mode`：`hybrid` 先由本地 qwen 处理，再决定是否调云端；`direct` 跳过本地处理直连 worker；
  `local` 只用本地端点回答，不发任何云端请求。缺省沿用配置里的 `hybrid.mode`
  （网页设置面板改的就是这个全局值）。

SSE 事件：

| 事件 | 载荷 |
|---|---|
| `thinking` | 推理原文的分片 |
| `delta` | 正文分片 |
| `tool_start` | 工具名与参数 |
| `done` | 最终回答、`model`、`route`、`stopped` 标记、省下的字数 |
| `error` | 错误原因 |

生成失败或中断且没有任何正文时，本轮问答节点会被删除，历史里不留空问答；
有正文的中断保留已生成内容并标记 `stopped`。

## 检索与导出

| 路径 | 作用 |
|---|---|
| `GET /search?q=...&limit=50` | 跨会话全文检索，返回命中的问题/回答与高亮片段 |
| `GET /sessions/<id>/export?format=md\|json` | 导出当前分支（md，`thinking=0` 去思考）或完整结构（json，含所有分支） |
| `GET /export` | 导出全部会话为一个 JSON 备份 |

检索逐会话扫事件、跳过已删除节点；空格分隔的多个词需在同一消息内全部命中，
片段用控制字符标出命中位置供前端高亮。不建索引，160+ 个会话约 0.25 秒。

## 状态与元信息

| 路径 | 作用 |
|---|---|
| `GET /health` | 当前模式、启用工具、镜头数、会话数、profile 模型、`needs_setup` |
| `GET /lenses` / `/lens-names` | 镜头目录 / id → 中文名 |
| `GET /settings` · `POST /settings` · `POST /settings/test` | 见 [配置](configuration.md) |

`needs_setup` 为真时网页首次打开会自动弹出设置面板（新用户没填 key 的情况）。

## 命令行

```bash
python -m mote serve                    # 启动网页服务（自动开浏览器）
python -m mote chat                     # 终端对话（默认命令）
python -m mote ask "问题"               # 单次提问
python -m mote sessions                 # 列出会话
python -m mote state                    # 打印当前状态卡
python -m mote lenses                   # 镜头目录
python -m mote lenses --id inversion    # 某个镜头的提问清单
python -m mote lenses --all             # 全部 46 个的完整清单
python -m mote tools                    # 已注册工具
```

全局参数 `--no-hybrid`（走直连）与 `--local`（只用本地）可放在任意子命令前，
只覆盖本次运行，不会写回配置文件。

REPL 斜杠命令：

| 命令 | 作用 |
|---|---|
| `/lenses [all]` | 镜头目录 / 清单 |
| `/state` | 当前状态卡 |
| `/log` | 事件日志摘要 |
| `/compact` | 立即压缩上下文 |
| `/new` | 新会话 |
| `/sessions` · `/resume <id>` | 列出 / 恢复会话 |
| `/model` | 当前模型归属 |
| `/tools` | 工具列表 |

## 示例

```bash
# 新建会话，返回 {"session":"s-..."}
curl -s -X POST localhost:9000/sessions
# 提问
curl -s localhost:9000/inbox -H 'content-type: application/json' \
     -d '{"message":"现在几点","session":"s-20261124-abcd"}'
```
