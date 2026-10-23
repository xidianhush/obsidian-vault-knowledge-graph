#!/usr/bin/env python3
"""自动校验 dist/graph.json —— 把「能脚本判定的验收标准」全部断言一遍。

无法脚本客观判定的事（动画帧率、悬停响应、file:// 双击体验）不在这里假装通过，
README.md 里给了人工核对清单。

布局换成 circle packing 之后，这里的几何断言也跟着换了一副骨架：旧版校验的是
「半径严格等比 r_L = base × ratio^(L-1)」+「同圈相邻节点的弧长间距」，这两条都
建立在「一层一圈圆周」上；新版校验的是三条包含关系（子在父内、父至少比子大
level_ratio 倍、兄弟互不相交）。这三条一旦成立，就顺带把旧版要靠采样才能检查的
「任意缩放下可见节点不重叠」变成了定理 —— 证明写在下面 [包含几何] 段。
"""

from __future__ import annotations

import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kg.ioutils import setup_stdout

setup_stdout()

from kg import config as config_mod
from kg import layout as layout_mod

# x/y 按 3 位小数、r 按 4 位小数落盘，而 _pack_siblings 是「相切」打包 ——
# 兄弟圆恰好接触（dist == r_i + r_j），正是对舍入最敏感的那一批。
# 所以三条几何断言一律用相对容差，不用绝对容差。
REL_TOL = 2e-3


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
    layers = data["layers"]
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

    # ── 范围一致性：图上出现的东西必须都在这个 scope 声明的目录里 ────────
    # 这是「一份真源」的验收标准：范围改了而图没跟上、或者图里漏出一个本该私有的
    # 目录，都能在这里当场抓住。
    print("\n[范围一致性] 节点与 scope 声明对齐")
    scope_roots = list(cfg.get("roots") or [])
    if not scope_roots:
        _check(False, "scope 没有声明任何内容根目录", failures)
    else:
        _check(set(roots) == set(scope_roots),
               f"depth=1 的 {len(roots)} 个根 == scope「{cfg['scope']}」声明的 {len(scope_roots)} 个"
               f"目录（{'、'.join(sorted(scope_roots))}）", failures)
        outside = sorted({n["id"].split("/")[0] for n in data["nodes"]} - set(scope_roots))
        _check(not outside,
               f"没有节点落在 scope 之外的目录里（越界 {len(outside)} 个）"
               + (f"：{'、'.join(outside)}" if outside else ""), failures)
        # remap 生效的证明：真实路径前缀不该以节点 id 的形式残留（如 public 里的 Logs/）
        leftover = sorted({r["from"] for r in (cfg.get("remap") or [])
                           if any(n["id"] == r["from"] or n["id"].startswith(r["from"] + "/")
                                  for n in data["nodes"])})
        _check(not leftover,
               f"重写过的路径前缀没有残留成节点 id（残留 {len(leftover)} 个）"
               + (f"：{'、'.join(leftover)}" if leftover else ""), failures)

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
    # packing 下同心是合法几何：父节点只有一个孩子时，_pack_siblings 把那一个孩子
    # 放在原点，于是父子同心、只按 level_ratio 缩小半径 —— 正是地图上「这个省只有
    # 一个市」的画法。所以旧版「坐标两两不同」要放宽成「重合的一对必须是父子」。
    coords = {}
    dup_pairs = []
    for node in data["nodes"]:
        key = (round(node["x"], 3), round(node["y"], 3))
        if key in coords:
            dup_pairs.append((coords[key], node["id"]))
        coords[key] = node["id"]
    nonfamily = [(a, b) for a, b in dup_pairs
                 if nodes[a]["parent"] != b and nodes[b]["parent"] != a]
    _check(not nonfamily,
           f"{len(data['nodes'])} 个节点里坐标重合的 {len(dup_pairs)} 对全是父子关系"
           f"（独子链同心；非父子重合 {len(nonfamily)} 对）", failures)

    # ── 包含几何 ────────────────────────────────────────────────────────
    # 这三条是 packing 的全部契约，其余视觉性质都从它们推出来：
    #   ① 子在父内      dist(c,p) + r_c ≤ r_p        —— 用户要求 3「子元素在父圆内」
    #   ② 父至少大 1.5 倍 r_p ≥ level_ratio × r_c     —— 用户要求 2「按包含关系分档」
    #   ③ 兄弟不相交    dist(a,b) ≥ r_a + r_b        —— 圆点互不糊在一起
    # ①+③ 合起来 ⇒ 任意两个「互不包含」的圆都不相交：取 a、b 的最近公共祖先 c，
    # a 落在 c 的某个孩子 S_a 里、b 落在另一个孩子 S_b 里（① 反复套用），而 S_a 与
    # S_b 是兄弟故不相交（③），于是 a ∩ b = ∅。这就是旧版要靠 40 档缩放采样才能
    # 检查的「屏幕上可见节点不重叠」—— 现在它是定理，不用再采样了（下面只在可见集
    # 很小的两个 zoom 上抽验一遍，防实现走样）。
    print("\n[包含几何] 子在父内 · 父比子大 level_ratio 倍 · 兄弟不相交")
    level_ratio = float(cfg["layout"]["level_ratio"])
    _check([row["depth"] for row in layers] == list(range(1, max_depth + 1)),
           f"{len(layers)} 层覆盖 depth 1..{max_depth}，无缺口", failures)
    _check(all(row["count"] == sum(1 for n in data["nodes"] if n["depth"] == row["depth"])
               for row in layers),
           "每层登记的 count 与实际节点数一致", failures)
    _check(all(n.get("r", 0) > 0 for n in data["nodes"]),
           f"{len(data['nodes'])} 个节点都有正的世界半径 r", failures)

    outside, too_small = [], []
    for n in data["nodes"]:
        p = nodes.get(n["parent"])
        if p is None:
            continue
        d = math.hypot(n["x"] - p["x"], n["y"] - p["y"])
        if d + n["r"] > p["r"] * (1 + REL_TOL):
            outside.append((n["id"], d + n["r"], p["r"]))
        if p["r"] < n["r"] * level_ratio * (1 - REL_TOL):
            too_small.append((n["id"], p["r"], n["r"]))
    _check(not outside,
           f"每个节点都完整落在父节点圆内（越界 {len(outside)} 个）", failures)
    _check(not too_small,
           f"每个父节点的半径都 ≥ 孩子的 {level_ratio} 倍（不足 {len(too_small)} 个）", failures)

    kids_of: dict = {}
    for n in data["nodes"]:
        if n["parent"] is not None:
            kids_of.setdefault(n["parent"], []).append(n)
    overlap = []
    sibling_pairs = 0
    for kids in kids_of.values():
        for i in range(len(kids)):
            for j in range(i + 1, len(kids)):
                sibling_pairs += 1
                a, b = kids[i], kids[j]
                d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                if d < (a["r"] + b["r"]) * (1 - REL_TOL):
                    overlap.append((a["id"], b["id"], d, a["r"] + b["r"]))
    _check(not overlap,
           f"{sibling_pairs} 对兄弟圆互不相交（重叠 {len(overlap)} 对）", failures)

    # ── LOD r：按缩放裁剪细节的依据 ─────────────────────────────────────
    # r 是布局契约：沿包含链严格递减 ⇒ 子圆永远装在父圆内部。
    # 2026-10-21 起它**不再**决定「何时浮现」——浮现时机改由「深度的层级带」决定
    # （见下面的 [LOD 层级带]）。r 仍然决定「同一层里画多大」，以及可读性地板。
    print("\n[LOD r] 世界半径沿包含链严格递减（布局契约：子圆永远在父圆内）")
    min_px = float(cfg["lod"]["min_px"])
    fade = float(cfg["lod"]["fade_span"])
    viol = [n["id"] for n in data["nodes"]
            if n["parent"] in nodes and n["r"] >= nodes[n["parent"]]["r"] * (1 - REL_TOL)]
    _check(not viol,
           f"r 沿包含链严格递减（违反 {len(viol)} 个）", failures)

    need = sorted(min_px / n["r"] for n in data["nodes"])   # = minzoom
    root_need = max(min_px / n["r"] for n in data["nodes"] if n["depth"] == 1)
    z_lo = root_need * float(cfg["zoom"]["zoom_out_floor"])
    z_hi = need[-1] * float(cfg["zoom"]["zoom_in_ceiling"])
    _check(z_hi > z_lo, f"缩放区间 [{z_lo:.4f}, {z_hi:.4f}] 非空", failures)
    _check(root_need <= need[-1],
           "顶层学科全部出现所需的缩放，不大于最挤节点所需的缩放", failures)

    # ── 层级带：浮现时机由「深度」决定（2026-10-21 起）────────────────────
    # enter[L-1] = 第 L 层**开始淡入**的 zoom；M[L] = enter[L-1] × fade_span =
    # 该层**成熟**（全部满不透明）的 zoom。同一层的所有节点共用这条带 ⇒
    # 同层同时出现、同色；父圆在「下一层的成熟点」压暗。
    # 阶梯是「以 home 视角锚定的等比序列」（kg/layout.py），所以加一篇笔记不会让
    # 所有层级门槛一起跳 —— 这是它取代 per-node 门槛（min_px/r）的主要理由之二。
    print("\n[LOD 层级带] 按深度的淡入带（同层同时出现、同色）")
    lod = meta.get("lod", {})
    enter = lod.get("enter") or []
    home = lod.get("home_layer")
    home_band = float(cfg["zoom"].get("home_band", 0.5))
    mature = [e * fade for e in enter]
    depth1 = [n for n in data["nodes"] if n["depth"] == 1]
    _check(len(enter) == max_depth,
           f"enter 覆盖 depth 1..{max_depth}（实到 {len(enter)} 项）", failures)
    _check(all(b > a + 1e-9 for a, b in zip(enter, enter[1:])),
           "enter 严格递增 —— 每层都有自己的入口 zoom，HUD 上能逐层区分", failures)
    _check(all(mature[i] < enter[i + 1] - 1e-9 for i in range(len(enter) - 1)),
           "相邻两层的带不重叠（M[L] < enter[L+1]）—— 这是「同层同色」的前提："
           "同一时刻最多只有一层正处在淡入过程中", failures)
    _check(bool(enter) and abs(mature[-1] - z_hi) < 1e-6 * max(1.0, z_hi),
           f"最深层的成熟点 M[{max_depth}]={mature[-1] if mature else 0:.4f} "
           f"== zMax={z_hi:.4f}（阶梯构造等式）", failures)

    # home 的定义：整张图缩到「布局根圆恰好贴合视口」再乘 home_fit 的余量。
    # home_fit 的硬上限是 padding（= 布局根半径 / 最大包围盒半径），config._validate
    # 已经把这条钉死了，这里只负责用它复算 home_layer。
    fit = layout_mod.NOMINAL_FIT_RADIUS
    _check(abs(fit - float(meta["nominal_fit_radius"])) < 1e-6,
           f"meta.nominal_fit_radius={meta['nominal_fit_radius']} 与 layout 常量 {fit} 一致",
           failures)
    root_radius = float(meta["layout_root_radius"])
    home_fit = float(cfg["zoom"]["home_fit"])
    home_zoom = fit / root_radius * home_fit
    cand = [d for d in range(1, max_depth + 1) if enter[d - 1] <= home_zoom] if enter else []
    _check(home == (max(cand) if cand else 1),
           f"home_layer={home} 是 home_zoom={home_zoom:.4f} 下**已开始淡入**的最深一层"
           f"（布局根半径 {root_radius:.0f}，候选 {cand}）", failures)
    if home and 1 <= home <= len(enter):
        lo, hi = enter[home - 1], mature[home - 1]
        _check(lo <= home_zoom <= hi,
               f"home_zoom={home_zoom:.4f} 落在第 {home} 层的淡入带 [{lo:.4f}, {hi:.4f}] 内",
               failures)
        p = (home_zoom - lo) / (hi - lo) if hi > lo else 0.0
        _check(abs(p - home_band) < 1e-3,
               f"home 在第 {home} 层带上的进度 {p:.3f} ≈ zoom.home_band={home_band}"
               f"（0 = 刚开始浮现，1 = 完全成熟）", failures)

    r_median_of = {row["depth"]: row["r_median"] for row in layers}
    print(f"         {'层':>3}{'节点':>7}{'r中位':>10}{'r最小':>9}{'r最大':>10}"
          f"{'enter(开始)':>12}{'M(成熟)':>11}")
    for row in layers:
        print(f"         {row['depth']:>3}{row['count']:>7}{row['r_median']:>10.2f}"
              f"{row['r_min']:>9.2f}{row['r_max']:>10.2f}"
              f"{enter[row['depth'] - 1]:>12.4f}{mature[row['depth'] - 1]:>11.4f}")
    distinct = len({round(v, 4) for v in enter})
    print(f"         enter 有 {distinct}/{len(enter)} 个互不相同的取值"
          + ("（每层在 HUD 上都能区分开）" if distinct == len(enter) else "（有层共用入口）"))

    # ── 第 11 带：叶子圆内药丸 + Obsidian 式预览（2026-10-23 第四轮）──────────
    # 用户口径：**只有「下一级直接是正文」的元素**（没有子元素、自己直接含正文）才在
    # 它**自己的实心圆里**挂一枚药丸，出现由该圆自己的屏幕半径决定（44→64px 淡入），
    # 不再有全局缩放带；Ctrl 悬停 / 单击 → 预览浮层并从**这一节的锚点**滚起。
    # 数据侧守：预览 HTML 完整、叶子标记正确、正文长度/锚点齐全、图片可解析、链接可落地。
    pv_cfg = cfg.get("preview") or {}
    if pv_cfg.get("enabled"):
        print("\n[预览/叶子药丸] 第 11 带：叶子元素圆内药丸 + Obsidian 式预览")
        all_nodes = data["nodes"]
        notes = [n for n in all_nodes if n["kind"] == "note"]
        heads = [n for n in all_nodes if n["kind"] == "heading"]
        previews = [n.get("preview") or "" for n in notes]
        _check(all(previews), f"{len(notes)} 篇笔记都有预览 HTML", failures)
        total = sum(len(p) for p in previews)
        _check(total > 0, f"预览 HTML 总字符 {total}", failures)
        # 只查「正文文本」里的残留：代码块里的 `np.array([[1, 2]])` 是内容不是语法
        text_only = [re.sub(r"<(pre|code)\b[^>]*>.*?</\1>", "", p, flags=re.S) for p in previews]
        _check(not any("[[" in p for p in text_only),
               "预览正文里没有残留 [[ ]] 语法（代码块不算）", failures)
        _check(not any(p.lstrip().startswith("---") for p in previews),
               "预览里没有残留 frontmatter", failures)
        _check(any("$" in p for p in previews),
               "预览里保留了公式定界符（交给运行时 KaTeX 渲染）", failures)
        # 图片引用按「相对 dist/」写出，必须真能找到文件（519MB 不内联，只能引用）
        dist_dir = os.path.dirname(os.path.join(cfg["root"], cfg["output"]["html"]))
        bad = []
        for p in previews:
            for mm in re.finditer(r'<img[^>]+src="([^"]+)"', p):
                src = mm.group(1)
                if "://" in src or src.startswith("data:"):
                    continue
                if not os.path.isfile(os.path.normpath(os.path.join(dist_dir, src))):
                    bad.append(src)
        _check(not bad, f"预览里的图片引用都能找到文件（缺失 {len(bad)} 个）", failures)
        node_ids = {n["id"] for n in all_nodes}
        all_links = [l for n in notes for l in (n.get("links") or [])]
        _check(all(l.get("t") in node_ids for l in all_links),
               f"预览里的链接目标都落在图上节点（{len(all_links)} 条）", failures)
        # ── 叶子 / 正文长度 / 锚点（第四轮新增）────────────────────────────
        leaves = [n for n in all_nodes
                  if n.get("leaf") and n.get("hasText") and (n.get("tlen") or 0) > 0]
        _check(len(leaves) > 0,
               f"有正文的叶子元素 {len(leaves)} 个（药丸就画在这些圆里）", failures)
        _check(all(n.get("kind") in ("note", "heading") for n in leaves),
               "叶子药丸只给笔记/标题节点，文件夹不挂", failures)
        kids = {}
        for n in all_nodes:
            p = n.get("parent")
            if p:
                kids[p] = kids.get(p, 0) + 1
        bad_leaf = [n["id"] for n in all_nodes
                    if bool(n.get("leaf")) != (kids.get(n["id"], 0) == 0)]
        _check(not bad_leaf,
               f"leaf 标记与「没有子节点」严格一致（不一致 {len(bad_leaf)} 个）", failures)
        anchors = [n.get("anchor") for n in heads if n.get("anchor")]
        # 锚点只在**同一篇笔记的预览 HTML 内**唯一（每篇都从 pv-h0 起，跨笔记重复是正常的）
        per_note_anchor = {}
        for n in heads:
            if n.get("anchor"):
                per_note_anchor.setdefault(n.get("note"), []).append(n["anchor"])
        n_dup = [k for k, v in per_note_anchor.items() if len(v) != len(set(v))]
        _check(not n_dup, f"同一篇笔记内标题锚点不重复（重复 {len(n_dup)} 篇）", failures)
        per_note = {}
        for h in heads:
            if h.get("anchor"):
                per_note.setdefault(h.get("note"), set()).add(h["anchor"])
        missing_anchor = []
        for note in notes:
            html = note.get("preview") or ""
            for a in per_note.get(note["id"], ()):
                if ('id="%s"' % a) not in html:
                    missing_anchor.append(a)
        _check(not missing_anchor,
               f"每个标题锚点都能在所属笔记的预览 HTML 里找到（缺 {len(missing_anchor)} 个）",
               failures)
        with_text = [n for n in heads if (n.get("tlen") or 0) > 0]
        with_anchor = [n for n in with_text if n.get("anchor")]
        ratio = len(with_anchor) / max(1, len(with_text))
        _check(ratio >= 0.95,
               f"含正文的标题里 {len(with_anchor)}/{len(with_text)} 有锚点"
               f"（≥95%：python-markdown 与我们的标题解析口径允许极少数差异，"
               f"没锚点的会退回预览顶部）", failures)
        n_leaf_head = len([n for n in leaves if n["kind"] == "heading"])
        n_leaf_note = len(leaves) - n_leaf_head
        print(f"         叶子+正文 {len(leaves)} 个（标题 {n_leaf_head} / 笔记 {n_leaf_note}）；"
              f"锚点 {len(anchors)} 个；预览 {total} 字；出站链接 {len(all_links)} 条")

    # ── 「落笔」的解析复刻（与 render.js 的 draw() 判据对齐）─────────────
    # 一个节点这一帧会被画出来，当且仅当：
    #   ① 它所属的层已经开始淡入：z > enter[depth-1]
    #   ② 屏幕半径 ≥ 0.5×min_px（可读性地板；render.js 里低于它直接 continue）
    # 注意 ① 用的是**层**的入口，不是节点自己的 minzoom —— 后者只决定「同层里多大」，
    # 已经与可见性脱钩（这正是 2026-10-21 那次改动的核心）。
    def painted(z):
        out = []
        for n in data["nodes"]:
            if z <= enter[n["depth"] - 1]:
                continue
            if n["r"] * z < 0.5 * min_px:
                continue
            out.append(n)
        return out

    steps = 40
    prev = -1
    counts = []
    nonmono = 0
    for i in range(steps + 1):
        z = z_lo * (z_hi / z_lo) ** (i / steps)
        cnt = len(painted(z))
        counts.append(cnt)
        if cnt < prev:
            nonmono += 1
        prev = cnt
    _check(nonmono == 0, f"落笔节点数随缩放单调不减（回退 {nonmono} 次）", failures)
    _check(counts[-1] == len(data["nodes"]),
           f"放到最内见全部 {counts[-1]} 个节点", failures)

    at_lo = painted(z_lo)
    at_lo_ids = {n["id"] for n in at_lo}
    missing_roots = [n["id"] for n in depth1 if n["id"] not in at_lo_ids]
    _check(not missing_roots,
           f"缩到最小（z={z_lo:.4f}）时 {len(depth1)} 个顶层学科全部可见"
           f"（缺 {len(missing_roots)} 个）", failures)
    deeper_at_lo = [n["id"] for n in at_lo if n["depth"] > 1]
    _check(not deeper_at_lo,
           f"缩到最外层**只剩第 1 层**（z={z_lo:.4f} 时更深的节点一个都没开始淡入，"
           f"越界 {len(deeper_at_lo)} 个）—— 层级带的核心契约", failures)
    # 2026-10-21 前这里是「z_lo 处可见的不止 6 个根」—— 那是 per-node 门槛的后果
    # （大孩子的 minzoom 远低于小学科根）。层级带之后 z_lo 恰好只剩 6 个根。
    at_home = painted(home_zoom)
    too_deep_home = [n["id"] for n in at_home if n["depth"] > (home or 1)]
    _check(bool(at_home),
           f"home 视图（z={home_zoom:.4f}）有内容（落笔 {len(at_home)} 个）", failures)
    _check(not too_deep_home,
           f"home 视图只画出 depth≤{home} 的元素（越界 {len(too_deep_home)} 个）—— "
           f"home 落在第 {home} 层", failures)

    # 用户要求 2/4 的守门条件：home 视图下每个学科根都必须大到看得见。
    # 这条同时把 size_exponent 钉住了 —— 调大到 0.6，最小的 Medical and Health
    # 在 home 只有 18.24px，贴着 min_px=18 没有余量；0.5 时是 20.39px。
    small_roots = [(n["id"], n["r"] * home_zoom) for n in depth1 if n["r"] * home_zoom < min_px]
    _check(not small_roots,
           f"home_zoom 下 {len(depth1)} 个学科根的屏幕半径都 ≥ min_px={min_px}"
           f"（最小 {min(n['r'] for n in depth1) * home_zoom:.2f}px、"
           f"最大 {max(n['r'] for n in depth1) * home_zoom:.1f}px）", failures)

    # 判据：滚轮一格不能齐刷刷弹出一大片。
    # ⚠️ 2026-10-21 的口径变更：层级带**有意**让同一层一起开始淡入，所以这条不再
    # 用「alpha>0 的节点数」（那样每一层入口都会一次涌入 26%），而是用**真正落笔**
    # 的节点数（层已开始 且 屏幕半径 ≥ 0.5×min_px）—— 后者才是用户眼睛看到的量。
    # 上限从 20% 放宽到 35%：这是设计变更（同层同现）的直接代价，淡入带 fade_span
    # 把它摊在约 2.6 格滚轮上。实测约 24%，仍远低于同心环时代的 66%。
    wheel_step = float(cfg["zoom"]["wheel_step"])
    total = len(data["nodes"])
    notch_counts = []
    z = z_lo
    while z < z_hi * (1 + 1e-9):
        notch_counts.append(len(painted(z)))
        z *= wheel_step
    notch_counts.append(total)
    jumps = [b - a for a, b in zip(notch_counts, notch_counts[1:])]
    worst = max(jumps) / total if jumps else 0.0
    _check(worst <= 0.35,
           f"滚轮单格最大落笔涌入 {worst:.0%}（{max(jumps)}/{total} 个节点，"
           f"共 {len(jumps)} 格），不超过 35%", failures)

    # 抽验 packing 的间距定理：屏幕上任意两个互不包含的**落笔**圆，圆心距 ≥ min_px。
    # （未交叠 ⇒ 屏幕距离 ≥ 两者屏幕半径之和；而落笔的前提是各自 ≥ 0.5×min_px，
    #   所以和 ≥ min_px。2026-10-21 前落笔门槛是 min_px，那时这条是 2×min_px。）
    # 只在落笔集很小的两个 zoom 上做全对检查（z_hi 处 3500 个节点两两配对要 600 万次，
    # 而这个性质上面已经证过了，抽样只是防实现走样）。
    def ancestors(nid):
        out = set()
        cur = nodes[nid]["parent"]
        while cur in nodes:
            out.add(cur)
            cur = nodes[cur]["parent"]
        return out

    spacing_bad = []
    for z in (z_lo, home_zoom):
        vis = painted(z)
        anc = {n["id"]: ancestors(n["id"]) for n in vis}
        for i in range(len(vis)):
            for j in range(i + 1, len(vis)):
                a, b = vis[i], vis[j]
                if b["id"] in anc[a["id"]] or a["id"] in anc[b["id"]]:
                    continue        # 嵌套关系，本来就该一个套在另一个里
                d = math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * z
                if d < min_px * (1 - REL_TOL):
                    spacing_bad.append((round(z, 4), a["id"], b["id"], round(d, 2)))
    _check(not spacing_bad,
           f"z_lo 与 home 两处，落笔的非嵌套圆屏幕中心距都 ≥ min_px={min_px}"
           f"（不足 {len(spacing_bad)} 对）", failures)

    notch = math.log(z_hi / z_lo) / math.log(wheel_step)
    print(f"         r 区间 [{min(n['r'] for n in data['nodes']):.3f}, "
          f"{max(n['r'] for n in data['nodes']):.1f}] 世界单位，"
          f"跨度 {max(n['r'] for n in data['nodes']) / min(n['r'] for n in data['nodes']):.0f} 倍")
    print(f"         缩放区间 [{z_lo:.4f}, {z_hi:.4f}] = {z_hi / z_lo:.0f} 倍，"
          f"滚轮约 {notch:.0f} 格（每层平均 {notch / len(layers):.1f} 格）")
    print(f"         home 视图 z={home_zoom:.4f} 落笔 {len(at_home)} 个（第 {home} 层）；"
          f"缩到最小 z={z_lo:.4f} 落笔 {len(at_lo)} 个（只剩第 1 层）")
    print(f"         单格涌入峰值 {worst:.0%}（第 {jumps.index(max(jumps)) + 1} 格，按落笔口径）；"
          f"视口理论容量约 (视口半径/min_px)² = ({fit:.0f}/{min_px:.0f})² ≈ {(fit / min_px) ** 2:.0f} 个圆")
    if len(enter) >= 3:
        step_ratio = enter[2] / enter[1]
        print(f"         相邻层入口比 {step_ratio:.2f}×（约 "
              f"{math.log(step_ratio) / math.log(wheel_step):.1f} 格滚轮/层）；"
              f"第 1 层被压到 zMin 以下成熟（M[1]={mature[0]:.4f} < z_lo={z_lo:.4f}）")

    # 跨层（父→子）半径比只做信息输出：它衡量「包含关系在视觉上有多明显」。
    # 独子链是下界情形 —— 只有一个孩子时 s 被 level_ratio 那一项夹住，
    # 比值恰好等于 level_ratio，孩子正好同心缩在父亲中间。
    ratios = sorted(nodes[n["parent"]]["r"] / n["r"]
                    for n in data["nodes"] if n["parent"] in nodes)
    sole = sorted(nodes[n["parent"]]["r"] / n["r"]
                  for n in data["nodes"]
                  if n["parent"] in nodes and len(kids_of.get(n["parent"], [])) == 1)
    if ratios:
        print(f"         父/子半径比：最小 {ratios[0]:.3f}、中位 {ratios[len(ratios) // 2]:.3f}、"
              f"最大 {ratios[-1]:.2f}")
    if sole:
        print(f"         其中独子链 {len(sole)} 个，父/子比 "
              f"{sole[0]:.3f} / {sole[len(sole) // 2]:.3f} / {sole[-1]:.3f}"
              f"（= level_ratio {level_ratio}，同心嵌套）")
    for n in sorted(depth1, key=lambda n: -n["r"]):
        kids = kids_of.get(n["id"], [])
        biggest = max((k["r"] for k in kids), default=0.0)
        print(f"         {n['label']:<34} r={n['r']:>8.2f}  孩子 {len(kids):>2} 个，"
              f"最大的孩子 r={biggest:>7.2f}（父/子 {n['r'] / biggest if biggest else 0:.2f}）")

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
    print(f"         {'层级':<8}{'r中位':>9}{'文件夹':>7}{'笔记':>7}{'标题':>7}{'边':>8}{'语义边':>8}")
    for budget, row in sorted(payload_levels(data).items(), key=lambda kv: int(kv[0])):
        print(f"         depth≤{int(budget):<4}{r_median_of.get(int(budget), 0):>9.2f}"
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
