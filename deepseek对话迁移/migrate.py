"""把 DeepSeek 导出的 zip 导入 Mote（本地运行，不联网、不上传）。

用法：
    双击 运行.bat            # Windows
    python migrate.py           # 任意系统
    python migrate.py --dry-run # 只看会导入多少，不写盘
    python migrate.py --force   # 覆盖同名会话重新导入

脚本做三件事：解压本文件夹里的 zip、找到 chat_sessions、调用 Mote 自带的
tools/import_deepseek.py 写成事件日志。重复的会话默认跳过，不会覆盖已有对话。
"""

import argparse
import importlib.util
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(BASE)
IMPORTER = os.path.join(PROJECT, "tools", "import_deepseek.py")
WORK = os.path.join(BASE, "_解压")
MEMORY = os.path.join(PROJECT, "memory")


def say(text=""):
    print(text, flush=True)


def show_path(path):
    """尽量显示相对路径；目标在别的盘符时保持原样。"""
    try:
        return os.path.relpath(path, PROJECT)
    except ValueError:
        return path


def find_export(root):
    """在解压结果里找包含 chat_sessions 的那一层目录。"""
    found = []
    for folder, dirs, _files in os.walk(root):
        if "chat_sessions" in dirs:
            found.append(folder)
            dirs[:] = []  # 不再往会话目录里找
    return found


def safe_extract(zip_path, dest):
    """只解到 dest 内：导出包里的路径不能带 .. 或绝对路径。"""
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for item in zf.infolist():
            name = item.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise SystemExit(f"压缩包里有可疑路径，已停止：{item.filename}")
            target = os.path.abspath(os.path.join(dest, *[p for p in name.split("/") if p]))
            if not target.startswith(os.path.abspath(dest)):
                raise SystemExit(f"压缩包里有可疑路径，已停止：{item.filename}")
        zf.extractall(dest)


def load_importer():
    if not os.path.isfile(IMPORTER):
        raise SystemExit(f"找不到导入程序：{IMPORTER}\n"
                         "请把本文件夹放在 Mote 项目根目录下，不要单独拷走。")
    spec = importlib.util.spec_from_file_location("mote_import_deepseek", IMPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def zip_files():
    names = []
    for name in sorted(os.listdir(BASE)):
        if name.lower().endswith(".zip"):
            names.append(os.path.join(BASE, name))
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把 DeepSeek 导出的 zip 导入 Mote 的本地会话库")
    parser.add_argument("--source", help="已经解压好的目录（含 chat_sessions）；默认自动解压 zip")
    parser.add_argument("--root", default=MEMORY, help="Mote 会话库位置，默认项目下的 memory")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同名会话")
    parser.add_argument("--sync", action="store_true", help="只升级旧导入格式，保留已有新对话")
    parser.add_argument("--limit", type=int, default=0, help="最多导入几个会话，0 表示全部")
    parser.add_argument("--current-only", action="store_true", help="只导入当前分支")
    args = parser.parse_args(argv)

    say("=" * 62)
    say("Mote · DeepSeek 对话迁移")
    say("=" * 62)
    say(f"会话将写入：{show_path(args.root)}")
    say()

    sources = []
    if args.source:
        src = os.path.abspath(args.source)
        if not os.path.isdir(os.path.join(src, "chat_sessions")):
            raise SystemExit(f"{src} 里没有 chat_sessions，确认选的是导出数据目录")
        sources.append(src)
    else:
        archives = zip_files()
        if archives:
            for path in archives:
                name = os.path.splitext(os.path.basename(path))[0]
                say(f"解压：{os.path.basename(path)}")
                dest = os.path.join(WORK, name)
                safe_extract(path, dest)
                hits = find_export(dest)
                if not hits:
                    raise SystemExit(f"{os.path.basename(path)} 里没找到 chat_sessions，"
                                     "确认这是 DeepSeek 的导出包")
                sources.extend(hits)
                say(f"  找到 {len(hits)} 份导出数据")
        else:
            hits = find_export(WORK)
            if not hits:
                say("没有找到 zip。")
                say("请把 DeepSeek 导出的 zip 直接拖进这个文件夹，再运行一次。")
                say(f"（也可以把已解压的目录用 --source 指过来）")
                return 2
            say(f"没有新 zip，沿用上次解压的数据：{len(hits)} 份")
            sources.extend(hits)

    importer = load_importer()
    code = 0
    for src in sources:
        say()
        say(f"导入来源：{src}")
        say("-" * 62)
        argv_in = ["--source", src, "--root", args.root]
        if args.dry_run:
            argv_in.append("--dry-run")
        if args.force:
            argv_in.append("--force")
        if args.sync:
            argv_in.append("--sync")
        if args.limit:
            argv_in.extend(["--limit", str(args.limit)])
        if args.current_only:
            argv_in.append("--current-only")
        code = importer.main(argv_in) or code
        if code:
            break

    say()
    if code == 0 and not args.dry_run:
        say("完成。启动或刷新 Mote 页面即可在左侧看到这些对话。")
        say("  启动：在 Mote 目录执行  python -m mote serve")
    return code


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        say("\n已取消。")
        code = 130
    except SystemExit as err:
        say(str(err))
        code = 1
    if not sys.argv[1:] and sys.stdin.isatty():
        try:
            input("\n按回车退出…")
        except EOFError:
            pass
    raise SystemExit(code)
