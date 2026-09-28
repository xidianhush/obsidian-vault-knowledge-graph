"""输出：dist/graph.json 与自包含单文件 dist/knowledge-graph.html。

单文件 HTML 的必然性：Chrome 在 file:// 协议下禁止 fetch/XHR 读本地文件，
所以数据与 Cytoscape 都必须内联，否则「双击打开」这条验收标准直接不成立。
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.request

CYTO_VERSION = "3.30.2"
CYTO_URLS = [
    f"https://cdn.jsdelivr.net/npm/cytoscape@{CYTO_VERSION}/dist/cytoscape.min.js",
    f"https://unpkg.com/cytoscape@{CYTO_VERSION}/dist/cytoscape.min.js",
    "https://cdn.jsdelivr.net/npm/cytoscape@3/dist/cytoscape.min.js",
]


class EmitError(Exception):
    pass


def write_json(cfg, payload, path=None):
    path = path or os.path.join(cfg["root"], cfg["output"]["json"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return path


def ensure_vendor(cfg, quiet=False):
    path = os.path.join(cfg["root"], "vendor", "cytoscape.min.js")
    if os.path.exists(path) and os.path.getsize(path) > 50_000:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    last_error = None
    for url in CYTO_URLS:
        try:
            if not quiet:
                print(f"[vendor] 下载 {url}")
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            text = data.decode("utf-8", errors="replace")
            if "cytoscape" not in text.lower() or len(data) < 50_000:
                raise EmitError(f"下载内容不像 cytoscape.js（{len(data)} 字节）")
            with open(path, "wb") as fh:
                fh.write(data)
            return path
        except Exception as exc:            # noqa: BLE001 - 逐个镜像重试
            last_error = exc
    raise EmitError(
        "无法自动获取 cytoscape.min.js。\n"
        f"  最后一次错误：{last_error}\n"
        "  解决办法：手动下载 https://cdn.jsdelivr.net/npm/"
        f"cytoscape@{CYTO_VERSION}/dist/cytoscape.min.js\n"
        f"  保存到 {path} 后重新运行 build。"
    )


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def build_html(cfg, payload, quiet=False):
    vendor = ensure_vendor(cfg, quiet=quiet)
    template = _read(os.path.join(cfg["root"], "web", "template.html"))
    app = _read(os.path.join(cfg["root"], "web", "app.js"))
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")

    for marker, text in (("/*__CYTOSCAPE__*/", _read(vendor)),
                         ("/*__APP__*/", app),
                         ("/*__DATA__*/", data)):
        if marker not in template:
            raise EmitError(f"web/template.html 缺少占位符 {marker}")

    html = template
    html = html.replace("/*__DATA__*/", data)
    html = html.replace("/*__APP__*/", app)
    html = html.replace("/*__CYTOSCAPE__*/", _read(vendor))
    html = html.replace("__PAGE_TITLE__", cfg.get("page_title", "知识图谱"))
    html = html.replace("__GENERATED__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    out = os.path.join(cfg["root"], cfg["output"]["html"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out
