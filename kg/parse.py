"""单篇笔记的解析：frontmatter、标题树、wiki 链接、摘要。"""

from __future__ import annotations

import os
import re

import yaml

FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
CODE_SPAN_RE = re.compile(r"`[^`]*`")


class Heading:
    __slots__ = ("level", "title", "line", "path", "id", "parent")

    def __init__(self, level, title, line, path, hid, parent=None):
        self.level = level
        self.title = title
        self.line = line
        self.path = path
        self.id = hid
        self.parent = parent


class WikiLink:
    __slots__ = ("target", "anchor", "alias", "embed", "raw", "line")

    def __init__(self, target, anchor, alias, embed, raw, line):
        self.target = target
        self.anchor = anchor
        self.alias = alias
        self.embed = embed
        self.raw = raw
        self.line = line


def read_text(path: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, "r", encoding=encoding) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def split_frontmatter(text: str):
    """返回 (frontmatter dict, 正文, frontmatter 行数)。"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text, 0
    for i in range(1, min(len(lines), 400)):
        if lines[i].strip() in ("---", "..."):
            raw = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            try:
                fm = yaml.safe_load(raw) or {}
            except Exception:
                fm = {}
            return (fm if isinstance(fm, dict) else {}), body, i + 1
    return {}, text, 0


def parse_headings(body: str, note_id: str, line_offset: int = 0):
    """解析标题树，跳过代码块内的 # 行。返回 Heading 列表（文档顺序）。"""
    headings: list[Heading] = []
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    fence = None
    for lineno, line in enumerate(body.split("\n"), start=1 + line_offset):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        if not title:
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = stack[-1][2] if stack else note_id
        path = [t for _, t, _ in stack] + [title]
        base = note_id + "#" + "/".join(path)
        n = seen.get(base, 0)
        seen[base] = n + 1
        hid = base if n == 0 else f"{base}~{n + 1}"
        stack.append((level, title, hid))
        headings.append(Heading(level, title, lineno, path, hid, parent_id))
    return headings


def parse_wikilinks(body: str, line_offset: int = 0):
    """逐行扫描 wiki 链接，跳过代码块内的内容。返回 WikiLink 列表（文档顺序）。

    逐行而非整篇 finditer：一是能拿到行号（heading→heading 边需要源端归属），
    二是代码块里的 [[Foo]] 不是真链接（此前整篇扫描会误认）。
    """
    links: list[WikiLink] = []
    fence = None
    for lineno, line in enumerate(body.split("\n"), start=1 + line_offset):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        for m in WIKILINK_RE.finditer(line):
            inner = m.group(2)
            embed = m.group(1) == "!"
            alias = None
            if "|" in inner:
                inner, alias = inner.split("|", 1)
                alias = alias.strip() or None
            anchor = None
            if "#" in inner:
                inner, anchor = inner.split("#", 1)
                anchor = anchor.strip() or None
            target = inner.strip().replace("\\", "/")
            if not target:
                continue
            links.append(WikiLink(target, anchor, alias, embed, m.group(0), lineno))
    return links


def excerpt(body: str, limit: int = 220) -> str:
    text = re.sub(r"^\s{0,3}(#{1,6})\s+.*$", "", body, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+\[[ xX]\]\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*\|.*\|\s*$", "", text, flags=re.M)
    text = CODE_SPAN_RE.sub("", text)
    text = INLINE_LINK_RE.sub("", text)
    text = WIKILINK_RE.sub(lambda m: m.group(2).split("|")[0].split("#")[0], text)
    text = re.sub(r"[*_>`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def is_attachment(target: str, attachments: set) -> bool:
    ext = os.path.splitext(target)[1].lower()
    return bool(ext) and ext in attachments


class Note:
    __slots__ = ("file", "frontmatter", "body", "headings", "links", "excerpt", "text")

    def __init__(self, file, frontmatter, body, headings, links, excerpt_text, text):
        self.file = file
        self.frontmatter = frontmatter
        self.body = body
        self.headings = headings
        self.links = links
        self.excerpt = excerpt_text
        self.text = text


def parse_note(file, attachments: set) -> Note:
    text = read_text(file.abs)
    fm, body, offset = split_frontmatter(text)
    return Note(
        file=file,
        frontmatter=fm,
        body=body,
        headings=parse_headings(body, file.id, offset),
        links=parse_wikilinks(body, offset),
        excerpt_text=excerpt(body),
        text=text,
    )
