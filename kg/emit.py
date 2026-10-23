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
    # 数据是塞进 <script type="application/json"> 的，必须让 JSON 里**一个 < 都不出现**：
    #   * "</" 会提前闭合 <script> 元素；
    #   * "<!--" 会让 HTML 分词器进入 script-data-escaped 状态。
    # 早先这里用的是 JS 字面量那套写法 "\\/" / "<\\!--" —— 但这是 JSON，不是 JS：
    # JSON 只认 \" \\ \/ \b \f \n \r \t \uXXXX，"<\\!--" 里的 \! 是**非法转义**，
    # 浏览器 JSON.parse 直接抛 SyntaxError，整个页面初始化失败、画布全空（连作者
    # 姓名都不显示），而且构建侧毫无察觉 —— 笔记正文里只要出现一次 "<!--" 就必中
    # （实测：Science and Tech/Mathematics Basic 下三篇笔记的 excerpt 里就有）。
    # 统一换成 \u003c：合法 JSON、解析回来仍是 "<"，上面两个坑一起堵掉。
    data = data.replace("<", "\\u003c")
    # 构建期自证：转义之后再解析一遍，确保内联进 HTML 的仍是合法 JSON。
    # 挡的正是「转义写错 → 页面白屏、构建却报成功」这类静默失败：翻遍 dist 和日志
    # 都看不出问题，只有双击打开才发现是空的。宁可构建直接失败。
    try:
        json.loads(data)
    except json.JSONDecodeError as exc:
        raise EmitError(
            f"内联数据在转义之后不是合法 JSON（{exc}）—— 页面的 JSON.parse 会抛错、"
            "画布全空。检查 build_html 里的 < 转义。")

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
    # KaTeX（Obsidian 式预览里的公式渲染）只在 preview.enabled 时内联：关掉实验功能
    # 就不该为它背 0.6MB。三个占位符要么一起在、要么一起不在，避免半套页面。
    katex = None
    if (cfg.get("preview") or {}).get("enabled"):
        for marker in ("/*__KATEX_CSS__*/", "/*__KATEX_JS__*/", "/*__KATEX_AUTO__*/"):
            if marker not in template:
                raise EmitError(f"web/template.html 缺少占位符 {marker}")
        from .preview import katex_assets
        katex = katex_assets(root)

    html = template
    html = html.replace("/*__DATA__*/", data)
    for marker, path in parts:
        html = html.replace(marker, _read(path))
    if katex:
        html = html.replace("/*__KATEX_CSS__*/", katex["css"])
        html = html.replace("/*__KATEX_JS__*/", katex["js"])
        html = html.replace("/*__KATEX_AUTO__*/", katex["auto"])
    html = html.replace("__PAGE_TITLE__", cfg.get("page_title", "知识图谱"))
    html = html.replace("__GENERATED__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    out = os.path.join(root, cfg["output"]["html"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out
