"""层级径向布局。

设计要点（也是「节点位置永不跳动」的实现方式）：

* 半径 = 深度 × radius_step，角度按子树的笔记数（叶子数）加权分配；
* 所有层级的坐标在构建时**一次算定**，语义缩放只切换可见性，从不重算坐标；
* 因此同一节点在 depth=1 和 depth=5 时的绝对坐标完全相同 —— 位置稳定是构造出来的，
  不是靠动画掩盖的。
"""

from __future__ import annotations

import math

from .graph import TYPE_CONTAINS


def _leaf_counts(nodes: dict, children: dict):
    """自底向上算每个节点的笔记数（叶子数）。"""
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
    """给每个节点写入 x / y（以及供背景框使用的包围盒）。"""
    radius_step = float(cfg["layout"]["radius_step"])
    start_angle = math.radians(float(cfg["layout"]["start_angle"]))

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
        return (0 if node["kind"] == "folder" else 1, -node["weight"], node["label"])

    for kids in children.values():
        kids.sort(key=sort_key)
    roots.sort(key=sort_key)

    counts = _leaf_counts(nodes, children)
    total = sum(counts.get(r, 1) for r in roots) or 1

    positions: dict[str, tuple[float, float]] = {}

    def assign(node_id: str, a0: float, a1: float):
        mid = (a0 + a1) / 2
        depth = nodes[node_id]["depth"]
        r = depth * radius_step
        positions[node_id] = (r * math.cos(mid), -r * math.sin(mid))
        kids = children.get(node_id, [])
        if not kids:
            return
        span = a1 - a0
        sub = sum(counts.get(k, 1) for k in kids) or 1
        cursor = a0
        for kid in kids:
            share = span * counts.get(kid, 1) / sub
            assign(kid, cursor, cursor + share)
            cursor += share

    cursor = start_angle
    for root in roots:
        span = 2 * math.pi * counts.get(root, 1) / total
        assign(root, cursor, cursor + span)
        cursor += span

    for node_id, node in nodes.items():
        x, y = positions.get(node_id, (0.0, 0.0))
        node["x"] = round(x, 3)
        node["y"] = round(y, 3)

    frames = _frames(nodes, children, max_depth)
    return frames


def _frames(nodes: dict, children: dict, max_depth: int):
    """按层级预先算好「省界」轮廓。

    第 level 层显示的是深度 < level 的文件夹的轮廓，且轮廓只包住「截至该层已经可见」
    的后代（深度 ≤ level）—— 这样轮廓永远落在当前视口内，不会伸到看不见的地方去。
    """
    frames: dict[str, list] = {}
    for level in range(1, max_depth + 1):
        rows = []
        for node_id, node in nodes.items():
            if node["kind"] != "folder" or node["depth"] != level - 1:
                continue
            members = [node_id] + _descendants_within(node_id, children, nodes, level)
            if len(members) < 2:
                continue
            xs = [nodes[m]["x"] for m in members]
            ys = [nodes[m]["y"] for m in members]
            width = max(xs) - min(xs)
            height = max(ys) - min(ys)
            if width < 30 and height < 30:
                continue
            pad = 44
            rows.append({
                "id": f"frame::{level}::{node_id}",
                "frame_of": node_id,
                "depth": level - 1,
                "domain": node["domain"],
                "label": node["label"],
                "x1": round(min(xs) - pad, 2),
                "y1": round(min(ys) - pad, 2),
                "x2": round(max(xs) + pad, 2),
                "y2": round(max(ys) + pad, 2),
                "note_count": sum(1 for m in members if nodes[m]["kind"] == "note"),
            })
        if rows:
            frames[str(level)] = rows
    return frames


def _descendants_within(node_id: str, children: dict, nodes: dict, level: int) -> list[str]:
    out: list[str] = []
    stack = list(children.get(node_id, []))
    while stack:
        current = stack.pop()
        if nodes[current]["depth"] > level:
            continue
        out.append(current)
        if nodes[current]["kind"] != "note":
            stack.extend(children.get(current, []))
    return out
