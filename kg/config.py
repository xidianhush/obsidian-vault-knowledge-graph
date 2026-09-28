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
        "parent_dim": 0.5,
        "wheel_sensitivity": 0.5,
        "transition_ms": 260,
        "min": 0.10,
        "max": 5.0,
        "zoom_in_ceiling": 1.35,
        "zoom_out_floor": 0.75,
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
    "layout": {"radius_step": 260, "start_angle": -90},
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
    if not isinstance(zoom.get("wheel_sensitivity"), (int, float)) or zoom["wheel_sensitivity"] <= 0:
        _fail("zoom.wheel_sensitivity 必须是正数")
    if not isinstance(zoom.get("zoom_in_ceiling"), (int, float)) or zoom["zoom_in_ceiling"] <= 1:
        _fail("zoom.zoom_in_ceiling 必须大于 1（它是顶层适配缩放的放大倍数上限）")
    if not isinstance(zoom.get("zoom_out_floor"), (int, float)) or not 0 < zoom["zoom_out_floor"] < 1:
        _fail("zoom.zoom_out_floor 必须在 (0, 1) 之间（它是深层适配缩放的收缩倍数下限）")
    if zoom["transition_ms"] < 0:
        _fail("zoom.transition_ms 不能为负")
    if zoom["max"] <= zoom["min"]:
        _fail("zoom.max 必须大于 zoom.min")
    if not isinstance(cfg["layout"].get("radius_step"), (int, float)) or cfg["layout"]["radius_step"] <= 0:
        _fail("layout.radius_step 必须是正数")
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
