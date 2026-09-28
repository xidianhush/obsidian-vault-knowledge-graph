#!/usr/bin/env python3
"""自动校验 dist/graph.json —— 把「能脚本判定的验收标准」全部断言一遍。

无法脚本客观判定的事（动画帧率、悬停响应、file:// 双击体验）不在这里假装通过，
README.md 里给了人工核对清单。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kg.ioutils import setup_stdout

setup_stdout()

from kg import config as config_mod


class CheckFailure(Exception):
    pass


def _check(condition, message, failures):
    if condition:
        print(f"  [ok]   {message}")
    else:
        print(f"  [FAIL] {message}")
        failures.append(message)


def run(cfg, payload_path=None):
    payload_path = payload_path or os.path.join(cfg["root"], cfg["output"]["json"])
    if not os.path.exists(payload_path):
        raise CheckFailure(f"找不到 {payload_path}，先跑 python build.py build")
    with open(payload_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    meta = data["meta"]
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    aggregates = data["aggregates"]
    frames = data["frames"]
    headings = data["headings"]
    failures: list[str] = []

    print(f"\n校验 {payload_path}")

    # ── 标准 2：最浅一层只有学科大类，且没有悬空边 ──────────────────────
    print("\n[标准 2] 缩放到最浅层 = 只显示学科大类，且无悬空边")
    roots = sorted(n["id"] for n in data["nodes"] if n["depth"] == 1)
    note_domains = {n["domain"] for n in data["nodes"] if n["kind"] == "note"}
    _check(set(roots) == note_domains,
           f"depth=1 的 {len(roots)} 个节点恰好是笔记所属的 {len(note_domains)} 个顶层学科", failures)
    top = aggregates.get("1", [])
    visible_top = {n["id"] for n in data["nodes"] if n["depth"] == 1}
    _check(all(e["s"] in visible_top and e["t"] in visible_top for e in top),
           f"depth≤1 的 {len(top)} 条边两端都在可见集合内（无悬空边）", failures)
    top_visible = [n["id"] for n in data["nodes"] if n["depth"] <= 1]
    _check(all(n["kind"] == "folder" for n in data["nodes"] if n["depth"] == 1),
           "depth=1 上只有文件夹节点，没有笔记直接挂在根部", failures)
    print(f"         该层可见：{'、'.join(top_visible)}")

    # ── 标准 3：最深层显示全部笔记 ──────────────────────────────────────
    print("\n[标准 3] 缩放到最深层 = 显示全部笔记")
    max_depth = meta["max_depth"]
    note_nodes = [n for n in data["nodes"] if n["kind"] == "note"]
    _check(len(note_nodes) == meta["note_count"], f"笔记节点 {len(note_nodes)} 篇", failures)
    _check(len(note_nodes) == meta["scan"]["included"],
           f"笔记数 {len(note_nodes)} == 扫描纳入数 {meta['scan']['included']}", failures)
    deepest = aggregates.get(str(max_depth), [])
    visible_deep = {n["id"] for n in data["nodes"] if n["depth"] <= max_depth}
    _check(all(e["s"] in visible_deep and e["t"] in visible_deep for e in deepest),
           f"depth≤{max_depth} 的 {len(deepest)} 条边两端都可见", failures)
    _check(all(n["depth"] <= max_depth for n in data["nodes"]),
           "没有节点的深度超过 max_depth", failures)

    # ── 边与节点引用完整性 ──────────────────────────────────────────────
    print("\n[引用完整性] 边、链接、附件")
    dangling = [e for e in edges if e["s"] not in nodes or e["t"] not in nodes]
    _check(not dangling, f"{len(edges)} 条边两端都存在（悬空 {len(dangling)} 条）", failures)
    per_level_dangling = [
        (budget, e) for budget, rows in aggregates.items() for e in rows
        if e["s"] not in nodes or e["t"] not in nodes
        or nodes[e["s"]]["depth"] > int(budget) or nodes[e["t"]]["depth"] > int(budget)
    ]
    _check(not per_level_dangling,
           f"各层聚合边都没有引用比该层更深的节点（越界 {len(per_level_dangling)} 条）", failures)
    attachment_ext = tuple("." + e for e in cfg["attachment_ext"])
    bad = [n for n in nodes.values() if n["id"].lower().endswith(attachment_ext)]
    _check(not bad, f"没有把附件当成节点（{len(bad)} 个）", failures)
    _check("heading_links" in data, "标题级链接（[[笔记#标题]]）已输出", failures)
    dangling_links = [h for h in data.get("heading_links", [])
                      if h["heading"].split("#")[0] not in nodes]
    _check(not dangling_links,
           f"{len(data.get('heading_links', []))} 处标题级链接都指向存在的笔记"
           f"（悬空 {len(dangling_links)} 处）", failures)
    print(f"         附件链接 {meta['link_stats'].get('attachment_links', 0)} 条已丢弃，"
          f"解析失败 {meta['link_stats'].get('unresolved_links', 0)} 条"
          + (f"：{meta['unresolved'][:3]}" if meta["unresolved"] else ""))
    print(f"         标题级链接命中 {meta.get('heading_link_total', 0)} 处，"
          f"锚点未命中 {meta['link_stats'].get('heading_anchor_miss', 0)} 处")

    # ── 标准 4：位置稳定（构造性保证 + 包含关系一致） ───────────────────
    print("\n[标准 4] 节点位置稳定 —— 坐标一次算定，缩放只切可见性")
    coords = {}
    duplicates = []
    for node in data["nodes"]:
        key = (round(node["x"], 2), round(node["y"], 2))
        if key in coords:
            duplicates.append((coords[key], node["id"]))
        coords[key] = node["id"]
    _check(not duplicates, f"{len(coords)} 个节点坐标两两不同（重叠 {len(duplicates)} 对）", failures)

    violations = []
    by_id = {n["id"]: n for n in data["nodes"]}
    frame_count = 0
    for lv, rows in frames.items():
        frame_count += len(rows)
        for frame in rows:
            box = (frame["x1"], frame["y1"], frame["x2"], frame["y2"])
            for node in data["nodes"]:
                if node["kind"] != "note" or node["depth"] > int(lv):
                    continue
                ancestor = node["parent"]
                while ancestor and ancestor != frame["frame_of"]:
                    ancestor = by_id[ancestor]["parent"]
                if ancestor != frame["frame_of"]:
                    continue
                if not (box[0] <= node["x"] <= box[2] and box[1] <= node["y"] <= box[3]):
                    violations.append((frame["id"], node["id"]))
    _check(not violations,
           f"{frame_count} 个「省界」轮廓包住了各自截至该层已可见的全部笔记"
           f"（越界 {len(violations)} 个）", failures)
    _check(all(int(lv) >= 2 for lv in frames),
           f"轮廓只出现在 depth≥2 的层级（实际层级 {sorted(frames, key=int)}）", failures)

    # ── 标题层 ──────────────────────────────────────────────────────────
    print("\n[标题层]")
    total_headings = sum(len(v) for v in headings.values())
    _check(total_headings == meta["heading_total"],
           f"标题总数 {total_headings} == 元数据 {meta['heading_total']}", failures)
    _check(set(headings) == {n["id"] for n in note_nodes},
           "每篇笔记都有对应的标题列表（哪怕是空列表）", failures)
    broken = [
        (note_id, h["id"]) for note_id, items in headings.items() for h in items
        if h["parent"] != note_id and h["parent"] not in {x["id"] for x in items}
    ]
    _check(not broken, f"标题的父子指针都指向存在的标题或所属笔记（坏了 {len(broken)} 个）", failures)
    headingless = [note_id.rsplit("/", 1)[-1] for note_id, items in headings.items() if not items]
    if headingless:
        print(f"         [note] {len(headingless)} 篇笔记没有标题（不构成失败）："
              f"{'、'.join(headingless[:8])}")
    lv = {}
    for items in headings.values():
        for h in items:
            lv[h["level"]] = lv.get(h["level"], 0) + 1
    print(f"         层级分布 {dict(sorted(lv.items()))}")

    # ── 各层一览 ────────────────────────────────────────────────────────
    print("\n[各层可见内容]")
    print(f"         {'层级':<6}{'文件夹':>7}{'笔记':>7}{'边':>7}{'语义边':>8}")
    for budget, row in sorted(payload_levels(data).items(), key=lambda kv: int(kv[0])):
        print(f"         depth≤{budget:<2}{row['folders']:>7}{row['notes']:>7}"
              f"{row['edges']:>7}{row['semantic_edges']:>8}")

    print()
    if failures:
        print(f"✗ {len(failures)} 项未通过\n")
        return 1
    print("✓ 全部自动校验通过\n")
    return 0


def payload_levels(data):
    return data.get("levels", {})


def main(cfg=None):
    cfg = cfg or config_mod.load()
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
