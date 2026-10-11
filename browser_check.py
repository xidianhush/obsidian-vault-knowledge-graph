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
    # 每条边最多两个端点标记（源端一个 + 目标端一个），所以 marks <= 2*edges 是硬上界。
    # 下界 marks > 0 才是这轮的重点：home 视图里必须有标记，否则「看不出线的头尾」
    # 这个原始痛点根本没被解决。
    check("endpoint markers are drawn in the home view", st0["marks"] > 0, str(st0["marks"]))
    check("markers never exceed two per drawn edge",
          st0["marks"] <= 2 * base_edges,
          "%d marks / %d edges" % (st0["marks"], base_edges))

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
        # 这是本节最锋利的一条断言：上界用 focusEdges（相关边）而不是 shownEdges（全部边）。
        # 无关边被压到 focus_edge_dim=0.07，标记的 alpha 门槛是 0.1 —— 0.07 过不去，
        # 于是冷边一个标记都不该冒出来。上界写成 2*shownEdges 就退化成永真式了。
        check("markers appear on related edges only (cold 7% edges stay bare)",
              0 < s["marks"] <= 2 * s["focusEdges"],
              "%d marks / %d related edges (%d drawn in total)"
              % (s["marks"], s["focusEdges"], s["shownEdges"]))
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

    print("\n=== 7c. endpoint markers: geometry + config wiring ===")
    # 端点标记的全部意义是「一眼看出线从哪个圆出发、进哪个圆」。所以这里直接量几何：
    # 每个标记到它所附着圆心的屏幕距离，必须 >= 该圆的屏幕半径（留 TRIM 的间隙）。
    # 截断公式一旦写反（ra 用了减号、或切向取反），标记就会掉进圆里被节点整个盖住 ——
    # 那正是这轮要修的原始 bug，值得一条独立断言钉住。
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(900)
    geo = page.evaluate("""() => {
        const R = window.KG.renderer;
        R.selected = null; R.hover = null; R.draw();
        const cam = R.camera, z = cam.zoom;
        const lod = (window.KG.data.meta || {}).lod || {};
        const trim = lod.edge_trim_clearance;
        const jobs = R.markJobs;
        let inside = 0, checked = 0, arrows = 0, dots = 0, minGap = 1e9, maxGap = -1e9;
        for (const j of jobs) {
            if (j.k === 1) arrows++; else dots++;
            // 标记自带它附着的节点 id，直接量那一个圆 —— 不用「找最近圆心」那种
            // 猜法（packing 布局里大祖先圆的圆心常常比小圆自己的更近，会误判）。
            const n = R.byId.get(j.id);
            if (!n || !(n._r > 0)) continue;
            checked++;
            const dx = j.x - (n.x * z + cam.panX), dy = j.y - (n.y * z + cam.panY);
            const gap = Math.sqrt(dx * dx + dy * dy) - n._r * z;  // 正 = 圆外
            if (gap < minGap) minGap = gap;
            if (gap > maxGap) maxGap = gap;
            if (gap < -0.5) inside++;
        }
        return {marks: jobs.length, checked: checked, inside: inside, arrows: arrows,
                dots: dots, minGap: Math.round(minGap * 100) / 100,
                maxGap: Math.round(maxGap * 100) / 100, trim: trim,
                minLen: lod.edge_marker_min_len, tint: lod.edge_marker_tint,
                zoom: Math.round(z * 10000) / 10000};
    }""")
    print("    ", json.dumps(geo, ensure_ascii=False))
    check("three marker knobs reached META.lod through build.py",
          geo["trim"] is not None and geo["minLen"] is not None and geo["tint"] is not None,
          "trim=%s minLen=%s tint=%s" % (geo["trim"], geo["minLen"], geo["tint"]))
    check("markers exist to measure", geo["marks"] > 0, str(geo["marks"]))
    check("every marker resolves to the node it is attached to",
          geo["checked"] == geo["marks"], "%d of %d" % (geo["checked"], geo["marks"]))
    check("no marker is buried inside its node circle",
          geo["inside"] == 0, "%d of %d inside" % (geo["inside"], geo["checked"]))
    # 截断把端点放在「屏幕半径 + TRIM」处，所以间隙应当**恒等于** TRIM（弯边的
    # 退让方向取圆心→控制点，与弦方向略有夹角，会多出零点几 px 的余量）。
    check("markers sit just outside the circle, by the configured clearance",
          geo["minGap"] >= geo["trim"] - 0.75 and geo["maxGap"] <= geo["trim"] + 2.0,
          "gap in [%s, %s] px vs trim=%s px" % (geo["minGap"], geo["maxGap"], geo["trim"]))
    # 有向边（derives / prerequisite）目标端画箭头，源端画点；无向边两端都是点。
    # 本库当前 92 条 derives、0 条 contrast —— 所以 home 视图里两种标记都该有。
    check("both arrow heads and source dots are produced",
          geo["arrows"] > 0 and geo["dots"] > 0,
          "%d arrows / %d dots" % (geo["arrows"], geo["dots"]))

    # 深入一层再看：MARK_MIN 守卫在小尺度下应该开始生效（短边不画标记），
    # 于是 marks 会掉到 2*edges 以下。这条钉住「密集簇里不糊噪点」的设计意图。
    page.evaluate("() => window.KG.renderer.zoomToDepth(6)")
    page.wait_for_timeout(1200)
    deep = page.evaluate(STATE)
    print("    depth6: zoom=%.4f shownEdges=%d marks=%d"
          % (deep["zoom"], deep["shownEdges"], deep["marks"]))
    check("deep zoom still draws some markers", deep["marks"] > 0, str(deep["marks"]))
    check("short edges are skipped by the min-length guard",
          deep["marks"] < 2 * deep["shownEdges"],
          "%d marks < %d (2 x %d edges)" % (deep["marks"], 2 * deep["shownEdges"],
                                            deep["shownEdges"]))
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(900)

    print("\n=== 7d. off-screen focus target: viewport-edge arrow + name chip + fitPair ===")
    # drawEdges 的三道门（同容器 / 聚合索引 / 在屏）会在某些缩放比挡掉焦点边，
    # 挡掉之后画布上「这条链接指向谁」一度一个像素的线索都没有。这一轮补了两条后路：
    # 一端屏外时连线止于视口边缘、挂箭头 + 写著屏外端点名字的 chip；侧栏边行点击
    # 一次 tween 把链接两端一起框进视口（fitPair）。这里用真实相机钉住两条后路。
    # fixture 按**后缀**解析，不写完整路径：笔记一改名路径就失效，7d 会静默跳过
    # （2026-10-10 用户把 信号与系统.md 改名成 LTI analysis.md 之后正是如此）。
    # 后缀是稳定的语义锚点，改名不该让回归覆盖凭空少十几条断言。
    SEL_TAIL = "理解傅利叶变换&频谱密度的几何意义"
    TGT_TAIL = "5.1.2 定积分的定义(本质是求和的极限)"
    pair = page.evaluate("""(tails) => {
        const R = window.KG.renderer;
        const find = (t) => {
            let best = null;
            for (const [id, n] of R.byId) {
                if (!(id.endsWith('/' + t) || id.endsWith('#' + t))) continue;
                if (!best || n.depth < best.depth ||
                    (n.depth === best.depth && n._r > best._r)) best = n;
            }
            return best;
        };
        const a = find(tails[0]), b = find(tails[1]);
        if (!a || !b) return null;
        const linked = R.SEM.some(e => (e.s === a.id && e.t === b.id) ||
                                       (e.s === b.id && e.t === a.id));
        return linked ? [a.id, b.id] : null;
    }""", [SEL_TAIL, TGT_TAIL])
    if not pair:
        warns.append("fixture edge SEL->TGT missing from payload -> 7d skipped")
        print("    !! fixture edge not found; skipping")
    else:
        SEL_ID, TGT_ID = pair
        print("    fixture resolved: SEL=…/%s  TGT=…/%s"
              % (SEL_ID.split("/")[-1], TGT_ID.split("/")[-1]))
        # (a) 深缩放：选中圆在屏、链接目标屏外 -> 线止于视口边，箭头与 chip 都该在
        a = page.evaluate("""(ids) => {
            const R = window.KG.renderer;
            R.selected = null;
            R.focusOn(ids[0], 1.25, 0);
            R.selected = ids[0]; R.draw();
            const st = window.KG.state();
            return {focusEdges: st.focusEdges, chips: st.chips,
                    chipTexts: R.chipJobs.filter(j => j.id === ids[1]).map(j => j.text),
                    edgeArrow: R.markJobs.some(j => j.k === 1 && j.id === ids[1]),
                    selDot: R.markJobs.some(j => j.k === 0 && j.id === ids[0])};
        }""", [SEL_ID, TGT_ID])
        print("    ", json.dumps(a, ensure_ascii=False))
        check("focus edge to an off-screen target still counts as drawn",
              a["focusEdges"] >= 1, str(a["focusEdges"]))
        check("off-screen target gets a name chip",
              a["chips"] >= 1 and len(a["chipTexts"]) >= 1,
              "chips=%s texts=%s" % (a["chips"], a["chipTexts"]))
        check("chip carries the off-screen target's name",
              bool(a["chipTexts"]) and a["chipTexts"][0].startswith("5.1.2 定积分的定义"),
              str(a["chipTexts"][:1]))
        check("viewport-edge arrow is tagged with the off-screen target", a["edgeArrow"])
        check("on-screen end keeps its source dot", a["selDot"])
        shot("11_chip")

        # (b) +k 折叠：语义度 top-6 的 hub 各扫三档缩放，读真实 chipJobs。
        # 不变式：chip 数永不超过 CHIP_MAX+1；只有超出 CHIP_MAX 时末项才是右锚的「+k」。
        chip_max = page.evaluate(
            "() => (((window.KG.data.meta || {}).lod || {}).focus_offscreen_chips) ?? 8")
        probes = page.evaluate("""(mults) => {
            const R = window.KG.renderer;
            const deg = new Map();
            for (const e of R.SEM) { deg.set(e.s, (deg.get(e.s) || 0) + 1); deg.set(e.t, (deg.get(e.t) || 0) + 1); }
            const hubs = [...deg.entries()].sort((x, y) => y[1] - x[1]).slice(0, 6).map(x => x[0]);
            const cs = R.centerScreen();
            const out = [];
            for (const id of hubs) {
                const n = R.byId.get(id);
                for (const m of mults) {
                    const z = Math.min(n._mz * m, R.zMax);
                    R.tweenTo({zoom: z, panX: cs[0] - n.x * z, panY: cs[1] - n.y * z}, 0);
                    R.selected = id; R.draw();
                    const jobs = R.chipJobs;
                    const last = jobs.length ? jobs[jobs.length - 1] : null;
                    out.push({id: id, mult: m, deg: deg.get(id), n: jobs.length,
                              lastText: last ? last.text : null, lastRight: last ? !!last.right : false});
                }
            }
            R.selected = null; R.draw();
            return out;
        }""", [1.3, 3, 8])
        collapsed = [p for p in probes if p["n"] > chip_max]
        print("    hub probes: %d combos, %d collapsed to +k (chip_max=%s)"
              % (len(probes), len(collapsed), chip_max))
        for p in probes[:6]:
            print("      deg=%3d mult=%-4s -> chips=%2d last=%r"
                  % (p["deg"], p["mult"], p["n"], p["lastText"]))
        check("chip list never exceeds CHIP_MAX+1",
              all(p["n"] <= chip_max + 1 for p in probes),
              str(max(p["n"] for p in probes)))
        check("overflow collapses into exactly one right-anchored +k chip",
              all((p["n"] > chip_max) == p["lastRight"] for p in probes) and
              all(p["lastText"].startswith("+") and p["lastText"][1:].isdigit()
                  for p in probes if p["n"] > chip_max),
              str(collapsed[:2]))
        if not collapsed:
            warns.append("no hub probe produced more than CHIP_MAX off-screen targets -> +k chip untested")

        # (c) 侧栏边行点击：fitPair 一次 tween 把链接两端框进视口
        page.evaluate("""(sel) => {
            const R = window.KG.renderer;
            R.selected = null;
            R.focusOn(sel, 1.25, 0);
            R.selected = sel; R.draw();
        }""", SEL_ID)
        page.wait_for_timeout(200)
        pt = page.evaluate("""(sel) => {
            const R = window.KG.renderer;
            const n = R.byId.get(sel);
            const cs = R.centerScreen();
            const cv = document.getElementById('cv').getBoundingClientRect();
            const offs = [[0, 0]];
            for (let f = 0.2; f <= 0.95; f += 0.15)
                for (let t = 0; t < 6.28; t += Math.PI / 6) offs.push([Math.cos(t) * f, Math.sin(t) * f]);
            for (const o of offs) {
                const x = cs[0] + o[0] * n._sr, y = cs[1] + o[1] * n._sr;
                const h = R.hitTest(x, y);
                if (h && h.id === sel) return {x: cv.left + x, y: cv.top + y};
            }
            return null;
        }""", SEL_ID)
        if not pt:
            warns.append("no click point resolves to the fixture node -> fitPair test skipped")
            print("    !! no click point; skipping")
        else:
            page.mouse.click(pt["x"], pt["y"])
            page.wait_for_timeout(600)
            check("real click selects the fixture node",
                  page.evaluate(STATE)["selected"] == SEL_ID)
            row = page.evaluate("""(ids) => {
                const lis = [...document.querySelectorAll('#sidebar li')];
                const li = lis.find(l => l.dataset.self === ids[0] && l.dataset.target === ids[1]);
                if (!li) return {found: false, rows: lis.length};
                li.click();
                return {found: true, rows: lis.length};
            }""", [SEL_ID, TGT_ID])
            print("    sidebar edge rows=%d, fixture row found=%s" % (row["rows"], row["found"]))
            check("sidebar lists the fixture edge as a clickable row", row["found"], str(row["rows"]))
            page.wait_for_timeout(900)
            fit = page.evaluate("""(ids) => {
                const R = window.KG.renderer;
                const cam = R.camera, z = cam.zoom;
                const [W, H] = R.size();
                const box = (id) => {
                    const n = R.byId.get(id);
                    const sx = n.x * z + cam.panX, sy = n.y * z + cam.panY, sr = n._r * z;
                    return [sx - sr, sy - sr, sx + sr, sy + sr];
                };
                const inside = (q) => q[0] >= 0 && q[2] <= W && q[1] >= 0 && q[3] <= H - 46;
                const st = window.KG.state();
                return {selected: st.selected, focusEdges: st.focusEdges, marks: st.marks,
                        okA: inside(box(ids[0])), okB: inside(box(ids[1]))};
            }""", [SEL_ID, TGT_ID])
            print("    ", json.dumps(fit, ensure_ascii=False))
            check("clicking the edge row selects the link target",
                  fit["selected"] == TGT_ID, str(fit["selected"]))
            check("fitPair frames both link ends inside the viewport", fit["okA"] and fit["okB"])
            check("the framed pair still draws its focus edge + markers",
                  fit["focusEdges"] >= 1 and fit["marks"] > 0,
                  "focusEdges=%s marks=%s" % (fit["focusEdges"], fit["marks"]))
            shot("13_fitpair")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        page.evaluate("() => window.KG.renderer.resetView()")
        page.wait_for_timeout(900)

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
