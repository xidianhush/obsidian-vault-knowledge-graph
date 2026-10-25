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

Which build to check: $KG_HTML (a filename under dist/). Defaults to the private
one, knowledge-graph.html. Both scopes share web/*.js, so the public build gets
the same contract checked with a different payload:
    KG_HTML=knowledge-graph.public.html python browser_check.py

Every expectation has to hold for any scope, so none of them may encode one
graph's shape (how many top-level roots there are, how many nodes a zoom floor
happens to show, how many wheel steps it takes to reach the ceiling). Where an
expectation needs a number, it is derived from the payload the HTML carries
(meta.lod / meta.zoom, node radii) or asked of the renderer through its own API
(state(), alphaOf(), matchSet, zoomToDepth) rather than written down here.

Edges are drawn one line per [[link]] at every zoom level: the *number* of lines
carries the strength, endpoints stay on the real nodes, and width / colour /
opacity do not change with zoom. There used to be a second, scale-aggregated
drawing mode behind a toolbar select; it was removed on 2026-10-24, so this is
the only edge path left. Sections 7b/7c/7d cover focus filtering, marker
geometry and the off-screen chip on that single path.
"""
import json
import math
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
# 2026-10-24（阶段 0.3）：KG_HTML 允许绝对路径 —— 多 fixture 回归（fixtures/run_sweep.py）
# 要用它指向 fixtures/vaults/<name>/dist/graph.html；只给文件名时仍按 dist/ 解析（老用法不变）。
_HTML_ENV = os.environ.get("KG_HTML", "knowledge-graph.html")
HTML = _HTML_ENV if os.path.isabs(_HTML_ENV) else os.path.join(ROOT, "dist", _HTML_ENV)
URL = "file:///" + HTML.replace("\\", "/")
SHOT = os.path.join(os.environ.get("KG_SHOT_DIR", tempfile.gettempdir()), "kg_%s.png")
# 身份闸：sweep 会设它，钉住「这份 HTML 到底是哪一本库的」。不设 = 单库人跑，不校验。
EXPECT_VAULT = os.environ.get("KG_EXPECT_VAULT", "")

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
    // 扫描点还必须是**画布自己在最上层**：图例 / 侧栏 / 提示气泡都是绝对定位的覆盖层，
    // 落在它们底下的圆点得到、却点不着（page.mouse.click 打给覆盖层）。2026-10-24 删节点
    // 权重后布局按 label 重排，public 那份就有靶子落进了图例区域，于是「探针说 A、
    // 点击选中 None」的假红 —— 和 2026-10-20 的浮点坐标坑是同一类测试自身问题。
    const cvEl = document.getElementById('cv');
    const cr = cvEl.getBoundingClientRect();
    const topmost = (x, y) => document.elementFromPoint(cr.left + x, cr.top + y) === cvEl;
    // ⚠️ 扫描点必须是**整数屏幕像素**：page.mouse.click 会把浮点坐标截成整数，
    // 而 hitTest 的命中判据是 d <= max(_sr,4)+3。浮点扫描（x += 5 累加出 483.2）
    // 会挑到离子圆边缘不到 1px 的点，截断后正好落到圆外、命中它的父圆 ——
    // 于是「探针说 A、真实点击选中 B」的假红（2026-10-20 在 public 那份上实测：
    // 探针 x=483.2 命中 Physics basic，点击落在 483 命中其父 Science and Tech）。
    // 从 ceil 起算、步长 5 全是整数，探针与点击点数因此逐位相同。
    if (opt.smallest) {                       // 全屏扫一遍，取屏上半径最小的那个
        let best = null;
        for (let y = Math.ceil(H * 0.15); y < H * 0.85; y += 6)
            for (let x = Math.ceil(W * 0.10); x < W * 0.90; x += 6) {
                if (!topmost(x, y)) continue;
                const n = R.hitTest(x, y);
                if (ok(n) && (!best || n._sr < best.sr)) best = rec(n, x, y);
            }
        return best;
    }
    for (let y = Math.ceil(H * 0.30); y < H * 0.72; y += 5) {
        for (let x = Math.ceil(W * 0.28); x < W * 0.72; x += 5) {
            if (!topmost(x, y)) continue;
            const n = R.hitTest(x, y);
            if (ok(n)) return rec(n, x, y);
        }
    }
    for (let y = Math.ceil(H * 0.15); y < H * 0.85; y += 6) {
        for (let x = Math.ceil(W * 0.10); x < W * 0.90; x += 6) {
            if (!topmost(x, y)) continue;
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
# 屏内（alpha > 0 且圆与视口相交）的节点 id，可选屏幕半径下限。地板处的
# 「必须画出来的圆」与标签判据的候选集都从这里取，判据全是 payload 自己的数
# （r × zoom 对 min_px / fade_span）。CULL 取得比渲染器宽（200 vs 32）：多算只会
# 让候选集更保守，不会漏算；这里也刻意不碰 maxzoom 停画那一档 —— 地板处整张图都
# 铺得下（floor = max(r) × zoom_out_floor 那一档），没有圆会被停画。
ON_SCREEN = """(minSr) => {
    const R = window.KG.renderer;
    const [W, H] = R.size(), z = R.camera.zoom, cam = R.camera;
    const CULL = 200, FOOTER = 46;
    const out = [];
    for (const n of R.NODES) {
        const sr = n.r * z, cx = n.x * z + cam.panX, cy = n.y * z + cam.panY;
        if (sr < minSr) continue;
        if (cx + sr < -CULL || cx - sr > W + CULL || cy + sr < -CULL || cy - sr > H + CULL) continue;
        if (R.alphaOf(n.id) <= 0) continue;
        out.push(n.id);
    }
    return out;
}"""
# bug C 的判据要用「渲染器自己放得下标签吗」，而不是「屏幕上有几个圆」。深缩放到祖先圆
# 内部时，圆内摆放的标签锚点（圆顶）整条都在屏幕外 —— 那种帧一个标签都不该有。把候选集
# 塞进 matchSet（渲染器自带的「绕过 label_alpha 门槛」入口，rank 也提到最前），让它自己
# 走完锚点、字号、碰撞那一整套。不在测试里复刻 drawLabels 的判据 —— 复刻的判据一旦和
# 实现漂移就会假绿（本文件既有风格）。用完把 matchSet 还回 null。
FORCE_LABELS = """(ids) => {
    const R = window.KG.renderer;
    R.matchSet = new Set(ids);
    R.draw();
    const n = R.stats.labels;
    R.matchSet = null;
    R.draw();
    return n;
}"""

# 「空白兜底提示有没有落笔」的探针：不是取正中心**一个**像素 —— 提示是 textAlign:center
# 的长文本，屏幕正中那一点很可能正好落在两个字之间的空隙里，单像素抽样会随机假阴性。
# 改成扫过中心的一条横带（含 dpr 缩放），数有多少像素**不是透明**。
# 2026-10-24 视觉改版：画布背景改由 CSS 提供（body 的深青渐变 + 颗粒），render.js 每帧
# 只 clearRect —— 于是「空画布 = alpha 0」是精确判据，比旧的「和 #0f1116 逐通道精确比较」
# 更稳，也不会因为换背景色而假绿。没画东西 → 0。
HINT_PIXELS = """() => {
    const cv = document.getElementById('cv'); const g = cv.getContext('2d');
    const [W, H] = window.KG.renderer.size(); const k = cv.width / W;
    const band = Math.max(1, Math.round(28 * k));
    // 2026-10-24 阶段 1.5：兜底提示画在**内容区中心**（扣掉顶栏/页脚/侧栏），不再固定
    // (H-46)/2 —— 采样带要跟着内容中心走，否则窗口一变就采不到文字、假红。
    const cc = window.KG.renderer.centerScreen();
    const cy = Math.round(cc[1] * k);
    const y0 = Math.max(0, Math.min(cv.height - band, cy - Math.round(band / 2)));
    const d = g.getImageData(0, y0, cv.width, band).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) {
        if (d[i] > 8) n++;
    }
    return n;
}"""

# 整块画布上「有东西」的像素数 —— 「画布是不是肉眼全空」的直接度量，比统计量更硬
# （stats.nodes 是候选集大小、stats.painted 是几何精确的落笔数，两者都只是代理）。
# 判据同 HINT_PIXELS：画布透明背景 ⇒ alpha > 8 即「落过笔」。读整块画布比较贵，
# 所以只在 3d 那一段用。
CANVAS_LIT = """() => {
    const cv = document.getElementById('cv'); const g = cv.getContext('2d');
    const d = g.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) {
        if (d[i] > 8) n++;
    }
    return {lit: n, shown: window.KG.renderer.stats.nodes,
            painted: window.KG.renderer.stats.painted};
}"""

fails = []
warns = []
oks = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("ok" if cond else "FAIL", name, ("  " + detail) if detail else ""))
    if cond:
        oks.append(name)
    else:
        fails.append(name + (" :: " + detail if detail else ""))


def skip_check(name, why):
    """显式跳过一条用例：**必须计数**（阶段 0.3 的纪律：静默少跑 = 假绿）。"""
    warns.append(why + " :: " + name)
    print("    [skip] %s（%s）" % (name, why))


# 形状感知的前置条件表：边界形状（0 条语义边、退化规模）让某些用例的前提不成立，
# 这时显式跳过并计数，而不是判红、也不是默默不跑。
SHAPE_OK = {}
SHAPE_WHY = {}


def require(shape, why):
    SHAPE_OK[shape] = False
    SHAPE_WHY[shape] = why


def check_edge(name, cond, detail=""):
    """边相关断言：库里有 0 条语义边时整段跳过。"""
    if not SHAPE_OK.get("edges", True):
        skip_check(name, SHAPE_WHY.get("edges", "该形状不支持"))
        return
    check(name, cond, detail)


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
    try:
        page.wait_for_function("() => window.KG && window.KG.state && window.KG.renderer", timeout=60000)
    except Exception:
        # 页面根本没起来。这类静默失败最典型的是「内联 JSON 里有非法转义 → JSON.parse
        # 抛错 → 整个脚本没跑完 → 画布全空」：构建侧毫无察觉，双击打开只看到白屏。
        # 如果这里只把 wait_for_function 的超时抛出去，看日志的人根本不知道发生了什么，
        # 所以把 browser 侧已经收集到的报错原样打出来再退出。
        print("!! window.KG 在 60 秒内没有建立 —— 页面脚本没能完成初始化")
        for e in perr[:5]:
            print("   pageerror:", e)
        for c in cerr[:5]:
            print("   console error:", c)
        if not perr and not cerr:
            print("   （没有任何 pageerror / console error：检查 HTML 是否被截断）")
        b.close()
        sys.exit(1)
    page.wait_for_timeout(1500)

    print("=== 1. load ===")
    check("no pageerror", not perr, "; ".join(perr[:3]))
    check("no console error", not cerr, "; ".join(cerr[:3]))

    # 身份闸（阶段 0.3）：多 fixture 回归里最容易的假绿就是「忘设 KG_HTML / 跑到旧 dist」。
    # sweep 每轮都会设 KG_EXPECT_VAULT，对不上就直接红。
    if EXPECT_VAULT:
        got_vault = page.evaluate("() => window.KG.data.meta.vault || ''")
        norm = lambda p: os.path.normcase(os.path.normpath(os.path.abspath(p or ".")))
        check("payload belongs to the expected vault", norm(got_vault) == norm(EXPECT_VAULT),
              "%s" % os.path.basename(got_vault or "<empty>"))

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
        // 下面三个是「这张图自己的形状」：地板/天花板的可见带、滚轮一步的倍率
        // 都由它们推出来，测试里不再出现私有图的绝对数。
        minPx: window.KG.data.meta.lod.min_px,
        fade: window.KG.data.meta.lod.fade_span,
        wheelStep: window.KG.data.meta.zoom.wheel_step,
        zMin: window.KG.zMin, zMax: window.KG.zMax, zHome: window.KG.zHome,
        nodeCount: window.KG.data.nodes.length})""")
    print("   ", json.dumps(meta, ensure_ascii=False)[:420])
    # 阶段 0.3：测试里的「第 4 层」不再写死。浅库（max_depth 小）上要退到「还能再深一层」的那档，
    # 否则 setLevel(4) 会落在 zMax、`]` 无路可走 —— 那是 fixture 形状差异，不是回归缺陷。
    LV_START = max(1, min(4, meta["maxDepth"] - 1))
    LV_DBL = max(1, min(3, meta["maxDepth"] - 1))

    # ── 形状前置条件（阶段 2）：边界形状让部分用例前提不成立，显式登记 ──────────
    n_sem = page.evaluate("() => (window.KG.renderer.SEM || []).length")
    print("    semantic edges = %d" % n_sem)
    if not n_sem:
        require("edges", "这个库没有任何语义边（0 条）")
        print("    !! 0 条语义边 -> 7b/7c/7d 的边相关用例会显式跳过（并计数）")
    # 阶段 2.2：边密集的库在 home 就会抽稀（可见面积预算 / area×600）。stride>1 时
    # 「焦点前后条数相等」这类前提不成立，显式登记。
    home_stride = page.evaluate("() => window.KG.renderer.stats.edgeStride || 1")
    print("    edge stride at home = %s" % home_stride)
    if home_stride > 1:
        require("edge_stride", "边密集：home 抽稀 stride=%d（焦点前后 shownEdges 不再相等）"
                % home_stride)
    # （作者库最小根 18.9px、最大根 262px —— 它照样有标签，所以判据必须看 max）。
    root_sr = page.evaluate("""() => {
        const R = window.KG.renderer; let lo = Infinity, hi = 0;
        for (const n of R.NODES) if (n.depth === 1) {
            const sr = (n._r || n.r) * R.zMin;
            lo = Math.min(lo, sr); hi = Math.max(hi, sr);
        }
        return [isFinite(lo) ? lo : 0, hi]; }""")
    print("    top-level root sr @zMin = %.1f .. %.1f px" % (root_sr[0], root_sr[1]))
    if root_sr[1] < 28:
        require("floor_labels", "所有顶层根在 zMin 处都 <28px（按设计不挂标签）")
    check("no zoom.min/max in payload", "min" not in meta["zoomKeys"] and "max" not in meta["zoomKeys"],
          str(meta["zoomKeys"]))
    check("initial level == home_layer", st["level"] == meta["homeLayer"],
          "%s vs %s" % (st["level"], meta["homeLayer"]))
    check("initial zoom == zHome", abs(st["zoom"] - meta["zHome"]) < 0.01,
          "%s vs %s" % (st["zoom"], meta["zHome"]))
    # 层级带之后（2026-10-21）home 只画到 home_layer 层，落笔数从旧的 55 掉到 ~17，
    # 写死区间没有意义了。改成从 payload / 渲染器现场推出来的判据：
    #   ① 有内容；② 只画到 home_layer 层；③ 不超过 home_layer 以内的节点总数。
    check("initial shownNodes > 0", st["shownNodes"] > 0, str(st["shownNodes"]))
    deeper0 = page.evaluate("""(h) => {
        const R = window.KG.renderer;
        return [...R.byId.values()].filter(n => n.depth > h && R.alphaOf(n.id) > 0).length;
    }""", meta["homeLayer"])
    check("home shows nothing deeper than home_layer", deeper0 == 0, str(deeper0))
    max_home = page.evaluate(
        "(h) => [...window.KG.renderer.byId.values()].filter(n => n.depth <= h).length",
        meta["homeLayer"])
    check("home node count fits inside the home layers",
          st["shownNodes"] <= max_home, "%d vs %d" % (st["shownNodes"], max_home))

    painted = page.evaluate("""() => {
        const cv = document.getElementById('cv'); const g = cv.getContext('2d');
        const d = g.getImageData(0, 0, cv.width, cv.height).data;
        let n = 0;
        for (let i = 3; i < d.length; i += 4 * 97) if (d[i] > 8) n++;
        return n; }""")
    # 判据原来是「采样到 50 个不透明点」—— 那是按 3500 节点的库调的。退化规模（2 个节点）
    # 的库采样点必然很少，但那不是缺陷：真正要守的是「画布上有东西，且渲染器确实落了笔」。
    check("canvas painted (non-transparent samples)",
          painted > 8 and st["shownNodes"] > 0,
          "n=%d shownNodes=%d" % (painted, st["shownNodes"]))

    # bug C: 标签门槛原来读 label_min_px/reveal，而祖先层被 parent_dim 压到 0.5，
    # 两个条件互相抵消 => shownLabels 恒为 0，整张地图一个文字都没有。
    check("home view has text labels", st["shownLabels"] > 0, str(st["shownLabels"]))

    # 阶段 2.4：深层库（深目录 + h6 能到 16~18 层）的层级胶囊会把搜索框 / 重置按钮挤出
    # 顶栏（2026-10-20 的老 bug 形态：控件被压成竖排、被裁掉）。判据与形状无关：
    # 顶栏每个可见子元素都必须完整落在顶栏矩形内；胶囊多时必须靠横向滚动消化。
    bar = page.evaluate("""() => {
        const bar = document.getElementById('topbar');
        const br = bar.getBoundingClientRect();
        const kids = [...bar.children].filter(el => el.offsetWidth > 0);
        const bad = kids.filter(el => { const r = el.getBoundingClientRect();
            return r.right > br.right + 1 || r.left < br.left - 1 ||
                   r.bottom > br.bottom + 1 || r.top < br.top - 1; })
            .map(el => el.id || el.className || el.tagName);
        const pills = document.getElementById('pills');
        return {bad: bad, barH: Math.round(br.height),
                pillCount: pills.children.length,
                pillsScroll: pills.scrollWidth > pills.clientWidth + 1}; }""")
    check("topbar controls stay inside the bar (deep vaults scroll their pill bar)",
          not bar["bad"], "%s (pills=%d scrollable=%s barH=%d)"
          % (bar["bad"], bar["pillCount"], bar["pillsScroll"], bar["barH"]))

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
    # 阶段 2.1：预算不再是写死的 400 个候选，而是「真正画出来的张数」，由内容区面积派生。
    budget = page.evaluate("() => window.KG.renderer.labelBudget()")
    check("labels stay inside the per-frame budget", on <= budget, "%d <= %d" % (on, budget))
    # 阶段 2.1：'只显示选中' 以前被映射成 'off'（一个标签都不画）—— 现在必须是
    # 「选中项 + 邻居 + 悬停项」那一小撮，而不是零。
    picked_lbl = page.evaluate(PICK_NODE, {"minDepth": 1})
    if picked_lbl:
        page.mouse.click(picked_lbl["x"], picked_lbl["y"])
        page.wait_for_timeout(500)
        # 阶段 2.5 泛化：屏幕半径 <28px 的圆按设计**不挂标签**（标签只进圆内）。
        # wide-roots 上探针可能点中 17px 的小圆 —— 那不是「off 老 bug」，是形状。
        # 所以先把选中的圆放大到能放字（focusOn 瞬时），再验 selected 模式。
        page.evaluate("(id) => window.KG.renderer.focusOn(id, 1.0, 0)", picked_lbl["id"])
        page.wait_for_timeout(700)
        page.evaluate("() => { window.KG.renderer.labelMode = 'selected'; window.KG.renderer.draw(); }")
        page.wait_for_timeout(300)
        sel_n = page.evaluate(STATE)["shownLabels"]
        nb = page.evaluate("() => window.KG.state().focusNeighbors")
        sel_sr = page.evaluate("(id) => Math.round((window.KG.renderer.byId.get(id) || {})._sr || 0)",
                               picked_lbl["id"])
        print("    labelMode 'selected': labels=%d neighbors=%s selected_sr=%dpx"
              % (sel_n, nb or 0, sel_sr))
        check("labelMode 'selected' labels the selection (not zero, the old 'off' bug)",
              sel_n > 0, "labels=%d" % sel_n)
        check("labelMode 'selected' shows far fewer labels than 'auto'",
              sel_n <= max(12, (nb or 0) + 3), "labels=%d neighbors=%s" % (sel_n, nb or 0))
        page.evaluate("""() => { const R = window.KG.renderer;
            R.labelMode = 'auto'; R.selected = null; R.draw(); }""")
        page.wait_for_timeout(300)
        # 关掉侧栏：01_home 是给人眼验收的「首页」截图，不该带着选中态的侧栏
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        page.evaluate("() => window.KG.renderer.resetView()")
        page.wait_for_timeout(600)
    else:
        warns.append("no node picked for labelMode 'selected' test -> skipped")
    shot("01_home")

    print("\n=== 2. the zoom floor landmark: land on zMin, every top-level root on screen ===")
    page.mouse.move(720, 430)
    # 地板现在**显式落到渲染器的地标 zMin 上**，而不是「往下滚 20 格」—— 滚轮的 clamp
    # 已经拆掉（见 2b），滚 20 格会一路滚过 zMin 进到空白里。地标本身要钉住的行为没变：
    # zMin = 最小的顶层学科刚好看得见的那一档，所以「每个顶层学科都在画面上」必须成立。
    page.evaluate("() => window.KG.renderer.setZoom(window.KG.renderer.zMin)")
    page.wait_for_timeout(400)
    out = page.evaluate(STATE)
    # state().zoom 只保留 3 位小数，判边界必须读未舍入的相机值
    camz = page.evaluate("() => window.KG.renderer.camera.zoom")
    print("   ", json.dumps({k: out[k] for k in ("zoom", "level", "shownNodes", "shownEdges")}, ensure_ascii=False))
    check("setZoom(zMin) lands exactly on the landmark", abs(camz - meta["zMin"]) < 1e-9,
          "%.8f vs zMin %.8f" % (camz, meta["zMin"]))
    check("level == 1 at floor", out["level"] == 1, str(out["level"]))
    top = page.evaluate("""() => {
        const R = window.KG.renderer;
        const roots = R.NODES.filter(n => n.depth === 1);
        return {roots: roots.length,
                vis: roots.filter(n => R.alphaOf(n.id) > 0.05).length};
    }""")
    # 顶层学科数由 payload 自己说了算 —— 私有图 6 个、公开图 3 个，写死 6 是把一张图的
    # 形状当成契约。要钉住的行为不变：地板处**每一个**顶层学科都在画面上。地板 zoom 由
    # max(r) × zoom_out_floor 现算，任何一个根算错（半径/最小缩放）都会让 vis < roots。
    print("    depth-1 roots=%d, visible=%d" % (top["roots"], top["vis"]))
    check("all %d top-level roots visible at the zoom floor" % top["roots"],
          top["roots"] >= 1 and top["vis"] == top["roots"], str(top))
    # 地板处的可见带也由 payload 现算：屏幕半径够 min_px 的圆（淡入进度 = 1）必须全部画出来，
    # 半径不到 min_px/fade_span 的圆（淡入还没开始）一个都不该出现。私有图 [44..54]、
    # 公开图 [12..16] —— 旧的 40..120 两个方向都放水：同心环时代地板只剩顶层圆（6 个）
    # 会漏过去的下界，正是这条断言当初想抓的回归。
    band_lo = len(page.evaluate(ON_SCREEN, meta["minPx"]))
    band_hi = len(page.evaluate(ON_SCREEN, meta["minPx"] / meta["fade"]))
    print("    floor legible band = [%d..%d], shownNodes=%d" % (band_lo, band_hi, out["shownNodes"]))
    check("floor shows exactly the band the payload says is legible ([%d..%d])" % (band_lo, band_hi),
          band_lo <= out["shownNodes"] <= band_hi,
          "shownNodes=%d, band=[%d..%d], total=%d" % (out["shownNodes"], band_lo, band_hi,
                                                      meta["nodeCount"]))
    if SHAPE_OK.get("floor_labels", True):
        check("the top-level roots are labelled at the zoom floor",
              out["shownLabels"] >= 1, str(out["shownLabels"]))
    else:
        skip_check("the top-level roots are labelled at the zoom floor",
                   SHAPE_WHY["floor_labels"])
    shot("02_zmin")

    print("\n=== 2b. the floor is a landmark, not a wall: the wheel may pass it into empty space ===")
    # 需求：缩放上下限放开。滚轮不再被 clamp 到 zMin —— 一路往下滚要能滚过它，
    # 画面随之清空，并且**不是死黑**：全空白兜底提示必须画出来。这条同时证明了
    # 「放开」是真的，以及「放开之后缩丢了也不至于看到一片什么都没有的屏幕」。
    # 不能写死次数：要缩到「连世界半径 1000 的根都淡出」需要 log(0.0133/zMin)/log(1.12)
    # 约 30 格，而根是最后才消失的那个。所以滚到空为止（上限兜住）。
    below, steps_down = None, 0
    for _ in range(60):
        page.mouse.wheel(0, 100)
        page.wait_for_timeout(35)
        steps_down += 1
        st = page.evaluate(STATE)
        below = page.evaluate("() => window.KG.renderer.camera.zoom")
        if st["shownNodes"] == 0:
            break
    page.wait_for_timeout(400)
    empty = page.evaluate(STATE)
    print("    下滚 %d 格后 zoom=%.6f (zMin=%.6f)  shownNodes=%d"
          % (steps_down, below, meta["zMin"], empty["shownNodes"]))
    check("wheel goes below zMin (floor is a landmark, not a wall)",
          below < meta["zMin"] * 0.999, "%.6f < %.6f?" % (below, meta["zMin"]))
    check("zooming far enough past the floor empties the viewport", empty["shownNodes"] == 0,
          str(empty["shownNodes"]))
    hint_n = page.evaluate(HINT_PIXELS)
    check("empty viewport still paints the fallback hint (not a dead black screen)",
          hint_n > 50, "中心带非透明像素=%d" % hint_n)
    check("no pageerror while roaming past the floor", not perr, "; ".join(perr[:2]))
    # 回到地标，后面的段落都假设从这里开始往上滚
    page.evaluate("() => window.KG.renderer.setZoom(window.KG.renderer.zMin)")
    page.wait_for_timeout(300)

    # 到天花板要多少步，由这张图自己的缩放跨度算：log(zMax/zMin)/log(wheel_step)，再加
    # 3 步余量（clamp 与最后一步的取整）。私有图 157× = 45 步，公开图 338× = 52 步 ——
    # 写死 48 步只够前者，公开图第 48 步停在中途（45.7 vs zMax 66.9），看起来像 zoom 卡住了。
    up_steps = int(math.ceil(math.log(meta["zMax"] / meta["zMin"]) /
                             math.log(meta["wheelStep"]))) + 3
    print("\n=== 3. wheel up x%d (span %.1fx) -> zoom/level monotonic, reach max_depth and the ceiling landmark ==="
          % (up_steps, meta["zMax"] / meta["zMin"]))
    ups, prev_z, prev_lv, z_mono, lv_mono = [], 0.0, 0, True, True
    label_gap = []
    for i in range(up_steps):
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(38)
        s = page.evaluate(STATE)
        ups.append((round(s["zoom"], 4), s["level"], s["shownNodes"], s["shownEdges"], s["shownLabels"]))
        if s["zoom"] < prev_z - 1e-9:
            z_mono = False
        if s["level"] < prev_lv:
            lv_mono = False
        prev_z, prev_lv = s["zoom"], s["level"]
        if i % 6 == 0 or i == up_steps - 1:
            print("    step %2d  zoom=%8.4f  level=%2d  nodes=%4d  edges=%3d  labels=%3d" % (i + 1, *ups[-1]))
        if i in (4, up_steps // 3, 2 * up_steps // 3, up_steps - 1):
            shot("03_up%02d" % (i + 1))
        # bug C 的判据：这一帧一个标签都没有时，问渲染器自己「够大的圆上放得下标签吗」。
        # 候选集 = 屏内、屏幕半径 ≥ min_px 的圆（淡入进度已经是 1，label_alpha 门槛必过）。
        # 深缩放到祖先圆内部时圆顶的标签锚点整条都在屏外，渲染器自己也放不下 —— 那是
        # 合法状态（公开图 z=23.151 那一帧：12 个屏内圆、legibleOnScreen=12、forced=0）。
        # 只要有候选却一个都没落笔，就是 bug C 复发。判据全在渲染器自己的锚点/碰撞代码里。
        if s["shownLabels"] == 0:
            cand = page.evaluate(ON_SCREEN, meta["minPx"])
            forced = page.evaluate(FORCE_LABELS, cand) if cand else 0
            if forced:
                label_gap.append((round(s["zoom"], 4), s["shownNodes"], len(cand), forced))
    check("zoom monotonic increasing on wheel up", z_mono)
    check("level monotonic non-decreasing (direction lock)", lv_mono)
    check("reached max_depth %d" % meta["maxDepth"], prev_lv == meta["maxDepth"], str(prev_lv))
    # 天花板也不再是墙：滚轮可以越过 zMax（多滚几格就超了）。这条只要求「可达且被越过」，
    # zMax 仍然是地标 —— 深度层级（enterAt）与层级胶囊都还用它。
    check("the ceiling landmark zMax is reached and passed (not a wall)",
          prev_z >= meta["zMax"] * 0.999, "%.4f vs zMax %.4f" % (prev_z, meta["zMax"]))
    nanseen = [u for u in ups if any(v != v for v in u)]
    check("no NaN during %d wheel steps" % up_steps, not nanseen, str(nanseen[:2]))
    check("labels never all vanish while the renderer itself could place one (was 0 at every zoom before)",
          not label_gap, str(label_gap[:3]))

    print("\n=== 3b. bug B: empty viewport must say so, not look broken ===")
    # 同心环布局的中心天然是空的，天花板处直接就能验；packing 下父圆套着子圆、
    # 画面处处有归属，得先在圆之间的间隙里平移把视口清空。
    at_center = page.evaluate(STATE)["shownNodes"]
    drift = pan_to_empty()
    print("    shownNodes at ceiling center=%d, empty after pan=%s" % (at_center, drift))
    if drift is None:
        warns.append("no empty viewport found at the zoom ceiling -> bug B tested only via 2b/3c")
        print("    !! no gap; skipping (2b 与 3c 已经用同一条兜底提示覆盖了空视口)")
    else:
        hint_n = page.evaluate(HINT_PIXELS)
        check("hint text painted at screen center", hint_n > 50, "中心带非透明像素=%d" % hint_n)
    shot("07_blank")

    print("\n=== 3c. zooming in far past the ceiling: maxzoom hides everything, hint still shows ===")
    # 放大侧放开之后会撞上另一条**本来就有**的规则（render.js 的 maxzoom）：圆的屏幕半径
    # 超过「圆心到视口最远角」就停画，因为再画只是一层纯色罩。于是足够深的放大之后视口也会
    # 空。这是设计如此（地图到最深一级也是这样），但放开之后它变得可达，所以必须钉住：
    # 空得掉、不报错、且照样有兜底提示。
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(700)
    z0 = page.evaluate("() => window.KG.renderer.camera.zoom")
    empty_at = None
    for i in range(18):
        page.evaluate("() => window.KG.renderer.zoomBy(4)")
        page.wait_for_timeout(90)
        st = page.evaluate(STATE)
        # 判据是「painted 与 bodyChars **同时**为 0」：第 11 带（正文）开启之后，
        # 正文只画字、不画圆，光看 painted 会把「满屏正文」误判成空。而兜底提示本来
        # 就只在两者都为空时才落笔（render.js draw() 末尾的判据同步改了）。
        # 判据必须是 stats.painted（几何精确的落笔数），**不能**用 shownNodes：
        # 那是候选集大小，会被「中心远在屏外、半径极大的圆」撑住 —— public 在 z=1e6 时
        # shownNodes 恒为 1，而画布上其实一无所有、提示正常画着（见 3d 的说明）。
        if st["painted"] == 0:
            empty_at = page.evaluate("() => window.KG.renderer.camera.zoom")
            break
    print("    home z=%.3f -> 空于 z=%s（%s× home，%s× zMax）" % (
        z0, ("%.1f" % empty_at) if empty_at else "未达到",
        ("%.1f" % (empty_at / z0)) if empty_at else "-",
        ("%.1f" % (empty_at / meta["zMax"])) if empty_at else "-"))
    if empty_at is None:
        # 阶段 2.4 泛化：「放大到极端会空」只对**有更深层可看**的库成立。浅库（plain 实测）
        # 最深层就是笔记本身，圆一直铺满视口 —— `drawNodes` 的前景层不参与 wash 的 maxzoom
        # 退场（那条规则只管祖先罩子），所以在这个库里「空视口」这个状态根本不存在。
        # 这是形状前提不成立，显式跳过并计数，而不是判红。
        skip_check("zooming in far enough does empty the viewport (maxzoom rule, pre-existing)",
                   "放大到 ZOOM_HARD 上限仍有 %s 个圆覆盖视口（最深层圆太大，没有空视口态）"
                   % page.evaluate(STATE)["painted"])
    else:
        check("zooming in far enough does empty the viewport (maxzoom rule, pre-existing)",
              True, str(empty_at))
        hint_n2 = page.evaluate(HINT_PIXELS)
        check("extreme zoom-in still paints the fallback hint",
              hint_n2 > 50, "中心带非透明像素=%d" % hint_n2)
    check("no pageerror at extreme zoom-in", not perr, "; ".join(perr[:2]))
    # Home 必须能救回来 —— 这是放开缩放之后承诺的找回手段。
    # 判据用「恢复到 zHome」而不是「比某个阈值大」：后者在小视口下会因为
    # homeZoom 自身被 clamp 到 zMin 而变得脆弱，前者才是真正的契约。
    page.keyboard.press("Home")
    page.wait_for_timeout(900)
    home_after = page.evaluate("() => window.KG.renderer.camera.zoom")
    check("Home key recovers from the empty state back to the home view",
          abs(home_after - meta["zHome"]) < 1e-6,
          "%.6f vs zHome %.6f" % (home_after, meta["zHome"]))

    print("\n=== 3e. 第 11 带：圆即入口（Ctrl + 悬停标题圆 → 从这一节滚起）===")
    # 2026-10-24 第五轮：药丸层整个删除 —— **实心圆自己就是入口**。
    #   * Ctrl + 悬停**标题**圆 → 弹预览并从该标题的锚点滚起；
    #   * Ctrl + 悬停**文件夹/笔记**圆 → 不预览，toast 提示「还没到标题」；
    #   * 松开 Ctrl → 收起；药丸相关的 API / 统计必须不存在（防止改回去）。
    if not page.evaluate("() => !!(window.KG.renderer.hitTest)"):
        warns.append("renderer.hitTest 不存在 -> 跳过第 11 带断言")
        print("    !! no hitTest; skipping preview checks")
    elif not page.evaluate(
            "() => window.KG.renderer.NODES.some(n => n.kind === 'heading' && n.anchor)"):
        # 阶段 0.3：无标题的库（plain / shallow）没有「可预览的标题圆」，
        # 3e 整段的前提不存在 —— 显式跳过并计数，而不是拿 None 去索引崩掉。
        warns.append("这个库没有任何带锚点的标题圆 -> 3e 整段跳过（不是回归）")
        print("    !! no heading with anchor; skipping 3e")
    else:
        # 靶子：深一点的标题（小圆 → 放大后圆够大才方便悬停），且所属笔记带公式和图片
        tgt = page.evaluate("""() => {
            const R = window.KG.renderer;
            let best = null, fallback = null;
            for (const n of R.NODES) {
                if (n.kind !== 'heading' || !n.anchor) continue;
                const note = R.byId.get(n.note) || {};
                const p = note.preview || '';
                const box = document.createElement('div');
                box.innerHTML = p;
                box.querySelectorAll('pre,code').forEach(e => e.remove());
                const txt = box.textContent || '';
                const hasImg = p.indexOf('<img') >= 0;
                const hasMath = txt.split('$').length >= 3;
                const rec = {id: n.id, x: n.x, y: n.y, r: n._r || n.r,
                             anchor: n.anchor, note: n.note,
                             noteLabel: note.label || '', label: n.label || '',
                             img: hasImg, math: hasMath};
                if (hasImg && hasMath && (!best || rec.r < best.r)) best = rec;
                if (!fallback || rec.r < fallback.r) fallback = rec;
            }
            return best || fallback;
        }""")
        print("    靶子标题: %s（anchor=%s，sr≈%.2f @zoom=1）"
              % (tgt["label"][:34], tgt["anchor"], tgt["r"]))
        z_big = 120.0 / max(tgt["r"], 1e-6)

        VW = page.viewport_size["width"]
        VH = page.viewport_size["height"]

        def center_on(node, z):
            page.evaluate("""(a) => {
                const R = window.KG.renderer;
                R.setZoom(a.z);
                const W = window.innerWidth, H = window.innerHeight;
                R.camera.panX = W / 2 - a.x * R.camera.zoom;
                R.camera.panY = (H - 46) / 2 - a.y * R.camera.zoom;
                R.draw();
            }""", {"z": z, "x": node["x"], "y": node["y"]})
            page.wait_for_timeout(200)

        center_on(tgt, z_big)
        hit = page.evaluate("() => { const R = window.KG.renderer;"
                            " const h = R.hitTest(window.innerWidth / 2, (window.innerHeight - 46) / 2);"
                            " return h ? {id: h.id, kind: h.kind} : null; }")
        check("放大后视口中心命中的就是这个标题圆", hit and hit["id"] == tgt["id"],
              "hit=%s" % (hit and hit["id"].rsplit("/", 1)[-1][:26]))

        # ① Ctrl + 悬停标题圆 → 预览浮层（顺带：Ctrl 模式要给标题圆画虚线圈）
        page.keyboard.down("Control")
        page.mouse.move(VW / 2, (VH - 46) / 2)
        page.wait_for_timeout(600)
        rings = page.evaluate("() => window.KG.renderer.stats.ctrlRings")
        check("按住 Ctrl 时标题圆出现「可预览」虚线圈", rings > 0, "rings=%d" % rings)
        page.wait_for_timeout(600)
        pv = page.evaluate("""() => {
            const el = document.getElementById('preview');
            if (!el || !el.classList.contains('show')) return null;
            const imgs = [...el.querySelectorAll('img')];
            const a = el.querySelector('#' + %r);
            const blk = a ? a.closest('h1,h2,h3,h4,h5,h6') : null;
            const pr = el.getBoundingClientRect();
            const crumbs = el.querySelector('.pv-crumbs');
            return {
                katex: el.querySelectorAll('.katex').length,
                imgs: imgs.length,
                broken: imgs.filter(i => !i.naturalWidth).length,
                scrollTop: el.scrollTop,
                anchorRel: blk ? (blk.getBoundingClientRect().top - pr.top) : -9999,
                anchorTag: blk ? blk.tagName : '',
                anchorText: (() => {
                    if (!blk) return '';
                    // KaTeX 会渲染两份（MathML + HTML），textContent 会把公式重复一遍
                    const clone = blk.cloneNode(true);
                    clone.querySelectorAll('.katex-mathml').forEach(e => e.remove());
                    return (clone.textContent || '').trim().slice(0, 120);
                })(),
                crumbs: crumbs ? (crumbs.textContent || '') : '',
                crumbsH: crumbs ? crumbs.offsetHeight : 0,
                tooltipShown: (document.getElementById('tooltip') || {}).style.display === 'block',
                inViewport: pr.left >= -1 && pr.top >= -1 &&
                            pr.right <= window.innerWidth + 1 &&
                            pr.bottom <= window.innerHeight + 1,
            };
        }""" % tgt["anchor"])
        check("Ctrl + 悬停标题圆打开预览", pv is not None, tgt["label"][:26])
        if pv:
            if tgt["math"]:
                check("预览里的 KaTeX 公式真的渲染了", pv["katex"] > 0, "katex=%d" % pv["katex"])
            else:
                warns.append("靶子笔记没有公式 -> KaTeX 断言跳过")
            if tgt["img"]:
                check("预览里的图片真的加载了", pv["imgs"] > 0 and pv["broken"] == 0,
                      "imgs=%d broken=%d" % (pv["imgs"], pv["broken"]))
            else:
                warns.append("靶子笔记没有图片 -> 图片断言跳过")
            # 「从这一节开始」：锚点标题落在浮层顶部附近，且标题**真的渲染出来了**
            # 标题要落在**面包屑下方**（不是被 sticky 面包屑盖住）。
            # 2026-10-24 阶段 2：短笔记的锚点本来就在顶部、scrollTop=0 是**正常**的
            # （wide-roots / tiny 实测），所以「必须滚过 100px」这条不能当硬条件 ——
            # 真正要守的是锚点相对面包屑的位置。
            check("预览从这一节的标题开始（标题在面包屑下方可见）",
                  (pv["scrollTop"] > 100 or pv["anchorRel"] <= pv["crumbsH"] + 120)
                  and pv["anchorRel"] >= pv["crumbsH"] - 6
                  and pv["anchorRel"] <= pv["crumbsH"] + 180,
                  "scrollTop=%d 锚点 top=%dpx 面包屑高=%dpx"
                  % (pv["scrollTop"], pv["anchorRel"], pv["crumbsH"]))
            check("这一节的标题本身渲染出来了（<hN> 有文字）",
                  pv["anchorTag"][:1] == "H" and len(pv["anchorText"]) > 0,
                  "%s %r" % (pv["anchorTag"], pv["anchorText"]))
            # 关键回归：预览里的标题必须**就是悬停的那个标题**（2026-10-24 用户实测
            # 悬停 A 却看到 B 的正文 —— 锚点按 HTML 顺序编号时整体错位一格）
            norm = lambda s: "".join(ch for ch in (s or "")
                                     if ch not in " \t\n$\\{}*_`|>#[]()")
            pv_txt, hov_txt = norm(pv["anchorText"]), norm(tgt["label"])
            head = hov_txt[:min(10, len(hov_txt))]
            check("预览里的标题就是悬停的那个标题（不是下一个）",
                  bool(head) and pv_txt.startswith(head),
                  "预览=%r 悬停=%r" % (pv["anchorText"][:24], tgt["label"][:24]))
            check("Ctrl 预览模式下不弹 hover 气泡", not pv["tooltipShown"])
            check("浮层面包屑显示「笔记 › 这一节」",
                  tgt["noteLabel"][:6] in pv["crumbs"] and tgt["label"][:6] in pv["crumbs"],
                  pv["crumbs"][:60])
            check("预览浮层没有超出视口", pv["inViewport"])
        shot("16_circle_preview")

        # ② Ctrl 悬停中单击 = 固定预览（移开鼠标、松开 Ctrl 都不消失；Esc 收起）
        page.mouse.click(VW / 2, (VH - 46) / 2)
        page.wait_for_timeout(450)
        pinned = page.evaluate("() => window.KG.previewState().pinned")
        check("Ctrl 悬停中单击标题圆 = 固定预览", pinned)
        page.mouse.move(40, VH - 120)
        page.keyboard.up("Control")
        page.wait_for_timeout(500)
        still = page.evaluate("() => window.KG.previewState().open")
        check("固定预览移开鼠标、松开 Ctrl 都不消失", pinned and still,
              "打开=%s 移开后=%s" % (pinned, still))
        pg_shot = page.evaluate("() => document.getElementById('preview').scrollTop")
        check("固定预览可以滚动（长笔记能读下去）", pg_shot >= 0, "scrollTop=%d" % pg_shot)
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        check("Esc 收起固定预览",
              page.evaluate("() => !document.getElementById('preview').classList.contains('show')"))
        check("松开 Ctrl 后提示圆环消失",
              page.evaluate("() => window.KG.renderer.stats.ctrlRings") == 0,
              "rings=%s" % page.evaluate("() => window.KG.renderer.stats.ctrlRings"))

        # ③ 光标停在「笔记」圆上按 Ctrl → 不预览 + toast 提示
        note_target = None
        note_zoom = 0
        for cand in page.evaluate("""() => {
            const R = window.KG.renderer;
            return R.NODES.filter(n => n.kind === 'note' && n.preview)
                .sort((a, b) => (b.r || 0) - (a.r || 0)).slice(0, 12)
                .map(n => ({id: n.id, x: n.x, y: n.y, r: n._r || n.r}));
        }"""):
            z = 120.0 / max(cand["r"], 1e-6)
            center_on(cand, z)
            h = page.evaluate("() => { const R = window.KG.renderer;"
                              " const x = R.hitTest(window.innerWidth / 2, (window.innerHeight - 46) / 2);"
                              " return x ? {id: x.id, kind: x.kind} : null; }")
            if h and h["id"] == cand["id"]:
                note_target, note_zoom = cand, z
                break
        if note_target:
            # 干净的顺序：先 Esc 关掉一切，再把光标放到笔记圆心，最后按下 Ctrl ——
            # 按下 Ctrl 那一刻就会按光标下的节点给提示（不依赖 mousemove，浮层也不会
            # 盖住圆心把事件吃掉）。
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            center_on(note_target, note_zoom)
            page.mouse.move(VW / 2, (VH - 46) / 2)
            page.wait_for_timeout(200)
            page.keyboard.down("Control")
            page.wait_for_timeout(450)
            st = page.evaluate("""() => {
                const ps = window.KG.previewState();
                return {shown: ps.open, toast: (document.getElementById('toast') || {}).textContent || '',
                        hit: (() => { const h = window.KG.renderer.hitTest(window.innerWidth / 2,
                                    (window.innerHeight - 46) / 2); return h ? h.kind : null; })()};
            }""")
            check("悬停笔记圆不弹预览（还没到标题层）", not st["shown"],
                  "shown=%s 命中=%s" % (st["shown"], st["hit"]))
            check("悬停笔记圆给出「还没到标题」提示", "还没到标题" in st["toast"], st["toast"][:40])
        else:
            warns.append("没找到中心落在笔记圆上的视图 -> 笔记圆提示未测")
        page.keyboard.up("Control")
        page.wait_for_timeout(250)

        # ④ 药丸层必须真的没了（防止有人把 pills 改回来）
        gone = page.evaluate("""() => {
            const R = window.KG.renderer;
            return {jobs: typeof R.linkJobs, at: typeof R.linkAt,
                    links: window.KG.state().links};
        }""")
        check("药丸层已删除（无 linkJobs / linkAt / stats.links）",
              gone["jobs"] == "undefined" and gone["at"] == "undefined"
              and gone["links"] is None,
              str(gone))

        page.evaluate("() => window.KG.renderer.resetView()")
        page.wait_for_timeout(700)

    print("\n=== 3d. no zoom/pan may leave a blank canvas without the hint ===")
    # 这是 3c 的真正用途，也是放开缩放的前提条件：画布**肉眼全空**时必须有兜底提示。
    # 曾经的判据是「候选集为空」（wash/front 是否为空），会被「中心远在屏外、半径极大的圆」
    # 骗过 —— 它那道 maxzoom 门（sr < farCornerDist）会因为远处的 far 同样很大而放行，
    # 填充被 fade 压到看不见、界线弧又整条在画布之外，于是画布上一无所有而兜底不画。
    # 放开缩放之后放大到极端就能撞上（实测 public 在 z ≥ 5000 时 0 个非背景像素、
    # stats.nodes 却是 1）。现在判据改成 stats.painted（按 PAINT_MIN 与 near/far 几何精确
    # 判定的落笔数），这一段把「任何缩放 × 任何平移都不允许出现无提示的空白」扫一遍钉住。
    probes = [0.005, 0.02, 0.1, 0.4612, 3, 30, 1000, 30000, 1e5]
    pans = [(0, 0), (600, 400), (-1200, -800), (3000, -2500)]
    blanks = []
    for px, py in pans:
        for z in probes:
            page.evaluate("(a) => { const R = window.KG.renderer; R.camera.panX = a[0];"
                          " R.camera.panY = a[1]; R.setZoom(a[2]); }", [px, py, z])
            page.wait_for_timeout(45)
            s = page.evaluate(CANVAS_LIT)
            if s["lit"] < 500:
                blanks.append((px, py, z, s["shown"], s["painted"], s["lit"]))
    print("    扫了 %d 组（%d 缩放 × %d 平移），空白且无提示：%d 组"
          % (len(probes) * len(pans), len(probes), len(pans), len(blanks)))
    check("no zoom/pan combination leaves a blank canvas with no hint",
          not blanks, str(blanks[:3]))
    check("no pageerror during the zoom/pan sweep", not perr, "; ".join(perr[:2]))
    # 收尾必须是**瞬时**归位，不能靠 resetView()：那是 364ms 的 tween，而极端 zoom 下
    # 每一帧绘制极慢（要把半径上百万像素的圆弧栅格化），rAF 被拖住、tween 迟迟走不完，
    # 后面的段落就会在「相机还在飞」的中间态上取样（实测把 _sr 读成 378442px 而实际
    # 该是 38px，进而挑错目标节点）。测试要的是确定的起始状态，不是动画。
    page.evaluate("""() => { const R = window.KG.renderer;
        const cc = R.centerScreen();
        R.setZoom(R.zHome); R.camera.panX = cc[0]; R.camera.panY = cc[1]; R.draw(); }""")
    page.wait_for_timeout(250)

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
        # 在**放大之前**取全库落笔占比（放大后当然会变小，放后面取会永远不成立）
        painted_ratio_before = page.evaluate(
            "() => window.KG.renderer.stats.painted / Math.max(1, window.KG.renderer.NODES.length)")
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
        # 2026-10-24 阶段 2：宽扇出的库（wide-roots 实测 90 → 90）在 home 就把靶子的**全部**
        # 后代画出来了 —— 这时「放大露出更多」的前提不成立。判据直接从节点树数真实后代总数
        # （与 DESC_COUNT 同口径），而不是用 PICK_NODE 报的 desc（含自身/口径差会误判）。
        total_desc = page.evaluate("""(id) => {
            const R = window.KG.renderer; let n = 0;
            for (const x of R.NODES) {
                let cur = x.parent, guard = 0;
                while (cur && guard++ < 200) {
                    if (cur === id) { n++; break; }
                    const p = R.byId.get(cur); cur = p ? p.parent : null;
                }
            }
            return n; }""", tgt["id"])
        if before >= total_desc or meta["maxDepth"] <= s_before["level"] + 1:
            skip_check("zooming in reveals more of the target's subtree",
                       "靶子的 %d 个后代在 home 已画出 %d 个；depth=%s、home 在第 %s 层，"
                       "下面只剩 %d 层可揭（不足两层），本用例前提不成立"
                       % (total_desc, before, meta["maxDepth"], s_before["level"],
                          meta["maxDepth"] - s_before["level"]))
        else:
            check("zooming in reveals more of the target's subtree",
                  after > before, "%d -> %d（共 %d 个后代）" % (before, after, total_desc))
        check("the target itself stays visible while zooming in",
              page.evaluate("(id) => window.KG.renderer.alphaOf(id)", tgt["id"]) > 0.05)
        check("level did not go backwards", s_after["level"] >= s_before["level"],
              "%d -> %d" % (s_before["level"], s_after["level"]))
        shot("08_lod")

    print("\n=== 5. keyboard [ / ] ===")
    page.evaluate("(n) => window.KG.setLevel(n)", LV_START)
    page.wait_for_timeout(700)
    a = page.evaluate(STATE)["level"]
    page.keyboard.press("BracketRight")
    page.wait_for_timeout(750)
    b2 = page.evaluate(STATE)["level"]
    page.keyboard.press("BracketLeft")
    page.wait_for_timeout(750)
    c2 = page.evaluate(STATE)["level"]
    print("    setLevel(%d)=%d  ] -> %d  [ -> %d" % (LV_START, a, b2, c2))
    check("] deepens", b2 > a, "%d->%d" % (a, b2))
    check("[ shallows", c2 < b2, "%d->%d" % (b2, c2))

    print("\n=== 5b. arrow keys pan the camera — and must NOT disturb the selection ===")
    # 用户报的问题：想看两个远处元素之间的箭头，而平移只能靠鼠标拖；拖的过程中一次不到
    # 5px 的抖动会被判成点击（render.js 的 dragMoved > 5），于是选中切到别的大父圆上，
    # 焦点模式立刻把想看的箭头滤掉。方向键平移把「平移」与「点击」解耦：panBy 不碰
    # selectedId，所以这条断言要同时钉住「画面动了」和「选中一点没变」。
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(800)

    def cam():
        return page.evaluate("""() => { const R = window.KG.renderer;
            return {x: R.camera.panX, y: R.camera.panY, sel: R.selected,
                    fx: R.stats.focusEdges, z: R.camera.zoom}; }""")

    step = page.evaluate("() => window.KG.renderer.panStep(false)")
    step_fast = page.evaluate("() => window.KG.renderer.panStep(true)")
    # 先钉住「鼠标拖拽平移仍然可用」—— 加方向键是**增加**一条通道，不是替换掉原来那条。
    # 顺带验 render.js 的点击/拖拽阈值（dragMoved > 5）：拖了 120/80 px 之后不该被当成
    # 点击去改选中，否则用户只是想把画面挪一挪就把焦点过滤换了一轮。
    d0 = cam()
    page.mouse.move(720, 430)
    page.mouse.down()
    page.mouse.move(840, 510, steps=8)
    page.mouse.up()
    page.wait_for_timeout(250)
    d1 = cam()
    print("    拖拽 (120,80): panX %.1f -> %.1f ; panY %.1f -> %.1f ; 选中 %s -> %s"
          % (d0["x"], d1["x"], d0["y"], d1["y"], d0["sel"], d1["sel"]))
    check("mouse drag still pans, by exactly the drag distance",
          abs((d1["x"] - d0["x"]) - 120) < 1 and abs((d1["y"] - d0["y"]) - 80) < 1,
          "dx=%.1f dy=%.1f" % (d1["x"] - d0["x"], d1["y"] - d0["y"]))
    check("a real drag is not treated as a click (selection untouched)",
          d1["sel"] == d0["sel"], "%s -> %s" % (d0["sel"], d1["sel"]))

    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(800)
    p0 = cam()
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(150)
    p1 = cam()
    print("    ArrowRight: panX %.1f -> %.1f (panStep %.1f)  zoom 不变=%s"
          % (p0["x"], p1["x"], step[0], abs(p1["z"] - p0["z"]) < 1e-12))
    check("ArrowRight pans right by exactly one panStep",
          abs((p1["x"] - p0["x"]) - step[0]) < 0.5, "%.2f vs %.2f" % (p1["x"] - p0["x"], step[0]))
    check("arrow panning does not change the zoom", abs(p1["z"] - p0["z"]) < 1e-12,
          "%.6f -> %.6f" % (p0["z"], p1["z"]))

    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(150)
    p2 = cam()
    check("ArrowDown pans down by exactly one panStep",
          abs((p2["y"] - p1["y"]) - step[1]) < 0.5, "%.2f vs %.2f" % (p2["y"] - p1["y"], step[1]))

    page.keyboard.down("Shift")
    page.keyboard.press("ArrowRight")
    page.keyboard.up("Shift")
    page.wait_for_timeout(150)
    p3 = cam()
    print("    Shift+ArrowRight 位移 %.1f（期望 %.1f，≈4×普通）" % (p3["x"] - p2["x"], step_fast[0]))
    check("Shift+Arrow pans about 4x further",
          abs((p3["x"] - p2["x"]) - step_fast[0]) < 0.5, "%.2f vs %.2f" % (p3["x"] - p2["x"], step_fast[0]))

    # 核心：选中之后平移，选中与焦点边数都必须纹丝不动。
    # 必须挑一个**真的有连线**的节点：随便挑个孤立节点的话 focusEdges 恒为 0，
    # 这条断言就退化成 0 == 0 的空转 —— 看起来有覆盖，其实什么都没验。
    # 所以在页面里先搜一遍：谁能选出 >0 条焦点边就用谁，并把「确实有边」当前置条件。
    pick = page.evaluate("""() => {
        const R = window.KG.renderer;
        const keep = R.selected;
        // 门槛 0.2 而不是 0.95：层级带之后 home 上最大的 alpha 只有约 0.5（第 2 层正
        // 落在淡入带半程），旧门槛会把候选集筛空、整段被静默跳过。0.2 仍然要求
        // 「在画面上明确可见」，只是不再要求饱和。
        const cand = R.NODES.filter(n => R.alphaOf(n.id) > 0.2).slice(0, 300);
        let hit = null;
        for (const n of cand) {
            R.selected = n.id; R.draw();
            if (R.stats.focusEdges > 0) { hit = {id: n.id, fx: R.stats.focusEdges}; break; }
        }
        R.selected = keep; R.draw();
        return hit;
    }""")
    if not pick:
        warns.append("no visible node with focus edges found -> 'pan keeps the arrow' check skipped")
    else:
        sel_id = pick["id"]
        page.evaluate("(id) => { window.KG.renderer.selected = id; }", sel_id)
        page.wait_for_timeout(400)
        s0 = cam()
        check("precondition: the picked node really has focus edges (else this test is vacuous)",
              s0["fx"] > 0, "%s fx=%d" % (sel_id, s0["fx"]))
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(300)
        s1 = cam()
        print("    选中 %s（%d 条焦点边）后按两次 ArrowLeft：sel %s -> %s ; focusEdges %d -> %d ; panX %.1f -> %.1f"
              % (sel_id, s0["fx"], s0["sel"], s1["sel"], s0["fx"], s1["fx"], s0["x"], s1["x"]))
        check("panning keeps the selection", s1["sel"] == s0["sel"] == sel_id,
              "%s -> %s" % (s0["sel"], s1["sel"]))
        check("panning actually moved the camera", abs(s1["x"] - s0["x"]) > 1,
              "%.1f -> %.1f" % (s0["x"], s1["x"]))
        check("the selected element still shows focus edges after panning",
              s1["fx"] > 0, "%d -> %d" % (s0["fx"], s1["fx"]))
        # 注意：**不能**断言 focusEdges 前后严格相等。它是屏幕空间的视觉计数：
        # 主绘制趟按视口裁掉整条线段出屏的边（render.js 的 bbox 门），被挡下的焦点边
        # 交 drawFocusEdges 兜底计数，而它按「真实端点 + 关系类型」分组去重 —— 平移会让
        # 分组自然合并/拆分，计数本来就会变（实测 public 上 2 -> 1）。真正承诺的契约是
        # 「状态没被改动」—— 挪出去再挪回来，画面必须回到逐位相同。这条既严格又不会
        # 因为屏内屏外而假红。
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(400)
        back = cam()
        check("panning away and back restores the same focus edge count and position "
              "(panning only moves the camera, it never edits the focus state)",
              back["fx"] == s0["fx"] and abs(back["x"] - s0["x"]) < 1,
              "fx %d -> %d ; panX %.1f -> %.1f" % (s0["fx"], back["fx"], s0["x"], back["x"]))

    # 搜索框里按方向键应该是移动光标，不是平移画布（app.js 的 input/select 守卫）
    page.keyboard.press("/")
    page.wait_for_timeout(200)
    q0 = cam()
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(200)
    q1 = cam()
    check("arrows do not pan while the search box has focus",
          abs(q1["x"] - q0["x"]) < 1e-9, "%.2f -> %.2f" % (q0["x"], q1["x"]))
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)

    # panBy 必须像拖拽一样取消进行中的 tween，否则两者会互相拉扯
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(800)
    page.evaluate("() => window.KG.renderer.zoomToDepth(6)")
    page.wait_for_timeout(60)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(500)
    tz1 = page.evaluate("() => window.KG.renderer.camera.zoom")
    page.wait_for_timeout(500)
    tz2 = page.evaluate("() => window.KG.renderer.camera.zoom")
    check("panBy cancels an in-flight tween (zoom stops changing)",
          abs(tz2 - tz1) < 1e-12, "%.6f -> %.6f" % (tz1, tz2))
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(700)

    print("\n=== 6. bug A regression: HUD must follow programmatic zoom ===")
    page.evaluate("(n) => window.KG.setLevel(n)", LV_START)
    page.wait_for_timeout(800)
    pill = page.evaluate("() => { const e = document.querySelector('#pills .on'); return e ? e.textContent.trim() : null; }")
    ro = page.evaluate("() => document.getElementById('readout').textContent")
    print("    after setLevel(%d): active pill=%r readout=%r" % (LV_START, pill, ro[:90]))
    check("a pill is active", pill is not None)
    check("active pill == %d after KG.setLevel(%d) (was stuck at the last wheel level)"
          % (LV_START, LV_START), pill == str(LV_START), str(pill))
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

    # 7b/7c/7d 验的是「焦点过滤 + 端点标记 + 屏外 chip」这几条硬不变式。
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
    check_edge("focus test starts from a view that has edges", base_edges > 0, str(base_edges))
    check_edge("no focus stats while nothing is selected",
          st0["focusEdges"] == 0 and st0["focusNeighbors"] == 0,
          "focusEdges=%s focusNeighbors=%s" % (st0["focusEdges"], st0["focusNeighbors"]))
    # 每条边最多两个端点标记（源端一个 + 目标端一个），所以 marks <= 2*edges 是硬上界。
    # 下界 marks > 0 才是这轮的重点：home 视图里必须有标记，否则「看不出线的头尾」
    # 这个原始痛点根本没被解决。
    check_edge("endpoint markers are drawn in the home view", st0["marks"] > 0, str(st0["marks"]))
    check_edge("markers never exceed two per drawn edge",
          st0["marks"] <= 2 * base_edges,
          "%d marks / %d edges" % (st0["marks"], base_edges))

    # 靶子探测挪到**第 4 层**：层级带之后 home（第 2 层）只落笔 ~17 个圆，且屏上
    # 这些圆的邻居大多还没浮现 ⇒ focusNeighbors 恒为 0、相关边在 home 尺度下短于
    # raw_marker_min_len，取样集为空（整段会被 weaken 掉甚至假红）。第 4 层既够深（邻居
    # 已落笔）又够浅（同屏圆够多），是这段判据的合适取样点。
    # 前面那几条「home 视图必须有标记」的断言已经在 home 上跑过了，这里只换取样点。
    page.evaluate("() => window.KG.setLevel(4)")
    page.wait_for_timeout(900)
    st0 = page.evaluate(STATE)
    base_edges = st0["shownEdges"]
    print("    probe baseline (level %d): shownNodes=%d shownEdges=%d zoom=%.4f"
          % (st0["level"], st0["shownNodes"], base_edges, st0["zoom"]))
    check_edge("focus probe view still has edges", base_edges > 0, str(base_edges))

    # 靶子探测：把屏上每个圆轮流设成选中、强制重画、读真实 stats。不在测试里复刻
    # isFocusSide 的判据 —— 复刻的判据一旦和实现漂移就会假绿（本文件既有风格）。
    # 取样点同样要求画布在最上层：图例 / 侧栏盖住的点能探到圆、却点不着（假红）。
    probe = page.evaluate("""() => {
        const R = window.KG.renderer; const [W, H] = R.size();
        const cvEl = document.getElementById('cv');
        const cr = cvEl.getBoundingClientRect();
        const seen = new Set(); const out = [];
        for (let y = H * 0.15; y < H * 0.85; y += 6) {
            for (let x = W * 0.10; x < W * 0.90; x += 6) {
                if (document.elementFromPoint(cr.left + x, cr.top + y) !== cvEl) continue;
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
        check_edge("click selected the probed node", s["selected"] == tgt["id"],
              "%s vs %s" % (s["selected"], tgt["id"]))
        # 阶段 2.2：边密集的库会按可见面积做确定性抽稀（stride>1），此时「焦点模式前后
        # shownEdges 相等」这条前提不成立（焦点边不抽、冷边抽），显式跳过而不是判红。
        if SHAPE_OK.get("edge_stride", True):
            check_edge("focus keeps every edge on canvas (dim, not delete)",
                       s["shownEdges"] == base_edges, "%d vs base %d"
                       % (s["shownEdges"], base_edges))
        else:
            skip_check("focus keeps every edge on canvas (dim, not delete)",
                       SHAPE_WHY["edge_stride"])
        check_edge("focus marks some (not all) edges related",
              0 < s["focusEdges"] < s["shownEdges"],
              "%d of %d" % (s["focusEdges"], s["shownEdges"]))
        check_edge("real click agrees with the programmatic probe",
              s["focusEdges"] == tgt["rel"], "%d vs %d" % (s["focusEdges"], tgt["rel"]))
        check_edge("focus rings at least one neighbour", s["focusNeighbors"] > 0,
              str(s["focusNeighbors"]))
        # 这是本节最锋利的一条断言：上界用 focusEdges（相关边）而不是 shownEdges（全部边）。
        # 无关边被压到 focus_edge_dim=0.07，标记的 alpha 门槛是 0.1 —— 0.07 过不去，
        # 于是冷边一个标记都不该冒出来。上界写成 2*shownEdges 就退化成永真式了。
        check_edge("markers appear on related edges only (cold 7% edges stay bare)",
              0 < s["marks"] <= 2 * s["focusEdges"],
              "%d marks / %d related edges (%d drawn in total)"
              % (s["marks"], s["focusEdges"], s["shownEdges"]))
        shot("09_focus")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        e = page.evaluate(STATE)
        check_edge("Escape drops the focus filter",
              e["selected"] is None and e["focusEdges"] == 0 and e["focusNeighbors"] == 0,
              json.dumps({k: e[k] for k in ("selected", "focusEdges", "focusNeighbors")},
                         ensure_ascii=False))
        if SHAPE_OK.get("edge_stride", True):
            check_edge("Escape restores the full edge count", e["shownEdges"] == base_edges,
                       "%d vs %d" % (e["shownEdges"], base_edges))
        else:
            skip_check("Escape restores the full edge count", SHAPE_WHY["edge_stride"])
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
                rawMinLen: lod.raw_marker_min_len,
                tint: lod.edge_marker_tint,
                zoom: Math.round(z * 10000) / 10000};
    }""")
    print("    ", json.dumps(geo, ensure_ascii=False))
    check_edge("three marker knobs reached META.lod through build.py",
          geo["trim"] is not None and geo["rawMinLen"] is not None
          and geo["tint"] is not None,
          "trim=%s rawMinLen=%s tint=%s"
          % (geo["trim"], geo["rawMinLen"], geo["tint"]))
    check_edge("markers exist to measure", geo["marks"] > 0, str(geo["marks"]))
    check_edge("every marker resolves to the node it is attached to",
          geo["checked"] == geo["marks"], "%d of %d" % (geo["checked"], geo["marks"]))
    check_edge("no marker is buried inside its node circle",
          geo["inside"] == 0, "%d of %d inside" % (geo["inside"], geo["checked"]))
    # 截断把端点放在「屏幕半径 + TRIM」处，所以间隙应当**恒等于** TRIM（连线恒为
    # 直线、端点沿弦方向截断，取整只会带来零点几 px 的余量）。
    check_edge("markers sit just outside the circle, by the configured clearance",
          geo["minGap"] >= geo["trim"] - 0.75 and geo["maxGap"] <= geo["trim"] + 2.0,
          "gap in [%s, %s] px vs trim=%s px" % (geo["minGap"], geo["maxGap"], geo["trim"]))
    # 有向边（derives / prerequisite）目标端画箭头，源端画点；无向边两端都是点。
    # 本库当前 92 条 derives、0 条 contrast —— 所以 home 视图里两种标记都该有。
    check_edge("both arrow heads and source dots are produced",
          geo["arrows"] > 0 and geo["dots"] > 0,
          "%d arrows / %d dots" % (geo["arrows"], geo["dots"]))

    # 深入再看：raw_marker_min_len 守卫在小尺度下应该开始生效（短边不画标记），
    # marks 掉到 2*edges 以下；同时长边仍然要带标记。以前这里写死 depth 6 —— 那是
    # 私有图的形状：公开图在 depth 6 的画面上只剩一条边（数字信号处理(自己理解) →
    # LTI analysis：圆心距 546px，两圆屏幕半径 83+467，截断后只剩 4px），6px 门槛与
    # alpha≥0.1 两道门都合理地压掉了它，marks=0 是数据形状而不是渲染回归（同层私有图
    # 有两条边、其中一条 189px，所以有标记）。
    # 改成沿 payload 自己的 zoom 阶梯（enter[L-1]*1.05，正是 zoomToDepth 用的那一档）
    # 逐层扫，每一层都验「每条边最多两个标记」。判「这一档该不该有标记」的依据不是
    # **边数**而是**边长**：每档都实测「有几条边同时过了长度门与 alpha 门」（下面的
    # long），只对 long>0 的档要求 marks>0。long 只用来判「这一档不要求有标记」，
    # **不**拿来做等式断言（理由见下面两处「刻意不断言」的注释）。
    # 「确实有短边被压掉」仍然是 raw_marker_min_len 守卫唯一能被观测到的地方
    # （marks < 2*edges 的那些档）。
    rungs = []
    # 扫之前清掉选中：选中会把无关连线压到 focus_edge_dim(0.07)，过不了标记的
    # alpha>=0.1 门，marks 于是被焦点状态左右；而下面比较用的 shownEdges 是中立帧的
    # 读数。这一段验的是**普通边标记**的几何，与选中无关，所以先让输入集干净。
    page.evaluate("() => { window.KG.renderer.selected = null; }")
    page.wait_for_timeout(300)
    # 每一档除了计数，还要量「这一帧真正落笔的边，两端截断后各有多长」。
    # 标记有两道门（raw_marker_min_len 与 alpha>=0.1），所以 marks=0 未必是回归：
    # 可能这一档所有边都短于门槛（实测某些档两条边截断后各只有 4.0px，被门压掉是
    # 对的，「有 >=2 条边就必须有标记」于是假红）。要区分「守卫正常工作」和「渲染丢了
    # 标记」，就得知道边的长度；而截断公式在 drawEdges / drawSegment 里（圆心距减两端
    # 屏幕半径再减 TRIM，恒为直线、没有控制点偏移），在测试里复刻一遍正是 7c 上面那几条
    # 断言刻意避免的事。改成从 canvas 侧量：包一层 moveTo / lineTo，把每条「两点 +
    # round cap」的路径记下来 —— 圆走 arc 不经过 moveTo，端点标记是多段路径，正好都
    # 被这个过滤器排掉。
    # ⚠️ 记到的条数**不保证**与 state().shownEdges 恒等：实测 private L=1 探针多记到
    # 1 条（53 vs 52）。所以这个探针只做诊断打印（long / longest 两列），不拿来做等式
    # 断言。
    SEGS = """() => {
        const R = window.KG.renderer;
        const lod = (window.KG.data.meta || {}).lod || {};
        // 标记门槛就是 raw_marker_min_len（默认 6）；用错旋钮会让 long 列整列判错。
        const MM = lod.raw_marker_min_len == null ? 6 : lod.raw_marker_min_len;
        const proto = CanvasRenderingContext2D.prototype;
        const om = proto.moveTo, ol = proto.lineTo, oq = proto.quadraticCurveTo;
        const rec = []; let cur = null;
        proto.moveTo = function (x, y) {
            cur = {p: [[x, y]], cap: this.lineCap, a: this.globalAlpha};
            rec.push(cur); return om.apply(this, arguments);
        };
        proto.lineTo = function (x, y) {
            if (cur) cur.p.push([x, y]); return ol.apply(this, arguments);
        };
        proto.quadraticCurveTo = function (cx, cy, x, y) {
            if (cur) cur.p.push([x, y]); return oq.apply(this, arguments);
        };
        try { R.draw(); } finally {
            proto.moveTo = om; proto.lineTo = ol; proto.quadraticCurveTo = oq;
        }
        let long = 0, maxLen = 0, n = 0;
        for (const r of rec) {
            if (r.p.length !== 2 || r.cap !== 'round') continue;
            n++;
            const dx = r.p[1][0] - r.p[0][0], dy = r.p[1][1] - r.p[0][1];
            const len = Math.sqrt(dx * dx + dy * dy);
            if (len > maxLen) maxLen = len;
            // 两道门与 render.js 同序：长度门在前，alpha 门在后。没有选中/悬停时
            // 标记用的 alpha 就等于连线自己的 globalAlpha（热边才有 0.75 地板值）。
            if (len >= MM && r.a >= 0.1) long++;
        }
        return {n: n, long: long, minLen: MM,
                maxLen: Math.round(maxLen * 100) / 100};
    }"""
    for L in range(meta["maxDepth"], 0, -1):
        page.evaluate("(L) => window.KG.renderer.zoomToDepth(L)", L)
        page.wait_for_timeout(850)
        s = page.evaluate(STATE)
        g = page.evaluate(SEGS)
        rungs.append((L, s["zoom"], s["shownEdges"], s["marks"], g["long"], g["n"], g["maxLen"]))
    for L, z, e, m, lg, n, mx in rungs:
        print("    rung L=%2d zoom=%8.4f edges=%3d marks=%3d long=%3d longest=%8.2fpx"
              % (L, z, e, m, lg, mx))
    # 这里刻意**不**断言「探针线段数 == shownEdges」：那不是不变量。被 TRIM 压到零长度
    # 的边、以及 focus/ancestor 兜底路径都会让两个计数差上一两条（实测 private L=1 差
    # 1 条，public 全档相等 —— 差异随数据形状走）。探针的价值在于 long / longest 两列：
    # 它们让「这一档 marks=0」可解释（边太短，守卫正常工作）而不是靠猜。
    long_rungs = [r for r in rungs if r[4] > 0]
    print("    rungs with an edge long enough for markers: %s" % [r[0] for r in long_rungs])
    check_edge("deep rungs still draw markers for the long edges",
          bool(long_rungs) and all(m > 0 for _, _, _, m, _, _, _ in long_rungs),
          "rungs %s" % [(L, e, m, lg) for L, _, e, m, lg, _, _ in long_rungs])
    # 硬不变式是 **≤** 2×edges：每条画出的边最多落两个标记（源端圆点 + 目标端箭头）。
    # 不能写成严格 `<`：一条边上两个标记本来就是正常的，所以「三条边全长、共 6 个标记」
    # 完全合法（实测 rung L=7 就是 3/6），严格小于会在正常数据上假红。
    check_edge("never more than two markers per drawn edge (hard invariant)",
          all(m <= 2 * e for _, _, e, m, _, _, _ in rungs),
          "all %s" % [(L, m, 2 * e) for L, _, e, m, _, _, _ in rungs])
    # 这里也刻意**不**断言 marks == 2×long。看着像等式，其实不是：long 是探针在 canvas 侧
    # 量的**截断后弦长**，只是 render.js 判门用的 glen 的近似下界（TRIM 退让方向、标记
    # 自身的截断与取整都会让两者错开），所以「渲染器认为该挂、探针量出来不够」是正常的。
    # 绑上去就是间歇性假红。真正钉得住的是上面那条硬不变式（marks ≤ 2×edges）与下面
    # 那条「守卫确实压掉过标记」。
    # raw_marker_min_len 守卫是否真的在生效，用「阶梯上存在某档标记数严格少于 2×edges」
    # 来证明 —— 也就是确实有短边被压掉了。只要有边界够短，这一条就会亮；守卫一旦被删掉
    # 整条阶梯都会顶满 2×edges，这条就红。
    suppressed = [(L, e, m) for L, _, e, m, _, _, _ in rungs if m < 2 * e]
    check_edge("the min-length guard really suppresses some markers somewhere on the ladder",
          bool(suppressed), "rungs with marks < 2*edges: %s" % [(L, m, 2 * e) for L, e, m in suppressed])
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(900)

    print("\n=== 7d. off-screen focus target: name chip + fitPair ===")
    # 深缩放时链接的一端常常在屏外。线本来就一路画到屏外、方向看得见，缺的只是
    # 「屏外那一端叫什么名字」—— 所以 chip 由 drawEdges 主循环挂在线穿出视口的那
    # 一点；两端都在屏外时也挂一枚（命名非焦点端）。侧栏边行点击再用一次 tween 把
    # 链接两端一起框进视口（fitPair）。这里用真实相机钉住这两条后路。
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
        const linked = (a, b) => R.SEM.some(e => (e.s === a.id && e.t === b.id) ||
                                                 (e.s === b.id && e.t === a.id));
        const a0 = find(tails[0]), b0 = find(tails[1]);
        if (a0 && b0 && linked(a0, b0)) return {pair: [a0.id, b0.id], how: 'author-fixture'};
        // 阶段 0.3：作者库那两条笔记名在别的库上当然不存在。通用兜底 = 挑一条两端世界距离
        // 最大的语义边（深缩放时更容易一端出屏），仍然完全由 payload 决定。
        let best = null;
        for (const e of R.SEM) {
            const a = R.byId.get(e.s), b = R.byId.get(e.t);
            if (!a || !b) continue;
            const d = Math.hypot((a.x || 0) - (b.x || 0), (a.y || 0) - (b.y || 0));
            if (!best || d > best.d) best = {d: d, pair: [e.s, e.t]};
        }
        return best ? {pair: best.pair, how: 'generic-farthest-edge'} : null;
    }""", [SEL_TAIL, TGT_TAIL])
    if pair and "how" in pair:
        print("    pair source: %s" % pair["how"])
        pair = pair["pair"]
    if not pair:
        warns.append("这个库没有可用的语义边对 -> 7d 跳过（不是回归）")
        print("    !! no usable edge pair; skipping 7d")
    else:
        SEL_ID, TGT_ID = pair
        # 阶段 0.3：chip 上的名字要跟 fixture 走（原来是作者库那条的具体标题文字）。
        TGT_LABEL = page.evaluate(
            "(id) => (window.KG.renderer.byId.get(id) || {}).label || ''", TGT_ID)
        TGT_KEY = (TGT_LABEL or "").strip()[:8] or TGT_ID.split("/")[-1][:8]
        print("    fixture resolved: SEL=…/%s  TGT=…/%s"
              % (SEL_ID.split("/")[-1], TGT_ID.split("/")[-1]))
        # (a) 深缩放：选中圆在屏、链接目标屏外 -> 线一路画到屏外，chip 写明目标是谁
        a = page.evaluate("""(ids) => {
            const R = window.KG.renderer;
            R.selected = null;
            R.focusOn(ids[0], 1.25, 0);
            R.selected = ids[0]; R.draw();
            const st = window.KG.state();
            return {focusEdges: st.focusEdges, chips: st.chips,
                    chipTexts: R.chipJobs.filter(j => j.id === ids[1]).map(j => j.text),
                    selDot: R.markJobs.some(j => j.k === 0 && j.id === ids[0])};
        }""", [SEL_ID, TGT_ID])
        print("    ", json.dumps(a, ensure_ascii=False))
        check_edge("focus edge to an off-screen target still counts as drawn",
              a["focusEdges"] >= 1, str(a["focusEdges"]))
        # 阶段 2.2 泛化：chip 有 CHIP_MAX=8 的折叠上限。焦点的这个端点如果本来就出度很大
        # （edge-storm 的 Note 们各 12 条链接），chip 列表会被折叠成「+k」，这时「这一枚
        # 名字牌写着目标」的前提不成立 —— 显式跳过，而不是判红。
        if a["chips"] > 8 or not a["chipTexts"]:
            skip_check("off-screen target gets a name chip",
                       "chip 列表折叠成 +k（焦点端点出度大，超过 CHIP_MAX=8）")
            skip_check("chip carries the off-screen target's name",
                       "chip 列表折叠成 +k（同上）")
        else:
            check_edge("off-screen target gets a name chip",
                       a["chips"] >= 1 and len(a["chipTexts"]) >= 1,
                       "chips=%s texts=%s" % (a["chips"], a["chipTexts"]))
            check_edge("chip carries the off-screen target's name",
                       bool(a["chipTexts"]) and a["chipTexts"][0].startswith(TGT_KEY),
                       str(a["chipTexts"][:1]))
        check_edge("on-screen end keeps its source dot", a["selDot"])
        shot("11_chip")

        # (a2) 两端都出屏：纯平移把选中圆整个推出屏（缩放不动），链接目标本来就已经在
        # 屏外。线照画（横穿视口就该看得见），chip 挂**一枚**、名字给非焦点端（这里就是
        # 目标端）。钉的是用户报的那个痛点：「方向键平移一下，选中项整圆出屏，名字牌跟着
        # 消失，就再也读不出这条线通向谁」。
        # 断言只验「有没有一枚、名字是谁、锚点在不在内容视口里」，不复刻 entryToward 的
        # 入口公式 —— 复刻的几何一旦和实现漂移就会假绿（本文件既有风格）。上面 JS 里那段
        # Liang-Barsky 是**前置条件**不是断言：线不横穿视口时「没有 chip」本来就对，那时
        # warn + skip，而不是让一条红得毫无信息量的断言留在这儿。
        a2 = page.evaluate("""(ids) => {
            const R = window.KG.renderer; const [W, H] = R.size(); const Hc = H - 46;
            R.selected = null;
            R.focusOn(ids[0], 1.25, 0);
            R.selected = ids[0];
            // 纯平移、缩放不动（钉的就是「方向键平移一下」那一下）。方向取「远离链接
            // 另一端」：选中圆被推出屏的同时，线段必定横穿视口。往别处推会让两端落到
            // 同一侧、线压根不进屏，那时「一枚 chip 也没有」才是对的，测出来只是假红。
            const cam = R.camera;
            const A = R.byId.get(ids[0]), B = R.byId.get(ids[1]);
            const dx = B.x - A.x, dy = B.y - A.y;
            const d = Math.hypot(dx, dy) || 1;
            const ux = dx / d, uy = dy / d;
            const push = Math.hypot(W, Hc) + A._r * cam.zoom + 60;
            R.panBy(-ux * push, -uy * push);
            R.draw();
            const scr = (m) => [m.x * cam.zoom + cam.panX, m.y * cam.zoom + cam.panY];
            const off = (m) => {
                const [x, y] = scr(m), r = m._r * cam.zoom;
                return x + r < 0 || x - r > W || y + r < 0 || y - r > Hc;
            };
            // 线段真的横穿内容视口吗（Liang-Barsky）。这里只当**前置条件**用，不当断言：
            // 万一和实现的 entryToward 漂了，结果是 warn+skip，不会假绿。
            const crosses = (() => {
                const [x0, y0] = scr(A), [x1, y1] = scr(B);
                const vx = x1 - x0, vy = y1 - y0;
                let t0 = 0, t1 = 1;
                for (const [p, q] of [[-vx, x0], [vx, W - x0], [-vy, y0], [vy, Hc - y0]]) {
                    if (Math.abs(p) < 1e-9) { if (q < 0) return false; continue; }
                    const r = q / p;
                    if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; }
                    else { if (r < t0) return false; if (r < t1) t1 = r; }
                }
                return true;
            })();
            const st = window.KG.state();
            return {bothOff: off(A) && off(B), crosses: crosses,
                    focusEdges: st.focusEdges, chips: st.chips, shownEdges: st.shownEdges,
                    tgtChips: R.chipJobs.filter(j => j.id === ids[1]).map(j => j.text),
                    selChips: R.chipJobs.filter(j => j.id === ids[0]).map(j => j.text),
                    anchored: R.chipJobs.length > 0 &&
                              R.chipJobs.every(j => j.px >= -1 && j.px <= W + 1 &&
                                                       j.py >= -1 && j.py <= Hc + 1)};
        }""", [SEL_ID, TGT_ID])
        print("    ", json.dumps(a2, ensure_ascii=False))
        if not (a2["bothOff"] and a2["crosses"]):
            warns.append("fixture did not put both ends off screen across the viewport "
                         "(bothOff=%s crosses=%s) -> a2 (both-off chip) skipped"
                         % (a2["bothOff"], a2["crosses"]))
            print("    !! both ends not off screen across the viewport; skipping a2")
        else:
            # 阶段 2.2 泛化：这条用例的前提是「只有一条焦点边横穿视口」。出度大的端点会
            # 同时有多条边出屏，chip 会被折叠/出现多枚 —— 那时「恰好一枚」不成立，显式跳过。
            if a2["chips"] == 1 and len(a2["tgtChips"]) == 1:
                check_edge("both ends off screen: the crossing edge still keeps one name chip",
                           a2["chips"] == 1,
                           "chips=%s focusEdges=%s shownEdges=%s"
                           % (a2["chips"], a2["focusEdges"], a2["shownEdges"]))
            else:
                skip_check("both ends off screen: the crossing edge still keeps one name chip",
                           "焦点端出度大 / chip 已折叠（chips=%s，目标 chip=%d 枚）"
                           % (a2["chips"], len(a2["tgtChips"])))
            if a2["chips"] == 1 and len(a2["tgtChips"]) == 1:
                check_edge("that chip names the off-screen target, not the selection",
                           bool(a2["tgtChips"]) and not a2["selChips"] and
                           all(t.startswith(TGT_KEY) for t in a2["tgtChips"]),
                           "tgt=%s sel=%s" % (a2["tgtChips"], a2["selChips"]))
            else:
                skip_check("that chip names the off-screen target, not the selection",
                           "多枚 chip（焦点端出度大）—— 「唯一一枚写着目标」的前提不成立")
            check_edge("both-off chip anchor lands inside the content viewport",
                  a2["anchored"], str(a2["anchored"]))
            shot("11b_both_off_chip")

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
        check_edge("chip list never exceeds CHIP_MAX+1",
              all(p["n"] <= chip_max + 1 for p in probes),
              str(max(p["n"] for p in probes)))
        check_edge("overflow collapses into exactly one right-anchored +k chip",
              all((p["n"] > chip_max) == p["lastRight"] for p in probes) and
              all(p["lastText"].startswith("+") and p["lastText"][1:].isdigit()
                  for p in probes if p["n"] > chip_max),
              str(collapsed[:2]))
        if not collapsed:
            warns.append("no hub probe exceeded CHIP_MAX -> +k chip untested")

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
                if (document.elementFromPoint(cv.left + x, cv.top + y) !==
                    document.getElementById('cv')) continue;
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
            check_edge("real click selects the fixture node",
                  page.evaluate(STATE)["selected"] == SEL_ID)
            row = page.evaluate("""(ids) => {
                const lis = [...document.querySelectorAll('#sidebar li')];
                const li = lis.find(l => l.dataset.self === ids[0] && l.dataset.target === ids[1]);
                if (!li) return {found: false, rows: lis.length};
                li.click();
                return {found: true, rows: lis.length};
            }""", [SEL_ID, TGT_ID])
            print("    sidebar edge rows=%d, fixture row found=%s" % (row["rows"], row["found"]))
            check_edge("sidebar lists the fixture edge as a clickable row", row["found"], str(row["rows"]))
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
            check_edge("clicking the edge row selects the link target",
                  fit["selected"] == TGT_ID, str(fit["selected"]))
            check_edge("fitPair frames both link ends inside the viewport", fit["okA"] and fit["okB"])
            check_edge("the framed pair still draws its focus edge + markers",
                  fit["focusEdges"] >= 1 and fit["marks"] > 0,
                  "focusEdges=%s marks=%s" % (fit["focusEdges"], fit["marks"]))
            shot("13_fitpair")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        page.evaluate("() => window.KG.renderer.resetView()")
        page.wait_for_timeout(900)

    print("\n=== 8. search ===")
    # 阶段 0.3：查询词不再写死「微分方程」—— 从 payload 里取一个笔记名的前两个字，
    # 既保证命中，又对任意库成立。
    q = page.evaluate("""() => {
        const R = window.KG.renderer;
        for (const n of R.NODES) {
            const lab = (n.label || '').trim();
            if (n.kind === 'note' && lab.length >= 2) return lab.slice(0, 2);
        }
        const any = R.NODES.find(n => (n.label || '').trim().length >= 2);
        return any ? any.label.trim().slice(0, 2) : '';
    }""")
    page.fill("#search", q)
    page.keyboard.press("Enter")
    page.wait_for_timeout(900)
    sr = page.evaluate("""() => ({
        hits: document.querySelectorAll('#hits > *').length,
        q: window.KG.state().search,
        first: (document.querySelector('#hits > *') || {}).textContent || null})""")
    print("    ", json.dumps(sr, ensure_ascii=False)[:260])
    check("search recorded the query", sr["q"] == q, repr(sr["q"]))
    check("search produced hits", sr["hits"] > 0, str(sr["hits"]))
    shot("05_search")
    if sr["hits"]:
        page.evaluate("() => document.querySelector('#hits > *').click()")
        page.wait_for_timeout(1000)
        check("clicking a hit selects and focuses it", page.evaluate(STATE)["selected"] is not None)
    page.evaluate("() => window.KG.runSearch('')")
    page.wait_for_timeout(300)

    print("\n=== 8b. 搜索防抖/命中上限与面板自适应（阶段 2.5）===")
    st_search = page.evaluate(STATE)
    # 命中封顶：1 个字符的查询在最坏形状上能匹配全库；matchSet 必须有上限。
    check("search hit set respects the cap (2000)",
          st_search["searchMatches"] <= 2000, str(st_search["searchMatches"]))
    page.evaluate("() => window.KG.runSearch('')")
    page.wait_for_timeout(400)
    check("clearing the search empties the match set",
          page.evaluate(STATE)["searchMatches"] == 0,
          str(page.evaluate(STATE)["searchMatches"]))
    # 图例：学科多时两列，且不许横向溢出（30 个学科的库单列会变成一条长滚动条）
    legend = page.evaluate("""() => {
        const box = document.getElementById('legend-domains');
        const n = ((window.KG.data.meta || {}).domains || []).length;
        return {n: n, display: getComputedStyle(box).display,
                overflow: box.scrollWidth > box.clientWidth + 1,
                panelW: Math.round(document.getElementById('legend').getBoundingClientRect().width),
                vw: window.innerWidth}; }""")
    check("legend switches to two columns only when there are many domains",
          (legend["display"] == "grid") == (legend["n"] > 12),
          "domains=%d display=%s" % (legend["n"], legend["display"]))
    check("legend domains do not overflow horizontally", not legend["overflow"],
          "scrollWidth>clientWidth? %s" % legend["overflow"])
    check("legend panel stays under half the viewport width",
          legend["panelW"] <= legend["vw"] * 0.5 + 1,
          "panel=%dpx vw=%dpx" % (legend["panelW"], legend["vw"]))

    print("\n=== 9. filters (domain) ===")
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(900)
    base = page.evaluate(STATE)["shownNodes"]
    n_domains = page.evaluate("() => document.querySelectorAll('#domain option').length")
    if n_domains <= 2:
        # 阶段 0.3：只有一个学科（或没有学科分组）的库，过滤前后节点数当然一样 ——
        # 这是形状差异，不是缺陷。显式跳过并计数。
        warns.append("只有 %d 个学科选项 -> domain 过滤断言跳过（不是回归）" % n_domains)
        print("    !! only %d domain options; skipping" % n_domains)
    else:
        page.select_option("#domain", index=1)
        page.wait_for_timeout(700)
        filt = page.evaluate(STATE)["shownNodes"]
        print("    shownNodes all=%d  filtered=%d" % (base, filt))
        check("domain filter reduces visible nodes", filt < base, "%d -> %d" % (base, filt))
        # 阶段 2.3：过滤后不许留「残线」—— 只要有一端被过滤掉，那条边就不能画。
        # 判据：这一帧真正画的边数 ≤ 「两端都还在」的语义边数。
        orphans = page.evaluate("""() => { const R = window.KG.renderer; const fs = R.filterSet;
            if (!fs) return null;
            let kept = 0;
            for (const e of R.SEM) { if (fs.has(e.s) && fs.has(e.t)) kept++; }
            return {drawn: R.stats.edges, kept: kept,
                    ghost: R.stats.ghost}; }""")
        print("    edges drawn=%s  both-ends-kept=%s  ghost=%s"
              % (orphans and orphans["drawn"], orphans and orphans["kept"],
                 orphans and orphans["ghost"]))
        check("filtered-out edges are not drawn (no orphan lines)",
              bool(orphans) and orphans["drawn"] <= orphans["kept"],
              json.dumps(orphans, ensure_ascii=False))
        page.select_option("#domain", index=0)
        page.wait_for_timeout(700)
        check("clearing the filter restores", page.evaluate(STATE)["shownNodes"] == base)

    print("\n=== 10. dblclick deepens / dblclick empty resets ===")
    page.evaluate("(n) => window.KG.setLevel(n)", LV_DBL)
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

    # ── 11b. 视口自适应（2026-10-24 阶段 1.5）────────────────────────────────
    # 构建期的阶梯按**标称视口**（1440×900）锚定；运行时 fit 半径随窗口变，所以 home 的
    # 绝对 zoom 会变。设计意图是「home 落在 home_layer 的淡入带里」—— 这必须在任何窗口
    # 尺寸下都成立（小窗略裁外圈、大窗多留边）。这里用渲染器的**原始 zoom**判，
    # 不用 KG.state()（它对 zoom 做了 4 位舍入，卡在带边界上会假红）。
    # 放在最后：它会切窗口尺寸，不能夹在预览 / 相机用例中间。
    print("\n=== 11b. 视口自适应：窗口尺寸不改变 home 的层级（阶段 1.5）===")
    home_layer = meta["homeLayer"]
    band_lo = float(meta["enter"][home_layer - 1])
    band_hi = band_lo * float(meta["fade"])
    for vw, vh in ((1280, 720), (1920, 1080), (1440, 900)):
        page.set_viewport_size({"width": vw, "height": vh})
        page.wait_for_timeout(450)
        page.evaluate("() => window.KG.renderer.resetView()")
        page.wait_for_timeout(900)
        raw = page.evaluate("""() => ({zoom: window.KG.renderer.camera.zoom,
                                       layer: window.KG.renderer.homeLayer,
                                       insets: window.KG.renderer.getInsets()})""")
        tol = max(1e-6, band_hi * 1e-4)
        in_band = (band_lo - tol) <= raw["zoom"] <= (band_hi + tol)
        check("home stays in layer %d's band at %dx%d" % (home_layer, vw, vh),
              raw["layer"] == home_layer and in_band,
              "layer=%s zoom=%.6f band=[%.6f, %.6f] insets=%s"
              % (raw["layer"], raw["zoom"], band_lo, band_hi, raw["insets"]))

    # 侧栏打开时右侧被面板盖住 —— 内容区 inset 必须扣掉它，否则 fit / 居中会把节点藏到面板下
    ins0 = page.evaluate("() => window.KG.renderer.getInsets()")
    picked_side = page.evaluate(PICK_NODE, {"minDepth": 1})
    if picked_side:
        page.mouse.click(picked_side["x"], picked_side["y"])
        page.wait_for_timeout(800)
        ins1 = page.evaluate("() => window.KG.renderer.getInsets()")
        check("opening the sidebar reduces the content width",
              ins1["right"] > 0, "right=%s (was %s)" % (ins1["right"], ins0["right"]))
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        ins2 = page.evaluate("() => window.KG.renderer.getInsets()")
        check("closing the sidebar restores the content width",
              ins2["right"] == 0, "right=%s" % ins2["right"])
    else:
        warns.append("no node picked for sidebar-inset test -> skipped")
    page.evaluate("() => window.KG.renderer.resetView()")
    page.wait_for_timeout(600)

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
    # 阶段 2.2：边密集的库会按可见面积抽稀（stride>1）——这时「20 次 Playwright 滚轮」
    # 的绝对耗时既含协议往返、又含抽稀后的帧数，拿来当阈值没有意义。改判真正重要的量：
    # **单帧绘制耗时**（dense 库实测 3.1 ms），它才是「拖得动拖不动」的证据。
    stride = page.evaluate("() => window.KG.renderer.stats.edgeStride || 1")
    draw_ms = page.evaluate("""() => { const R = window.KG.renderer;
        const t0 = performance.now();
        for (let i = 0; i < 20; i++) R.draw();
        return (performance.now() - t0) / 20; }""")
    if stride > 1:
        check("dense vault: per-frame draw stays under 40ms (edge stride %d)" % stride,
              draw_ms < 40, "%.1f ms/frame" % draw_ms)
    else:
        check("wheel interaction not janky (<3s for 20 steps)", dt < 3000, "%.0fms" % dt)

    check("still no pageerror at end", not perr, "; ".join(perr[:3]))
    check("still no console error at end", not cerr, "; ".join(cerr[:3]))
    b.close()

print("\n" + "=" * 62)
if warns:
    print("WARNINGS:")
    for w in warns:
        print("  -", w)
# 阶段 0.3：机器可读的结果行 —— fixtures/run_sweep.py 靠它做 ok 计数硬闸。
# 没有这一行，「少跑了几条」和「全跑过」在输出上长得一模一样。
print("## BROWSER_RESULT " + json.dumps(
    {"ok": len(oks), "fail": len(fails), "skipped": len(warns),
     "html": os.path.basename(HTML), "vault": EXPECT_VAULT or None},
    ensure_ascii=False))
if fails:
    print("FAILED %d:" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL BROWSER CHECKS PASSED")
