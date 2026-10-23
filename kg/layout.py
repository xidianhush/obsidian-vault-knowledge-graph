"""Circle packing 布局：半径编码「内容规模」，嵌套编码「层级深度」。

为什么不是同心环
----------------
旧版把每个深度摊在一圈圆周上，半径 = base_radius × ring_ratio^(L-1)。那个模型里
半径只能用来**分圈**，压根不携带子树规模的信息（旧 docstring 里那条「约分推导」
证明了：把某圈半径撑大丝毫不能改善该圈自己的疏密）。于是有两个改不掉的毛病：

1. 同一圈上所有节点一样大 —— 「包含内容多的应该更大」无从表达；
2. 子节点在父节点**外面**一圈 —— 「子元素落在父元素内部」几何上不可能。

根子上的范畴差别：同心环把深度编码成**半径**，地图把细节编码成**尺度**，两者不同构。
circle packing 才同构 —— 深度 = 嵌套层数，规模 = 圆半径，缩放到哪一层就看见哪一层。

「换 packing 等于推翻整套数据侧」这个顾虑是错的
------------------------------------------------
被推翻的只有布局，没有被推翻的是**前提**：坐标依然在构建期一次算定，语义缩放只改
相机、从不重算坐标，同一节点在任何缩放下的世界坐标完全相同。聚合边（aggregates）、
层级表（levels）、标题级链接（heading_links）都与布局无关，原样保留。

真正被删掉的是三个补丁函数 —— 它们全是在为「半径=深度」擦屁股：

* ``_reveal``：算「到同圈最近邻的世界弧长」。packing 下没有「同圈」，且节点自己
  的半径就是它与邻居的间距保证；
* ``_clamp_to_ancestors``：把 reveal 沿包含链取前缀最小，防止深层节点比祖先先冒出来。
  packing 下祖先半径**严格**更大，minzoom 沿链严格递增，这条自动成立；
* ``_apply_depth_floor``：按深度给 reveal 封顶，人为把「放大 = 更深」的单调性补回来
  （同心环的深层圈在世界尺度上反而更稀疏，enter 到第 8 圈就饱和在 0.7466，
  滚轮 8 格不再解锁任何层级）。packing 下单调性是几何构造出来的，不需要封顶。

半径怎么定：leaves^p 定向 + 自顶向下等比缩放
-------------------------------------------
先自底向上数出每个节点的叶子数 L（叶子 = 没有子节点的节点），再自顶向下分配半径：

    T[n] = L[n] ** size_exponent        # 该节点「想要」的相对大小
    assign(n, R):                       # R 是父节点分给它的实际半径
        radius[n] = R
        positions, enc = _pack_siblings([T[c] for c in children])
        s = min(R / (enc × padding),    # 上界一：子圆必须装得下
                R / (max(T) × level_ratio))   # 上界二：父圆必须明显大于最大子圆
        child 的半径 = T[c] × s，中心 = n 的中心 + positions[c] × s

**为什么不能反过来自底向上打包**（「每个节点 = 把子圆打包后的包围圆」）：那样半径
会随叶子数近乎线性增长。实测本 vault 的等效指数是 L^0.83~L^0.95，六个学科根的半径
spread 高达 79.6× —— 任何一个能让最小根（8 个叶子）看得清的 zoom，都会让最大根
（2104 个叶子）冲出屏幕 80 倍远。自顶向下 + 固定指数把 spread 钉成
(2104/8)^0.5 = 16.2×，这是唯一能同时让六个学科在 home 视图都可见的办法。

**为什么 p = 0.5 是特殊的**：p = 0.5 时

    √(Σ T_i²) = √(Σ L_i) = √L = T_parent        （因为 Σ L_i = L，叶子数可加）

而六方密堆下包围圆半径 ≈ √(Σ T_i²/0.907) = 1.05·√(Σ T_i²)。于是子圆们**自然打包
出来的尺寸恰好等于父圆的目标尺寸**，每层的缩放因子退化成一个与分支数无关的常数
s ≈ 1/(1.05·padding) ≈ 0.85。p 偏离 0.5 都会破坏这个恒等式：p > 0.5 时
enc < 1.05·T_parent，s 变大，深层圆相对膨胀，根 spread 上升（实测 p=0.6 → 28.3×）；
p < 0.5 时相反，深层圆急剧缩小，zMax 爆掉，缩放跨度拉长。

**为什么不会指数爆炸**：两个上界都 < R，所以 s 严格小于「父节点那一层的累积缩放」。
反例是「永远把子圆放大到填满父圆」：那会得到 A[n] = A[parent]²·k，即
A[d] = k^(2^d − 1) —— k = 0.85 时第 10 层是 10^−73，彻底崩掉。本方案里 A[d] 只是
几何衰减，实测每层约 ×0.68，10 层累积 0.02，有界。

``level_ratio`` 负责分支数少的退化情形：独子节点打包出来的包围圆就等于子圆自己，
光靠 padding 只能保证 1.12× 的差，肉眼分不出父子。有了 level_ratio 这条硬上界，
父圆至少是最大子圆的 1.5 倍 —— 实测 343 条独子链的父子半径比精确落在 1.500，
既不会塌成同心靶环，也不会因为「填满」而失控。

代价：半径不再是「绝对内容量」的函数，而是「相对父节点分到的份额」。深层同叶子数的
两个节点半径可以差几倍，取决于它们各自路径上的累积缩放。这是有意为之 —— 用户关心
的是**包含关系**（文件夹 > 其内笔记 > 其内标题）和**同级相对大小**（同层里内容多的
更大），这两条都被完整保留；跨分支比较绝对大小从来不是这张图的读法。

LOD：minzoom = min_px / worldR
------------------------------
每个节点的世界半径 r 就是它的「细节尺度」。渲染侧只需

    minzoom_n = min_px / r_n      （min_px = 该圆在屏幕上值得被画出来的最小半径）

r 沿包含链严格递减 ⇒ minzoom 严格递增 ⇒「滚轮向上（放大）= 看到更深的层级」，
和地图一致。

它还顺带解决了同心环时代那笔无解的账：第 6 圈 939 个节点整体适配视口时只剩
2.7px 间距，任何半径、任何 angle_power 都改不了。packing 下这 939 个节点**不会
被同时要求浮现** —— 它们分散在各自的父圆里，只有放大到对应父圆时才出现。浮现的
圆两两不相交且屏幕半径 ≥ min_px，于是同屏圆数 ≤ (视口半径/min_px)²，是个常数上界。

同心环时代还有个更隐蔽的毛病：所有叶子半径相同 ⇒ minzoom 相同 ⇒ 2308 个叶子会在
**同一格滚轮**里齐刷刷弹出（实测单个 notch 涌入 2308/3481 = 66% 的节点）。packing
下叶子半径随路径累积缩放而分散（最深处的叶子约小 3~5 倍），浮现被摊开到十几格
滚轮上，实测单 notch 最大涌入降到 18%。

缩放轴的三条边界
----------------
* ``zMin = max(depth1 的 minzoom) × zoom_out_floor``：滚轮能滚到最外面的一档。
  由最小那个学科根决定，所以 zoom_out_floor **必须 ≥ 1** —— 取 0.9 会让最小根只剩
  16.2px < min_px，「缩到最外层看见全部 6 个学科」的契约当场破掉。默认 1.05，
  留 5% 余量抵消落盘时 r 只保留 4 位小数的舍入。
* ``home_zoom = NOMINAL_FIT_RADIUS / root_radius × home_fit``：初始视图。
  home_fit 的上限由「六个学科全部完整落在视口内」决定，即
  home_fit ≤ NOMINAL_FIT_RADIUS / root_enc ÷ (NOMINAL_FIT_RADIUS / root_radius)
  = root_radius / root_enc = padding = 1.12。默认 1.08 贴着这个上限，
  再大就会把 Science and Tech 裁掉。
* ``zMax = max(所有节点的 minzoom) × zoom_in_ceiling``。

算法：Wang et al. 2001 前端链相切打包（d3.pack 同款），零第三方依赖
--------------------------------------------------------------------
``_pack_siblings`` 只管「一组圆怎么摆得两两相切且包围圆尽量小」，摆完平移到包围圆
圆心为原点，所以返回值可以直接当作「子节点相对父节点中心的偏移」。半径的**大小**
由上面的定向 + 等比缩放决定，``_pack_siblings`` 只负责**方向**。

6 个真根再打包进一个**虚拟根**，但虚拟根**不落盘为节点** —— depth==1 必须恰好是
6 个学科，否则前端「缩到最外层看到 6 个学科」的契约就破了。虚拟根处**不套
level_ratio**（它不是节点，没有「父子要看得出差别」的需求），直接取
root_radius = 包围圆半径 × padding，省掉白扔的 1.5×。这个值写进
meta.layout_root_radius，供前端算 zMin 与 home_zoom。

最后统一归一化到 norm_root_radius，把世界坐标量级钉住（JSON 体积可控，
且 zMin/zMax 的数值不随 vault 增长而漂移）。

兄弟顺序沿用 sort_key（folder 优先；heading 按文档顺序；其余按 weight 降序再 label），
打包完整体旋转 start_angle —— 同输入必得同输出，这是 30 分钟同步任务的硬要求。
"""

from __future__ import annotations

import math

# 落盘 home_layer 时用的标称视口半径（屏幕像素）：1600×900 的窗口减去 46px 页脚，
# 再取半高。真实值依赖窗口尺寸，所以前端拿到 enter 与 layout_root_radius 后会自己
# 复算一遍 —— 这个常量只是为了让 dist/graph.json 里也有一个可用的默认值。
NOMINAL_FIT_RADIUS = (900 - 46) / 2


# ── 前端链相切打包 ──────────────────────────────────────────────────────
def _place(a, b, c):
    """把圆 c 放到与 a、b 同时外切的位置（取两解中固定的那一支）。"""
    ax, ay = a["x"], a["y"]
    da = b["r"] + c["r"]
    db = a["r"] + c["r"]
    dx = b["x"] - ax
    dy = b["y"] - ay
    dc = dx * dx + dy * dy
    if dc:
        da2 = da * da
        db2 = db * db
        x = 0.5 + (db2 - da2) / (2 * dc)
        db3 = db2 - dc
        y = math.sqrt(max(0.0, 2 * da2 * (db2 + dc) - db3 * db3 - da2 * da2)) / (2 * dc)
        c["x"] = ax + x * dx + y * dy
        c["y"] = ay + x * dy - y * dx
    else:
        c["x"] = ax + db
        c["y"] = ay


def _intersects(a, b):
    dx = b["x"] - a["x"]
    dy = b["y"] - a["y"]
    dr = a["r"] + b["r"]
    return dr * dr - 1e-6 > dx * dx + dy * dy


def _enclose(disks):
    """一组圆的包围圆 (cx, cy, R)。

    n ≤ 2 给精确的最小包围圆；n ≥ 3 用「面积加权质心 + 朝最远支撑圆爬山收紧」。
    后者不保证最小，但 R 每轮都重新取 max(dist + r)，**包含性是构造出来的**，
    爬山只可能让它更小。子节点数上限只有 18，这点近似换来的简单性很划算。
    """
    n = len(disks)
    if n == 0:
        return 0.0, 0.0, 0.0
    if n == 1:
        d = disks[0]
        return d["x"], d["y"], d["r"]
    if n == 2:
        p, q = disks[0], disks[1]
        dx = q["x"] - p["x"]
        dy = q["y"] - p["y"]
        d = math.hypot(dx, dy)
        R = (d + p["r"] + q["r"]) / 2
        if d <= 1e-12:
            return p["x"], p["y"], R
        t = (R - p["r"]) / d
        return p["x"] + t * dx, p["y"] + t * dy, R

    total = sum(d["r"] * d["r"] for d in disks) or 1.0
    cx = sum(d["x"] * d["r"] * d["r"] for d in disks) / total
    cy = sum(d["y"] * d["r"] * d["r"] for d in disks) / total
    R = max(math.hypot(d["x"] - cx, d["y"] - cy) + d["r"] for d in disks)

    for _ in range(12):
        far = max(disks, key=lambda d: math.hypot(d["x"] - cx, d["y"] - cy) + d["r"])
        best = (R, cx, cy)
        for step in (0.5, 0.25, 0.125, 0.0625):
            nx = cx + (far["x"] - cx) * step
            ny = cy + (far["y"] - cy) * step
            cand = max(math.hypot(d["x"] - nx, d["y"] - ny) + d["r"] for d in disks)
            if cand < best[0] - 1e-12:
                best = (cand, nx, ny)
        if best[0] >= R - 1e-12:
            break
        R, cx, cy = best
    return cx, cy, R


def _pack_siblings(radii):
    """把一组圆两两相切打包，返回 (positions, 包围圆半径)。

    positions 已平移到以包围圆圆心为原点，所以调用方可以直接把它们当作
    「子节点相对父节点中心的偏移」。
    """
    n = len(radii)
    if n == 0:
        return [], 0.0
    C = [{"x": 0.0, "y": 0.0, "r": float(radii[i])} for i in range(n)]
    if n == 1:
        return [(0.0, 0.0)], C[0]["r"]

    a, b = C[0], C[1]
    a["x"] = -b["r"]
    b["x"] = a["r"]
    b["y"] = 0.0
    if n == 2:
        cx, cy, R = _enclose(C)
        return [(p["x"] - cx, p["y"] - cy) for p in C], R

    _place(b, a, C[2])
    nxt = [0] * n
    prv = [0] * n
    nxt[0], prv[0] = 1, 2
    nxt[1], prv[1] = 2, 0
    nxt[2], prv[2] = 0, 1

    ai, bi = 0, 1
    i = 3
    # 前端链每次至多删掉一个成员，所以总步数被 2n 兜住；guard 只为防御性收尾
    guard = 0
    while i < n and guard < 64 * n + 64:
        guard += 1
        c = C[i]
        _place(C[ai], C[bi], c)
        j = nxt[bi]
        k = prv[ai]
        sj = C[bi]["r"]
        sk = C[ai]["r"]
        collided = False
        while True:
            if sj <= sk:
                if _intersects(C[j], c):
                    bi = j
                    nxt[ai] = bi
                    prv[bi] = ai
                    collided = True
                    break
                sj += C[j]["r"]
                j = nxt[j]
            else:
                if _intersects(C[k], c):
                    ai = k
                    nxt[ai] = bi
                    prv[bi] = ai
                    collided = True
                    break
                sk += C[k]["r"]
                k = prv[k]
            if j == nxt[k]:
                break
        if collided:
            continue                      # 用新的 a、b 重试同一个圆
        prv[i] = ai
        nxt[i] = bi
        nxt[ai] = i
        prv[bi] = i
        bi = i
        i += 1

    cx, cy, R = _enclose(C)
    return [(p["x"] - cx, p["y"] - cy) for p in C], R


# ── 主入口 ─────────────────────────────────────────────────────────────
def compute(nodes: dict, cfg: dict, max_depth: int):
    """给每个节点写入 x / y / r，返回 (layers, enter, home_layer, root_radius)。

    * layers：每层 {"depth","count","r_min","r_median","r_max","minzoom_median"}；
    * enter：长度 max_depth 的列表，enter[L-1] 是「完全解锁第 L 层」所需的 zoom，
      沿深度单调不减。渲染侧用它把连续 zoom 反推成 HUD 上的层级读数；
    * home_layer：初始视图停在第几层（按 NOMINAL_FIT_RADIUS 估的落盘值，前端会复算）；
    * root_radius：虚拟根的归一化后半径 —— 整张图刚好装进屏幕时 zoom = fit/root_radius。
    """
    lcfg = cfg["layout"]
    leaf_radius = float(lcfg.get("leaf_radius", 1.0))
    level_ratio = float(lcfg.get("level_ratio", 1.5))
    padding = float(lcfg.get("padding", 1.12))
    size_exponent = float(lcfg.get("size_exponent", 0.5))
    norm_root = float(lcfg.get("norm_root_radius", 1000.0))
    start_angle = math.radians(float(lcfg.get("start_angle", -90)))
    min_px = float(cfg.get("lod", {}).get("min_px", 18))
    home_fit = float(cfg.get("zoom", {}).get("home_fit", 1.08))

    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for node_id, node in nodes.items():
        parent = node.get("parent")
        if parent is None or parent not in nodes:
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

    # ── Pass 1（自底向上）：数叶子 ────────────────────────────────────────
    leaves: dict[str, int] = {}

    def count_leaves(node_id: str) -> int:
        if node_id in leaves:
            return leaves[node_id]
        kids = children.get(node_id, [])
        # 先占位再递归，parent 环（数据损坏时）才会退化成 1 而不是无限递归
        leaves[node_id] = 1
        total = 1 if not kids else sum(count_leaves(k) for k in kids)
        leaves[node_id] = total
        return total

    for root in roots:
        count_leaves(root)

    # ── Pass 2（自顶向下）：leaves^p 定向 + 等比缩放 ─────────────────────
    radius: dict[str, float] = {}
    pos: dict[str, tuple] = {}

    def assign(node_id: str, x: float, y: float, allocated: float):
        radius[node_id] = allocated
        pos[node_id] = (x, y)
        kids = children.get(node_id, [])
        if not kids:
            return
        targets = [leaves.get(k, 1) ** size_exponent for k in kids]
        positions, enc = _pack_siblings(targets)
        biggest = max(targets)
        if enc > 0 and biggest > 0:
            s = min(allocated / (enc * padding), allocated / (biggest * level_ratio))
        else:
            s = 1.0
        for kid, (ox, oy), target in zip(kids, positions, targets):
            assign(kid, x + ox * s, y + oy * s, target * s)

    # 虚拟根：把真根们打包在一起，但它自己**不**成为节点。
    # 这里不套 level_ratio —— 虚拟根不画出来，没有「父子要看得出差别」的需求。
    root_targets = [leaves.get(r, 1) ** size_exponent for r in roots]
    if root_targets:
        root_positions, root_enc = _pack_siblings(root_targets)
        root_radius = root_enc * padding
    else:
        root_positions, root_radius = [], leaf_radius

    scale = norm_root / root_radius if root_radius > 0 else 1.0
    for root, (ox, oy), target in zip(roots, root_positions, root_targets):
        assign(root, ox * scale, oy * scale, target * scale)
    root_radius *= scale

    # 孤点（parent 链断裂、又不在 roots 里）：摊在虚拟根之外的一圈，避免与正常节点
    # 重合。本 vault 目前是 0 个，这段只是安全网。
    strays = [nid for nid in nodes if nid not in pos]
    if strays:
        ring = root_radius * 1.15
        for index, node_id in enumerate(strays):
            ang = 2 * math.pi * index / len(strays)
            assign(node_id, ring * math.cos(ang), ring * math.sin(ang), leaf_radius * scale)
            root_radius = max(root_radius, ring + radius[node_id])

    cos_a, sin_a = math.cos(start_angle), math.sin(start_angle)
    for node_id, node in nodes.items():
        x, y = pos.get(node_id, (0.0, 0.0))
        rx = x * cos_a - y * sin_a
        ry = x * sin_a + y * cos_a
        node["x"] = round(rx, 3)
        node["y"] = round(-ry, 3)          # 屏幕坐标系 y 向下
        node["r"] = round(radius.get(node_id, leaf_radius * scale), 4)

    # ── LOD：minzoom = min_px / r ────────────────────────────────────────
    by_depth: dict[int, list[str]] = {}
    for node_id, node in nodes.items():
        by_depth.setdefault(node["depth"], []).append(node_id)

    def minzoom(node_id: str) -> float:
        return min_px / max(nodes[node_id]["r"], 1e-9)

    layers = []
    for depth in range(1, max_depth + 1):
        members = by_depth.get(depth, [])
        rs = sorted(nodes[m]["r"] for m in members)
        mz = sorted(minzoom(m) for m in members)
        layers.append({
            "depth": depth,
            "count": len(members),
            "r_min": round(rs[0], 4) if rs else 0.0,
            "r_median": round(_median(rs), 4) if rs else 0.0,
            "r_max": round(rs[-1], 4) if rs else 0.0,
            "minzoom_median": round(_median(mz), 6) if mz else 0.0,
        })

    # ── 层级带（2026-10-21 起，取代 per-node 门槛当「浮现时机」）──────────
    # 同深度的节点共用一条淡入带 ⇒ 同层同时浮现、同色；父圆在「下一层成熟」时
    # 压暗。半径从此只决定「在同层里画多大」，不再决定「什么时候出现」。
    # 动机见 HANDOFF §4 坑 39：per-node 门槛下，同一层的兄弟会因为半径差 9~40 倍
    # 而错开五六个滚轮格，顶层学科也会因为各自孩子的大小不同而深浅不一。
    #
    # 阶梯形状：把 home 视角锚定在第 home_level 层（默认 2），上下按等比 rung 铺到
    # zMax。rung 由「从 home_level 到最深层的 zoom 跨度」反解 —— 层数固定时整条
    # 阶梯与 vault 内容无关，加一篇笔记不会让所有层级的门槛一起跳（旧算法用
    # minzoom 中位数，会跟着内容漂）。
    fade = float(cfg.get("lod", {}).get("fade_span", 1.35))
    ceiling = float(cfg.get("zoom", {}).get("zoom_in_ceiling", 1.35))
    home_level = int(cfg.get("zoom", {}).get("home_level", 2))
    home_level = max(1, min(home_level, max_depth))
    # home 落在第 home_level 层淡入带的哪个位置（0 = 刚开始浮现，1 = 完全成熟）。
    # 取 0 会让 home 看起来还是上一层；取 1 会让该层全部满不透明 —— 而层内半径差
    # 能到 40 倍，满不透明时最大的那几个会把父圆结构整个糊掉。0.5 是实测能同时
    # 保住「层级可读」与「父圆还透得出来」的位置。
    home_band = min(1.0, max(0.0, float(cfg.get("zoom", {}).get("home_band", 0.5))))

    home_zoom = NOMINAL_FIT_RADIUS / root_radius * home_fit if root_radius > 0 else 0.0
    all_r = [nodes[nid]["r"] for nid in nodes if nodes[nid]["r"] > 0]
    max_mz = min_px / min(all_r) if all_r else 1.0
    z_hi = max_mz * ceiling
    # 反解锚点：home 在带 [M/fade, M] 上的进度 home_band ⇒ M = home·fade / (1 + p(fade-1))
    anchor = (home_zoom * fade / (1.0 + home_band * (fade - 1.0))) if home_zoom > 0 else 1.0
    steps = max_depth - home_level
    rung = (z_hi / anchor) ** (1.0 / steps) if (steps > 0 and anchor > 0) else 1.0
    # 每层至少跨一条淡入带，否则相邻两层的带会叠在一起、又变成「同时出现」。
    rung = max(rung, fade * 1.02)

    mature = [anchor * (rung ** (depth - home_level))
              for depth in range(1, max_depth + 1)]
    # 第 1 层必须在**最外层（zMin）之前**就成熟，否则「缩到最小都看不见学科根」。
    # 两个 scope 的 zMin 差别很大（private 0.367 / public 0.142，由各自最小根决定），
    # 而阶梯是以 home 锚定的，两者不必自然相容 —— 所以这里直接把 M[1] 压到 zMin 以下。
    # 只动第 1 层：M[2..] 与 home 锚定保持不变，单调性也不受影响。
    zoom_out_floor = float(cfg.get("zoom", {}).get("zoom_out_floor", 1.05))
    roots = by_depth.get(1, [])
    if roots:
        z_lo = min_px / max(nodes[r]["r"] for r in roots) * zoom_out_floor
        mature[0] = min(mature[0], z_lo)
    # enter[L-1] = 第 L 层「开始淡入」的 zoom（成熟点 / fade_span）。
    # 渲染侧 alpha = smoothstep(enter[L-1], enter[L-1] * fade_span, zoom)。
    enter = [m / fade for m in mature]
    home_layer = home_level

    # ── 第 11 带：链接带（2026-10-22 第三轮：Obsidian 式悬浮预览）──────────
    # 「链接带」不是节点深度，所以**不进 enter[]**（那 10 项是与 max_depth 对齐的
    # 数据契约，verify 直接断言 len(enter)==max_depth）。它在阶梯上再接一级，并且
    # **在一个窗口内退场**：
    #     淡入 [enter, mature] → 满 [mature, hold] → 淡出 [hold, exit]
    # 越过 exit 之后画布回到「空视口 + 兜底提示」，zMax 之外既有的契约原样保留。
    # 窗口用同一条等比 rung 铺：enter = M[10]×rung/fade，等于假设的第 11 层入口，
    # 于是「h6 成熟后再滚约 2.7 格，链接开始浮现」。
    # 带内画什么：视口中心命中节点所属**笔记**的出站 [[链接]] 药丸（数据在 payload
    # 的 note.links 上）；Ctrl 悬停药丸 → 浮层预览目标笔记（app.js + preview HTML）。
    links_band = None
    if (cfg.get("preview") or {}).get("enabled"):
        links_enter = mature[-1] * rung / fade
        links_mature = links_enter * fade
        links_hold = links_mature * rung
        links_exit = links_hold * fade
        links_band = {
            "enter": round(links_enter, 6),
            "mature": round(links_mature, 6),
            "hold": round(links_hold, 6),
            "exit": round(links_exit, 6),
        }

    return layers, enter, home_layer, root_radius, links_band


def _median(values):
    if not values:
        return 0.0
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2
