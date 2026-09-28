"""层级径向布局。

设计要点（也是「节点位置永不跳动」的实现方式）：

* 每个深度一圈，角度按子树规模加权分配，半径按**等比**逐圈放大；
* 所有层级的坐标在构建时**一次算定**，语义缩放只改相机、从不重算坐标；
* 因此同一节点在任何缩放下的世界坐标完全相同 —— 位置稳定是构造出来的，
  不是靠动画掩盖的。

为什么半径是等比的、而不是「按同圈最小间距反解」出来的
------------------------------------------------------
第 L 圈刚好适配视口时 zoom_L = R / r_L（R = 视口半径，屏幕像素）。圈上相邻两点的
屏幕间距 = (r_L · Δθ) · zoom_L = R · Δθ —— **r_L 被约掉了**。也就是说，把某一圈的
半径撑大丝毫不能改善该圈自己的疏密，疏密只由角度分布 Δθ 决定；半径唯一能决定的
是「圈与圈的相对位置」，即适配第 L 圈时上一圈出现在 R / ratio 处。

所以这里把两件事彻底分开：

* 角度：子树规模加权（angle_power 次线性压缩），负责同圈的疏密与扇形嵌套；
* 半径：base_radius × ring_ratio^(L-1)，负责圈间分离，且让每层适配缩放构成
  等比数列 —— 于是滚轮每格推进的层级深度是均匀的，不会某几层挤在一起过不去。

早期版本用「同圈弧长 ≥ min_gap（世界单位）」反解半径，正是踩了上面那个约分的坑：
一个极窄扇形就能把整圈半径顶到上万，depth 1→2 的半径比一度是 20 倍，语义缩放
的层级阈值全挤在 1% 的缩放区间里，滚轮根本落不进去。

reveal：把「该不该画这个节点」交给缩放，而不是交给层级
----------------------------------------------------
约分那条推导还有个更要命的推论：**某一圈整体适配视口时，圈上节点的屏幕间距
= 2πR / N_L，只由该圈节点数 N_L 决定**。本 vault 的 N_L 是
6/22/63/193/558/939/862/585/212/41 —— 第 6 圈 939 个节点，就算完美等角分布，
适配时也只剩 2.7px，任何半径、任何 angle_power 都改不了这个数。

所以「让第 L 圈刚好装进视口」不能当作第 L 层的定义。改用地图软件的做法：
每个 feature 带一个 minzoom，够大才画（Mapbox 的 vector tile 就是这样，
国家级只显示高速、市级才显示街道）。这里给每个节点算一个世界量纲的

    reveal_n = r_L × Δθ_n     （Δθ_n = 与同圈最近邻的角间距）

渲染侧只需 minzoom_n = min_px / reveal_n：屏幕间距 = reveal_n × zoom，
于是「zoom ≥ minzoom_n」等价于「这个节点与最近邻在屏幕上至少分开 min_px」。
可见节点两两间距恒 ≥ min_px，是构造出来的保证，不是调参调出来的。

它同时修好了缩放方向：zoom 越大 → 门槛 min_px/zoom 越低 → 可见节点越多、
越深。也就是**滚轮向上（放大）= 看到更深的层级**，和地图一致；
而旧的「圈适配视口」定义恰好是反的（放大反而只剩最内圈）。
"""

from __future__ import annotations

import math


def _leaf_counts(nodes: dict, children: dict):
    """自底向上算每个节点的叶子数（无子节点的笔记与末级标题都算叶子）。"""
    counts: dict[str, int] = {}

    def walk(node_id: str) -> int:
        kids = children.get(node_id, [])
        if not kids:
            counts[node_id] = 1
            return 1
        total = sum(walk(k) for k in kids)
        counts[node_id] = total
        return total

    for node_id, node in nodes.items():
        if node["parent"] is None:
            walk(node_id)
    return counts


def compute(nodes: dict, cfg: dict, max_depth: int):
    """给每个节点写入 x / y，并返回每圈的半径表 rings。

    rings 的每一项是 {"depth", "radius", "count"}，渲染侧用它把连续的 zoom
    反推成当前层级（depthFromZoom）。
    """
    lcfg = cfg["layout"]
    base_radius = float(lcfg.get("base_radius", 300))
    ring_ratio = float(lcfg.get("ring_ratio", 1.7))
    angle_power = float(lcfg.get("angle_power", 0.5))
    start_angle = math.radians(float(lcfg.get("start_angle", 90)))

    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for node_id, node in nodes.items():
        parent = node["parent"]
        if parent is None:
            roots.append(node_id)
        else:
            children.setdefault(parent, []).append(node_id)

    def sort_key(node_id):
        node = nodes[node_id]
        order = 0 if node["kind"] == "folder" else 1
        if node["kind"] == "heading":
            # 标题没有 weight，按文档顺序排，读起来才和笔记里一致
            return (order, 0.0, node.get("line", 0), node["label"])
        return (order, -node["weight"], 0, node["label"])

    for kids in children.values():
        kids.sort(key=sort_key)
    roots.sort(key=sort_key)

    counts = _leaf_counts(nodes, children)
    # 次线性压缩：标题节点让子树规模差出三个数量级，线性加权会把小文件夹挤成
    # 极窄扇形；但压得太狠又会让大子树的后代挤在一起。angle_power 是这两者的旋钮。
    weights = {nid: cnt ** angle_power for nid, cnt in counts.items()}
    total = sum(weights.get(r, 1.0) for r in roots) or 1.0

    angles: dict[str, float] = {}

    def assign(node_id: str, a0: float, a1: float):
        angles[node_id] = (a0 + a1) / 2
        kids = children.get(node_id, [])
        if not kids:
            return
        span = a1 - a0
        sub = sum(weights.get(k, 1.0) for k in kids) or 1.0
        cursor = a0
        for kid in kids:
            share = span * weights.get(kid, 1.0) / sub
            assign(kid, cursor, cursor + share)
            cursor += share

    cursor = start_angle
    for root in roots:
        span = 2 * math.pi * weights.get(root, 1.0) / total
        assign(root, cursor, cursor + span)
        cursor += span

    by_depth: dict[int, list[str]] = {}
    for node_id, node in nodes.items():
        by_depth.setdefault(node["depth"], []).append(node_id)

    rings = []
    radius_of: dict[int, float] = {}
    for depth in range(1, max_depth + 1):
        radius = base_radius * ring_ratio ** (depth - 1)
        rings.append({
            "depth": depth,
            "radius": round(radius, 3),
            "count": len(by_depth.get(depth, [])),
        })
        radius_of[depth] = radius

    reveal = _reveal(by_depth, angles, radius_of, max_depth, base_radius)
    _clamp_to_ancestors(nodes, reveal, max_depth)

    outer = radius_of.get(max_depth, base_radius)
    strays = [nid for nid in nodes if angles.get(nid) is None]
    for index, node_id in enumerate(nodes):
        node = nodes[node_id]
        angle = angles.get(node_id)
        if angle is None:
            # 不在任何根的子树里（孤点）：摊在最外圈之外，避免与正常节点重合
            angle = 2 * math.pi * index / max(len(strays), 1)
            node["x"] = round(outer * 1.05 * math.cos(angle), 3)
            node["y"] = round(-outer * 1.05 * math.sin(angle), 3)
            node["reveal"] = round(reveal.get(node_id, outer), 3)
            continue
        radius = radius_of.get(node["depth"], outer)
        node["x"] = round(radius * math.cos(angle), 3)
        node["y"] = round(-radius * math.sin(angle), 3)
        node["reveal"] = round(reveal.get(node_id, radius), 3)

    return rings


def _reveal(by_depth, angles, radius_of, max_depth, base_radius):
    """每个节点到同圈最近邻的世界弧长 r_L × Δθ；单节点圈给整圈周长。

    只比同圈：相邻两圈的径向间距是 0.7·r_L，远大于同圈的角向拥挤，
    真正决定「画得下画不下」的是同一圈上的角间距。
    """
    reveal: dict[str, float] = {}
    outer = radius_of.get(max_depth, base_radius)
    for depth, members in by_depth.items():
        radius = radius_of.get(depth, outer)
        if len(members) < 2:
            for node_id in members:
                reveal[node_id] = 2 * math.pi * radius
            continue
        ordered = sorted(members, key=lambda nid: angles.get(nid, 0.0))
        theta = [angles.get(nid, 0.0) for nid in ordered]
        count = len(ordered)
        for i, node_id in enumerate(ordered):
            prev = theta[i] - theta[(i - 1) % count]
            nxt = theta[(i + 1) % count] - theta[i]
            if i == 0:
                prev += 2 * math.pi
            if i == count - 1:
                nxt += 2 * math.pi
            reveal[node_id] = radius * min(prev, nxt)
    return reveal


def _clamp_to_ancestors(nodes, reveal, max_depth):
    """沿包含路径取前缀最小：reveal_n ← min(reveal_n, reveal_parent)。

    不夹会出这种事：某个深层节点恰好落在极稀疏的扇形里，reveal 高达数千，
    于是它在 zoom 0.0013 就冒出来，而 6 个顶层学科要等到 0.0555 ——
    缩到最外面时屏幕上只剩一个孤立标题。语义上也不该如此：
    子节点出现的前提是它所属的那一整条包含链都已经摊开到位。
    夹完之后 minzoom 沿树单调不降，「先看到学科，再看到它的细节」是构造保证的。
    """
    for depth in range(1, max_depth + 1):
        for node_id, node in nodes.items():
            if node["depth"] != depth:
                continue
            parent = node.get("parent")
            if parent is not None and parent in reveal and parent in nodes:
                reveal[node_id] = min(reveal[node_id], reveal[parent])


