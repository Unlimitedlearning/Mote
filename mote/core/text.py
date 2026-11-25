"""纯文本处理：预览裁剪、Markdown 引用、导出文件名。

这一层不碰磁盘也不认识会话，只做字符串变换，便于单独测试。
"""

import re


def clip(text, limit):
    """先截断再压空白：预览只取开头，不必为几百字的长回答跑整段正则。"""
    text = str(text or "")
    if limit and len(text) > limit:
        text = text[:limit] + "…"
    return re.sub(r"\s+", " ", text).strip()


def quote(text):
    """把多行问题写成 Markdown 引用块，空行也保留引用前缀。"""
    lines = str(text or "").splitlines() or [""]
    return "\n".join("> " + line if line.strip() else ">" for line in lines)


def filename(title, ext="md"):
    """把会话标题压成安全的文件名，保留可读的中文，去掉路径与非法字符。"""
    stem = re.sub(r"[\\/:*?\"<>|\s]+", "-", str(title or "")).strip("-._") or "mote"
    return f"{stem[:40]}.{ext}"
