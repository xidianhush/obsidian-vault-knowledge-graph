"""Browser-level verification of web/render.js + web/app.js.

Drives wheel / keyboard / click / search / filters against the built single-file
HTML and asserts the same LOD contract that verify.py proves on the data side,
plus regressions for the three bugs found by hand:
  A. camera tween never notified hooks.onCamera -> HUD stale after programmatic zoom
  B. fully empty viewport gave no feedback (concentric layout has an empty center)
  C. label gate read the parent_dim-dimmed alpha -> zero labels at every zoom level

Usage: pip install playwright, then `python browser_check.py` after a build.
Drives the installed Chrome (channel="chrome"); screenshots go to %TEMP%
(or $KG_SHOT_DIR) as kg_*.png for eyeballing.
"""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(ROOT, "dist", "knowledge-graph.html")
URL = "file:///" + HTML.replace("\\", "/")
SHOT = os.path.join(os.environ.get("KG_SHOT_DIR", tempfile.gettempdir()), "kg_%s.png")

STATE = "() => window.KG.state()"
DESC_COUNT = """(tgt) => {
    const R = window.KG.renderer;
    let n = 0;
    for (const x of R.NODES) {
        if (x.id === tgt) continue;
        if (R.alphaOf(x.id) <= 0.05) continue;
        let cur = x, guard = 0;
        while (cur && cur.parent && guard++ < 40) {
            if (cur.parent === tgt) { n++; break; }
            cur = R.byId.get(cur.parent);
        }
    }
    return n;
}"""
PICK_NODE = """(minDesc) => {
    const R = window.KG.renderer; const [W, H] = R.size();
    for (let y = H * 0.30; y < H * 0.72; y += 5) {
        for (let x = W * 0.28; x < W * 0.72; x += 5) {
            const n = R.hitTest(x, y);
            if (n && R.descOf(n.id) >= minDesc) return {id: n.id, x: x, y: y, d: R.descOf(n.id)};
        }
    }
    for (let y = H * 0.15; y < H * 0.85; y += 6) {
        for (let x = W * 0.10; x < W * 0.90; x += 6) {
            const n = R.hitTest(x, y);
            if (n) return {id: n.id, x: x, y: y, d: R.descOf(n.id)};
        }
    }
    return null;
}"""
PICK_EMPTY = """() => {
    const R = window.KG.renderer; const [W, H] = R.size();
    const cv = document.getElementById('cv'); const r = cv.getBoundingClientRect();
    const cand = [[W*0.5,H*0.93],[W*0.07,H*0.5],[W*0.93,H*0.5],[W*0.5,H*0.09]];
    for (let y = H*0.55; y < H*0.92; y += 6)
        for (let x = W*0.08; x < W*0.92; x += 6) cand.push([x, y]);
    for (const [x, y] of cand) {
        if (R.hitTest(x, y)) continue;
        if (document.elementFromPoint(r.left + x, r.top + y) !== cv) continue;
        return {x: r.left + x, y: r.top + y};
    }
    return null;
}"""

fails = []
warns = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("ok" if cond else "FAIL", name, ("  " + detail) if detail else ""))
    if not cond:
        fails.append(name + (" :: " + detail if detail else ""))


def shot(tag):
    page.screenshot(path=SHOT % tag)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    page = b.new_page(viewport={"width": 1440, "height": 900})
    perr, cerr = [], []
    page.on("pageerror", lambda e: perr.append(str(e)[:400]))
    page.on("console", lambda m: cerr.append(m.text[:400]) if m.type == "error" else None)

    page.goto(URL)
    page.wait_for_function("() => window.KG && window.KG.state && window.KG.renderer", timeout=60000)
    page.wait_for_timeout(1500)

    print("=== 1. load ===")
    check("no pageerror", not perr, "; ".join(perr[:3]))
    check("no console error", not cerr, "; ".join(cerr[:3]))

    size = page.evaluate("() => window.KG.renderer.size()")
    check("canvas has real size (not the 300x150 replaced-element default)",
          size[0] > 1000 and size[1] > 600, str(size))

    st = page.evaluate(STATE)
    print("   initial:", json.dumps({k: st[k] for k in
          ("zoom", "level", "shownNodes", "shownEdges", "shownLabels")}, ensure_ascii=False))
    nums = [v for v in st.values() if isinstance(v, (int, float))]
    check("no NaN in state", all(v == v and abs(v) != float("inf") for v in nums), str(nums))

    meta = page.evaluate("""() => ({
        zoomKeys: Object.keys(window.KG.data.meta.zoom),
        maxDepth: window.KG.data.meta.max_depth,
        enter: window.KG.data.meta.lod.enter,
        homeLayer: window.KG.data.meta.lod.home_layer,
        zMin: window.KG.zMin, zMax: window.KG.zMax, zHome: window.KG.zHome,
        nodeCount: window.KG.data.nodes.length})""")
    print("   ", json.dumps(meta, ensure_ascii=False)[:420])
    check("no zoom.min/max in payload", "min" not in meta["zoomKeys"] and "max" not in meta["zoomKeys"],
          str(meta["zoomKeys"]))
    check("initial level == home_layer", st["level"] == meta["homeLayer"],
          "%s vs %s" % (st["level"], meta["homeLayer"]))
    check("initial zoom == zHome", abs(st["zoom"] - meta["zHome"]) < 0.01,
          "%s vs %s" % (st["zoom"], meta["zHome"]))
    check("initial shownNodes in 150..350", 150 <= st["shownNodes"] <= 350, str(st["shownNodes"]))

    painted = page.evaluate("""() => {
        const cv = document.getElementById('cv'); const g = cv.getContext('2d');
        const d = g.getImageData(0, 0, cv.width, cv.height).data;
        let n = 0;
        for (let i = 0; i < d.length; i += 4 * 97) if (d[i] !== 15 || d[i+1] !== 17 || d[i+2] !== 22) n++;
        return n; }""")
    check("canvas painted (non-background samples)", painted > 50, "n=%d" % painted)

    # bug C: 标签门槛原来读 label_min_px/reveal，而祖先层被 parent_dim 压到 0.5，
    # 两个条件互相抵消 => shownLabels 恒为 0，整张地图一个文字都没有。
    check("home view has text labels", st["shownLabels"] > 0, str(st["shownLabels"]))

    print("\n=== 1b. label mode switch ===")
    page.evaluate("() => { window.KG.renderer.labelMode = 'off'; }")
    page.wait_for_timeout(400)
    off = page.evaluate(STATE)["shownLabels"]
    page.evaluate("() => { window.KG.renderer.labelMode = 'on'; }")
    page.wait_for_timeout(400)
    on = page.evaluate(STATE)["shownLabels"]
    page.evaluate("() => { window.KG.renderer.labelMode = 'auto'; }")
    page.wait_for_timeout(400)
    back = page.evaluate(STATE)["shownLabels"]
    print("    labels  auto=%d  off=%d  on=%d  back-to-auto=%d"
          % (st["shownLabels"], off, on, back))
    check("labelMode 'off' hides every label", off == 0, str(off))
    check("labelMode 'on' still produces labels", on > 0, str(on))
    check("labelMode 'auto' restored", back == st["shownLabels"], "%d vs %d" % (back, st["shownLabels"]))
    check("labels stay inside the per-frame budget", on <= 400, str(on))
    shot("01_home")

    print("\n=== 2. wheel down x20 -> zoom floor, only the 6 top disciplines left ===")
    page.mouse.move(720, 430)
    for _ in range(20):
        page.mouse.wheel(0, 100)
        page.wait_for_timeout(40)
    page.wait_for_timeout(400)
    out = page.evaluate(STATE)
    # state().zoom 只保留 3 位小数，判边界必须读未舍入的相机值
    camz = page.evaluate("() => window.KG.renderer.camera.zoom")
    print("   ", json.dumps({k: out[k] for k in ("zoom", "level", "shownNodes", "shownEdges")}, ensure_ascii=False))
    check("zoom hit floor", abs(camz - meta["zMin"]) < 1e-9,
          "%.8f vs zMin %.8f" % (camz, meta["zMin"]))
    check("level == 1 at floor", out["level"] == 1, str(out["level"]))
    check("shownNodes == 6 (top disciplines)", out["shownNodes"] == 6, str(out["shownNodes"]))
    check("the 6 top disciplines are labelled at the zoom floor",
          out["shownLabels"] >= 1, str(out["shownLabels"]))
    shot("02_zmin")

    print("\n=== 3. wheel up x40 -> zoom/level monotonic, reach max_depth and ceiling ===")
    ups, prev_z, prev_lv, z_mono, lv_mono = [], 0.0, 0, True, True
    for i in range(40):
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(38)
        s = page.evaluate(STATE)
        ups.append((round(s["zoom"], 4), s["level"], s["shownNodes"], s["shownEdges"], s["shownLabels"]))
        if s["zoom"] < prev_z - 1e-9:
            z_mono = False
        if s["level"] < prev_lv:
            lv_mono = False
        prev_z, prev_lv = s["zoom"], s["level"]
        if i in (0, 5, 9, 14, 19, 24, 29, 35, 39):
            print("    step %2d  zoom=%8.4f  level=%2d  nodes=%4d  edges=%3d  labels=%3d" % (i + 1, *ups[-1]))
        if i in (4, 13, 24, 39):
            shot("03_up%02d" % (i + 1))
    check("zoom monotonic increasing on wheel up", z_mono)
    check("level monotonic non-decreasing (direction lock)", lv_mono)
    check("reached max_depth %d" % meta["maxDepth"], prev_lv == meta["maxDepth"], str(prev_lv))
    check("zoom hit ceiling", prev_z >= meta["zMax"] * 0.999, "%.4f vs zMax %.4f" % (prev_z, meta["zMax"]))
    nanseen = [u for u in ups if any(v != v for v in u)]
    check("no NaN during 40 wheel steps", not nanseen, str(nanseen[:2]))
    nolabel = [u for u in ups if u[2] > 0 and u[4] == 0]
    check("labels never all vanish while nodes are on screen (was 0 at every zoom before)",
          not nolabel, str(nolabel[:3]))

    print("\n=== 3b. bug B: empty viewport must say so, not look broken ===")
    check("premise: viewport really is empty at the center of the rings",
          ups[-1][2] == 0, "shownNodes=%d" % ups[-1][2])
    px = page.evaluate("""() => {
        const cv = document.getElementById('cv'); const g = cv.getContext('2d');
        const [W, H] = window.KG.renderer.size(); const k = cv.width / W;
        const d = g.getImageData(Math.round(W/2*k), Math.round((H-46)/2*k), 1, 1).data;
        return [d[0], d[1], d[2]]; }""")
    check("hint text painted at screen center", px != [15, 17, 22], str(px))
    shot("07_blank")

    print("\n=== 4. LOD contract: zooming in on a node reveals its descendants ===")
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(900)
    tgt = page.evaluate(PICK_NODE, 20)
    if not tgt:
        warns.append("no node with >=20 descendants found -> LOD contract test skipped")
        print("    !! no suitable node; skipping")
    else:
        print("    target %s (desc=%d) at (%d,%d)" % (tgt["id"], tgt["d"], tgt["x"], tgt["y"]))
        before = page.evaluate(DESC_COUNT, tgt["id"])
        s_before = page.evaluate(STATE)
        page.mouse.move(tgt["x"], tgt["y"])
        for _ in range(6):
            page.mouse.wheel(0, -100)
            page.wait_for_timeout(50)
        page.wait_for_timeout(400)
        after = page.evaluate(DESC_COUNT, tgt["id"])
        s_after = page.evaluate(STATE)
        print("    revealed descendants %d -> %d ; zoom %.4f -> %.4f ; level %d -> %d ; on-screen %d -> %d"
              % (before, after, s_before["zoom"], s_after["zoom"],
                 s_before["level"], s_after["level"], s_before["shownNodes"], s_after["shownNodes"]))
        check("zooming in reveals more of the target's subtree", after > before, "%d -> %d" % (before, after))
        check("the target itself stays visible while zooming in",
              page.evaluate("(id) => window.KG.renderer.alphaOf(id)", tgt["id"]) > 0.05)
        check("level did not go backwards", s_after["level"] >= s_before["level"],
              "%d -> %d" % (s_before["level"], s_after["level"]))
        shot("08_lod")

    print("\n=== 5. keyboard [ / ] ===")
    page.evaluate("() => window.KG.setLevel(4)")
    page.wait_for_timeout(700)
    a = page.evaluate(STATE)["level"]
    page.keyboard.press("BracketRight")
    page.wait_for_timeout(750)
    b2 = page.evaluate(STATE)["level"]
    page.keyboard.press("BracketLeft")
    page.wait_for_timeout(750)
    c2 = page.evaluate(STATE)["level"]
    print("    setLevel(4)=%d  ] -> %d  [ -> %d" % (a, b2, c2))
    check("] deepens", b2 > a, "%d->%d" % (a, b2))
    check("[ shallows", c2 < b2, "%d->%d" % (b2, c2))

    print("\n=== 6. bug A regression: HUD must follow programmatic zoom ===")
    page.evaluate("() => window.KG.setLevel(4)")
    page.wait_for_timeout(800)
    pill = page.evaluate("() => { const e = document.querySelector('#pills .on'); return e ? e.textContent.trim() : null; }")
    ro = page.evaluate("() => document.getElementById('readout').textContent")
    print("    after setLevel(4): active pill=%r readout=%r" % (pill, ro[:90]))
    check("a pill is active", pill is not None)
    check("active pill == 4 after KG.setLevel(4) (was stuck at the last wheel level)",
          pill == "4", str(pill))
    check("readout non-empty", bool(ro.strip()), ro[:80])
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(1000)
    pill2 = page.evaluate("() => { const e = document.querySelector('#pills .on'); return e ? e.textContent.trim() : null; }")
    lv2 = page.evaluate(STATE)["level"]
    print("    after resetView(): level=%d active pill=%r" % (lv2, pill2))
    check("active pill tracks level after resetView()", pill2 == str(lv2), "%r vs %d" % (pill2, lv2))
    check("resetView returns to home layer", lv2 == meta["homeLayer"], str(lv2))

    print("\n=== 7. click a node -> sidebar + breadcrumb ===")
    picked = page.evaluate(PICK_NODE, 0)
    if picked:
        page.mouse.click(picked["x"], picked["y"])
        page.wait_for_timeout(600)
        sbsel = page.evaluate("""() => ({
            selected: window.KG.state().selected,
            open: document.getElementById('sidebar').classList.contains('open'),
            h2: (document.querySelector('#sidebar h2') || {}).textContent || null,
            crumbs: document.querySelectorAll('#sidebar a[data-goto]').length,
            metaRows: document.querySelectorAll('#sidebar .meta *').length})""")
        print("    ", json.dumps(sbsel, ensure_ascii=False)[:300])
        check("click selected a node", sbsel["selected"] == picked["id"],
              "%s vs %s" % (sbsel["selected"], picked["id"]))
        check("sidebar opened", sbsel["open"])
        check("sidebar has a title", bool(sbsel["h2"]))
        check("breadcrumb has clickable ancestors", sbsel["crumbs"] >= 1, str(sbsel["crumbs"]))
        shot("04_sidebar")
        page.keyboard.press("Escape")
        page.wait_for_timeout(350)
        check("Escape clears selection", page.evaluate(STATE)["selected"] is None)
    else:
        warns.append("no node found under scan -> click test skipped")
        print("    !! no node hit; skipping")

    print("\n=== 8. search ===")
    page.fill("#search", "微分方程")
    page.keyboard.press("Enter")
    page.wait_for_timeout(900)
    sr = page.evaluate("""() => ({
        hits: document.querySelectorAll('#hits > *').length,
        q: window.KG.state().search,
        first: (document.querySelector('#hits > *') || {}).textContent || null})""")
    print("    ", json.dumps(sr, ensure_ascii=False)[:260])
    check("search recorded the query", sr["q"] == "微分方程", repr(sr["q"]))
    check("search produced hits", sr["hits"] > 0, str(sr["hits"]))
    shot("05_search")
    if sr["hits"]:
        page.evaluate("() => document.querySelector('#hits > *').click()")
        page.wait_for_timeout(1000)
        check("clicking a hit selects and focuses it", page.evaluate(STATE)["selected"] is not None)
    page.evaluate("() => window.KG.runSearch('')")
    page.wait_for_timeout(300)

    print("\n=== 9. filters (domain) ===")
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(900)
    base = page.evaluate(STATE)["shownNodes"]
    page.select_option("#domain", index=1)
    page.wait_for_timeout(700)
    filt = page.evaluate(STATE)["shownNodes"]
    print("    shownNodes all=%d  filtered=%d" % (base, filt))
    check("domain filter reduces visible nodes", filt < base, "%d -> %d" % (base, filt))
    page.select_option("#domain", index=0)
    page.wait_for_timeout(700)
    check("clearing the filter restores", page.evaluate(STATE)["shownNodes"] == base)

    print("\n=== 10. dblclick deepens / dblclick empty resets ===")
    page.evaluate("() => window.KG.setLevel(3)")
    page.wait_for_timeout(800)
    z3 = page.evaluate(STATE)["zoom"]
    picked = page.evaluate(PICK_NODE, 0)
    if picked:
        page.mouse.dblclick(picked["x"], picked["y"])
        page.wait_for_timeout(1300)
        z4 = page.evaluate(STATE)["zoom"]
        print("    dblclick node: zoom %.4f -> %.4f" % (z3, z4))
        check("dblclick on a node zooms in", z4 > z3 * 1.15, "%.4f->%.4f" % (z3, z4))
    empty = page.evaluate(PICK_EMPTY)
    if empty:
        page.mouse.dblclick(empty["x"], empty["y"])
        page.wait_for_timeout(1300)
        zr = page.evaluate(STATE)
        print("    dblclick empty at (%d,%d): level=%d zoom=%.4f" % (empty["x"], empty["y"], zr["level"], zr["zoom"]))
        check("dblclick on empty space resets to home", zr["level"] == meta["homeLayer"], str(zr["level"]))
    else:
        warns.append("no empty canvas point found -> dblclick-reset test skipped")
        print("    !! no empty point; skipping")
    shot("06_final")

    print("\n=== 11. perf ===")
    fps = page.evaluate("""() => new Promise(res => {
        let n = 0; const t0 = performance.now();
        (function f(){ n++; if (performance.now() - t0 < 1000) requestAnimationFrame(f); else res(n); })(); })""")
    print("    idle rAF frames in 1s:", fps)
    check("rAF loop alive", fps > 10, str(fps))
    t0 = page.evaluate("() => performance.now()")
    page.mouse.move(720, 430)
    for _ in range(20):
        page.mouse.wheel(0, -60)
    page.wait_for_timeout(400)
    dt = page.evaluate("() => performance.now()") - t0
    print("    20 wheel steps took %.0f ms" % dt)
    check("wheel interaction not janky (<3s for 20 steps)", dt < 3000, "%.0fms" % dt)

    check("still no pageerror at end", not perr, "; ".join(perr[:3]))
    check("still no console error at end", not cerr, "; ".join(cerr[:3]))
    b.close()

print("\n" + "=" * 62)
if warns:
    print("WARNINGS:")
    for w in warns:
        print("  -", w)
if fails:
    print("FAILED %d:" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL BROWSER CHECKS PASSED")
