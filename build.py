#!/usr/bin/env python3
"""知识笔记语义缩放可视化系统 —— 命令行入口。

    python build.py scan       扫描 vault，打印纳入/排除与链接统计
    python build.py suggest    挖掘候选边 → candidates.yaml
    python build.py build      生成 dist/graph.json 与单文件 HTML
    python build.py watch      笔记改动后自动重建
    python build.py verify     跑自动校验
    python build.py all        scan + suggest + build
"""

from __future__ import annotations

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


from kg.ioutils import setup_stdout

setup_stdout()

import yaml

from kg import candidates as cand_mod
from kg import config as config_mod
from kg import emit, graph, layout, parse, scan


def _bar(label, count, total, width=24):
    filled = int(width * count / max(total, 1))
    return f"  {label:<12} {'█' * filled}{'·' * (width - filled)} {count}"


def load_pipeline(cfg, quiet=False, need_text=True):
    notes, folders, stats = scan.scan(cfg)
    parsed = []
    total = len(notes)
    for i, note in enumerate(notes, 1):
        parsed.append(parse.parse_note(note, cfg["attachments"]))
        if not quiet and (i % 25 == 0 or i == total):
            print(f"\r  解析笔记 {i}/{total}", end="", flush=True)
    if not quiet and total:
        print("\r" + " " * 40 + "\r", end="")
    return parsed, folders, stats


def load_annotations(cfg):
    path = os.path.join(cfg["root"], cfg["annotations"])
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        return yaml.safe_load(fh) or {}


def build_payload(cfg, quiet=False):
    parsed, folders, stats = load_pipeline(cfg, quiet=quiet)
    annotations = load_annotations(cfg)
    cand_doc = cand_mod.load(cfg)

    builder = graph.GraphBuilder(cfg, parsed, folders)
    builder.build_nodes(annotations)
    builder.build_heading_nodes()        # 必须早于 build_wiki_edges：标题要先成为节点
    builder.build_contains()
    builder.build_wiki_edges()
    builder.build_frontmatter_edges()
    builder.build_annotation_edges(annotations)
    builder.build_candidate_edges(cand_doc)

    max_depth = max((n["depth"] for n in builder.nodes.values()), default=stats["max_depth"])
    rings, enter, home_layer = layout.compute(builder.nodes, cfg, max_depth)
    aggregates = builder.build_aggregates(max_depth)
    levels = builder.levels_table(aggregates)

    nodes = []
    by_kind = {"folder": 0, "note": 0, "heading": 0}
    for node in builder.nodes.values():
        item = dict(node)
        item.pop("aliases", None)
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
        nodes.append(item)

    meta = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "vault": cfg["vault"],
        "vault_name": cfg["vault_name"],
        "note_count": by_kind["note"],
        "folder_count": by_kind["folder"],
        "heading_count": by_kind["heading"],
        "node_count_by_kind": by_kind,
        "max_depth": max_depth,           # 深度轴已含标题层
        "file_depth": stats["max_depth"],  # 文件系统本身的深度（不含标题）
        "layer_count": len(rings),
        "zoom": cfg["zoom"],
        "lod": dict(cfg.get("lod", {}),
                    enter=[round(v, 6) for v in enter],
                    home_layer=home_layer),
        "theme": cfg["theme"],
        "page_title": cfg.get("page_title") or "知识图谱",
        "scan": stats,
        "link_stats": dict(sorted(builder.stats.items())),
        "unresolved": sorted(builder.unresolved.items(), key=lambda kv: -kv[1])[:50],
        "heading_total": by_kind["heading"],
        "heading_link_total": len(builder.heading_links),
        "precedence": cfg["precedence"],
    }
    payload = {
        "meta": meta,
        "nodes": nodes,
        "edges": builder.edges,
        "aggregates": aggregates,
        "rings": rings,
        "heading_links": builder.heading_links,
        "levels": levels,
    }
    return payload, builder


# ── 子命令 ──────────────────────────────────────────────────────────────
def cmd_scan(cfg, args):
    parsed, folders, stats = load_pipeline(cfg)
    builder = graph.GraphBuilder(cfg, parsed, folders)
    builder.build_nodes(load_annotations(cfg))
    builder.build_heading_nodes()
    builder.build_contains()
    builder.build_wiki_edges()

    total_links = sum(len(n.links) for n in parsed)
    resolved = builder.stats["wiki_edges_raw"]
    attachments = builder.stats["attachment_links"]
    unresolved = builder.stats["unresolved_links"]
    headings = sum(len(n.headings) for n in parsed)
    headingless = [n.file.stem for n in parsed if not n.headings]
    fm_notes = [n.file.stem for n in parsed if n.frontmatter]

    print(f"\n配置：{cfg['config_path']}")
    print(f"Vault：{cfg['vault']}")
    print(f"\n[公开范围]  vault 内 .md 共 {stats['vault_md_total']} 篇，"
          f"纳入 {stats['included']} 篇，排除 {stats['excluded']} 篇")
    print(f"[层级]      文件夹 {stats['folders']} 个，最大深度 {stats['max_depth']}")
    print(f"[深度分布]  笔记所在层：{stats['depth_histogram']}")
    print(f"\n[链接]      [[链接]] 总数 {total_links}")
    print(_bar("附件链接", attachments, total_links))
    print(_bar("笔记→笔记", resolved, total_links))
    print(_bar("自链接", builder.stats["self_links"], total_links))
    print(_bar("解析失败", unresolved, total_links))
    if builder.unresolved:
        print("  解析失败明细：")
        for target, count in sorted(builder.unresolved.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    ×{count}  {target}")
    print(f"\n[标题]      共 {headings} 个，平均 {headings / max(len(parsed), 1):.1f} 个/篇")
    if headingless:
        print(f"  无标题笔记 {len(headingless)} 篇：{'、'.join(headingless[:10])}")
    print(f"[frontmatter] {len(fm_notes)} 篇带有 frontmatter"
          + (f"：{'、'.join(fm_notes[:5])}" if fm_notes else "（数据模型为空，走自动推断）"))
    ann = load_annotations(cfg)
    print(f"[标注]      annotations.yaml：{len((ann.get('notes') or {}))} 篇笔记，"
          f"{len((ann.get('edges') or []))} 条边")
    print()
    return 0


def cmd_suggest(cfg, args):
    parsed, folders, stats = load_pipeline(cfg)
    builder = graph.GraphBuilder(cfg, parsed, folders)
    builder.build_nodes(load_annotations(cfg))
    builder.build_heading_nodes()
    builder.build_contains()
    builder.build_wiki_edges()
    builder.build_annotation_edges(load_annotations(cfg))
    existing = {(e["s"], e["t"]) for e in builder.edges if e["origin"] != "hierarchy"}

    found = cand_mod.collect(cfg, parsed, existing)
    preserved = cand_mod.preserved_statuses(cfg)
    kept = 0
    for item in found:
        key = (item["source"], item["target"], item["type"])
        if key in preserved:
            if preserved[key] != "pending":
                kept += 1
            item["status"] = preserved[key]
    path = cand_mod.write(cfg, found)
    print(f"\n候选边 {len(found)} 条 → {path}")
    if kept:
        print(f"  保留了 {kept} 条既有审核结果")
    print(f"  已有语义边（作为已知关系剔除）：{len(existing)} 条")
    print("\n  得分最高的 8 条：")
    for item in found[:8]:
        print(f"    {item['score']:.2f}  {item['source'].rsplit('/', 1)[-1]}"
              f" --{item['type']}--> {item['target'].rsplit('/', 1)[-1]}")
        print(f"          {item['reason']}")
    print("\n  审核方式：把想保留的条目 status 改成 accepted，然后 python build.py build\n")
    return 0


def cmd_build(cfg, args):
    payload, builder = build_payload(cfg)
    json_path = emit.write_json(cfg, payload)
    html_path = emit.build_html(cfg, payload)
    meta = payload["meta"]
    print(f"\n文件夹 {meta['folder_count']} 个 / 笔记 {meta['note_count']} 篇 / "
          f"标题 {meta['heading_count']} 个  →  共 {len(payload['nodes'])} 个节点")
    print(f"深度轴 {meta['max_depth']} 层"
          f"（文件系统本身 {meta['file_depth']} 层 + 标题层级）")
    contains = sum(1 for e in payload["edges"] if e["type"] == "contains")
    print(f"语义边 {len(payload['edges']) - contains} 条 / 层级包含边 {contains} 条")
    print(f"标题级链接 {meta['heading_link_total']} 处"
          f"（锚点未命中 {meta['link_stats'].get('heading_anchor_miss', 0)} 处）")
    print("\n各层可见内容（r = 该圈布局半径，世界单位）：")
    radius_of = {r["depth"]: r["radius"] for r in payload["rings"]}
    for budget, row in sorted(payload["levels"].items(), key=lambda kv: int(kv[0])):
        print(f"  depth≤{int(budget):<3} r={radius_of.get(int(budget), 0):>8.0f}"
              f"   {row['folders']:>3} 夹 + {row['notes']:>3} 笔记 + {row['headings']:>4} 标题"
              f"  →  {row['edges']:>5} 条边（语义 {row['semantic_edges']}）")
    print(f"\nJSON   {json_path}")
    print(f"HTML   {html_path}  ({os.path.getsize(html_path) / 1024:.0f} KB)")
    print("       双击打开即可，无需服务器、无需联网\n")
    return 0


def cmd_verify(cfg, args):
    import verify
    return verify.main(cfg)


def cmd_watch(cfg, args):
    def snapshot():
        state = {}
        for root, dirs, files in os.walk(cfg["vault"]):
            dirs[:] = [d for d in dirs if d not in scan.SKIP_DIRS and not d.startswith(".")]
            for name in files:
                if name.lower().endswith(".md"):
                    path = os.path.join(root, name)
                    try:
                        state[path] = os.path.getmtime(path)
                    except OSError:
                        pass
        for extra in (cfg["config_path"],
                      os.path.join(cfg["root"], cfg["annotations"]),
                      os.path.join(cfg["root"], cfg["candidates_file"])):
            if os.path.exists(extra):
                state[extra] = os.path.getmtime(extra)
        return state

    print("监听中（Ctrl+C 退出）：笔记 / config / annotations / candidates 任一改动即重建")
    last = snapshot()
    cmd_build(cfg, args)
    try:
        while True:
            time.sleep(2)
            current = snapshot()
            if current != last:
                last = current
                print(f"\n[{time.strftime('%H:%M:%S')}] 检测到改动，重建…")
                try:
                    cmd_build(cfg, args)
                except Exception:                     # noqa: BLE001 - watch 模式不退出
                    traceback.print_exc()
    except KeyboardInterrupt:
        print("\n已停止监听")
    return 0


COMMANDS = {
    "scan": cmd_scan,
    "suggest": cmd_suggest,
    "build": cmd_build,
    "verify": cmd_verify,
    "watch": cmd_watch,
}


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    command = args[0] if args else "scan"
    if command not in COMMANDS and command != "all":
        print(__doc__)
        return 2
    try:
        cfg = config_mod.load()
    except config_mod.ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2
    if command == "all":
        cmd_scan(cfg, args)
        cmd_suggest(cfg, args)
        return cmd_build(cfg, args)
    return COMMANDS[command](cfg, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
