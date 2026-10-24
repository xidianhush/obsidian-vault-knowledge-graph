"""学科色板：手写覆盖优先，其余按 golden-angle 自动分配（PLAN_APPLICABILITY.md 阶段 1.3）。

**为什么放在构建期而不是渲染期**：颜色必须对「这份库实际出现的 domain 集合」成立，
而不是渲染时遇到一个没登记的 domain 就退到同一个灰（阶段 0.3 体检表里 wide-roots 的
30 个学科有 23 个同灰，`theme.domains` 只手写了 7 个）。构建期一次算完、写进 payload：

  * `meta.theme.domains`：**完整**的 domain → 颜色映射（手写覆盖 + 自动补齐）
  * `meta.domains`：按「笔记数降序 + 名字」排好的列表（图例、学科下拉直接用它）

渲染与宿主只查表，不需要知道色板是怎么来的 —— 将来插件移植也少一份逻辑（PLAN §9.1）。
"""
from __future__ import annotations

import colorsys

# 默认参数。写进 config.yaml 的 `theme.auto_palette` 可以覆盖。
DEFAULTS = {
    "hue_start": 205.0,      # 首个自动色的色相：偏冷蓝，与现有视觉语言同轨
    "saturation": 0.46,      # 低饱和：深青底上不能出现糖果色
    "lightness": 0.62,
    "golden_angle": 137.508,  # 相邻自动色的色相间隔（黄金角，N 个时散布最均匀）
    "min_hue_gap": 18.0,     # 与手写色/已分配色的最小色相间隔（度）
}


def hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360.0) / 360.0,
                                  max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _hue_of_hex(value: str) -> float:
    try:
        r = int(value[1:3], 16) / 255.0
        g = int(value[3:5], 16) / 255.0
        b = int(value[5:7], 16) / 255.0
    except (ValueError, IndexError):
        return 0.0
    h, _l, _s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0


def _hue_dist(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def assign(counts: dict, hand: dict, fallback: str, opts: dict | None = None) -> dict:
    """返回**完整**的 domain → 颜色映射。

    counts   : {domain: 笔记数}
    hand     : config.yaml 的 theme.domains（手写覆盖，永远优先）
    fallback : config.yaml 的 theme.fallback（只留给「没有 domain」的节点，例如根笔记）

    排序用「笔记数降序 + 名字」：新学科通常出现在末尾，已有学科的色不会整体漂移，
    这样同一个库两次构建之间用户认得的颜色是稳的。
    """
    opt = dict(DEFAULTS)
    opt.update({k: v for k, v in (opts or {}).items() if v is not None})
    hand = {str(k): str(v) for k, v in (hand or {}).items()}

    result = {d: c for d, c in hand.items() if d in counts}   # 只保留真出现的（手写多余的不进图例）
    taken = [_hue_of_hex(c) for c in result.values()]

    order = sorted((d for d in counts if d not in result),
                   key=lambda d: (-int(counts[d]), str(d)))
    k = 0
    for domain in order:
        hue = None
        for _ in range(64):
            candidate = (float(opt["hue_start"]) + k * float(opt["golden_angle"])) % 360.0
            k += 1
            if all(_hue_dist(candidate, t) >= float(opt["min_hue_gap"]) for t in taken):
                hue = candidate
                break
        if hue is None:                                   # 兜底：色相用尽就继续转
            hue = (float(opt["hue_start"]) + k * float(opt["golden_angle"])) % 360.0
            k += 1
        taken.append(hue)
        result[domain] = hsl_to_hex(hue, float(opt["saturation"]), float(opt["lightness"]))
    return result


def ordered(counts: dict, colors: dict) -> list:
    """图例 / 学科下拉用的有序列表：[{name, color, count}]。"""
    items = [{"name": d, "color": colors.get(d, ""), "count": int(counts.get(d, 0))}
             for d in counts]
    items.sort(key=lambda it: (-it["count"], it["name"]))
    return items
