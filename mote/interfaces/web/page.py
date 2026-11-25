"""网页页面：读取 assets 下的模板与静态资源，拼成一个可直接返回的字符串。

保持单响应、无外链：CSS 与 JS 都内联进 HTML，浏览器不需要额外请求，
离线打开也不会因为 CDN 不可达而变成白页。资源改动后重启服务即可生效。
"""

from pathlib import Path

ASSETS = Path(__file__).with_name("assets")


def _asset(name):
    """资源文件统一以换行结尾，内联时去掉首尾空行由模板负责。"""
    return (ASSETS / name).read_text(encoding="utf-8").strip("\n")


def build_page():
    """按模板占位符拼装：boot（防闪白）/ style / app（主脚本）。"""
    html = (_asset("index.html")
            .replace("{{BOOT}}", _asset("boot.js"))
            .replace("{{STYLE}}", _asset("style.css"))
            .replace("{{APP}}", _asset("app.js")))
    return html + "\n"


PAGE = build_page()
