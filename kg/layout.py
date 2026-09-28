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

但 reveal 单独还不够：必须再叠一层「按深度的下限门控」
----------------------------------------------------
上一段的乐观结论只对了一半。reveal 是**局部**量（与同圈最近邻的角间距 ×
该圈半径），而「放大 = 更深」要的是一个**全局单调**关系。两者并不自动等价：

* 半径每圈 ×1.7（ring_ratio），
* 每圈节点数却在第 6 圈见顶（939）后一路回落到 41，

于是深层圈在**世界尺度上反而更稀疏**。实测本 vault 每圈 minzoom 的中位数是
0.051 / 0.179 / 0.147 / 0.277 / 0.471 / 0.684 / 0.649 / 0.747 / 0.658 / 0.674 ——
到第 8 圈就饱和了。取前缀最大得到「完全解锁第 L 层所需的 zoom」enter[L]，
它在 0.7466 处封顶：滚轮从 0.75 推到 2.94 这 8 格不再解锁任何新层级，只是纯放大；
而居中在原点时 z=2.94 的视口只有 ±275 世界单位，最深的圈在半径 35576 处，
**画出来 0 个节点**。

根子在于：同心圆布局把深度编码成**半径**，地图把细节编码成**尺度**，两者不同构。
要保住「坐标一次算定、缩放只改相机」这个前提（换 circle packing / ZUI 布局
等于推翻整套数据侧），就必须人为把单调性补回来 —— 见 `_apply_depth_floor`。
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
    """给每个节点写入 x / y / reveal，并返回 (rings, enter, home_layer)。

    * rings：每圈 {"depth", "radius", "count"}，渲染侧用它算「这一圈要装进屏幕
      需要多大 zoom」；
    * enter：长度 max_depth 的列表，enter[L-1] 是「完全解锁第 L 层」所需的 zoom，
      沿深度单调不减。渲染侧用它把连续 zoom 反推成 HUD 上的层级读数；
    * home_layer：初始视图停在第几圈 —— 既已完全解锁、又能整圈装进屏幕的最深一圈。
      这里按 NOMINAL_FIT_RADIUS 估一个落盘值；真实值依赖视口，由前端复算。
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

    min_px = float(cfg.get("lod", {}).get("min_px", 6))
    reveal = _reveal(by_depth, angles, radius_of, max_depth, base_radius)
    _clamp_to_ancestors(nodes, reveal, max_depth)
    # 顺序要紧：按深度封顶必须在祖先夹取之后。封顶只会**降低** reveal，
    # 而 cap[L] = min_px/enter[L] 随 L 不增，所以
    # reveal_child ≤ cap[depth_child] ≤ cap[depth_parent] ≤ reveal_parent，
    # 祖先单调性自动保持，不需要再夹一次。
    enter = _apply_depth_floor(nodes, reveal, by_depth, max_depth, min_px)
    home_layer = _home_layer(enter, radius_of, max_depth)

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

    return rings, enter, home_layer


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


# 落盘 home_layer 时用的标称视口半径（屏幕像素）：1600×900 的窗口减去 46px 页脚，
# 再取半高。真实值依赖窗口尺寸，所以前端拿到 enter 与 rings 后会自己复算一遍 ——
# 这个常量只是为了让 dist/graph.json 里也有一个可用的默认值。
NOMINAL_FIT_RADIUS = (900 - 46) / 2


def _median(values):
    if not values:
        return 0.0
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def _apply_depth_floor(nodes, reveal, by_depth, max_depth, min_px):
    """给 reveal 叠一层「按深度的上限封顶」，把缩放方向锁死为「放大 = 更深」。

    为什么非做不可（详见模块 docstring 第三段）：reveal 是局部量，而 r_L 每圈 ×1.7、
    每圈节点数在第 6 圈见顶后回落，深层圈在世界尺度上反而更稀疏，
    「解锁第 L 层所需的 zoom」到第 8 圈就饱和在 0.75，之后滚轮 8 格不再解锁任何层级。

    做法：取每圈 minzoom 的中位数、沿深度做前缀最大，得到第 L 层的解锁门槛

        enter[L] = cummax_{L'≤L} median_{n∈ring L'}( min_px / reveal_n )

    再反过来把它变成 reveal 的上限：reveal_n ← min(reveal_n, min_px / enter[depth_n])。
    于是 minzoom_n = min_px / reveal_n ≥ enter[depth_n]，深度越大门槛越高。

    安全性：封顶只会降低 reveal → 抬高 minzoom → 让节点**更晚**出现，
    所以「同圈可见节点屏幕间距 ≥ min_px」的构造性保证不受影响（那条保证只依赖
    reveal 是间距的下界，缩小下界不改变已成立的不等式方向）。
    又因为 enter 单调不减 ⇒ cap[L] = min_px/enter[L] 单调不增，
    祖先单调性 reveal_child ≤ reveal_parent 自动保持，无需再夹一次。

    用中位数而不是最小值/最大值：最小值会被单个极窄扇形拖垮（等于没封顶），
    最大值则会把整圈最松的节点也推迟到最挤的那一刻，层级感全失。中位数表示
    「这一圈的典型拥挤程度」，正好是「这一层该在什么时候摊开」的语义。
    """
    enter: list[float] = []
    running = 0.0
    for depth in range(1, max_depth + 1):
        members = by_depth.get(depth, [])
        vals = sorted(min_px / max(reveal[nid], 1e-9) for nid in members)
        running = max(running, _median(vals))
        enter.append(running)

    caps = [(min_px / e) if e > 0 else float("inf") for e in enter]
    for node_id, node in nodes.items():
        depth = node.get("depth", 1)
        cap = caps[depth - 1] if 1 <= depth <= max_depth else caps[-1]
        if node_id in reveal and reveal[node_id] > cap:
            reveal[node_id] = cap
    return enter


def _home_layer(enter, radius_of, max_depth):
    """初始视图停在第几圈：既已完全解锁（enter[L] ≤ z）、又能整圈装进屏幕（z ≤ fit/r_L）
    的最深一圈。两个条件都满足才有意义 —— 只看前者会停在一个塞满屏幕的圈上，
    只看后者会停在一个还没解锁、圆点糊成一团的圈上。
    """
    best = 1
    for depth in range(1, max_depth + 1):
        radius = radius_of.get(depth)
        if not radius:
            continue
        if enter[depth - 1] <= NOMINAL_FIT_RADIUS / radius:
            best = depth
    return best


