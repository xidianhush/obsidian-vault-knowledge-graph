"""输出：dist/graph.json 与自包含单文件 dist/knowledge-graph.html。

单文件 HTML 的必然性：Chrome 在 file:// 协议下禁止 fetch/XHR 读本地文件，
所以数据与渲染代码都必须内联，否则「双击打开」这条验收标准直接不成立。

渲染层是自己的 Canvas2D 实现（web/render.js），不依赖任何第三方库，也就不需要
下载 vendor —— 早先用 Cytoscape 时这里要拉 373KB 的 vendor，既拖慢构建又把产物
撑到 9MB，而它的复合节点、样式重算、按需增删元素全都不是这套「构建期定坐标 +
连续淡入淡出」模型需要的东西。
"""

from __future__ import annotations

import datetime
import json
import os


class EmitError(Exception):
    pass


def write_json(cfg, payload, path=None):
    path = path or os.path.join(cfg["root"], cfg["output"]["json"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return path


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def build_html(cfg, payload, quiet=False):
    root = cfg["root"]
    template = _read(os.path.join(root, "web", "template.html"))
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # 数据是塞进 <script type="application/json"> 的，必须转义掉能提前闭合标签的序列
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")

    parts = (
        ("/*__RENDER__*/", os.path.join(root, "web", "render.js")),
        ("/*__APP__*/", os.path.join(root, "web", "app.js")),
    )
    for marker, path in parts:
        if marker not in template:
            raise EmitError(f"web/template.html 缺少占位符 {marker}")
        if not os.path.exists(path):
            raise EmitError(f"缺少前端源文件 {path}")
    if "/*__DATA__*/" not in template:
        raise EmitError("web/template.html 缺少占位符 /*__DATA__*/")

    html = template
    html = html.replace("/*__DATA__*/", data)
    for marker, path in parts:
        html = html.replace(marker, _read(path))
    html = html.replace("__PAGE_TITLE__", cfg.get("page_title", "知识图谱"))
    html = html.replace("__GENERATED__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    out = os.path.join(root, cfg["output"]["html"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out
