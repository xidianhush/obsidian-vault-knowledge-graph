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
        "home_level": 2,
        "home_band": 0.5,
    },
    "weight": {
        "wiki_link": 1.0,
        "heading_link_bonus": 0.5,
        "embed_factor": 0.6,
        "annotation_default": 3.0,
    },
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
        "focus_edge_dim": 0.07,
        "hover_edge_dim": 0.75,
        "idle_edge_dim": 0.45,
        "edge_trim_clearance": 2,
        "edge_marker_tint": 0.55,
        "raw_edge_width": 1.0,
        "raw_marker_min_len": 6,
        "ghost_alpha": 0.10,
        "ghost_label_alpha": 0.14,
        "ghost_label_min_px": 56,
        # 2026-10-24 阶段 0.1：下面四个键原来只存在于作者的 config.yaml 里，DEFAULTS 没有，
        # 于是「一份最小配置」（别人的 vault / fixture）会在 _validate 里直接报
        # 「lod.label_font_scale 必须是正数，收到 None」——默认值必须自洽到能跑。
        # ⚠️ 必须**追加在 lod 末尾**：_deep_merge 先放 DEFAULTS 的键、再把 config 独有的键
        # 追加在后，插在中间会改变 payload 里 lod 的键序（JSON 语义相同，但会让产物 diff 变脏）。
        "label_font_min": 11,
        "label_font_max": 64,
        "label_font_scale": 0.3,
        "label_bold_depth": 2,
    },
    # Obsidian 式预览 / 第 11 带「链接带」（2026-10-22 第三轮）。
    # 关掉它 = 完全回到「到第 10 带为止」：payload 不存预览 HTML、lod 里没有 links。
    "preview": {
        "enabled": True,
        "max_note_chars": 0,   # 0 = 不截断（预览是整篇笔记，用户口径）
    },
    "theme": {"domains": {}, "fallback": "#8B949E",
              "raw_edge": "#E6EDF3", "edge_color": "domain", "edge_tint": 0.52,
              # 2026-10-24 阶段 1.3：自动色板参数（不写 = 用 kg/palette.py 的默认值）
              "auto_palette": None},
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
    # 2026-10-24：节点的「掌握度 / 重要度」这一层标注已删（见 HANDOFF 坑 42），
    # precedence 只服务它们，随之下岗。见到就报错，不静默忽略。
    if "precedence" in cfg:
        _fail("precedence 已退役（2026-10-24 起不再有「掌握度 / 重要度」节点标注，"
              "annotations.yaml 只保留 aliases 与手工边），请删掉这个键")
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
    hl = zoom.get("home_level")
    if not isinstance(hl, int) or isinstance(hl, bool) or hl < 1:
        _fail(f"zoom.home_level 必须是 ≥1 的整数（初始视图停在第几层，默认 2），收到 {hl!r}")
    hb = zoom.get("home_band")
    if not isinstance(hb, (int, float)) or isinstance(hb, bool) or not 0 <= hb <= 1:
        _fail(f"zoom.home_band 必须在 [0, 1] 之间（home 落在该层淡入带的哪个位置），收到 {hb!r}")
    if zoom["transition_ms"] < 0:
        _fail("zoom.transition_ms 不能为负")
    pv = cfg.get("preview") or {}
    if not isinstance(pv, dict):
        _fail("preview 必须是字典（Obsidian 式预览 / 第 11 带「链接带」的开关组）")
    if not isinstance(pv.get("enabled"), bool):
        _fail(f"preview.enabled 必须是布尔值（默认 true），收到 {pv.get('enabled')!r}")
    mc = pv.get("max_note_chars", 0)
    if not isinstance(mc, int) or isinstance(mc, bool) or mc < 0:
        _fail(f"preview.max_note_chars 必须是 ≥0 的整数（0 = 整篇不截断），收到 {mc!r}")
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
    # 2026-10-24：聚合边模式已删，只保留「逐条链接」。这两个键只服务聚合边，
    # 直接报错而不是静默忽略 —— 免得有人改了它们却以为生效了。
    for retired in ("weak_edge_min_count", "edge_marker_min_len", "links"):
        if retired in lod:
            _fail(f"lod.{retired} 已退役（2026-10-24 起只有逐条链接一种画法："
                  f"端点标记门槛用 lod.raw_marker_min_len），请删掉这个键")
    if not isinstance(lod.get("min_px"), (int, float)) or not lod["min_px"] > 0:
        _fail("lod.min_px 必须是正数（一个圆值得被画出来所需的最小屏幕半径）")
    if not isinstance(lod.get("label_alpha"), (int, float)) or not 0 < lod["label_alpha"] <= 1:
        _fail("lod.label_alpha 必须在 (0, 1] 之间（参与标签竞争所需的淡入进度）")
    # 2026-10-21：标签一律画在圆内、字号跟着圆长大，下面三个键随之退役。
    # 直接报错而不是静默忽略 —— 免得有人改了它们却以为生效了。
    for retired in ("label_font_ref", "label_max_width", "label_smooth_dim"):
        if retired in lod:
            _fail(f"lod.{retired} 已退役（2026-10-21 起标签只画在圆内、字号 = "
                  f"label_font_scale × 屏幕半径 与「塞进圆的最大字号」取小），请删掉这个键")
    scale = lod.get("label_font_scale")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not scale > 0:
        _fail(f"lod.label_font_scale 必须是正数（字号 / 屏幕半径 的比例，默认 0.3），收到 {scale!r}")
    fs_min, fs_max = lod.get("label_font_min"), lod.get("label_font_max")
    if not isinstance(fs_min, (int, float)) or isinstance(fs_min, bool) or fs_min <= 0:
        _fail(f"lod.label_font_min 必须是正数，收到 {fs_min!r}")
    if not isinstance(fs_max, (int, float)) or isinstance(fs_max, bool) or fs_max < fs_min:
        _fail(f"lod.label_font_max 必须 ≥ label_font_min，收到 {fs_max!r}")
    if not isinstance(lod.get("fade_span"), (int, float)) or not lod["fade_span"] >= 1:
        _fail("lod.fade_span 必须是 ≥1 的倍率（1 = 硬切，不淡入）")
    for key in ("focus_edge_dim", "hover_edge_dim", "idle_edge_dim"):
        v = lod.get(key)
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            _fail(f"lod.{key} 必须在 [0, 1] 之间（0 = 完全不画无关连线，1 = 不压暗）")
    for key in ("edge_trim_clearance", "raw_marker_min_len"):
        v = lod.get(key)
        if not isinstance(v, (int, float)) or v < 0:
            _fail(f"lod.{key} 不能为负（它是屏幕 px；raw_marker_min_len 填 0 = 恒画标记）")
    if not isinstance(lod.get("edge_marker_tint"), (int, float)) or not 0 <= lod["edge_marker_tint"] <= 1:
        _fail("lod.edge_marker_tint 必须在 [0, 1] 之间（0 = 端点标记与连线同色，1 = 纯浅灰）")
    if not isinstance(lod.get("raw_edge_width"), (int, float)) or not lod["raw_edge_width"] > 0:
        _fail("lod.raw_edge_width 必须是正数（连线线的固定屏幕线宽 px）")
    # 2026-10-24 视觉改版：ghost 下一层（纯视觉景深，不参与 LOD / 命中 / 标签竞争）
    for key in ("ghost_alpha", "ghost_label_alpha"):
        v = lod.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1:
            _fail(f"lod.{key} 必须在 [0, 1] 之间（0 = 关闭 ghost / 不画 ghost 文字），收到 {v!r}")
    if not isinstance(lod.get("ghost_label_min_px"), (int, float)) or lod["ghost_label_min_px"] < 0:
        _fail(f"lod.ghost_label_min_px 必须是 ≥0 的像素值，收到 {lod.get('ghost_label_min_px')!r}")
    for name, color in cfg["theme"].get("domains", {}).items():
        if not _HEX_RE.match(str(color)):
            _fail(f"theme.domains[{name}] 颜色格式应为 #RRGGBB，收到 {color!r}")
    fallback = cfg["theme"].get("fallback", "#8B949E")
    if not _HEX_RE.match(str(fallback)):
        _fail(f"theme.fallback 颜色格式应为 #RRGGBB，收到 {fallback!r}")
    # 2026-10-24 阶段 1.3：自动色板参数（可选）。写坏了会在构建期直接报错，不静默取默认。
    auto = cfg["theme"].get("auto_palette")
    if auto is not None:
        if not isinstance(auto, dict):
            _fail("theme.auto_palette 必须是键值映射（hue_start / saturation / lightness / "
                  "golden_angle / min_hue_gap），不写 = 用 kg/palette.py 的默认值")
        for key, lo, hi in (("hue_start", 0, 360), ("saturation", 0, 1),
                            ("lightness", 0, 1), ("golden_angle", 0, 360),
                            ("min_hue_gap", 0, 180)):
            if key in auto:
                v = auto[key]
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                    _fail(f"theme.auto_palette.{key} 必须在 [{lo}, {hi}] 之间，收到 {v!r}")
    if "note_edge" in cfg["theme"]:
        _fail("theme.note_edge 已改名为 theme.raw_edge（2026-10-20 起 raw 模式统一配色，"
              "不再按整篇级/标题级分色），请把 config.yaml 里的键改名")
    raw_edge = cfg["theme"].get("raw_edge", "#E6EDF3")
    if not _HEX_RE.match(str(raw_edge)):
        _fail(f"theme.raw_edge 颜色格式应为 #RRGGBB，收到 {raw_edge!r}")
    # 2026-10-24 视觉改版：链接默认按**学科色**着色（同域同色、跨域两端渐变）。
    # edge_color = "flat" 退回旧的「所有链接统一近白」。
    ec = cfg["theme"].get("edge_color", "domain")
    if ec not in ("domain", "flat"):
        _fail(f"theme.edge_color 只能是 'domain'（按学科色，默认）或 'flat'（统一近白），收到 {ec!r}")
    et = cfg["theme"].get("edge_tint", 0.62)
    if not isinstance(et, (int, float)) or isinstance(et, bool) or not 0 <= et <= 1:
        _fail(f"theme.edge_tint 必须在 [0, 1] 之间（学科色向白提亮的比例），收到 {et!r}")
    # 2026-10-24：只有逐条链接一种画法，按关系类型分色的 theme.edges 随之退役
    #（关系类型仍由线型与端点标记表达）。
    if "edges" in cfg["theme"]:
        _fail("theme.edges 已退役（2026-10-24 起链接统一按学科色 / theme.raw_edge 配色，"
              "关系类型改由线型与端点标记表达），请删掉这个键")


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


def _contains_md(root: str, limit: int = 20000) -> bool:
    """目录里（递归）有没有 .md —— 只用来判断「这是不是内容根」，不读内容。"""
    seen = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.lower().endswith(".md"):
                return True
        seen += len(files)
        if seen > limit:
            return False
    return False


def _derive_roots(include: list, vault: str) -> list:
    """从 include 通配符推 scope 的顶层根名（内联 scope 用）。

    "Science and Tech/**"  → "Science and Tech"
    "Logs/Study log/**"    → "Logs"     ← 节点 id 的第一段就是它，verify 按这个断「越界 0 个」
    "**" / "*"             → 没有写出具体目录：退化成「vault 顶层每个**含 .md 的**目录
                            各算一个根」+「vault 根下的 .md 各算一个根」
    """
    roots, whole = [], False
    for pattern in include:
        p = str(pattern).strip().strip("/")
        for suffix in ("/**/*", "/**", "/*"):
            if p.endswith(suffix):
                p = p[: -len(suffix)].strip("/")
                break
        if not p or any(ch in p for ch in "*?["):
            whole = True
            continue
        roots.append(p.split("/")[0])
    if whole:
        # 阶段 0.3：只把「真的含 .md」的目录算成内容根。原来无脑把 vault 顶层每个目录都
        # 算进去，于是 Attachment/ 这类附件目录也成了「声明的学科」，verify 的
        # 「depth1 根 == scope 声明」就假红（heading-zoo fixture 实测）。
        for name in sorted(os.listdir(vault)):
            if name.startswith("."):
                continue
            full = os.path.join(vault, name)
            if os.path.isdir(full):
                if _contains_md(full):
                    roots.append(name)
            elif name.lower().endswith(".md"):
                # 根笔记：vault 根下直接放的笔记自身也是内容根（tiny fixture 实测）
                roots.append(os.path.splitext(name)[0])
    return sorted({r for r in roots if r})


def _resolve_inline_scopes(cfg: dict) -> dict:
    """没有 scope_file 时的退路：scope 直接写在 config.yaml 里。

    2026-10-24（阶段 0.1「任意 vault 能跑」）：原来范围只能来自 vault 里那份 Quartz 格式
    的 public-scope.yaml，别人的库没有这个文件就跑不起来。现在两种都行：
      * 有 scope_file → 走 _resolve_scopes（作者自己的工作流，行为一字不变）；
      * 没有 scope_file → 走这里：每个 scope 至少要给 include，roots 缺省从 include 推。
    """
    declared = cfg["scopes"]
    if not isinstance(declared, dict) or not declared:
        raise ConfigError(
            "config.yaml 既没有 scope_file，也没有 scopes —— 没有范围真源时至少要给一个"
            "内联 scope，例如：\n"
            "  scopes:\n"
            "    main:\n"
            "      include: [\"**\"]")
    single = len(declared) == 1
    scopes = {}
    for name, spec in declared.items():
        if spec is not None and not isinstance(spec, dict):
            raise ConfigError(f"config.yaml 的 scopes.{name} 必须是键值映射（内联 scope 定义）")
        spec = spec or {}
        include = list(spec.get("include") or cfg.get("include") or [])
        if not include:
            raise ConfigError(
                f"内联 scope「{name}」缺少 include —— 例如 include: [\"MyNotes/**\"]"
                f"（只要这个目录）或 [\"**\"]（整个 vault）")
        if not all(isinstance(p, str) and p.strip() for p in include):
            raise ConfigError(f"内联 scope「{name}」的 include 必须是非空字符串列表，收到 {include!r}")
        roots = spec.get("roots")
        if roots is None or roots == "auto":
            roots = _derive_roots(include, cfg["vault"])
        if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
            raise ConfigError(f"内联 scope「{name}」的 roots 必须是字符串列表或 \"auto\"，收到 {roots!r}")
        output = dict(spec.get("output") or {})
        output.setdefault("json", "dist/graph.json" if single else f"dist/graph.{name}.json")
        output.setdefault("html", "dist/knowledge-graph.html" if single
                         else f"dist/knowledge-graph.{name}.html")
        scopes[name] = {
            "name": name,
            "include": include,
            "exclude": list(spec.get("exclude") or cfg.get("exclude") or []),
            "exclude_notes": list(spec.get("exclude_notes") or cfg.get("exclude_notes") or []),
            "remap": list(spec.get("remap") or []),
            "mirror": [],
            "roots": list(roots),
            "publish_graph": False,
            "output": output,
        }
    return scopes


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

    **路径语义（2026-10-24 阶段 0.1 起）**：`config.yaml` 里写的一切相对路径都相对
    **配置文件所在目录**（`vault` / `scope_file` / `output` / `annotations` /
    `candidates_file`）；只有 `web/*.js`、`web/template.html` 这类前端资源仍相对
    项目目录（`cfg["root"]`），因为它们属于程序而不是某个 vault。
    主配置在项目根目录，所以这条改动对现有工作流**零影响**；但它让 fixture 的
    config 可以自包含（fixtures/vault-x/config.yaml + 自己的 dist/ + 自己的空 annotations）。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise ConfigError(f"找不到配置文件：{path}")
    with open(path, "r", encoding="utf-8-sig") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml 顶层必须是键值映射")

    cfg = _deep_merge(DEFAULTS, raw)
    config_dir = os.path.dirname(path)

    vault = cfg["vault"]
    if not os.path.isabs(vault):
        vault = os.path.join(config_dir, vault)
    vault = os.path.normpath(vault)
    if not os.path.isdir(vault):
        raise ConfigError(f"vault 目录不存在：{vault}")
    cfg["vault"] = vault
    cfg["root"] = root                 # 程序目录（web/ 资源）
    cfg["config_dir"] = config_dir     # 配置文件目录（配置里的所有相对路径）
    cfg["config_path"] = path

    scope_path = cfg["scope_file"]
    if scope_path:
        if not os.path.isabs(scope_path):
            scope_path = os.path.join(config_dir, scope_path)
        cfg["scope_file_path"] = os.path.normpath(scope_path)
        cfg["scope_source"] = "scope_file"
        cfg["scopes"] = _resolve_scopes(cfg, _read_scope_file(cfg["scope_file_path"]),
                                        cfg["scope_file_path"])
    else:
        # 2026-10-24 阶段 0.1：没有 Quartz 真源也能跑（别人的 vault 没有 quartz-setup/）
        cfg["scope_file_path"] = ""
        cfg["scope_source"] = "inline"
        cfg["scopes"] = _resolve_inline_scopes(cfg)

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
