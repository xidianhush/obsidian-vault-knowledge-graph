"""笔记预览 HTML（Ctrl+悬停浮层用）—— 构建期把 markdown 渲染成 HTML 片段。

为什么把渲染放在构建期：
  * markdown → HTML 用 `markdown`（构建机上的依赖），运行时只负责把片段塞进浮层，
    前端不因此多一个解析器；
  * **公式不在这里渲染**：4840 个公式内联成 SVG 会让产物涨 20–50MB。运行时用
    已 vendored 的 KaTeX（构建期内联进单文件），浮层打开时只渲染当前这一篇的几十个公式；
  * **图片不内联**：vault 里被引用的图共 519MB。这里只生成相对路径引用
    （`file://` 页面实测可以加载 vault 图片）。
"""

from __future__ import annotations

import base64
import os
import re

import markdown

IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")
MEDIA_EXT = IMG_EXT + (".pdf", ".mp4", ".mov", ".mp3", ".wav", ".zip", ".excalidraw", ".html")
WIKI_EMBED_RE = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")
MATH_BLOCK_RE = re.compile(r"\$\$.+?\$\$|\\\[.+?\\\]", re.S)
MATH_INLINE_RE = re.compile(r"(?<!\\)\$(?!\$)[^$\n]{1,300}\$")
HIGHLIGHT_RE = re.compile(r"==([^=\n]+?)==")
COMMENT_RE = re.compile(r"%%.+?%%", re.S)
# 坏掉的嵌入：`![[x.pdf]`（少一个右括号）、`![[图3-10 …]]`（写的是说明文字不是文件名）。
# 这两种既不是链接也不是图片，留着只会变成正文里的噪声。
BAD_EMBED_RE = re.compile(r"!\[\[[^\[\]]*\.[A-Za-z0-9]{2,5}\s*\](?!\])")
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)

# 浮层里的附件占位：非图片附件在预览里只报个名字（点它没意义）
ATTACH_TPL = '<span class="pv-attach">{name}</span>'
IMG_TPL = '<img class="pv-img" src="{src}"{size}{style}>'
MISSING_TPL = '<span class="pv-missing">[缺失附件 {name}]</span>'
WL_TPL = '<span class="pv-wl"{target}>{label}</span>'
WL_PLAIN_TPL = '<span class="pv-wl pv-unresolved">{label}</span>'

_MD = None


def _md() -> "markdown.Markdown":
    global _MD
    if _MD is None:
        _MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
    return _MD


def build_attachment_index(vault: str) -> dict:
    """文件名（小写）→ 绝对路径。Obsidian 的 `![[x.png]]` 只写文件名，需要全库索引。"""
    index = {}
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in (".git", ".obsidian", ".trash")]
        for name in files:
            index.setdefault(name.lower(), os.path.join(root, name))
    return index


def _rel(src_path: str, base_dir: str) -> str:
    return os.path.relpath(src_path, base_dir).replace("\\", "/")


def _usable(path: str | None) -> bool:
    """文件存在且非空：vault 里真的有 0 字节的图片，内联成 <img> 只会破图。"""
    return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0


def _escape_math(raw: str) -> str:
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+")


def _outside_fences(text: str, fn) -> str:
    """逐行处理，但**跳过代码围栏里的内容**（围栏里的 `![[x.png]]`、`==高亮==` 是代码，
    不该被替换：替换出的 HTML 在代码块里会被 markdown 转义成字面量，屏幕上就会看到
    `<span class="pv-attach">…` 这种字样）。"""
    out = []
    fence = None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            fence = marker if fence is None else (None if fence == marker else fence)
            out.append(line)
            continue
        out.append(line if fence is not None else fn(line))
    return "\n".join(out)




def _fence_flags(lines):
    """每一行是否在代码围栏内部（含围栏行本身）。"""
    flags = []
    fence = None
    for line in lines:
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            fence = marker if fence is None else (None if fence == marker else fence)
            flags.append(True)
            continue
        flags.append(fence is not None)
    return flags


def render(note, cfg: dict, index: dict, base_dir: str, resolve) -> tuple[str, list, list]:
    """把一篇笔记渲染成预览片段，返回 (html, links, anchors)。

    links：出站链接表 `[{"t": 目标节点 id, "l": 显示文字}, ...]`（去重、只留能解析到
    图上节点的），也给浮层里的链接 span 用。
    anchors：预览 HTML 里各标题的锚点 id（`pv-h0`…，文档序），给「从这一节滚起」用。
    """
    by_id = getattr(resolve, "by_id", {})
    links = []
    seen = set()

    def sub(m):
        bang, inner = m.group(1), m.group(2)
        body = inner.split("|")[0].strip()
        width = ""
        if "|" in inner:
            tail = inner.split("|", 1)[1].strip()
            if tail.isdigit():
                width = ' style="width:%spx"' % tail
        low = body.lower()
        if low.endswith(MEDIA_EXT) or bang and "." in body:
            if low.endswith(IMG_EXT):
                path = index.get(os.path.basename(low))
                if not _usable(path):
                    return MISSING_TPL.format(name=os.path.basename(body))
                return IMG_TPL.format(src=_rel(path, base_dir).replace('"', "%22"),
                                      size=_img_size_attrs(path), style=width)
            return ATTACH_TPL.format(name=os.path.basename(body))
        # [[笔记#标题|别名]]
        target, _, anchor = body.partition("#")
        alias = inner.split("|", 1)[1].strip() if "|" in inner else ""
        label = alias or anchor or target
        tid = resolve(target)
        if tid is None:
            return WL_PLAIN_TPL.format(label=label)
        node_id = tid
        if anchor:
            hid = _heading_id(by_id, tid, anchor)
            if hid:
                node_id = hid
        key = (node_id, label)
        if key not in seen:
            seen.add(key)
            links.append({"t": node_id, "l": label})
        return WL_TPL.format(target=' data-wl="%s"' % node_id.replace('"', "&quot;"), label=label)

    body = note.body
    body = COMMENT_RE.sub("", body)
    # 顺序很重要：先把**完整**的 ![[...]] 替换掉，再用「少一个右括号」的容错规则收尾。
    # 反过来的话容错规则会把正常图片吃掉一个 ]，651 个图片链接里有 631 个因此退化成
    # 附件文字（2026-10-23 用户截图里的元凶之一）。
    body = _outside_fences(body, lambda line: WIKI_EMBED_RE.sub(sub, line))
    body = _outside_fences(body, lambda line: BAD_EMBED_RE.sub(
        lambda m: ATTACH_TPL.format(
            name=os.path.basename(m.group(0)[3:].strip().rstrip("]").strip())), line))
    body = _outside_fences(body, lambda line: HIGHLIGHT_RE.sub(r"<mark>\1</mark>", line))
    # ── 锚点：按**源文件行号**注入，不依赖 markdown 里 <hN> 的输出顺序 ──────────
    # 为什么不能用「按 HTML 里 <hN> 出现顺序编号」：我们的标题解析与 python-markdown
    # 对「HTML 块里的 # 行」口径不同，会整体错位一格 —— 悬停 A 标题却看到 B 标题的
    # 正文（2026-10-24 用户实测截图）。按行号注入后顺序不参与，永远不会错位。
    offset = note.text.count("\n") - note.body.count("\n")
    line_anchor = {}
    for i, h in enumerate(note.headings):
        idx = h.line - 1 - offset
        if idx >= 0:
            line_anchor[idx] = "pv-h%d" % i
    ok_anchor = set()
    if line_anchor:
        lines = body.split("\n")
        flags = _fence_flags(lines)
        for idx, anchor_id in line_anchor.items():
            if idx >= len(lines) or flags[idx] or not HEADING_LINE_RE.match(lines[idx]):
                continue
            lines[idx] = HEADING_LINE_RE.sub(
                lambda m: m.group(1) + ' <span class="pv-anchor" id="%s"></span>' % anchor_id,
                lines[idx], count=1)
            ok_anchor.add(anchor_id)
        body = "\n".join(lines)
    anchors = ["pv-h%d" % i if ("pv-h%d" % i) in ok_anchor else None
               for i in range(len(note.headings))]
    # 公式先「保护」起来：nl2br 会把 $$…$$ 里的换行变 <br>，定界符被拆进不同元素，
    # 运行时的 auto-render 就匹配不到（spike 实测踩到过）。
    store = []

    def keep(m):
        store.append(m.group(0))
        return "@@MATH%d@@" % (len(store) - 1)

    body = MATH_BLOCK_RE.sub(keep, body)
    body = MATH_INLINE_RE.sub(keep, body)
    html = _md().reset().convert(body)
    for i, raw in enumerate(store):
        html = html.replace("@@MATH%d@@" % i, _escape_math(raw))

    # markdown 原生图片 `![alt](url)`：vault 里有作者把「说明文字」写进 url、文件其实
    # 不存在的（半导体物理 有 3 处）。存在的按文件名解析成真实路径，不存在的换成
    # 文字占位 —— 否则浮层里是一堆破图标。
    def fix_img(m):
        tag = m.group(0)
        src_m = re.search(r'src="([^"]*)"', tag)
        if not src_m:
            return tag
        src = src_m.group(1)
        if src.startswith("data:"):
            return tag
        if "://" in src:
            # 外链图片：**不加载**（离线/内网会一直转圈并报 console error），
            # 退化成可点的链接文字。
            return ('<span class="pv-attach">外链图片：<a href="%s" target="_blank" '
                    'rel="noopener">%s</a></span>' % (src, src[:60]))
        path = index.get(os.path.basename(src).lower())
        if _usable(path):
            real = _rel(path, base_dir).replace('"', "%22")
            # vault 里的 <img> 常自带 width/height：先删掉再加我们读到的尺寸，
            # 否则同一标签上出现两组 width/height（非法 HTML）。
            tag = re.sub(r'\s+width="[^"]*"', '', tag)
            tag = re.sub(r'\s+height="[^"]*"', '', tag)
            return tag.replace(src, real).replace(
                "<img", "<img" + _img_size_attrs(path), 1)
        alt_m = re.search(r'alt="([^"]*)"', tag)
        name = (alt_m.group(1) if alt_m else os.path.basename(src))[:60]
        return MISSING_TPL.format(name=name)

    html = IMG_TAG_RE.sub(fix_img, html)
    return html, links, anchors


def _heading_id(by_id: dict, note_id: str, anchor: str) -> str | None:
    """把 `#标题` 锚点解析到具体标题节点 id（宽松匹配：去除首尾空白与 `#`）。"""
    want = anchor.strip().lstrip("#").strip()
    if not want:
        return None
    for node_id, node in by_id.items():
        if node.get("kind") != "heading" or node.get("note") != note_id:
            continue
        if (node.get("title") or "").strip() == want:
            return node_id
    # 退一步：大小写不敏感 + 去掉行内 markdown 记号的比较
    low = want.lower().replace("*", "").replace("$", "")
    for node_id, node in by_id.items():
        if node.get("kind") != "heading" or node.get("note") != note_id:
            continue
        t = (node.get("title") or "").lower().replace("*", "").replace("$", "")
        if t == low:
            return node_id
    return None


_IMG_SIZE = {}


def _img_size_attrs(path: str) -> str:
    """读图片真实像素尺寸写进 width/height：预览里图片是异步加载的，不预留高度的话
    上方一加载完布局就整体位移，浮层会从「这一节」滑走（实测公共版锚点漂了 3000+px）。"""
    try:
        from PIL import Image
        key = (path, os.path.getmtime(path))
        size = _IMG_SIZE.get(key)
        if size is None:
            with Image.open(path) as im:
                size = im.size
            _IMG_SIZE[key] = size
        return ' width="%d" height="%d"' % size
    except Exception:
        return ""


_KATEX_CACHE = None


def katex_assets(root: str) -> dict:
    """KaTeX 的最小资产，css 里的 woff2 字体换成 base64（单文件、双击可用）。

    只内联 woff2：woff/ttf 是给老浏览器的兜底，本机 Chrome 用不到，省 0.3MB。
    """
    global _KATEX_CACHE
    if _KATEX_CACHE is not None:
        return _KATEX_CACHE
    base = os.path.join(root, "web", "vendor", "katex")
    with open(os.path.join(base, "katex.min.css"), encoding="utf-8") as fh:
        css = fh.read()
    # 先把 woff / ttf 这两档兜底去掉：本机 Chrome 只用 woff2，留着会让同一份字体
    # 的 base64 在 css 里出现 3 次（实测 1.06MB vs 0.6MB）。去掉后再把 woff2 换成
    # data URI，每个字体只内联一次。
    css = re.sub(r"\s*url\((?:fonts/)?[^)]+?\.(?:woff|ttf)\)\s*format\(\"[^\"]*\"\),?", "", css)
    css = re.sub(r",\s*([;}])", r"\1", css)
    fonts = {}

    def repl(m):
        name = m.group(1)
        stem = os.path.splitext(name)[0]
        woff2 = os.path.join(base, "fonts", stem + ".woff2")
        if not os.path.isfile(woff2):
            return "url(about:blank)"
        if woff2 not in fonts:
            with open(woff2, "rb") as fh:
                fonts[woff2] = base64.b64encode(fh.read()).decode("ascii")
        return "url(data:font/woff2;base64,%s)" % fonts[woff2]

    css = re.sub(r"url\((?:fonts/)?([^)]+?\.(?:woff2|woff|ttf))\)", repl, css)
    with open(os.path.join(base, "katex.min.js"), encoding="utf-8") as fh:
        js = fh.read()
    with open(os.path.join(base, "contrib", "auto-render.min.js"), encoding="utf-8") as fh:
        auto = fh.read()
    _KATEX_CACHE = {"css": css, "js": js, "auto": auto}
    return _KATEX_CACHE
