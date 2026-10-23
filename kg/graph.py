"""把解析结果装配成带层级的有向图：文件夹 / 笔记 / 标题节点、语义边、层级聚合边。"""

from __future__ import annotations

import os
import re
from collections import defaultdict

from . import parse

TYPE_PREREQ = "prerequisite"
TYPE_DERIVES = "derives"
TYPE_CONTRAST = "contrast"
TYPE_CONTAINS = "contains"


class GraphBuilder:
    def __init__(self, cfg: dict, notes, folders):
        self.cfg = cfg
        self.notes = notes                  # list[parse.Note]
        self.folders = folders              # sorted list[str]
        self.by_id = {n.file.id: n for n in self.notes}
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._edge_key: dict[tuple, dict] = {}
        self.unresolved: dict[str, int] = defaultdict(int)
        self.heading_links: list[dict] = []   # 笔记 → 目标笔记内部某个标题
        self.stats = defaultdict(int)
        self._build_index()

    # ── 索引与链接解析 ───────────────────────────────────────────────────
    def _build_index(self):
        self.by_stem = defaultdict(list)
        # 展示路径 ≠ 真实路径的笔记（scope 的 remap 改过前缀）：登记别名，
        # 让按真实路径写的 [[Logs/Study log/xxx]] 仍然解析得到。
        self.alias: dict[str, str] = {}
        for n in self.notes:
            self.by_stem[n.file.stem.lower()].append(n.file.id)
            src = n.file.source_id
            if src != n.file.id:
                self.alias[src.lower()] = n.file.id
        for ids in self.by_stem.values():
            ids.sort()

    def resolve(self, target: str) -> str | None:
        """按 Obsidian 的短路径规则把一个链接目标解析成笔记 id。"""
        if not target:
            return None
        t = target.strip().replace("\\", "/")
        if t.lower().endswith(".md"):
            t = t[:-3]
        if t in self.by_id:
            return t
        if t.lower() in self.alias:
            return self.alias[t.lower()]
        if "/" in t:
            hits = [i for i in self.by_id if i == t or i.endswith("/" + t)]
            if hits:
                return sorted(hits, key=len)[0]
            low = t.lower()
            aliased = [v for k, v in self.alias.items() if k == low or k.endswith("/" + low)]
            return sorted(aliased, key=len)[0] if aliased else None
        hits = self.by_stem.get(t.lower())
        if not hits:
            return None
        if len(hits) == 1:
            return hits[0]
        folded = "/".join(t.lower().split("/"))
        same_dir = [i for i in hits if i.rsplit("/", 1)[0].lower() == folded]
        return same_dir[0] if same_dir else hits[0]

    # ── 节点 ────────────────────────────────────────────────────────────
    def add_node(self, node_id: str, **kw):
        if node_id in self.nodes:
            return self.nodes[node_id]
        node = {"id": node_id, "label": node_id.rsplit("/", 1)[-1]}
        node.update(kw)
        self.nodes[node_id] = node
        return node

    def build_nodes(self, annotations: dict):
        ann_notes = annotations.get("notes", {}) or {}
        for folder in self.folders:
            parts = folder.split("/")
            self.add_node(
                folder,
                kind="folder",
                depth=len(parts),
                parent="/".join(parts[:-1]) or None,
                domain=parts[0],
                weight=0.0,
                mastery=0,
                note_count=0,
                heading_count=0,
            )
        for note in self.notes:
            fid = note.file.id
            ann = _lookup(ann_notes, note.file.stem, fid) or {}
            fm = note.frontmatter
            weight, mastery, source = _resolve_metrics(self.cfg, ann, fm, self.stats)
            node = self.add_node(
                fid,
                kind="note",
                depth=note.file.depth,
                parent="/".join(note.file.parts) or None,
                domain=note.file.parts[0] if note.file.parts else "",
                weight=weight,
                mastery=mastery,
                metric_source=source,
                heading_count=len(note.headings),
                excerpt=note.excerpt,
                path=note.file.rel,
                aliases=list(ann.get("aliases", []) or []),
                subject=fm.get("subject") or _subject_of(note.file.parts),
                parent_course=fm.get("parent") or (note.file.parts[-1] if note.file.parts else ""),
            )
            if node.get("domain_override"):
                node["domain"] = node["domain_override"]
            for alias in node["aliases"]:
                if isinstance(alias, str) and alias:
                    self.by_stem.setdefault(alias.strip().lower(), []).append(fid)

        for note in self.notes:
            ann = _lookup(ann_notes, note.file.stem, note.file.id) or {}
            override = ann.get("domain")
            if override:
                self.nodes[note.file.id]["domain"] = override

        self._rollup()

    def _rollup(self):
        """把笔记的 weight / mastery / 统计向上汇总到所属文件夹。"""
        for node_id, node in sorted(self.nodes.items(), key=lambda kv: -kv[1]["depth"]):
            if node["kind"] != "note":
                continue
            parent = node["parent"]
            while parent:
                p = self.nodes.get(parent)
                if p is None:
                    break
                p["weight"] += node["weight"]
                p["note_count"] += 1
                p["heading_count"] += node["heading_count"]
                if node["mastery"]:
                    p["_m_sum"] = p.get("_m_sum", 0) + node["mastery"]
                    p["_m_cnt"] = p.get("_m_cnt", 0) + 1
                parent = p["parent"]
        for node in self.nodes.values():
            if node["kind"] == "folder":
                cnt = node.pop("_m_cnt", 0)
                node["mastery"] = round(node.pop("_m_sum", 0) / cnt) if cnt else 0

    def build_heading_nodes(self):
        """把每篇笔记的标题树提升为一等节点。

        depth = 所属笔记 depth + 标题级别，于是「文件夹 → 笔记 → 章 → 节 → 小节」
        落在同一条深度轴上，缩放时可以逐层淡入而不必区分它们是文件还是标题。
        """
        count = 0
        for note in self.notes:
            nnode = self.nodes.get(note.file.id)
            if nnode is None:
                continue
            for h in note.headings:
                self.add_node(
                    h.id,
                    kind="heading",
                    label=h.title,
                    depth=nnode["depth"] + h.level,
                    parent=h.parent or note.file.id,
                    domain=nnode["domain"],
                    weight=0.0,
                    mastery=0,
                    level=h.level,
                    title=h.title,
                    line=h.line,
                    note=note.file.id,
                    path=nnode.get("path", ""),
                )
                count += 1
        self.stats["heading_nodes"] = count

    def attach_previews(self, cfg: dict, base_dir: str):
        """给每个笔记节点挂两样东西（2026-10-22 第三轮：Obsidian 式悬浮预览）：

        * `preview`：构建期渲染好的 HTML 片段（markdown → HTML，公式保留 `$…$` 定界符
          交给运行时 KaTeX，图片按相对路径引用 vault）；
        * `links`：出站 `[[链接]]` 表（`[{"t": 节点 id, "l": 显示文字}]`），给「链接带」
          画药丸用 —— 只留能解析到图上节点的、去重。
        """
        from . import preview as preview_mod

        if not (cfg.get("preview") or {}).get("enabled"):
            return
        index = preview_mod.build_attachment_index(cfg["vault"])
        total = 0
        for note in self.notes:
            node = self.nodes.get(note.file.id)
            if node is None:
                continue
            html, links = preview_mod.render(note, cfg, index, base_dir, self.resolve)
            node["preview"] = html
            node["links"] = links
            total += len(html)
        self.stats["preview_chars"] = total

    def _heading_at_line(self, note_id: str, line):
        """返回覆盖该行的标题 id：行号 ≤ line 的最后一个标题。

        标题按文档序排列，所以「最后一个 line ≤ 目标行的标题」就是包含该行的
        最内层标题。链接写在笔记前言里时返回 None。
        """
        note = self.by_id.get(note_id)
        if note is None or not line:
            return None
        found = None
        for h in note.headings:
            if h.line <= line:
                found = h
            else:
                break
        return found.id if found else None

    # ── 边 ──────────────────────────────────────────────────────────────
    def add_edge(self, source, target, etype, weight, origin, evidence=""):
        if not source or not target or source == target:
            return
        if source not in self.nodes or target not in self.nodes:
            return
        key = (source, target, etype, origin if origin == "candidate" else "")
        if key in self._edge_key:
            edge = self._edge_key[key]
            edge["weight"] = round(edge["weight"] + weight, 3)
            edge["hits"] += 1
            if evidence and len(edge["evidence"]) < 120:
                extra = f"; {evidence}"
                if extra not in edge["evidence"]:
                    edge["evidence"] += extra
            return
        edge = {
            "id": f"e{len(self.edges) + 1}",
            "s": source,
            "t": target,
            "type": etype,
            "weight": round(weight, 3),
            "origin": origin,
            "evidence": evidence,
            "hits": 1,
        }
        self.edges.append(edge)
        self._edge_key[key] = edge

    def build_contains(self):
        for node_id, node in self.nodes.items():
            if node["parent"]:
                self.add_edge(node["parent"], node_id, TYPE_CONTAINS, 1.0, "hierarchy")

    def build_wiki_edges(self):
        wcfg = self.cfg["weight"]
        for note in self.notes:
            for link in note.links:
                if parse.is_attachment(link.target, self.cfg["attachments"]):
                    self.stats["attachment_links"] += 1
                    continue
                target = self.resolve(link.target)
                if target is None:
                    self.unresolved[link.target] += 1
                    self.stats["unresolved_links"] += 1
                    continue
                if target == note.file.id:
                    self.stats["self_links"] += 1
                    if link.anchor:
                        self._record_heading_link(note.file.id, target, link)
                    continue
                weight = wcfg["wiki_link"]
                if link.embed:
                    weight *= wcfg["embed_factor"]
                if link.anchor:
                    weight += wcfg["heading_link_bonus"]
                    self._record_heading_link(note.file.id, target, link)
                self.add_edge(note.file.id, target, TYPE_DERIVES, weight, "wiki", link.raw)
                self.stats["wiki_edges_raw"] += 1

    def _record_heading_link(self, source, target, link):
        """把 [[笔记#标题]] 的锚点解析到目标笔记内部的具体标题上。

        笔记本体之间的边表达「引用了这篇笔记」；这里再把源端按行号归属到发出
        链接的那个标题，于是能建出 heading→heading 的真边 ——
        「信号与系统#求解微分方程的经典解法」→「Calculus#二阶常系数…」。
        源端归属不到（链接写在笔记前言里）时回落到笔记节点本身。
        """
        target_note = self.by_id.get(target)
        if target_note is None or not link.anchor:
            return
        wanted = _normalize_heading(link.anchor)
        from_heading = self._heading_at_line(source, link.line)
        for heading in target_note.headings:
            candidates = {
                _normalize_heading(heading.title),
                _normalize_heading("/".join(heading.path)),
            }
            if wanted and wanted in candidates:
                self.heading_links.append({
                    "source": source,
                    "from_heading": from_heading,
                    "heading": heading.id,
                    "note": target,
                    "raw": link.raw,
                    "anchor": link.anchor,
                    "line": link.line,
                })
                self.stats["heading_links"] += 1
                wcfg = self.cfg["weight"]
                self.add_edge(from_heading or source, heading.id, TYPE_DERIVES,
                              wcfg["wiki_link"] + wcfg["heading_link_bonus"], "wiki", link.raw)
                return
        self.stats["heading_anchor_miss"] += 1

    def build_frontmatter_edges(self):
        wcfg = self.cfg["weight"]
        for note in self.notes:
            fm = note.frontmatter
            nid = note.file.id
            for name in _as_list(fm.get("prerequisites")):
                target = self.resolve(name)
                if target:
                    self.add_edge(target, nid, TYPE_PREREQ, wcfg["annotation_default"], "frontmatter",
                                  f"prerequisites: {name}")
                else:
                    self.unresolved[str(name)] += 1
            for name in _as_list(fm.get("derives")):
                target = self.resolve(name)
                if target:
                    self.add_edge(nid, target, TYPE_DERIVES, wcfg["annotation_default"], "frontmatter",
                                  f"derives: {name}")
                else:
                    self.unresolved[str(name)] += 1
            for name in _as_list(fm.get("contrasts")):
                target = self.resolve(name)
                if target:
                    self.add_edge(nid, target, TYPE_CONTRAST, wcfg["annotation_default"], "frontmatter",
                                  f"contrasts: {name}")
                else:
                    self.unresolved[str(name)] += 1

    def build_annotation_edges(self, annotations: dict):
        wcfg = self.cfg["weight"]
        for item in annotations.get("edges", []) or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "accepted")).lower()
            if status in ("rejected", "pending", "no", "off"):
                self.stats["annotation_skipped"] += 1
                continue
            source = self.resolve(str(item.get("source", "")))
            target = self.resolve(str(item.get("target", "")))
            etype = str(item.get("type", TYPE_PREREQ))
            if etype not in (TYPE_PREREQ, TYPE_DERIVES, TYPE_CONTRAST):
                etype = TYPE_PREREQ
            weight = float(item.get("weight", wcfg["annotation_default"]))
            if source is None or target is None:
                self.unresolved[f"{item.get('source')} → {item.get('target')}"] += 1
                continue
            self.add_edge(source, target, etype, weight, "annotation",
                          str(item.get("reason", "annotations.yaml")))

    def build_candidate_edges(self, candidates: dict):
        wcfg = self.cfg["weight"]
        for item in (candidates or {}).get("candidates", []) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "pending")).lower() not in ("accepted", "yes", "on"):
                continue
            source = self.resolve(str(item.get("source", "")))
            target = self.resolve(str(item.get("target", "")))
            if source is None or target is None:
                self.stats["candidate_unresolved"] += 1
                continue
            etype = str(item.get("type", TYPE_PREREQ))
            if etype not in (TYPE_PREREQ, TYPE_DERIVES, TYPE_CONTRAST):
                etype = TYPE_PREREQ
            weight = float(item.get("weight", wcfg["annotation_default"]))
            self.add_edge(source, target, etype, weight, "candidate",
                          str(item.get("reason", "candidates.yaml")))

    # ── 聚合 ────────────────────────────────────────────────────────────
    def ancestors_at(self, node_id: str, budget: int) -> str:
        node = self.nodes.get(node_id)
        while node is not None and node["depth"] > budget:
            node = self.nodes.get(node["parent"]) if node["parent"] else None
        return node["id"] if node else node_id

    def build_aggregates(self, max_depth: int):
        """为每个层级预算算一套聚合边，并记下每条边首次出现的层级 minlayer。

        minlayer 是渲染侧做 LOD 裁剪的依据：一条边在浅层就已经存在（说明它连接
        的是两个大块头），那么在深层也不必重复画那些只在最浅层才有意义的弱边。
        """
        aggregates: dict[int, list] = {}
        semantic = [e for e in self.edges if e["type"] != TYPE_CONTAINS]
        first_seen: dict[tuple, int] = {}
        for budget in range(1, max_depth + 1):
            bucket: dict[tuple, dict] = {}
            for node_id, node in self.nodes.items():
                if node["depth"] <= budget and node["parent"]:
                    key = (node["parent"], node_id, TYPE_CONTAINS)
                    slot = bucket.setdefault(key, {"s": key[0], "t": key[1], "type": TYPE_CONTAINS,
                                                   "weight": 0.0, "count": 0, "origin": "hierarchy"})
                    first_seen.setdefault(key, budget)
                    slot["weight"] = round(slot["weight"] + 1.0, 3)
                    slot["count"] += 1
            for edge in semantic:
                s = self.ancestors_at(edge["s"], budget)
                t = self.ancestors_at(edge["t"], budget)
                if s == t or s not in self.nodes or t not in self.nodes:
                    continue
                key = (s, t, edge["type"])
                slot = bucket.setdefault(key, {"s": s, "t": t, "type": edge["type"],
                                               "weight": 0.0, "count": 0, "origin": edge["origin"]})
                first_seen.setdefault(key, budget)
                slot["weight"] = round(slot["weight"] + edge["weight"], 3)
                slot["count"] += 1
                if slot["origin"] != edge["origin"]:
                    slot["origin"] = "mixed"
            for edge in bucket.values():
                edge["minlayer"] = first_seen[(edge["s"], edge["t"], edge["type"])]
            aggregates[budget] = sorted(bucket.values(), key=lambda e: (e["s"], e["t"], e["type"]))
        return aggregates

    def levels_table(self, aggregates: dict):
        table = {}
        for budget, edges in aggregates.items():
            visible = [n for n in self.nodes.values() if n["depth"] <= budget]
            folders = sum(1 for n in visible if n["kind"] == "folder")
            notes = sum(1 for n in visible if n["kind"] == "note")
            headings = sum(1 for n in visible if n["kind"] == "heading")
            table[budget] = {
                "nodes": len(visible),
                "notes": notes,
                "folders": folders,
                "headings": headings,
                "edges": len(edges),
                "semantic_edges": sum(1 for e in edges if e["type"] != TYPE_CONTAINS),
            }
        return table


def _normalize_heading(text: str) -> str:
    """标题锚点匹配：忽略空白与大小写，与 Obsidian 的宽松匹配一致。"""
    return re.sub(r"[\s\u3000]+", "", str(text)).strip("#").lower()


def _lookup(mapping: dict, stem: str, note_id: str):
    if not isinstance(mapping, dict):
        return None
    for key in (note_id, stem, f"{stem}.md"):
        if key in mapping:
            return mapping[key]
    low = stem.lower()
    for key, value in mapping.items():
        if str(key).lower() in (low, note_id.lower()):
            return value
    return None


def _subject_of(parts):
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [v for v in value if v is not None]
    return [value]


def _resolve_metrics(cfg, ann, fm, stats):
    """按 precedence 决定 weight / mastery。"""
    weight, mastery, source = None, None, "default"
    for layer in cfg["precedence"]:
        if layer == "annotation":
            if ann.get("weight") is not None:
                weight = float(ann["weight"]); source = "annotation"
            if ann.get("mastery") is not None:
                mastery = int(ann["mastery"])
        elif layer == "frontmatter":
            if fm.get("weight") is not None and weight is None:
                weight = float(fm["weight"]); source = "frontmatter"
            if fm.get("mastery") is not None and mastery is None:
                mastery = int(fm["mastery"])
    if weight is None:
        weight = 1.0
    if mastery is None:
        mastery = 0
        stats["notes_without_mastery"] += 1
    else:
        stats["notes_with_mastery"] += 1
    mastery = max(0, min(5, int(mastery)))
    return float(weight), mastery, source
