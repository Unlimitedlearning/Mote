# DeepSeek 对话迁移

把 DeepSeek 导出的会话导入 Mote：保留问题、回答、思维过程与分支。
全程在本机运行，不联网、不上传，也不需要 API Key。

## 三步完成

1. **导出**：DeepSeek 网页/App → 设置 → 数据导出，按提示下载 zip（导出链接通常会发到邮箱）。
2. **拖进来**：把这个 zip 直接拖到本文件夹（不用解压）。
3. **运行**：
   - Windows：双击 `运行.bat`
   - macOS / Linux：在本文件夹执行 `python migrate.py`

看到「完成」后启动或刷新 Mote，左侧会话列表就会出现这些对话。

```bash
# 在 Mote 项目根目录启动
python -m mote serve
```

## 脚本做了什么

- 把本文件夹里的 `*.zip` 解压到 `_解压/<压缩包名>/`（不会动原 zip）；
- 递归找到含 `chat_sessions` 的那一层目录；
- 调用 Mote 自带的 `tools/import_deepseek.py`，把结果写进 `../memory/sessions/`；
- 同一个会话重复导入时默认跳过，不会覆盖你后来在 Mote 里继续的对话。

导入时一条 DeepSeek 的 `USER` + `ASSISTANT` 回复会变成一个 Mote 问答节点，
`THINK` 内容存成该回答的「思考过程」，`current_message_id` 所在路径成为当前分支。

## 常用参数

| 参数 | 作用 |
|---|---|
| `--dry-run` | 只统计会导入多少，不写盘 |
| `--limit 5` | 只导入 5 个会话，先看看效果 |
| `--force` | 覆盖同名会话，重新导入 |
| `--sync` | 只升级旧的导入格式，保留已有新对话 |
| `--current-only` | 只导入当前分支，不带兄弟分支 |
| `--source 目录` | 已经解压好的数据目录（含 `chat_sessions`） |
| `--root 目录` | 会话库位置，默认 Mote 项目下的 `memory` |

```bash
python migrate.py --dry-run
python migrate.py --limit 5
python migrate.py --source "D:/导出的/deepseek_data"
```

## 常见问题

**提示「没有找到 zip」**
把导出的压缩包直接放在本文件夹根目录（和 `migrate.py` 同一层），不要放进子文件夹。

**提示「没找到 chat_sessions」**
确认下载的是 DeepSeek 的完整数据导出，而不是聊天记录截图或单个对话的分享文件。

**导入后没看到对话**
先确认 Mote 用的是同一个 `memory` 目录；如果启动时加了 `--session` 或改过
`agent.memory_dir`，用 `--root` 指向实际位置。网页需要刷新一次。

**想重新导入某些会话**
加 `--force`。它会覆盖 `memory/sessions/<会话id>`，该会话在 Mote 里新增的内容也会丢失。

**导入的数据存在哪 / 怎么删**
只写 `memory/sessions/` 下的事件日志。删除会话可在 Mote 网页的 `···` 菜单里操作，
也可以直接删对应目录。`_解压/` 只是中间产物，确认导入成功后可删。

**需要什么环境**
Python 3.9+，无第三方依赖。Windows 没装 Python 时，先到 python.org 安装并勾选
「Add Python to PATH」，再双击 `运行.bat`。
