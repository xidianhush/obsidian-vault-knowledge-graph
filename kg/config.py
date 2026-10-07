"""config.yaml 的加载、默认值合并与校验。"""

from __future__ import annotations

import os
import re
import sys

import yaml

DEFAULTS: dict = {
    "vault": ".",
    "vault_name": "",
    "include": ["**/*.md"],
    "exclude": [],
    "exclude_notes": [],
    "attachment_ext": [
        "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "heic",
        "pdf", "mp4", "mov", "zip", "canvas", "drawio", "exe",
    ],
    "zoom": {
        "parent_dim": 0.22,
        "wheel_step": 1.18,
        "transition_ms": 260,
        "zoom_in_ceiling": 1.35,
        "zoom_out_floor": 1.05,
        "home_fit": 1.08,
    },
    "weight": {
        "wiki_link": 1.0,
        "heading_link_bonus": 0.5,
        "embed_factor": 0.6,
        "annotation_default": 3.0,
    },
    "precedence": ["annotation", "frontmatter", "wiki"],
    "candidates": {
        "enabled": True,
        "min_score": 0.45,
        "min_term_len": 3,
        "max_doc_freq_ratio": 0.25,
        "min_shared_terms": 2,
        "max_suggestions": 400,
        "generic_headings": [],
    },
    "layout": {
        "leaf_radius": 1.0,
        "level_ratio": 1.5,
        "padding": 1.12,
        "size_exponent": 0.5,
        "norm_root_radius": 1000.0,
        "start_angle": -90,
    },
    "lod": {
        "min_px": 18,
        "label_alpha": 0.55,
        "fade_span": 1.35,
        "weak_edge_min_count": 2,
        "focus_edge_dim": 0.07,
        "hover_edge_dim": 0.75,
    },
    "theme": {"domains": {}, "fallback": "#8B949E", "edges": {}},
    "output": {"json": "dist/graph.json", "html": "dist/knowledge-graph.html"},
    "annotations": "annotations.yaml",
    "candidates_file": "candidates.yaml",
}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ConfigError(Exception):
    pass


def _deep_merge(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _fail(msg: str):
    raise ConfigError(msg)


def _validate(cfg: dict):
    if not cfg["include"]:
        _fail("include 不能为空 —— 至少列出一个公开目录")
    for key in ("include", "exclude", "exclude_notes"):
        if not isinstance(cfg[key], list):
            _fail(f"{key} 必须是列表")
    zoom = cfg["zoom"]
    if not isinstance(zoom.get("parent_dim"), (int, float)) or not 0 < zoom["parent_dim"] <= 1:
        _fail("zoom.parent_dim 必须在 (0, 1] 之间（它是父级上下文层的最低不透明度）")
    if not isinstance(zoom.get("wheel_step"), (int, float)) or zoom["wheel_step"] <= 1:
        _fail("zoom.wheel_step 必须大于 1（它是滚轮一格的缩放倍率）")
    if not isinstance(zoom.get("zoom_in_ceiling"), (int, float)) or zoom["zoom_in_ceiling"] <= 1:
        _fail("zoom.zoom_in_ceiling 必须大于 1（它是顶层适配缩放的放大倍数上限）")
    if not isinstance(zoom.get("zoom_out_floor"), (int, float)) or zoom["zoom_out_floor"] < 1:
        _fail("zoom.zoom_out_floor 必须 ≥ 1（zMin 由最小学科根决定，"
              "小于 1 会让它在最外层跌破 lod.min_px，6 个学科就看不全了）")
    if not isinstance(zoom.get("home_fit"), (int, float)) or zoom["home_fit"] <= 0:
        _fail("zoom.home_fit 必须是正数（初始视图相对「刚好装下全图」的放大倍数）")
    if zoom["transition_ms"] < 0:
        _fail("zoom.transition_ms 不能为负")
    lcfg = cfg["layout"]
    if not isinstance(lcfg.get("leaf_radius"), (int, float)) or lcfg["leaf_radius"] <= 0:
        _fail("layout.leaf_radius 必须是正数（退化子树与孤点的兜底半径）")
    if not isinstance(lcfg.get("level_ratio"), (int, float)) or lcfg["level_ratio"] <= 1:
        _fail("layout.level_ratio 必须大于 1（父圆半径至少是最大子圆的这个倍数，"
              "否则独子链会塌成看不出父子关系的同心靶环）")
    if not isinstance(lcfg.get("padding"), (int, float)) or lcfg["padding"] < 1:
        _fail("layout.padding 必须 ≥ 1（父圆半径相对子圆包围圆的余量，小于 1 会让子圆溢出父圆）")
    if not isinstance(lcfg.get("size_exponent"), (int, float)) or not 0 < lcfg["size_exponent"] <= 1:
        _fail("layout.size_exponent 必须在 (0, 1] 之间（目标半径 ∝ 叶子数 ^ 此值；"
              "0.5 是无标度不动点，见 kg/layout.py 的推导）")
    if not isinstance(lcfg.get("norm_root_radius"), (int, float)) or lcfg["norm_root_radius"] <= 0:
        _fail("layout.norm_root_radius 必须是正数（虚拟根归一化后的半径，世界单位）")
    if zoom["home_fit"] > lcfg["padding"]:
        _fail(f"zoom.home_fit 不能超过 layout.padding（{lcfg['padding']}）—— "
              "home_fit 的硬上限就是 root_radius/root_enc = padding，"
              "再大会把最大的学科根裁出屏幕")
    lod = cfg.get("lod") or {}
    if not isinstance(lod.get("weak_edge_min_count"), int) or lod["weak_edge_min_count"] < 1:
        _fail("lod.weak_edge_min_count 必须是 ≥1 的整数")
    if not isinstance(lod.get("min_px"), (int, float)) or not lod["min_px"] > 0:
        _fail("lod.min_px 必须是正数（一个圆值得被画出来所需的最小屏幕半径）")
    if not isinstance(lod.get("label_alpha"), (int, float)) or not 0 < lod["label_alpha"] <= 1:
        _fail("lod.label_alpha 必须在 (0, 1] 之间（参与标签竞争所需的淡入进度）")
    if not isinstance(lod.get("fade_span"), (int, float)) or not lod["fade_span"] >= 1:
        _fail("lod.fade_span 必须是 ≥1 的倍率（1 = 硬切，不淡入）")
    for key in ("focus_edge_dim", "hover_edge_dim"):
        v = lod.get(key)
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            _fail(f"lod.{key} 必须在 [0, 1] 之间（0 = 完全不画无关连线，1 = 不压暗）")
    for name, color in cfg["theme"].get("domains", {}).items():
        if not _HEX_RE.match(str(color)):
            _fail(f"theme.domains[{name}] 颜色格式应为 #RRGGBB，收到 {color!r}")
    fallback = cfg["theme"].get("fallback", "#8B949E")
    if not _HEX_RE.match(str(fallback)):
        _fail(f"theme.fallback 颜色格式应为 #RRGGBB，收到 {fallback!r}")
    for name, color in cfg["theme"].get("edges", {}).items():
        if not _HEX_RE.match(str(color)):
            _fail(f"theme.edges.{name} 颜色格式应为 #RRGGBB，收到 {color!r}")


def load(path: str = "config.yaml") -> dict:
    """读取配置；path 相对于项目根目录（含本文件的上级目录）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    if not os.path.exists(path):
        raise ConfigError(f"找不到配置文件：{path}")
    with open(path, "r", encoding="utf-8-sig") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml 顶层必须是键值映射")

    cfg = _deep_merge(DEFAULTS, raw)
    _validate(cfg)

    vault = cfg["vault"]
    if not os.path.isabs(vault):
        vault = os.path.join(root, vault)
    vault = os.path.normpath(vault)
    if not os.path.isdir(vault):
        raise ConfigError(f"vault 目录不存在：{vault}")
    cfg["vault"] = vault
    cfg["root"] = root
    cfg["config_path"] = path
    if not cfg["vault_name"]:
        cfg["vault_name"] = os.path.basename(vault)
    cfg["attachments"] = {"." + e.lower().lstrip(".") for e in cfg["attachment_ext"]}
    return cfg


def rel(cfg: dict, *parts: str) -> str:
    """返回相对项目根目录的路径。"""
    return os.path.join(cfg["root"], *parts)


def warn(msg: str):
    print(f"[warn] {msg}", file=sys.stderr)
