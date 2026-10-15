"""config.yaml 的加载、默认值合并与校验。"""

from __future__ import annotations

import os
import re
import sys

import yaml

DEFAULTS: dict = {
    "vault": ".",
    "vault_name": "",
    # 范围三件套（include / exclude / exclude_notes）由 scope_file 解析而来，本文件不再手写。
    # include 默认空列表是刻意的：真源缺失时必须报错，而不是静默退回某个默认范围。
    "include": [],
    "exclude": [],
    "exclude_notes": [],
    # 公开范围真源：vault 里的 quartz-setup/public-scope.yaml。
    "scope_file": "",
    # 要构建哪个 scope；留空 = scopes 里的第一个。scopes 决定有哪些 scope、各自输出到哪。
    "scope": "",
    "scopes": {},
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
        "edge_trim_clearance": 2,
        "edge_marker_min_len": 20,
        "edge_marker_tint": 0.55,
        "raw_edge_width": 1.0,
        "raw_edge_spread": 5,
    },
    "theme": {"domains": {}, "fallback": "#8B949E", "edges": {}, "note_edge": "#E6EDF3"},
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
        _fail("zoom.zoom_in_ceiling 必须大于 1（它决定 zMax 地标：最挤节点完全浮现那一档。"
              "滚轮已不再被 zMax 夹住，但层级胶囊与 focusOn 的上界仍由它定）")
    if not isinstance(zoom.get("zoom_out_floor"), (int, float)) or zoom["zoom_out_floor"] < 1:
        _fail("zoom.zoom_out_floor 必须 ≥ 1（它决定 zMin 地标 = 最小学科根刚好完全浮现那一档。"
              "小于 1 会让最小的学科根在这一档跌破 lod.min_px，「缩到这一档看得见全部学科」"
              "这个地标含义就没了。注意滚轮本身已不再被 zMin 夹住，这条守的是地标值，不是滚轮）")
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
    for key in ("edge_trim_clearance", "edge_marker_min_len"):
        v = lod.get(key)
        if not isinstance(v, (int, float)) or v < 0:
            _fail(f"lod.{key} 不能为负（它是屏幕 px；edge_marker_min_len 填 0 = 不做长度守卫）")
    if not isinstance(lod.get("edge_marker_tint"), (int, float)) or not 0 <= lod["edge_marker_tint"] <= 1:
        _fail("lod.edge_marker_tint 必须在 [0, 1] 之间（0 = 端点标记与连线同色，1 = 纯浅灰）")
    if not isinstance(lod.get("raw_edge_width"), (int, float)) or not lod["raw_edge_width"] > 0:
        _fail("lod.raw_edge_width 必须是正数（非聚合模式下连线的固定屏幕线宽 px）")
    if not isinstance(lod.get("raw_edge_spread"), (int, float)) or lod["raw_edge_spread"] < 0:
        _fail("lod.raw_edge_spread 不能为负（它是屏幕 px；填 0 = 平行边不做扇形展开）")
    for name, color in cfg["theme"].get("domains", {}).items():
        if not _HEX_RE.match(str(color)):
            _fail(f"theme.domains[{name}] 颜色格式应为 #RRGGBB，收到 {color!r}")
    fallback = cfg["theme"].get("fallback", "#8B949E")
    if not _HEX_RE.match(str(fallback)):
        _fail(f"theme.fallback 颜色格式应为 #RRGGBB，收到 {fallback!r}")
    note_edge = cfg["theme"].get("note_edge", "#E6EDF3")
    if not _HEX_RE.match(str(note_edge)):
        _fail(f"theme.note_edge 颜色格式应为 #RRGGBB，收到 {note_edge!r}")
    for name, color in cfg["theme"].get("edges", {}).items():
        if not _HEX_RE.match(str(color)):
            _fail(f"theme.edges.{name} 颜色格式应为 #RRGGBB，收到 {color!r}")


SCOPE_SECTIONS = ("content", "assets")


def _read_scope_file(path: str) -> dict:
    """读取公开范围真源。任何问题都直接抛错 —— 范围定义坏掉时绝不能猜一个范围继续跑。"""
    if not os.path.exists(path):
        raise ConfigError(
            f"找不到公开范围真源：{path}\n"
            "（来自 config.yaml 的 scope_file，通常在 vault 的 quartz-setup/ 下）")
    with open(path, "r", encoding="utf-8-sig") as fh:
        doc = yaml.safe_load(fh) or {}
    if not isinstance(doc, dict):
        raise ConfigError(f"{path} 顶层必须是键值映射")
    for section in SCOPE_SECTIONS:
        value = doc.get(section)
        if value is not None and not isinstance(value, list):
            raise ConfigError(f"{path} 的 {section} 必须是列表")
    return doc


def _scope_entries(doc: dict, section: str, scope: str, path: str):
    """挑出某个 scope 在某 section 下的条目 → [(vault 路径, 落地名, 是否资源)]。"""
    out = []
    for item in doc.get(section) or []:
        if not isinstance(item, dict):
            raise ConfigError(f"{path} 的 {section} 每项必须是键值映射，收到 {item!r}")
        src = str(item.get("from") or "").strip().strip("/")
        if not src:
            raise ConfigError(f"{path} 的 {section} 里有缺 from 的条目")
        names = item.get("scopes")
        if not isinstance(names, list) or not names:
            raise ConfigError(f"{path}: {src} 没写 scopes（至少要写 public 或 private）")
        if scope not in names:
            continue
        # 没写 as 就用目录名落地 —— 和 robocopy 把 Logs/Study log 落到 content/Study log 一致
        dest = str(item.get("as") or src.rsplit("/", 1)[-1]).strip().strip("/")
        if not dest:
            raise ConfigError(f"{path}: {src} 的 as 不能为空")
        out.append((src, dest, section == "assets"))
    return out


def _resolve_scopes(cfg: dict, doc: dict, scope_path: str) -> dict:
    declared = cfg["scopes"]
    if not isinstance(declared, dict) or not declared:
        raise ConfigError("config.yaml 的 scopes 不能为空（它决定有哪几个 scope、各自输出到哪）")

    unknown = set()
    for section in SCOPE_SECTIONS:
        for item in doc.get(section) or []:
            names = item.get("scopes") if isinstance(item, dict) else None
            if isinstance(names, list):
                unknown |= {str(s) for s in names if str(s) not in declared}
    if unknown:
        raise ConfigError(f"{scope_path} 用到了 config.yaml 未声明的 scope：{sorted(unknown)}")

    vault = cfg["vault"]
    scopes = {}
    for name, spec in declared.items():
        spec = spec if isinstance(spec, dict) else {}
        entries = (_scope_entries(doc, "content", name, scope_path)
                   + _scope_entries(doc, "assets", name, scope_path))
        include, remap, mirror = [], [], []
        seen = set()
        for src, dest, is_asset in entries:
            if not os.path.isdir(os.path.join(vault, src)):
                raise ConfigError(f"{scope_path}: 目录不存在 —— {src}")
            if dest in seen:
                raise ConfigError(f"{scope_path}: {name} 的落地名重复：{dest}")
            seen.add(dest)
            mirror.append({"from": src, "to": dest})
            if is_asset:
                continue        # 资源只镜像，不进图谱
            include.append(f"{src}/**")
            if src != dest:
                # vault 路径前缀 ≠ 落地名 → 图谱里也按落地名建根，避免多一层包装目录
                remap.append({"from": src, "to": dest})
        if not include:
            raise ConfigError(f"{scope_path}: scope「{name}」没有命中任何内容目录")
        output = dict(spec.get("output") or {})
        output.setdefault("json", f"dist/graph.{name}.json")
        output.setdefault("html", f"dist/knowledge-graph.{name}.html")
        scopes[name] = {
            "name": name,
            "include": include,
            "exclude": list(doc.get("exclude") or []),
            "exclude_notes": list(doc.get("exclude_notes") or []),
            "remap": remap,
            "mirror": mirror,
            # 这个 scope 在图上的顶层根名（= 落地名），供 verify 断言「没有越界的节点」
            "roots": [dest for (_src, dest, is_asset) in entries if not is_asset],
            # 图谱 HTML 要不要真的发到站点上（约 8 MB/次，见 public-scope.yaml 的说明）
            "publish_graph": bool(doc.get("publish_graph", False)),
            "output": output,
        }
    return scopes


def load(path: str = "config.yaml", scope: str = "") -> dict:
    """读取配置并解析公开范围；path 相对项目根目录（含本文件的上级目录）。

    scope 留空时取 scopes 里的第一个。返回的 cfg 中 include / exclude / exclude_notes /
    remap / output 已是「当前 scope」的值，所以 scan / layout / emit / verify 都不需要
    知道 scope 的存在；全部 scope 的定义留在 cfg["scopes"] 里。
    """
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

    vault = cfg["vault"]
    if not os.path.isabs(vault):
        vault = os.path.join(root, vault)
    vault = os.path.normpath(vault)
    if not os.path.isdir(vault):
        raise ConfigError(f"vault 目录不存在：{vault}")
    cfg["vault"] = vault
    cfg["root"] = root
    cfg["config_path"] = path

    scope_path = cfg["scope_file"]
    if not scope_path:
        raise ConfigError("config.yaml 缺少 scope_file —— 公开范围必须来自 vault 里的 "
                          "quartz-setup/public-scope.yaml，不在这里另写一份")
    if not os.path.isabs(scope_path):
        scope_path = os.path.join(root, scope_path)
    cfg["scope_file_path"] = os.path.normpath(scope_path)
    cfg["scopes"] = _resolve_scopes(cfg, _read_scope_file(cfg["scope_file_path"]),
                                    cfg["scope_file_path"])

    want = scope or cfg["scope"] or next(iter(cfg["scopes"]))
    if want not in cfg["scopes"]:
        raise ConfigError(f"未知的 scope「{want}」，可选：{', '.join(cfg['scopes'])}")
    active = cfg["scopes"][want]
    cfg["scope"] = want
    cfg["scope_names"] = list(cfg["scopes"])
    for key in ("include", "exclude", "exclude_notes", "remap", "roots", "output",
                "mirror", "publish_graph"):
        cfg[key] = active[key]

    if not cfg["vault_name"]:
        cfg["vault_name"] = os.path.basename(vault)
    cfg["attachments"] = {"." + e.lower().lstrip(".") for e in cfg["attachment_ext"]}
    _validate(cfg)
    return cfg


def rel(cfg: dict, *parts: str) -> str:
    """返回相对项目根目录的路径。"""
    return os.path.join(cfg["root"], *parts)


def warn(msg: str):
    print(f"[warn] {msg}", file=sys.stderr)
