"""形状 sweep：把 8 个 fixture 逐个 build → verify →（可选）browser_check，按 manifest 判定。

**为什么要有它**：单个库的回归（作者库 110 ok / 132 / 133）只能证明「作者这个库没坏」。
这个 runner 证明的是「**别人的库**能不能用、红的是产品缺陷还是已知局限」。

用法：
    python fixtures/run_sweep.py                  # 全部 fixture：build + verify（不含浏览器）
    python fixtures/run_sweep.py --only plain,tiny
    python fixtures/run_sweep.py --browser        # 加上 browser_check（每库约 3 分钟，需 Chrome）
    python fixtures/run_sweep.py --update-manifest # 把实测 ok 数回填 manifest 的 expected_ok
    python fixtures/run_sweep.py --no-build       # 复用已有 dist（只验）

判红规则（对应 PLAN_APPLICABILITY.md §6 的三条硬闸）：
  1. **canary 不一致** → 红。人口对不上说明 fixture 或管线变了，「没有东西可坏」会变假绿。
  2. **ok 数 != manifest.expected_ok** → 红（expected_ok 为 null 时算「待标定」，不计红）。
     少跑几条和全跑过在输出上必须长得不一样 —— 这是本 runner 存在的首要理由。
  3. **FAIL > 0** → 红。红项会与 manifest.known_gaps 并排打印，人工确认「对得上已知局限」。
  4. 身份闸由 verify / browser_check 自己断（payload 的 vault 必须等于 fixture 的 vault）。

⚠️ 必须跑在**完全权限**下：build 要写 fixtures/vaults/<name>/dist，browser_check 要起 Chrome。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

import yaml

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
KG = os.path.dirname(HERE)
VAULTS = os.path.join(HERE, "vaults")
MANIFEST = os.path.join(HERE, "manifest.yaml")
SHOTS = os.path.join(HERE, ".shots")
PY = sys.executable

VERIFY_RE = re.compile(r"^## VERIFY_RESULT (\{.*\})\s*$", re.M)
BROWSER_RE = re.compile(r"^## BROWSER_RESULT (\{.*\})\s*$", re.M)


def load_manifest() -> dict:
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _run(args, env=None, timeout=900):
    p = subprocess.run(args, cwd=KG, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def payload_stats(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    meta = d["meta"]
    contains = sum(1 for e in d["edges"] if e["type"] == "contains")
    return {
        "folders": meta["node_count_by_kind"]["folder"],
        "notes": meta["note_count"],
        "headings": meta["heading_count"],
        "semantic_edges": len(d["edges"]) - contains,
        "max_depth": meta["max_depth"],
        "node_count": len(d["nodes"]),
    }


def check_canary(canary: dict, stats: dict) -> list:
    """canary 里写了的键都要对上（支持 folders/notes/headings/semantic_edges/max_depth …）。"""
    bad = []
    for key, want in canary.items():
        if key not in stats:
            bad.append("%s: 未知的 canary 字段（stats 里有 %s）" % (key, ", ".join(sorted(stats))))
        elif want != stats[key]:
            bad.append("%s: 期望 %s 实际 %s" % (key, want, stats[key]))
    return bad


def _fmt_expected(vals: dict) -> str:
    parts = []
    if "verify" in vals:
        parts.append("verify: %d" % vals["verify"])
    if "browser" in vals:
        parts.append("browser: %d" % vals["browser"])
    return "{" + ", ".join(parts) + "}"


def _merge_expected(existing_line: str, vals: dict) -> str:
    """把新读数**合并进**已有值 —— 不带 --browser 跑一次不会把 browser 的标定抹掉。

    （2026-10-25 踩过：一次普通的 --update-manifest 把 tiny/wide-roots/hub-dense 的
    browser 期望值全清了，sweep 随后把「未标定」当 pending，等于静默丢标定。）
    """
    m = re.search(r"\{([^}]*)\}", existing_line)
    cur = {}
    if m:
        try:
            cur = yaml.safe_load("{" + m.group(1) + "}") or {}
        except yaml.YAMLError:
            cur = {}
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(vals)
    return _fmt_expected(cur)


def patch_expected_ok(path: str, vals: dict) -> None:
    """只改 `expected_ok:` 那一行，保留 manifest 里的全部注释。

    （用 yaml.safe_dump 重写会把 40 行注释抹掉 —— manifest 的注释就是判据说明，不能丢。）
    """
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    cur = None
    out = []
    for line in lines:
        m = re.match(r"^  ([A-Za-z0-9_\-]+):\s*$", line)
        if m:
            cur = m.group(1)
        if cur in vals and re.match(r"^\s+expected_ok:", line):
            pad = line[:len(line) - len(line.lstrip())]
            out.append(pad + "expected_ok: " + _merge_expected(line, vals[cur]))
            continue
        out.append(line)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")


def main(argv) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--only", default="", help="逗号分隔的 fixture 名")
    ap.add_argument("--browser", action="store_true", help="额外跑 browser_check（慢）")
    ap.add_argument("--no-build", action="store_true", help="跳过 build，复用已有 dist")
    ap.add_argument("--update-manifest", action="store_true", help="把实测 ok 数回填 manifest")
    args = ap.parse_args(argv[1:])

    doc = load_manifest()
    fixtures = doc.get("fixtures") or {}
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    names = [n for n in fixtures if not only or n in only]
    if not names:
        print("没有选中任何 fixture")
        return 2

    os.makedirs(SHOTS, exist_ok=True)
    rows, errors, pending = [], [], []
    new_expected = {}

    for name in names:
        spec = fixtures[name] or {}
        base = os.path.join(VAULTS, name)
        # manifest 里的 config 路径相对 fixtures/（例如 "vaults/tiny/config.yaml"）
        cfg = os.path.join(HERE, spec.get("config", os.path.join("vaults", name, "config.yaml")))
        vault = os.path.join(base, "vault")
        html = os.path.join(base, "dist", "graph.html")
        jpath = os.path.join(base, "dist", "graph.json")
        row = {"name": name, "build": "-", "verify": "-", "browser": "-",
               "canary": "-", "reds": []}

        if not os.path.exists(cfg):
            errors.append(f"{name}: 缺配置 {cfg}（先跑 python fixtures/make_vaults.py）")
            rows.append(row)
            continue

        # 1) build
        if not args.no_build:
            code, out = _run([PY, "build.py", "build", "--config", cfg])
            if code != 0:
                row["build"] = "FAIL(%d)" % code
                errors.append(f"{name}: build 失败 —— " + out.strip().splitlines()[-1][:120])
                rows.append(row)
                continue
        row["build"] = "ok"

        # 2) payload + canary
        if not os.path.exists(jpath):
            errors.append(f"{name}: 没有 {jpath}")
            rows.append(row)
            continue
        stats = payload_stats(jpath)
        bad = check_canary(spec.get("canary") or {}, stats)
        row["canary"] = "ok" if not bad else "MISMATCH"
        if bad:
            errors.append(f"{name}: canary 不一致 —— " + "；".join(bad))

        # 3) verify
        vcode, vout = _run([PY, "build.py", "verify", "--config", cfg])
        m = VERIFY_RE.search(vout)
        if not m:
            row["verify"] = "NO-RESULT"
            errors.append(f"{name}: verify 没有输出 ## VERIFY_RESULT（崩了？）"
                          + "  " + vout.strip().splitlines()[-1][:100])
        else:
            vres = json.loads(m.group(1))
            row["verify"] = "%d ok / %d FAIL" % (vres["ok"], vres["fail"])
            raw_exp = spec.get("expected_ok")
            expected = raw_exp.get("verify") if isinstance(raw_exp, dict) else raw_exp
            if expected is None:
                pending.append(name)
            elif vres["ok"] != expected:
                errors.append(f"{name}: verify ok 数漂移 —— 期望 {expected} 实际 {vres['ok']}"
                              "（用例被吞或新增；没标定就先 --update-manifest）")
            if vres["fail"]:
                row["reds"] = [l.strip() for l in vout.splitlines() if "[FAIL]" in l][:6]
            new_expected.setdefault(name, {})["verify"] = vres["ok"]

        # 4) browser（可选）
        if args.browser:
            env = dict(os.environ)
            env["KG_HTML"] = html
            env["KG_EXPECT_VAULT"] = vault
            env["KG_SHOT_DIR"] = os.path.join(SHOTS, name)
            os.makedirs(env["KG_SHOT_DIR"], exist_ok=True)
            bcode, bout = _run([PY, os.path.join(KG, "browser_check.py")], env=env, timeout=1200)
            mb = BROWSER_RE.search(bout)
            if not mb:
                row["browser"] = "NO-RESULT"
                errors.append(f"{name}: browser_check 没有输出 ## BROWSER_RESULT"
                              + "  " + bout.strip().splitlines()[-1][:100])
            else:
                bres = json.loads(mb.group(1))
                row["browser"] = "%d ok / %d FAIL / %d skip" % (
                    bres["ok"], bres["fail"], bres["skipped"])
                raw_exp_b = spec.get("expected_ok")
                expected_b = raw_exp_b.get("browser") if isinstance(raw_exp_b, dict) else None
                if expected_b is None:
                    pending.append(name + "(browser)")
                elif bres["ok"] != expected_b:
                    errors.append(f"{name}: browser ok 数漂移 —— 期望 {expected_b} 实际 {bres['ok']}")
                new_expected.setdefault(name, {})["browser"] = bres["ok"]
        rows.append(row)

    # ── 报表 ────────────────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print(f"{'fixture':<12} {'build':<9} {'canary':<9} {'verify':<17} {'browser':<16}")
    print("-" * 104)
    for r in rows:
        print(f"{r['name']:<12} {r['build']:<9} {r['canary']:<9} {r['verify']:<17} {r['browser']:<16}")
    print("=" * 104)

    for r in rows:
        if r["reds"]:
            print(f"\n{r['name']} 的红项：")
            for line in r["reds"]:
                print("  " + line)
            gaps = (fixtures.get(r["name"]) or {}).get("known_gaps") or []
            if gaps:
                print("  对应 manifest.known_gaps：")
                for g in gaps:
                    print("    · " + str(g)[:110])
            else:
                print("  ⚠ manifest 里没有 known_gaps —— 这条红必须当回归处理")

    if args.update_manifest and new_expected:
        patch_expected_ok(MANIFEST, new_expected)
        print("\n已回填 expected_ok → fixtures/manifest.yaml（注释保留）")

    summary = {"fixtures": len(names), "errors": errors, "pending": pending,
               "browser": args.browser}
    print("\n## SWEEP_RESULT " + json.dumps(summary, ensure_ascii=False))
    if errors:
        print("\n红项（%d）：" % len(errors))
        for e in errors:
            print("  - " + e)
        return 1
    if pending:
        print("\n有 %d 个读数待标定（expected_ok 为 null）：%s"
              % (len(pending), "、".join(pending)))
        print("标定方式：python fixtures/run_sweep.py --update-manifest")
    print("\n全部 fixture 的 canary 与 ok 数都对得上。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
