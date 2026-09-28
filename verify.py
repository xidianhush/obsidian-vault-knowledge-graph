#!/usr/bin/env python3
"""自动校验 dist/graph.json —— 把「能脚本判定的验收标准」全部断言一遍。

无法脚本客观判定的事（动画帧率、悬停响应、file:// 双击体验）不在这里假装通过，
README.md 里给了人工核对清单。
"""

from __future__ import annotations

import json
import math
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
    rings = data["rings"]
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
    hlinks = data.get("heading_links", [])
    dangling_links = [h for h in hlinks if h["heading"] not in nodes]
    _check(not dangling_links,
           f"{len(hlinks)} 处标题级链接的目标标题都是一等节点（悬空 {len(dangling_links)} 处）",
           failures)
    bad_from = [h for h in hlinks
                if h.get("from_heading") is not None and h["from_heading"] not in nodes]
    _check(not bad_from,
           f"标题级链接的源端标题都能归属到节点（坏了 {len(bad_from)} 处）", failures)
    derives = {(e["s"], e["t"]) for e in edges if e["type"] == "derives"}
    missing_edges = [
        h for h in hlinks
        if (h.get("from_heading") or h["source"]) != h["heading"]
        and ((h.get("from_heading") or h["source"]), h["heading"]) not in derives
    ]
    _check(not missing_edges,
           f"每处标题级链接都建出了对应的 heading→heading 边（缺 {len(missing_edges)} 条）",
           failures)
    attributed = sum(1 for h in hlinks if h.get("from_heading"))
    hh = sum(1 for e in edges
             if nodes.get(e["s"], {}).get("kind") == "heading"
             and nodes.get(e["t"], {}).get("kind") == "heading")
    print(f"         {attributed} 处能归属到源标题（其余写在各篇笔记的前言里，回落到笔记节点）")
    print(f"         图上 heading→heading 语义边 {hh} 条")
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

    # ── 圈层几何 ────────────────────────────────────────────────────────
    print("\n[圈层几何] 半径等比放大；同圈疏密只由角度决定")
    base_radius = float(cfg["layout"]["base_radius"])
    ring_ratio = float(cfg["layout"]["ring_ratio"])
    radius_of = {r["depth"]: r["radius"] for r in rings}
    _check([r["depth"] for r in rings] == list(range(1, meta["max_depth"] + 1)),
           f"{len(rings)} 圈覆盖 depth 1..{meta['max_depth']}，无缺口", failures)
    expect = [round(base_radius * ring_ratio ** (d - 1), 3)
              for d in range(1, meta["max_depth"] + 1)]
    got = [r["radius"] for r in rings]
    _check(all(abs(a - b) < 0.01 for a, b in zip(got, expect)),
           f"半径严格等比 r_L = {base_radius} × {ring_ratio}^(L-1)"
           f"（r_1={got[0]:.0f} → r_{len(got)}={got[-1]:.0f}）", failures)
    _check(all(b > a for a, b in zip(got, got[1:])), "半径逐圈严格递增", failures)
    _check(all(r["count"] == sum(1 for n in data["nodes"] if n["depth"] == r["depth"])
               for r in rings), "每圈登记的 count 与实际节点数一致", failures)

    # ── reveal：按缩放裁剪细节的依据 ────────────────────────────────────
    # 某一圈整体适配视口时，圈上节点的屏幕间距 = 2πR/N_L，只由该圈节点数决定，
    # 与半径无关。所以「让第 L 圈装进视口」不能当作第 L 层的定义；改用地图软件的
    # minzoom 思路：reveal_n = 与同圈最近邻的世界弧长，minzoom_n = min_px / reveal_n，
    # 于是「可见 ⇒ 屏幕上与最近邻至少分开 min_px」是构造出来的保证。
    print("\n[LOD reveal] 每个节点自带「该在多大缩放下出现」")
    min_px = float(cfg["lod"]["min_px"])
    fade = float(cfg["lod"]["fade_span"])
    _check(all(n.get("reveal", 0) > 0 for n in data["nodes"]),
           f"{len(data['nodes'])} 个节点都有正的 reveal", failures)
    viol = [n["id"] for n in data["nodes"]
            if n["parent"] in nodes and n["reveal"] > nodes[n["parent"]]["reveal"] + 1e-9]
    _check(not viol,
           f"reveal 沿包含链单调不增 —— 子节点不会比祖先先出现（违反 {len(viol)} 个）",
           failures)

    need = sorted(min_px / n["reveal"] for n in data["nodes"])   # = minzoom
    root_need = max(min_px / n["reveal"] for n in data["nodes"] if n["depth"] == 1)
    z_lo = root_need * float(cfg["zoom"]["zoom_out_floor"])
    z_hi = need[-1] * float(cfg["zoom"]["zoom_in_ceiling"])
    _check(z_hi > z_lo, f"缩放区间 [{z_lo:.4f}, {z_hi:.4f}] 非空", failures)
    _check(root_need <= need[-1],
           "顶层学科全部出现所需的缩放，不大于最挤节点所需的缩放", failures)

    # 单调性 + 每层是否有独立的可见窗口（否则语义缩放就退化成一次全开）
    steps = 40
    prev = -1
    counts = []
    nonmono = 0
    for i in range(steps + 1):
        z = z_lo * (z_hi / z_lo) ** (i / steps)
        vis = sum(1 for n in data["nodes"] if n["reveal"] >= min_px / z)
        counts.append(vis)
        if vis < prev:
            nonmono += 1
        prev = vis
    _check(nonmono == 0, f"可见节点数随缩放单调不减（回退 {nonmono} 次）", failures)
    _check(counts[0] < len(data["nodes"]) and counts[-1] == len(data["nodes"]),
           f"缩到最外只见 {counts[0]} 个、放到最内见全部 {counts[-1]} 个", failures)

    # 注意：这里**不**要求「每层全部出现所需的缩放」逐层递增。全图最挤的点在哪一层，
    # 哪一层就最后解完；实测拥挤峰在 depth 6（939 个标题挤在一圈），depth 8..10 反而
    # 更早解完。地图同理：通往远方城市的高速先出现，近处的小路后出现。真正的不变量是
    # 上面那条「子节点不早于祖先」，以及下面这条同圈间距保证。
    #
    # 间距保证是构造出来的、不是调参调出来的：reveal_n 取的是到同圈最近邻的世界弧长，
    # 所以任意相邻一对的弧长 ≥ 两端各自的 reveal；而「可见」的定义就是
    # reveal ≥ min_px/zoom。两式相乘即得屏幕间距 ≥ min_px，对任意 zoom 成立。
    # 抽四个 zoom 复算一遍，防的是实现走样而非数据走样。
    # reveal 与坐标都按 3 位小数落盘，比对留 1e-3 的相对容差（不是放宽 min_px）。
    spacing_bad = []
    for z in (z_lo, need[len(need) // 2], need[-1], z_hi):
        thresh = min_px / z
        for r in rings:
            members = sorted((n for n in data["nodes"] if n["depth"] == r["depth"]),
                             key=lambda n: math.atan2(-n["y"], n["x"]))
            count = len(members)
            if count < 2:
                continue
            theta = [math.atan2(-n["y"], n["x"]) for n in members]
            for i in range(count):
                a, b = members[i], members[(i + 1) % count]
                if min(a["reveal"], b["reveal"]) < thresh:
                    continue        # 这一对里还有人没浮现，间距无从谈起
                gap = theta[(i + 1) % count] - theta[i]
                if i == count - 1:
                    gap += 2 * math.pi
                if gap * r["radius"] * z < min_px * (1 - 1e-3):
                    spacing_bad.append((round(z, 4), r["depth"], a["id"]))
    _check(not spacing_bad,
           f"任意缩放下，同圈相邻的可见节点屏幕间距都 ≥ min_px={min_px}"
           f"（不足 {len(spacing_bad)} 对）", failures)

    notch = math.log(z_hi / z_lo) / math.log(float(cfg["zoom"]["wheel_step"]))
    print(f"         reveal 区间 [{min(n['reveal'] for n in data['nodes']):.1f}, "
          f"{max(n['reveal'] for n in data['nodes']):.1f}] 世界单位")
    print(f"         缩放区间 [{z_lo:.4f}, {z_hi:.4f}] = {z_hi / z_lo:.0f} 倍，"
          f"滚轮约 {notch:.0f} 格（每层平均 {notch / len(rings):.1f} 格）")
    print(f"         {'圈':>3}{'节点':>7}{'半径':>10}{'全出现zoom':>12}{'可见数':>8}")
    for r in rings:
        members = [n for n in data["nodes"] if n["depth"] == r["depth"]]
        z = min_px / min(n["reveal"] for n in members) if members else 0.0
        at = sum(1 for n in data["nodes"] if n["reveal"] >= min_px / z) if members else 0
        print(f"         {r['depth']:>3}{r['count']:>7}{r['radius']:>10.0f}"
              f"{z:>12.4f}{at:>8}")
    print(f"         淡入带宽 fade_span={fade}（zoom 从 minzoom/{fade} 到 minzoom，"
          f"alpha 0→1，约 {math.log(fade) / math.log(float(cfg['zoom']['wheel_step'])):.1f} 格滚轮）")

    # 跨圈（父→子）间距只做信息输出，不作失败条件：包含关系已由半径几何表达，
    # 稀疏扇形里父子靠得近反而正好说明「这块内容不多」。
    # 量的是「子节点刚浮现的那一刻」它与父节点的屏幕距离。
    cross = sorted(
        math.hypot(n["x"] - nodes[n["parent"]]["x"], n["y"] - nodes[n["parent"]]["y"])
        * min_px / n["reveal"]
        for n in data["nodes"] if n["parent"] in nodes
    )
    if cross:
        print(f"         子节点刚浮现时与父节点的屏幕间距：最小 {cross[0]:.1f}px、"
              f"中位 {cross[len(cross) // 2]:.1f}px、最大 {cross[-1]:.1f}px（信息，不设门槛）")

    # ── 标题节点 ────────────────────────────────────────────────────────
    print("\n[标题节点] 标题已提升为一等节点")
    heading_nodes = [n for n in data["nodes"] if n["kind"] == "heading"]
    _check(len(heading_nodes) == meta["heading_total"] == meta["node_count_by_kind"]["heading"],
           f"标题节点 {len(heading_nodes)} 个 == 元数据 {meta['heading_total']}", failures)
    broken = [n["id"] for n in heading_nodes
              if n["parent"] not in nodes or nodes[n["parent"]]["depth"] >= n["depth"]]
    _check(not broken,
           f"标题节点的父指针都存在且比它浅（坏了 {len(broken)} 个）", failures)
    offnote = [n["id"] for n in heading_nodes
               if n["depth"] != nodes[n["note"]]["depth"] + n["level"]]
    _check(not offnote,
           f"标题节点深度 == 所属笔记深度 + 标题级别（不符 {len(offnote)} 个）", failures)
    lv = {}
    for n in heading_nodes:
        lv[n["level"]] = lv.get(n["level"], 0) + 1
    print(f"         标题级别分布 {dict(sorted(lv.items()))}")
    print(f"         标题落在 depth {min(n['depth'] for n in heading_nodes)}"
          f"..{max(n['depth'] for n in heading_nodes)}")

    # ── minlayer 单调 ───────────────────────────────────────────────────
    print("\n[LOD] 聚合边的 minlayer")
    seen_at: dict = {}
    bad_layer = []
    for budget, rows in aggregates.items():
        for e in rows:
            key = (e["s"], e["t"], e["type"])
            seen_at.setdefault(key, int(budget))
            if e["minlayer"] != seen_at[key] or e["minlayer"] > int(budget):
                bad_layer.append((budget, key))
    _check(not bad_layer,
           f"{len(seen_at)} 条聚合边的 minlayer 都等于它首次出现的层级"
           f"（不符 {len(bad_layer)} 条）", failures)
    shallow = sum(1 for b in seen_at.values() if b == 1)
    print(f"         其中 {shallow} 条在最浅层就已出现，"
          f"{len(seen_at) - shallow} 条要缩放更深才浮现")

    # ── 各层一览 ────────────────────────────────────────────────────────
    print("\n[各层可见内容]")
    print(f"         {'层级':<8}{'半径':>8}{'文件夹':>7}{'笔记':>7}{'标题':>7}{'边':>8}{'语义边':>8}")
    for budget, row in sorted(payload_levels(data).items(), key=lambda kv: int(kv[0])):
        print(f"         depth≤{int(budget):<4}{radius_of.get(int(budget), 0):>8.0f}"
              f"{row['folders']:>7}{row['notes']:>7}{row['headings']:>7}"
              f"{row['edges']:>8}{row['semantic_edges']:>8}")

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
