"""Browser-level verification of web/render.js + web/app.js.

Drives wheel / keyboard / click / search / filters against the built single-file
HTML and asserts the same LOD contract that verify.py proves on the data side,
plus regressions for the three bugs found by hand:
  A. camera tween never notified hooks.onCamera -> HUD stale after programmatic zoom
  B. fully empty viewport gave no feedback (deep zoom can land in a gap between circles)
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
PICK_NODE = """(opt) => {
    opt = opt || {};
    const R = window.KG.renderer; const [W, H] = R.size();
    const minDesc = opt.minDesc || 0, minDepth = opt.minDepth || 0;
    const ok = (n) => !!n && n.depth >= minDepth && R.descOf(n.id) >= minDesc;
    const rec = (n, x, y) => ({id: n.id, x: x, y: y, d: R.descOf(n.id),
                              sr: Math.round(n._sr), depth: n.depth});
    if (opt.smallest) {                       // 全屏扫一遍，取屏上半径最小的那个
        let best = null;
        for (let y = H * 0.15; y < H * 0.85; y += 6)
            for (let x = W * 0.10; x < W * 0.90; x += 6) {
                const n = R.hitTest(x, y);
                if (ok(n) && (!best || n._sr < best.sr)) best = rec(n, x, y);
            }
        return best;
    }
    for (let y = H * 0.30; y < H * 0.72; y += 5) {
        for (let x = W * 0.28; x < W * 0.72; x += 5) {
            const n = R.hitTest(x, y);
            if (ok(n)) return rec(n, x, y);
        }
    }
    for (let y = H * 0.15; y < H * 0.85; y += 6) {
        for (let x = W * 0.10; x < W * 0.90; x += 6) {
            const n = R.hitTest(x, y);
            if (ok(n)) return rec(n, x, y);
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
# packing 下「视口里一个圆都不落笔」不再是默认状态（父圆套着子圆，处处有归属），
# 要验 bug B 得先在圆之间的间隙里平移。这两段直接驱动真实相机、读真实 stats，
# 不在测试里复刻渲染器的裁剪/maxzoom 判据 —— 复刻的判据一旦和实现漂移就会假绿。
PAN_BY = """(d) => {
    const R = window.KG.renderer;
    R.tweenTo({zoom: R.camera.zoom, panX: R.camera.panX + d[0], panY: R.camera.panY + d[1]}, 0);
}"""
SCREEN_CENTER = """() => {
    const c = document.getElementById('cv').getBoundingClientRect();
    const s = window.KG.renderer.centerScreen();
    return {x: c.left + s[0], y: c.top + s[1]};
}"""

fails = []
warns = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("ok" if cond else "FAIL", name, ("  " + detail) if detail else ""))
    if not cond:
        fails.append(name + (" :: " + detail if detail else ""))


def shot(tag):
    page.screenshot(path=SHOT % tag)


def pan_to_empty(steps=((0, 0), (110, 80), (-130, 95), (180, -140), (-240, -110),
                        (300, 210), (-360, 260), (430, -330), (-520, 380))):
    """小幅平移直到视口里一个圆都不落笔，返回累计位移；找不到返回 None。"""
    drift = [0, 0]
    for dx, dy in steps:
        page.evaluate(PAN_BY, [dx, dy])
        drift[0] += dx
        drift[1] += dy
        page.wait_for_timeout(150)
        if page.evaluate(STATE)["shownNodes"] == 0:
            return tuple(drift)
    return None


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
    check("initial shownNodes in 40..120", 40 <= st["shownNodes"] <= 120, str(st["shownNodes"]))

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

    print("\n=== 2. wheel down x20 -> zoom floor, the 6 top disciplines all on screen ===")
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
    top = page.evaluate("""() => {
        const R = window.KG.renderer;
        const roots = R.NODES.filter(n => n.depth === 1);
        return {roots: roots.length,
                vis: roots.filter(n => R.alphaOf(n.id) > 0.05).length};
    }""")
    print("    depth-1 roots=%d, visible=%d" % (top["roots"], top["vis"]))
    # 同心环时代地板处「只剩 6 个圆」；packing 下父圆包含子圆，孩子随父圆一起留在画面里，
    # 所以这里只断言六个顶层学科全部可见 + 总数仍在合理区间。
    check("all 6 top disciplines visible at the zoom floor",
          top["roots"] == 6 and top["vis"] == 6, str(top))
    check("shownNodes in 40..120 at floor", 40 <= out["shownNodes"] <= 120, str(out["shownNodes"]))
    check("the 6 top disciplines are labelled at the zoom floor",
          out["shownLabels"] >= 1, str(out["shownLabels"]))
    shot("02_zmin")

    print("\n=== 3. wheel up x48 -> zoom/level monotonic, reach max_depth and ceiling ===")
    ups, prev_z, prev_lv, z_mono, lv_mono = [], 0.0, 0, True, True
    for i in range(48):
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(38)
        s = page.evaluate(STATE)
        ups.append((round(s["zoom"], 4), s["level"], s["shownNodes"], s["shownEdges"], s["shownLabels"]))
        if s["zoom"] < prev_z - 1e-9:
            z_mono = False
        if s["level"] < prev_lv:
            lv_mono = False
        prev_z, prev_lv = s["zoom"], s["level"]
        if i in (0, 5, 11, 17, 23, 29, 35, 41, 47):
            print("    step %2d  zoom=%8.4f  level=%2d  nodes=%4d  edges=%3d  labels=%3d" % (i + 1, *ups[-1]))
        if i in (4, 15, 29, 47):
            shot("03_up%02d" % (i + 1))
    check("zoom monotonic increasing on wheel up", z_mono)
    check("level monotonic non-decreasing (direction lock)", lv_mono)
    check("reached max_depth %d" % meta["maxDepth"], prev_lv == meta["maxDepth"], str(prev_lv))
    check("zoom hit ceiling", prev_z >= meta["zMax"] * 0.999, "%.4f vs zMax %.4f" % (prev_z, meta["zMax"]))
    nanseen = [u for u in ups if any(v != v for v in u)]
    check("no NaN during 48 wheel steps", not nanseen, str(nanseen[:2]))
    # 深缩放时画面可能只剩几个铺满视口的祖先圆（画不出标签）甚至落进圆之间的空隙，
    # 这些都是合法状态；只有「明显还有一堆内容却一个标签都没有」才算 bug C 复发。
    nolabel = [u for u in ups if u[2] > 8 and u[4] == 0]
    check("labels never all vanish while a real crowd is on screen (was 0 at every zoom before)",
          not nolabel, str(nolabel[:3]))

    print("\n=== 3b. bug B: empty viewport must say so, not look broken ===")
    # 同心环布局的中心天然是空的，天花板处直接就能验；packing 下父圆套着子圆、
    # 画面处处有归属，得先在圆之间的间隙里平移把视口清空。
    at_center = page.evaluate(STATE)["shownNodes"]
    drift = pan_to_empty()
    print("    shownNodes at ceiling center=%d, empty after pan=%s" % (at_center, drift))
    if drift is None:
        warns.append("no empty viewport found at the zoom ceiling -> bug B test skipped")
        print("    !! no gap; skipping")
    else:
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
    tgt = page.evaluate(PICK_NODE, {"minDesc": 20})
    if not tgt:
        warns.append("no node with >=20 descendants found -> LOD contract test skipped")
        print("    !! no suitable node; skipping")
    else:
        print("    target %s (desc=%d, depth=%d, sr=%dpx) at (%d,%d)"
              % (tgt["id"], tgt["d"], tgt["depth"], tgt["sr"], tgt["x"], tgt["y"]))
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
    # 要验面包屑就得点一个有祖先的节点；packing 下扫描最先命中的往往是顶层学科圆
    picked = page.evaluate(PICK_NODE, {"minDepth": 2})
    if picked:
        print("    picked %s (depth=%d, sr=%dpx)" % (picked["id"], picked["depth"], picked["sr"]))
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

    print("\n=== 7b. focus mode: selecting an element filters edges + rings neighbours ===")
    # 焦点模式的判据全在渲染器里（isFocusSide / hotNeighbors）。这一节只负责三件事：
    # ① 用真实相机找一个**确实带语义边**的靶子 ② 走真实 page.mouse.click 验端到端
    # ③ 钉住「无关连线是压暗而不是删除」这个设计决定（shownEdges 必须不变）。
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(900)
    st0 = page.evaluate(STATE)
    base_edges = st0["shownEdges"]
    print("    home baseline: shownNodes=%d shownEdges=%d zoom=%.4f"
          % (st0["shownNodes"], base_edges, st0["zoom"]))
    check("focus test starts from a view that has edges", base_edges > 0, str(base_edges))
    check("no focus stats while nothing is selected",
          st0["focusEdges"] == 0 and st0["focusNeighbors"] == 0,
          "focusEdges=%s focusNeighbors=%s" % (st0["focusEdges"], st0["focusNeighbors"]))

    # 靶子探测：把屏上每个圆轮流设成选中、强制重画、读真实 stats。不在测试里复刻
    # isFocusSide 的判据 —— 复刻的判据一旦和实现漂移就会假绿（本文件既有风格）。
    probe = page.evaluate("""() => {
        const R = window.KG.renderer; const [W, H] = R.size();
        const seen = new Set(); const out = [];
        for (let y = H * 0.15; y < H * 0.85; y += 6) {
            for (let x = W * 0.10; x < W * 0.90; x += 6) {
                const n = R.hitTest(x, y);
                if (!n || seen.has(n.id)) continue;
                seen.add(n.id);
                R.selected = n.id; R.draw();   // setter 只 invalidate，draw() 才立刻出真值
                out.push({id: n.id, x: x, y: y, depth: n.depth, sr: Math.round(n._sr),
                          rel: R.stats.focusEdges, nb: R.stats.focusNeighbors});
            }
        }
        R.selected = null; R.draw();
        return out;
    }""")
    print("    probed %d distinct on-screen nodes; %d of them carry a related edge"
          % (len(probe), len([c for c in probe if c["rel"] > 0])))
    # rel < base_edges 才看得出「无关的被压掉了」；nb > 0 才验得到邻居环
    cand = [c for c in probe if 0 < c["rel"] < base_edges and c["nb"] > 0]
    if not cand:
        cand = [c for c in probe if 0 < c["rel"] < base_edges]
        if cand:
            warns.append("no on-screen node has an *external* semantic edge -> "
                         "neighbour-ring assertion weakened")
    if cand:
        tgt = max(cand, key=lambda c: (c["nb"], -c["sr"]))
        print("    target %s (depth=%d, sr=%dpx) rel=%d/%d nb=%d"
              % (tgt["id"], tgt["depth"], tgt["sr"], tgt["rel"], base_edges, tgt["nb"]))
        page.mouse.click(tgt["x"], tgt["y"])
        page.wait_for_timeout(700)
        s = page.evaluate(STATE)
        print("    ", json.dumps({k: s[k] for k in
                                 ("selected", "shownEdges", "focusEdges", "focusNeighbors")},
                                ensure_ascii=False))
        check("click selected the probed node", s["selected"] == tgt["id"],
              "%s vs %s" % (s["selected"], tgt["id"]))
        check("focus keeps every edge on canvas (dim, not delete)",
              s["shownEdges"] == base_edges, "%d vs base %d" % (s["shownEdges"], base_edges))
        check("focus marks some (not all) edges related",
              0 < s["focusEdges"] < s["shownEdges"],
              "%d of %d" % (s["focusEdges"], s["shownEdges"]))
        check("real click agrees with the programmatic probe",
              s["focusEdges"] == tgt["rel"], "%d vs %d" % (s["focusEdges"], tgt["rel"]))
        check("focus rings at least one neighbour", s["focusNeighbors"] > 0,
              str(s["focusNeighbors"]))
        shot("09_focus")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        e = page.evaluate(STATE)
        check("Escape drops the focus filter",
              e["selected"] is None and e["focusEdges"] == 0 and e["focusNeighbors"] == 0,
              json.dumps({k: e[k] for k in ("selected", "focusEdges", "focusNeighbors")},
                         ensure_ascii=False))
        check("Escape restores the full edge count", e["shownEdges"] == base_edges,
              "%d vs %d" % (e["shownEdges"], base_edges))
        shot("10_focus_off")
    else:
        warns.append("no on-screen node carries a semantic edge -> focus test skipped")
        print("    !! nothing to focus on; skipping")
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
    picked = page.evaluate(PICK_NODE, {"smallest": True, "minDepth": 2})
    if picked:
        # 挑屏上最小的圆：它离「占满大半屏」最远，双击必然要放大过去。
        # 若挑中已经铺满屏幕的大圆，focusOn 算出来的目标 zoom 就等于当前 zoom（正确行为），
        # 断言会假失败。
        page.mouse.dblclick(picked["x"], picked["y"])
        page.wait_for_timeout(1300)
        z4 = page.evaluate(STATE)["zoom"]
        print("    dblclick %s (depth=%d, sr=%dpx): zoom %.4f -> %.4f"
              % (picked["id"], picked["depth"], picked["sr"], z3, z4))
        check("dblclick on a node zooms in", z4 > z3 * 1.15, "%.4f->%.4f" % (z3, z4))
    else:
        warns.append("no node found under scan -> dblclick-deepen test skipped")
        print("    !! no node hit; skipping")
    empty = page.evaluate(PICK_EMPTY)
    how = "in-view empty point"
    if not empty:
        # packing 下 hitTest 会命中「已铺满视口因而停画」的祖先圆（有意保留：点空隙=选中所在省），
        # 所以画面内几乎处处有归属。退一步把视口拖到所有内容之外再验 —— 这也正是
        # 空白提示里「双击空白处回到默认视角」真正会发生的场景。
        page.evaluate("() => window.KG.setLevel(3)")
        page.wait_for_timeout(800)
        page.evaluate(PAN_BY, [6000, 4000])
        page.wait_for_timeout(350)
        if page.evaluate(STATE)["shownNodes"] == 0:
            empty = page.evaluate(SCREEN_CENTER)
            how = "viewport dragged outside all content"
    if empty:
        page.mouse.dblclick(empty["x"], empty["y"])
        page.wait_for_timeout(1300)
        zr = page.evaluate(STATE)
        print("    dblclick empty (%s) at (%d,%d): level=%d zoom=%.4f"
              % (how, empty["x"], empty["y"], zr["level"], zr["zoom"]))
        check("dblclick on empty space resets to home", zr["level"] == meta["homeLayer"], str(zr["level"]))
        check("dblclick on empty space restores the home zoom",
              abs(zr["zoom"] - meta["zHome"]) < meta["zHome"] * 0.02,
              "%.4f vs zHome %.4f" % (zr["zoom"], meta["zHome"]))
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
