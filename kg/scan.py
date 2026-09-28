"""按 config.yaml 的白名单遍历 vault，收集公开范围内的笔记。"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass

SKIP_DIRS = {".git", ".obsidian", ".trash", ".smtcmp_json_db", "node_modules", ".smart-env"}


@dataclass
class NoteFile:
    rel: str        # posix 风格，相对 vault 根，含 .md
    abs: str
    stem: str       # 文件名去掉 .md
    parts: tuple    # 目录层级，如 ("Science and Tech", "Electronic engineering")
    depth: int      # 笔记所在深度：目录深度 + 1

    @property
    def id(self) -> str:
        return self.rel[:-3] if self.rel.lower().endswith(".md") else self.rel


def _match(rel: str, patterns) -> bool:
    """relpath 或 basename 命中任一 glob 即算匹配（Windows 下不区分大小写）。"""
    low = rel.lower()
    base = rel.rsplit("/", 1)[-1]
    for pat in patterns:
        p = str(pat).replace("\\", "/")
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(low, p.lower()):
            return True
        if "/" not in p and (fnmatch.fnmatch(base, p) or fnmatch.fnmatch(base.lower(), p.lower())):
            return True
    return False


def scan(cfg: dict):
    """返回 (notes, stats)。notes 已按路径排序。"""
    vault = cfg["vault"]
    include, exclude = cfg["include"], cfg["exclude"]
    excluded_by_name = set(cfg["exclude_notes"])
    notes: list[NoteFile] = []
    skipped_dirs = 0

    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            if not name.lower().endswith(".md"):
                continue
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, vault).replace("\\", "/")
            if not _match(rel, include):
                continue
            if _match(rel, exclude):
                continue
            stem = name[:-3]
            parts = tuple(rel.split("/")[:-1])
            if stem in excluded_by_name or rel in excluded_by_name or rel[:-3] in excluded_by_name:
                continue
            notes.append(NoteFile(
                rel=rel,
                abs=abs_path,
                stem=stem,
                parts=parts,
                depth=len(parts) + 1,
            ))

    total_md = 0
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        total_md += sum(1 for f in filenames if f.lower().endswith(".md"))

    folders = sorted({p for n in notes for i in range(1, len(n.parts) + 1)
                      for p in ("/".join(n.parts[:i]),)})
    stats = {
        "vault_md_total": total_md,
        "included": len(notes),
        "excluded": total_md - len(notes),
        "folders": len(folders),
        "max_depth": max((n.depth for n in notes), default=1),
        "depth_histogram": _histogram(n.depth for n in notes),
    }
    return notes, folders, stats


def _histogram(values):
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))
