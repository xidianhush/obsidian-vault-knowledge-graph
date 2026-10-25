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
        self._suffix: dict[str, list[str]] | None = None   # 阶段 3.3：含 / 的链接后缀索引
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
            hits = self._suffix_hits(t)
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

    def _suffix_hits(self, t: str) -> list[str]:
        """含 `/` 的链接目标：按**后缀索引**找，不再全表 `endswith` 扫描（阶段 3.3）。

        索引键是每个 id 的末 1~4 段（`"A/B/Note"` 这类目标够用；目标本身超过 4 段时
        退回全表扫，保持行为与旧实现完全一致 —— 这种写法极少）。
        """
        if self._suffix is None:
            idx: dict[str, list[str]] = {}
            for node_id in self.by_id:
                parts = node_id.split("/")
                for k in range(1, min(len(parts), 4) + 1):
                    idx.setdefault("/".join(parts[-k:]), []).append(node_id)
            self._suffix = idx
        if t.count("/") + 1 > 4:
            return [i for i in self.by_id if i == t or i.endswith("/" + t)]
        return self._suffix.get(t, [])

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
                note_count=0,
                heading_count=0,
            )
        for note in self.notes:
            fid = note.file.id
            ann = _lookup(ann_notes, note.file.stem, fid) or {}
            fm = note.frontmatter
            node = self.add_node(
                fid,
                kind="note",
                depth=note.file.depth,
                parent="/".join(note.file.parts) or None,
                # 2026-10-24 阶段 1.4：**根笔记**（直接放在 vault 根、没有文件夹）自己就是一个
                # 顶层单元 —— 原来 domain 留空串，于是这类库满图走 fallback 灰、图例空白、
                # 校验还报「depth1 不是学科」。现在 domain = 笔记自己的 id（= 文件名 stem）。
                domain=note.file.parts[0] if note.file.parts else fid,
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
        """把笔记的统计（笔记数 / 标题数）向上汇总到所属文件夹。"""
        for node_id, node in sorted(self.nodes.items(), key=lambda kv: -kv[1]["depth"]):
            if node["kind"] != "note":
                continue
            parent = node["parent"]
            while parent:
                p = self.nodes.get(parent)
                if p is None:
                    break
                p["note_count"] += 1
                p["heading_count"] += node["heading_count"]
                parent = p["parent"]

    def build_heading_nodes(self):
        """把每篇笔记的标题树提升为一等节点。

        **2026-10-24 阶段 1.1：标题级别先稠密化再当层数。**
        原来是 `depth = 笔记深度 + 标题级别字面值`（`######` 直接 +6）：一篇笔记里用一次
        六级标题就把整条深度轴拉长 5 层，全库只出现 h1/h3 时中间还会空出一层 ——
        空层占掉一整条缩放带，滚轮走过去画面什么都不变，HUD 的 n/max_depth 也虚高。
        现在按「这篇笔记自己用到的级别」排序映射成 1..k（h1,h3,h4 → 1,2,3），
        节点仍保留 `level` = 原始 markdown 级别（展示/调试用），`rank` = 压缩后的层。
        顺带好处：`h1 → h4` 这种跳级的父子深度差从 3 变成 1，层级带更连续。
        """
        count = 0
        for note in self.notes:
            nnode = self.nodes.get(note.file.id)
            if nnode is None:
                continue
            rank_of = {lv: i + 1 for i, lv
                       in enumerate(sorted({h.level for h in note.headings}))}
            for h in note.headings:
                rank = rank_of[h.level]
                self.add_node(
                    h.id,
                    kind="heading",
                    label=h.title,
                    depth=nnode["depth"] + rank,
                    parent=h.parent or note.file.id,
                    domain=nnode["domain"],
                    level=h.level,
                    rank=rank,
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
        # 阶段 3.3：按笔记分组的标题索引（note_id → 标题节点列表），建一次给所有笔记共用。
        # 旧版每遇到一个 `[[笔记#标题]]` 就在**全部节点**上扫两遍（2×N），2 万节点的库上
        # 3 千处锚点链接 = 1.2 亿次比较。
        heading_index: dict[str, list] = {}
        for nd in self.nodes.values():
            if nd.get("kind") == "heading":
                heading_index.setdefault(nd.get("note"), []).append(nd)
        preview_cfg = cfg.get("preview") or {}
        # 阶段 3.1：预览预算。预览是 payload 里最大的一块（作者库占节点字段 48%），
        # 不设上限时一篇 2 万字的笔记就能单独贡献几百 KB。规则：
        #   per_note = total_chars_budget / 笔记数（总预算按笔记数平分）
        #   limit    = min(per_note, max_note_chars)（用户显式设的每篇上限更优先）
        #   0 表示该项不限制；两项都不限 = 整篇（默认总预算 6M，作者库 1.6M 不触发）。
        total_budget = int(preview_cfg.get("total_chars_budget") or 0)
        max_note = int(preview_cfg.get("max_note_chars") or 0)
        per_note = int(total_budget / max(1, len(self.notes))) if total_budget else 0
        limits = [x for x in (per_note, max_note) if x > 0]
        limit = min(limits) if limits else 0
        truncated = 0
        total = 0
        for note in self.notes:
            node = self.nodes.get(note.file.id)
            if node is None:
                continue
            html, links, anchors = preview_mod.render(
                note, cfg, index, base_dir, self.resolve, limit_chars=limit,
                heading_index=heading_index)
            if limit and len(note.body) > limit and "…（预览已按预算截断）" in html:
                truncated += 1
            node["preview"] = html
            node["links"] = links
            total += len(html)
            # 第五轮（2026-10-24）：药丸层整个删掉 —— **实心圆自己就是入口**。
            # 所以只需要给每个标题记一个预览锚点（悬停标题圆时从那一节滚起）。
            for i, h in enumerate(note.headings):
                hn = self.nodes.get(h.id)
                if hn is not None:
                    hn["anchor"] = (anchors[i] if i < len(anchors) else "") or ""
        self.stats["preview_chars"] = total
        self.stats["preview_limit"] = limit
        self.stats["preview_truncated"] = truncated
        # 2026-10-24（阶段 0.3）：verify 原来断言「预览里必须有 $ 公式」—— 那是把作者库的
        # 内容特征当契约，纯文本库必红。这里给出**源文件里真带公式的笔记数**，让 verify 能
        # 问「有公式的库，公式定界符是否活过管线」，而不是「每个库都必须有公式」。
        self.stats["preview_math_notes"] = sum(
            1 for n in self.notes if "$" in (getattr(n, "body", "") or ""))

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

    # ── 每层读数 ────────────────────────────────────────────────────────
    def levels_table(self, max_depth: int):
        """每一层「累积可见了什么」的读数，供顶栏 #readout 与 verify 打印。

        2026-10-24 起不再依赖聚合边（那个画法已删）：边数 = 两端深度都 ≤ budget 的
        语义边条数，也就是「这一层上真的画得出来的链接有几条」，与渲染侧一致。
        """
        semantic = [e for e in self.edges if e["type"] != TYPE_CONTAINS]
        table = {}
        for budget in range(1, max_depth + 1):
            visible = [n for n in self.nodes.values() if n["depth"] <= budget]
            table[budget] = {
                "nodes": len(visible),
                "notes": sum(1 for n in visible if n["kind"] == "note"),
                "folders": sum(1 for n in visible if n["kind"] == "folder"),
                "headings": sum(1 for n in visible if n["kind"] == "heading"),
                "edges": sum(1 for e in semantic
                             if self.nodes[e["s"]]["depth"] <= budget
                             and self.nodes[e["t"]]["depth"] <= budget),
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

