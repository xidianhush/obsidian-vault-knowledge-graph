/* 渲染层：Canvas2D 语义缩放地图。
 *
 * 只干一件事：给定相机 {zoom, panX, panY}，把 payload 画出来。所有「该不该画、
 * 画多透明」都来自构建期算好的世界半径 r（→ minzoom = lod.min_px / r），
 * 渲染期不做任何布局计算 —— 坐标与半径一次算定，所以缩放时节点永不跳动。
 *
 * 方向：**放大（zoom 变大）= 看到更深的层级**，和地图一致。
 * 这个方向不是自动成立的，是 circle packing 的包含几何锁住的：kg/layout.py
 * 保证沿包含链 r 严格递减（父半径 ≥ level_ratio × 最大子半径），于是
 * minzoom = min_px / r 沿链严格递增 —— 孩子永远比父母更晚浮现。
 *
 * ── 圆的大小 = 它在知识树里占的地盘 ────────────────────────────────────────
 * r 不是按层级查表的常量，而是 packing 分配到的世界半径：包含的东西越多半径
 * 越大，且父圆一定套住全部子圆。屏幕半径一律 = r × zoom，所以放大就真的大，
 * 和地图上的省市区一样。父子同色（都继承所属学科的 domain 色），靠描边分界线；
 * 已经有孩子浮现的元素退化成压暗的「底图」（wash），当前尺度上最细的那一层
 * 才是不透明实心圆 —— 这就是「放大时省淡出、市界线淡入」。wash 还有地图瓦片
 * 的另一半语义 maxzoom：圆铺满整个视口后它的填充只是一层均匀色罩、界线也在
 * 屏幕外，继续画只会和更外层的罩子叠成不透明色块，所以接近铺满时平滑退场、
 * 铺满后停画，只留还没铺满的最内层圆当「你在哪个区域里」的界线。
 *
 * ── 用户那个「跨层级链接怎么淡入淡出」的疑惑，答案是两层机制叠加 ──────────
 * 地图软件处理「北京到上海的高铁」在省级图上是两个省会之间一条线、
 * 在市区图上是两个车站之间一条线，用的正是这两层：
 *
 *  1) 层级预聚合（generalization）—— 构建期已算好 aggregates[L]：
 *     任意两个元素之间的关系，在第 L 层表现为「各自在第 L 层的祖先」之间的一条
 *     聚合边，粗细随被合并的原始边数 count 变化。所以跨层级的链接不需要特殊处理，
 *     它在每个尺度上都有一个唯一确定的代表。
 *  2) per-node minzoom —— 就是 Mapbox vector tile 里那个 minzoom 字段。
 *     端点自己决定它什么时候浮现，边的 alpha 直接取两端点 alpha 的最小值。
 *
 * 于是「这条边现在画在哪两个点之间」由 (1) 决定，「它现在该不该出现、多透明」
 * 由 (2) 决定。边本身不做独立的淡入淡出 —— 那是它两端点的事。
 */

(function () {
  'use strict';

  var FOOTER_H = 46;          // 与 template.html 里 #footer 的高度一致
  var LABEL_CELL = 24;        // 标签碰撞网格边长（屏幕像素）
  var LABEL_BUDGET = 400;     // 每帧最多考虑多少个标签候选
  var CULL_MARGIN = 32;       // 视口外扩余量（屏幕像素）
  var LABEL_INSIDE_PX = 28;   // 屏幕半径超过这个值的容器，标签压在圆内顶部
  var TAU = 6.283185307179586;
  var FONT = '-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif';

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

  function smoothstep(e0, e1, x) {
    if (e1 <= e0) return x >= e1 ? 1 : 0;
    var t = (x - e0) / (e1 - e0);
    t = t < 0 ? 0 : t > 1 ? 1 : t;
    return t * t * (3 - 2 * t);
  }

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function hexToRgb(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return [139, 148, 158];
    var v = parseInt(m[1], 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }

  function rgba(rgb, a) {
    return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + a.toFixed(3) + ')';
  }

  // 描边色：domain 色往白里提一点。父子同色，全靠这条界线把嵌套的圆分开。
  function mixWhite(rgb, t) {
    return [Math.round(rgb[0] + (255 - rgb[0]) * t),
            Math.round(rgb[1] + (255 - rgb[1]) * t),
            Math.round(rgb[2] + (255 - rgb[2]) * t)];
  }

  function createRenderer(canvas, DATA, hooks) {
    hooks = hooks || {};

    var META = DATA.meta;
    var LOD = META.lod || {};
    var ZC = META.zoom || {};
    var THEME = META.theme || {};
    var NODES = DATA.nodes;
    var EDGES = DATA.edges;
    var AGG = DATA.aggregates;

    var MIN_PX = LOD.min_px || 18;
    // 标签门槛是「淡入进度」而不是「屏幕像素间距」，而且它不能读压暗后的 alpha ——
    // 祖先层被 parent_dim 压到底图浓度之后就永远够不到门槛，最粗视图（最该有
    // 标签的视图）会一个标签都没有。
    var LABEL_A = LOD.label_alpha == null ? 0.55 : LOD.label_alpha;
    var FADE = LOD.fade_span || 1.35;
    var WEAK = LOD.weak_edge_min_count || 2;
    var PARENT_DIM = ZC.parent_dim == null ? 0.22 : ZC.parent_dim;
    var WHEEL_STEP = ZC.wheel_step || 1.12;
    var TRANSITION = ZC.transition_ms || 260;
    var HOME_FIT = ZC.home_fit == null ? 1.08 : ZC.home_fit;
    var ENTER = LOD.enter || [];
    var MAXD = META.max_depth || ENTER.length || 1;
    // 虚拟根的世界半径（构建期落盘）。home 视角 = 让整个根正好铺满可视半径。
    var ROOT_R = META.layout_root_radius || 1000;

    var EDGE_RGB = {};
    Object.keys(THEME.edges || {}).forEach(function (k) { EDGE_RGB[k] = hexToRgb(THEME.edges[k]); });
    var FALLBACK_RGB = hexToRgb(THEME.fallback);
    var DOMAIN_RGB = {};
    Object.keys(THEME.domains || {}).forEach(function (k) { DOMAIN_RGB[k] = hexToRgb(THEME.domains[k]); });

    // ── 索引与预计算（全部一次算完，绘制循环里只做查表）─────────────────
    var byId = new Map();
    NODES.forEach(function (n) { byId.set(n.id, n); });

    var kids = new Map();
    NODES.forEach(function (n) {
      if (!n.parent) return;
      var list = kids.get(n.parent);
      if (!list) { list = []; kids.set(n.parent, list); }
      list.push(n.id);
    });

    // 后代数量：只用来给标签排优先级（规模大的先抢位置），不再参与半径计算 ——
    // 半径现在是构建期 packing 分配的世界半径 n.r。
    var desc = new Map();
    NODES.forEach(function (n) { desc.set(n.id, 0); });
    NODES.slice().sort(function (a, b) { return b.depth - a.depth; }).forEach(function (n) {
      if (n.parent && desc.has(n.parent)) {
        desc.set(n.parent, desc.get(n.parent) + 1 + desc.get(n.id));
      }
    });

    NODES.forEach(function (n) {
      var wr = n.r > 0 ? n.r : 1;
      n._r = wr;                                     // 世界半径
      n._mz = MIN_PX / wr;                           // minzoom
      n._d = desc.get(n.id) || 0;
      n._rgb = DOMAIN_RGB[n.domain] || FALLBACK_RGB;
      n._brgb = mixWhite(n._rgb, 0.4);
      // chain[L-1] = 该节点在第 L 层的祖先 id（L ≤ depth 时；更深的层就是它自己）
      var ch = new Array(MAXD);
      var cur = n;
      for (var L = n.depth; L >= 1 && cur; L--) { ch[L - 1] = cur.id; cur = byId.get(cur.parent); }
      var last = ch[n.depth - 1] || n.id;
      for (var k = 0; k < MAXD; k++) { if (!ch[k]) ch[k] = last; }
      for (var j = n.depth; j < MAXD; j++) { ch[j] = n.id; }
      n._chain = ch;
    });
    // 父节点在「所有子节点都已浮现」之后压暗，把视觉重量让给细节。
    // _gate 给 alphaOf 用（边、标签、api 都读它）；_cLo/_cHi 给填充用 ——
    // 孩子里最先浮现的那一个的淡入区间，父圆跟着它同步退成底图。
    kids.forEach(function (list, pid) {
      var p = byId.get(pid);
      if (!p) return;
      var g = 0, lo = Infinity;
      for (var i = 0; i < list.length; i++) {
        var c = byId.get(list[i]);
        if (!c) continue;
        if (c._mz > g) g = c._mz;
        if (c._mz < lo) lo = c._mz;
      }
      p._gate = g;
      p._cHi = lo;
      p._cLo = lo / FADE;
    });
    NODES.forEach(function (n) {
      if (n._cHi == null) { n._cHi = Infinity; n._cLo = Infinity; }
    });

    // 语义边（contains 不画：包含关系已经由半径几何表达，画出来只会糊成一团）
    var SEM = EDGES.filter(function (e) { return e.type !== 'contains'; });
    // aggregates[L] 里也混着 contains，同样只留语义边；按 "s\0t\0type" 建索引
    var aggIndex = {};
    Object.keys(AGG).forEach(function (L) {
      var m = new Map();
      AGG[L].forEach(function (e) {
        if (e.type === 'contains') return;
        m.set(e.s + '\u0000' + e.t + '\u0000' + e.type, e);
      });
      aggIndex[L] = m;
    });
    // 双向边要弯开，否则来回两条完全重叠、看起来只有一条。符号按字典序定，
    // 保证 A→B 与 B→A 弯向相反两侧。
    var pairSeen = new Map();
    SEM.forEach(function (e) {
      var k = e.s < e.t ? e.s + '\u0000' + e.t : e.t + '\u0000' + e.s;
      pairSeen.set(k, (pairSeen.get(k) || 0) + 1);
    });

    // ── 缩放边界：全部从 r / enter 现算，不写死任何绝对值 ─────────────────
    var rootNeed = 0, maxMz = 0;
    NODES.forEach(function (n) {
      if (n.depth === 1 && n._mz > rootNeed) rootNeed = n._mz;
      if (n._mz > maxMz) maxMz = n._mz;
    });
    var zMin = rootNeed * (ZC.zoom_out_floor == null ? 1.05 : ZC.zoom_out_floor);
    var zMax = maxMz * (ZC.zoom_in_ceiling == null ? 1.35 : ZC.zoom_in_ceiling);

    var W = 0, H = 0, dpr = 1;
    var cam = { zoom: zMin, panX: 0, panY: 0 };
    var tween = null;
    var dirty = true, rafId = 0;
    var hoverId = null, selectedId = null;
    var filterSet = null, matchSet = null, labelMode = 'auto';
    var stats = { nodes: 0, edges: 0, labels: 0 };
    var lastDrawn = [];
    var textW = new Map();
    var ctx = canvas.getContext('2d');

    function fitRadius() {
      return Math.max(40, Math.min(W / 2, (H - FOOTER_H) / 2));
    }

    // home 视角：让整个虚拟根（包住全部六个学科）正好铺满可视半径，再留 home_fit
    // 的余量。构建期按标称视口算了一个 home_layer 落盘，这里用真实视口复算。
    function homeZoom() {
      return clamp(fitRadius() / ROOT_R * HOME_FIT, zMin, zMax);
    }

    // home 层：home 视角下已经解锁的最深一层，即 max{ L : enter[L] ≤ homeZoom }
    function homeLayer() {
      var hz = homeZoom(), best = 1;
      for (var L = 1; L <= ENTER.length; L++) {
        if (ENTER[L - 1] <= hz) best = L; else break;
      }
      return best;
    }

    function resize() {
      dpr = window.devicePixelRatio || 1;
      W = canvas.clientWidth || window.innerWidth;
      H = canvas.clientHeight || window.innerHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      invalidate();
    }

    function invalidate() {
      dirty = true;
      if (!rafId) rafId = requestAnimationFrame(frame);
    }

    // 相机变化的唯一收口。滚轮、拖拽、tween、程序化变焦（pills / [ ] / resetView /
    // focusOn）走的是完全不同的代码路径，任何一条忘了回调 HUD，顶栏的层级高亮和读数
    // 就会停在上一次的旧值上 —— 所以不在各条路径里手动通知，而是每帧比对相机快照。
    var notified = { zoom: NaN, panX: NaN, panY: NaN };

    function frame(ts) {
      rafId = 0;
      if (tween) {
        var t = clamp((ts - tween.t0) / tween.ms, 0, 1);
        var e = easeInOutCubic(t);
        cam.zoom = Math.exp(Math.log(tween.from.zoom) + (Math.log(tween.to.zoom) - Math.log(tween.from.zoom)) * e);
        cam.panX = tween.from.panX + (tween.to.panX - tween.from.panX) * e;
        cam.panY = tween.from.panY + (tween.to.panY - tween.from.panY) * e;
        dirty = true;                       // 一帧就结束的 tween 也必须重绘一次
        if (t >= 1) tween = null;
      }
      if (dirty) { dirty = false; draw(); }
      if (cam.zoom !== notified.zoom || cam.panX !== notified.panX ||
          cam.panY !== notified.panY) {
        notified.zoom = cam.zoom; notified.panX = cam.panX; notified.panY = cam.panY;
        if (hooks.onCamera) hooks.onCamera();
      }
      if (tween) rafId = requestAnimationFrame(frame);
    }

    function w2sx(wx) { return wx * cam.zoom + cam.panX; }
    function w2sy(wy) { return wy * cam.zoom + cam.panY; }
    function s2wx(sx) { return (sx - cam.panX) / cam.zoom; }
    function s2wy(sy) { return (sy - cam.panY) / cam.zoom; }

    // 以屏幕点 (sx, sy) 为锚改缩放：该点下的世界坐标保持不动
    function zoomAt(sx, sy, z) {
      z = clamp(z, zMin, zMax);
      var wx = s2wx(sx), wy = s2wy(sy);
      cam.zoom = z;
      cam.panX = sx - wx * z;
      cam.panY = sy - wy * z;
      invalidate();
    }

    function setZoom(z, sx, sy) {
      if (sx == null) { sx = W / 2; sy = (H - FOOTER_H) / 2; }
      zoomAt(sx, sy, z);
    }

    function alphaOf(n) {
      var a = smoothstep(n._mz / FADE, n._mz, cam.zoom);
      if (a <= 0.01) return 0;
      if (n._gate && cam.zoom >= n._gate) a *= PARENT_DIM;
      if (filterSet && !filterSet.has(n.id)) return 0;
      return a;
    }

    // 填充用的 alpha。和 alphaOf 的区别只在一处：压暗不再是「全部孩子浮现后」
    // 的一次性跳变，而是跟着**最先浮现的那个孩子**同步渐变。
    // 旧同心环布局里节点互不嵌套，alphaOf 在 [_mz, _gate] 区间保持 1.0 是对的；
    // packing 下父圆真的套着子圆，那段平台会让父圆变成不透明色块、把正在淡入的
    // 同色孩子整个吃掉。改成同步渐变之后，「省淡出、市淡入」才真的接得上。
    // 端点行为与 alphaOf 一致：孩子没浮现时 = 淡入进度，全部浮现后 = 进度 × parent_dim。
    function fillAlphaOf(n) {
      var base = smoothstep(n._mz / FADE, n._mz, cam.zoom);
      if (base <= 0.01) return 0;
      if (filterSet && !filterSet.has(n.id)) return 0;
      if (n._cHi === Infinity) return base;
      var c = smoothstep(n._cLo, n._cHi, cam.zoom);
      return base * (1 - c * (1 - PARENT_DIM));
    }

    // HUD 上的层级读数：max{ L : enter[L] ≤ zoom }
    function enterAt(zoom) {
      var L = 0;
      for (var i = 0; i < ENTER.length; i++) { if (ENTER[i] <= zoom) L = i + 1; else break; }
      return Math.max(1, L);
    }

    // 端点沿祖先链「当前浮现在哪一层」：alpha 沿链单调不增（r 沿包含链严格递减
    // ⇒ minzoom 严格递增），所以从浅往深扫，遇到第一个不可见的就停。
    function visibleLayer(n) {
      var ch = n._chain, L = 1;
      for (var i = 0; i < n.depth; i++) {
        var a = byId.get(ch[i]);
        if (!a) break;
        if (filterSet && !filterSet.has(a.id)) break;
        if (smoothstep(a._mz / FADE, a._mz, cam.zoom) <= 0.01) break;
        L = i + 1;
      }
      return L;
    }

    function measure(s, font) {
      var k = font + '|' + s;
      var v = textW.get(k);
      if (v == null) { ctx.font = font; v = ctx.measureText(s).width; textW.set(k, v); }
      return v;
    }

    // ── 绘制 ────────────────────────────────────────────────────────────
    // 四趟：① 容器底图 → ② 语义边 → ③ 前景实心圆 → ④ 标签。
    // 边夹在底图和实心圆之间：压在底图之上才看得见，被实心圆盖住又正好形成
    // 「线连到圆边上」的观感。强调环（掌握度/命中/选中）单独一趟，永远在最上面。
    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = '#0f1116';
      ctx.fillRect(0, 0, W, H);

      var zoom = cam.zoom;
      var alpha = new Map();
      var drawn = [], wash = [], front = [];

      for (var i = 0; i < NODES.length; i++) {
        var n = NODES[i];
        var sr = n._r * zoom;
        // 视口裁剪必须按半径外扩：大圆的中心常常在屏幕外，圆本身却铺满整屏
        var cx = n.x * zoom + cam.panX, cy = n.y * zoom + cam.panY;
        if (cx + sr < -CULL_MARGIN || cx - sr > W + CULL_MARGIN ||
            cy + sr < -CULL_MARGIN || cy - sr > H + CULL_MARGIN) continue;
        var a = alphaOf(n);
        if (a <= 0) continue;
        n._sr = sr;
        alpha.set(n.id, a);
        drawn.push(n);
        // 地图矢量瓦片的 maxzoom：圆铺满整个内容视口后，它的填充只是一层均匀色
        // 罩、界线也在屏幕外，继续画只会和更外层的罩子叠成不透明色块。停画它，
        // 由还没铺满视口的最内层圆提供「你在哪个区域里」的界线 —— 省界退出屏幕
        // 后只剩市界，正是地图的做法。节点仍留在 drawn 里供命中测试与标签。
        if (sr >= farCornerDist(cx, cy)) continue;
        // 已经有孩子开始浮现 → 它是「区域」；否则它是当前尺度上的「点」
        if (n._cHi !== Infinity && smoothstep(n._cLo, n._cHi, zoom) > 0.01) wash.push(n);
        else front.push(n);
      }
      // 子盖父：深度升序，同深度大圆先画
      function byDepth(p, q) { return p.depth - q.depth || q._r - p._r; }
      wash.sort(byDepth);
      front.sort(byDepth);

      lastDrawn = drawn;
      // drawn 含「铺满视口而停画」的祖先（命中测试还要用它们），真正落笔的是
      // wash + front，footer 与空白兜底都以落笔数为准
      stats.nodes = wash.length + front.length;

      drawWash(wash);
      drawEdges(alpha);
      drawChainHighlight();
      drawNodes(front, alpha);
      drawEmphasis(drawn, alpha);
      drawLabels(drawn, alpha);

      // 全空白兜底：packing 布局没有空心，但一路放大到某个分支的最深处再往旁边
      // 平移，视口里确实可能一个圆都不落笔（铺满视口的祖先停画、间隙里又没有更
      // 细的圆）。地图软件在这种情况下会提示「此区域暂无详情」，这里照做。
      if (!wash.length && !front.length) {
        ctx.globalAlpha = 1;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = '13px ' + FONT;
        ctx.fillStyle = 'rgba(126,135,154,0.9)';
        ctx.fillText('此处没有内容 · 向下滚回到更粗的层级，或双击空白处回到默认视角',
                     W / 2, (H - FOOTER_H) / 2);
        ctx.textAlign = 'left';
      }

      if (hooks.onFrame) hooks.onFrame(stats);
    }

    // 内容视口（去掉 footer 那条）里离 (sx, sy) 最远的角的距离。屏幕半径超过它，
    // 圆就铺满整屏：填充退成均匀色罩、界线退出屏幕外 —— 即地图瓦片的 maxzoom。
    function farCornerDist(sx, sy) {
      var Hc = H - FOOTER_H;
      var dx = Math.max(sx, W - sx), dy = Math.max(sy, Hc - sy);
      return Math.sqrt(dx * dx + dy * dy);
    }

    // ① 容器底图：同色压暗填充 + 一条清晰界线。地图里的省就是这样 —— 面很淡，
    //    界线很清楚，市画在它上面。
    function drawWash(list) {
      for (var i = 0; i < list.length; i++) {
        var n = list[i];
        var sx = w2sx(n.x), sy = w2sy(n.y), sr = n._sr;
        // maxzoom 淡出：圆接近铺满视口时让它平滑退场（fade 1→0），否则停画那一
        // 瞬会看到整屏亮度跳一下；也避免多层罩子叠成不透明色块
        var dFar = farCornerDist(sx, sy);
        var fade = 1 - smoothstep(dFar * 0.7, dFar, sr);
        if (fade <= 0.004) continue;
        var fa = fillAlphaOf(n) * fade;
        if (fa > 0.004) {
          ctx.globalAlpha = fa;
          ctx.fillStyle = rgba(n._rgb, 1);
          ctx.beginPath();
          ctx.arc(sx, sy, sr, 0, TAU);
          ctx.fill();
        }
        ctx.globalAlpha = clamp(fa * 1.2 + 0.18 * fade, 0, 0.8);
        ctx.strokeStyle = rgba(n._brgb, 1);
        ctx.lineWidth = sr > 60 ? 1.6 : 1;
        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, TAU);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    function drawEdges(alpha) {
      // 每条原始语义边，按两端点「当前浮现的层级」取 min，再去 aggregates[L] 查代表边。
      // 多条原始边可能塌到同一条代表边上 —— 用 Map 去重，顺便把 count 取最大。
      var picks = new Map();
      for (var i = 0; i < SEM.length; i++) {
        var e = SEM[i];
        var A = byId.get(e.s), B = byId.get(e.t);
        if (!A || !B) continue;
        var La = visibleLayer(A), Lb = visibleLayer(B);
        var L = Math.min(La, Lb);
        var m = aggIndex[L];
        if (!m) continue;
        var sa = A._chain[L - 1], sb = B._chain[L - 1];
        if (!sa || !sb || sa === sb) continue;
        var agg = m.get(sa + '\u0000' + sb + '\u0000' + e.type);
        if (!agg) continue;
        var aa = alpha.get(sa), ab = alpha.get(sb);
        if (!aa || !ab) continue;
        var key = sa + '\u0000' + sb + '\u0000' + e.type;
        var prev = picks.get(key);
        var a = Math.min(aa, ab) * ((agg.count || 1) >= WEAK ? 1 : 0.45);
        if (!prev || a > prev.a) picks.set(key, { e: agg, a: a, sa: sa, sb: sb });
      }
      stats.edges = picks.size;
      if (!picks.size) return;

      var zoom = cam.zoom;
      ctx.lineCap = 'round';
      picks.forEach(function (p) {
        var A = byId.get(p.sa), B = byId.get(p.sb);
        if (!A || !B) return;
        var x1 = w2sx(A.x), y1 = w2sy(A.y), x2 = w2sx(B.x), y2 = w2sy(B.y);
        var cnt = p.e.count || 1;
        var lw = Math.min(4, 0.6 + 1.8 * Math.log(1 + cnt) / Math.LN2);
        var rgb = EDGE_RGB[p.e.type] || EDGE_RGB.derives || [76, 141, 255];
        var hot = hoverId && (p.sa === hoverId || p.sb === hoverId ||
                              byId.get(hoverId) && (A._chain.indexOf(hoverId) >= 0 || B._chain.indexOf(hoverId) >= 0));
        ctx.globalAlpha = clamp(p.a * (hot ? 1 : 0.75), 0, 1);
        ctx.strokeStyle = rgba(rgb, 1);
        ctx.lineWidth = hot ? lw + 0.8 : lw;

        // 弯开双向边：控制点沿法向偏移，符号按字典序定
        var pk = p.sa < p.sb ? p.sa + '\u0000' + p.sb : p.sb + '\u0000' + p.sa;
        var bidir = (pairSeen.get(pk) || 0) > 1;
        var dx = x2 - x1, dy = y2 - y1, dist = Math.sqrt(dx * dx + dy * dy) || 1;
        var cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
        var sign = p.sa < p.sb ? 1 : -1;
        var off = bidir ? 0.12 * dist * sign : 0;
        var mx = cx - dy / dist * off, my = cy + dx / dist * off;

        ctx.setLineDash(p.e.type === 'contrast' ? [5, 4] : []);
        ctx.beginPath();
        if (off) { ctx.moveTo(x1, y1); ctx.quadraticCurveTo(mx, my, x2, y2); }
        else { ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); }
        ctx.stroke();
        ctx.setLineDash([]);

        if (p.e.type === 'derives' || p.e.type === 'prerequisite') {
          // 箭头贴着目标圆的屏幕边缘
          var tr = B._r * zoom + 2;
          var tx = off ? x2 - mx : dx, ty = off ? y2 - my : dy;
          var tl = Math.sqrt(tx * tx + ty * ty) || 1;
          tx /= tl; ty /= tl;
          var ax = x2 - tx * tr, ay = y2 - ty * tr;
          var sz = clamp(3 + lw, 4, 8);
          ctx.fillStyle = rgba(rgb, 1);
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(ax - tx * sz - ty * sz * 0.5, ay - ty * sz + tx * sz * 0.5);
          ctx.lineTo(ax - tx * sz + ty * sz * 0.5, ay - ty * sz - tx * sz * 0.5);
          ctx.closePath();
          ctx.fill();
        }
      });
      ctx.globalAlpha = 1;
    }

    // 包含关系不画成线，但 hover / 选中时把祖先链点出来，弥补放大后失去的上下文
    function drawChainHighlight() {
      var target = hoverId || selectedId;
      if (!target) return;
      var n = byId.get(target);
      if (!n) return;
      var pts = [];
      var cur = n;
      while (cur) {
        var sx = w2sx(cur.x), sy = w2sy(cur.y);
        pts.push([sx, sy]);
        cur = cur.parent ? byId.get(cur.parent) : null;
      }
      if (pts.length < 2) return;
      ctx.globalAlpha = 0.35;
      ctx.strokeStyle = 'rgba(214,219,228,1)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    // ③ 前景实心圆：当前尺度上最细的一层，不透明、带描边
    function drawNodes(list, alpha) {
      for (var i = 0; i < list.length; i++) {
        var n = list[i];
        var sx = w2sx(n.x), sy = w2sy(n.y), sr = n._sr;
        var a = alpha.get(n.id);
        ctx.globalAlpha = a;
        ctx.fillStyle = rgba(n._rgb, 1);
        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, TAU);
        ctx.fill();
        ctx.globalAlpha = clamp(a * 0.85, 0, 1);
        ctx.strokeStyle = rgba(n._brgb, 1);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, TAU);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    // ③′ 强调环：掌握度 / 搜索命中 / hover-selected。单独一趟画在所有圆之上，
    //      否则会被后画的兄弟圆盖掉一半。
    function drawEmphasis(list, alpha) {
      for (var i = 0; i < list.length; i++) {
        var n = list[i];
        var isSel = n.id === selectedId, isHov = n.id === hoverId;
        var isMatch = matchSet && matchSet.has(n.id);
        if (!(isSel || isHov || isMatch || (n.kind === 'note' && n.mastery > 0))) continue;
        var sx = w2sx(n.x), sy = w2sy(n.y), sr = n._sr;
        var a = alpha.get(n.id);

        // 掌握度用描边环表达：1..5 越粗越实，≤3 用虚线表示「还没吃透」
        if (n.kind === 'note' && n.mastery > 0) {
          var m = clamp(n.mastery, 1, 5);
          ctx.globalAlpha = a;
          ctx.lineWidth = 1 + m * 0.75;
          ctx.strokeStyle = 'rgba(255,255,255,0.85)';
          if (m <= 3) ctx.setLineDash([2, 2]);
          ctx.beginPath();
          ctx.arc(sx, sy, sr + ctx.lineWidth * 0.7, 0, TAU);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        if (isMatch) {
          ctx.globalAlpha = a;
          ctx.lineWidth = 2;
          ctx.strokeStyle = 'rgba(227,179,65,0.95)';
          ctx.beginPath();
          ctx.arc(sx, sy, sr + 4, 0, TAU);
          ctx.stroke();
        }
        if (isSel || isHov) {
          ctx.globalAlpha = 1;
          ctx.lineWidth = isSel ? 2 : 1.4;
          ctx.strokeStyle = isSel ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.6)';
          ctx.beginPath();
          ctx.arc(sx, sy, sr + 2.5, 0, TAU);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }

    function drawLabels(drawn, alpha) {
      if (labelMode === 'off') { stats.labels = 0; return; }
      var forceAll = labelMode === 'on';
      var cands = [];
      for (var i = 0; i < drawn.length; i++) {
        var n = drawn[i];
        var forced = forceAll || (matchSet && matchSet.has(n.id)) ||
                     n.id === selectedId || n.id === hoverId;
        if (!forced) {
          // 用未被 parent_dim 压暗的淡入进度做门槛。压暗是「把视觉重量让给细节」的手段，
          // 不是藏标签的手段 —— 共用同一个 alpha 会让祖先层在任何 zoom 下都拿不到标签。
          if (smoothstep(n._mz / FADE, n._mz, cam.zoom) < LABEL_A) continue;
        }
        cands.push(n);
      }
      // 优先级：选中/hover/搜索命中 > 当前不透明度降序 > 规模降序 > 深度升序。
      // 用「当前」不透明度（含压暗）排序，让正处在浮现前沿的那一层先抢到标签位，
      // 祖先层用剩下的空隙做淡色上下文。
      cands.sort(function (p, q) {
        var fp = forcedRank(p), fq = forcedRank(q);
        if (fp !== fq) return fp - fq;
        var ap = alpha.get(p.id) || 0, aq = alpha.get(q.id) || 0;
        if (aq !== ap) return aq - ap;
        if (q._d !== p._d) return q._d - p._d;
        return p.depth - q.depth;
      });
      function forcedRank(n) {
        if (n.id === selectedId || n.id === hoverId) return 0;
        if (matchSet && matchSet.has(n.id)) return 1;
        return 2;
      }
      if (cands.length > LABEL_BUDGET) cands.length = LABEL_BUDGET;

      var occupied = new Map();
      var placed = 0;
      ctx.textBaseline = 'middle';
      for (var j = 0; j < cands.length; j++) {
        var m = cands[j];
        var font = (m.depth <= 2 ? '600 13px ' : '12px ') + FONT;
        var text = m.label || m.id;
        var wpx = measure(text, font) + 6;
        var hpx = 16;
        var sr = m._sr;
        var cxs = w2sx(m.x), cys = w2sy(m.y);
        // 大容器：标签居中压在圆内顶部（省名写在省的范围内，地图就这么干）；
        // 小圆点：标签挂在右侧，免得盖住圆本身。
        var inside = sr >= LABEL_INSIDE_PX;
        var sx, sy, x0, x1;
        if (inside) {
          sx = cxs; sy = cys - sr + 10;
          x0 = Math.floor((sx - wpx / 2) / LABEL_CELL);
          x1 = Math.floor((sx + wpx / 2) / LABEL_CELL);
        } else {
          sx = cxs + sr + 4; sy = cys;
          x0 = Math.floor(sx / LABEL_CELL);
          x1 = Math.floor((sx + wpx) / LABEL_CELL);
        }
        var y0 = Math.floor((sy - hpx / 2) / LABEL_CELL), y1 = Math.floor((sy + hpx / 2) / LABEL_CELL);
        // 锚点落在屏幕外的标签（铺满视口停画的容器、圆心在屏外的大圆）既不该占
        // LABEL_BUDGET，也不该进碰撞网格把真标签挤掉
        var bx0 = inside ? sx - wpx / 2 : sx, bx1 = inside ? sx + wpx / 2 : sx + wpx;
        if (bx1 < 0 || bx0 > W || sy + hpx / 2 < 0 || sy - hpx / 2 > H) continue;
        var rank = forcedRank(m);
        var clash = false;
        if (rank > 1) {
          for (var gx = x0; gx <= x1 && !clash; gx++) {
            for (var gy = y0; gy <= y1; gy++) {
              if (occupied.get(gx + ',' + gy)) { clash = true; break; }
            }
          }
        }
        if (clash) continue;
        for (var gx2 = x0; gx2 <= x1; gx2++) {
          for (var gy2 = y0; gy2 <= y1; gy2++) occupied.set(gx2 + ',' + gy2, 1);
        }
        var al = clamp(alpha.get(m.id), 0, 1);
        ctx.font = font;
        ctx.textAlign = inside ? 'center' : 'left';
        ctx.globalAlpha = al * 0.9;
        ctx.fillStyle = 'rgba(15,17,22,0.85)';
        ctx.fillText(text, sx + 1, sy + 1);
        ctx.globalAlpha = al;
        ctx.fillStyle = rank === 0 ? '#ffffff' : rank === 1 ? '#E3B341' : '#d6dbe4';
        ctx.fillText(text, sx, sy);
        placed++;
      }
      ctx.globalAlpha = 1;
      ctx.textAlign = 'left';
      stats.labels = placed;
    }

    // 拾取：线性扫上一帧真正画出来的圆，取「包含该点的最小圆」。
    // 不能用固定边长的屏幕网格 —— packing 下圆的屏幕半径从 18px 到几百 px，
    // 大圆的中心常常离鼠标好几个格子远。每帧至多几百个候选，扫一遍比建网格便宜。
    function hitTest(sx, sy) {
      var best = null, bestR = Infinity;
      for (var i = 0; i < lastDrawn.length; i++) {
        var n = lastDrawn[i];
        var dx = w2sx(n.x) - sx, dy = w2sy(n.y) - sy;
        var d = Math.sqrt(dx * dx + dy * dy);
        var rr = Math.max(n._sr, 4) + 3;
        if (d <= rr && rr < bestR) { bestR = rr; best = n; }
      }
      return best;
    }

    function focusOn(id, mult, ms) {
      var n = byId.get(id);
      if (!n) return;
      mult = mult || 1.25;
      // 两个下限：它自己得浮现（_mz × mult），而且得占满大半屏（0.7 × fit / r）——
      // 后者是新几何带来的：一个 r 很大的文件夹光「浮现」远不够看清它。
      var z = clamp(Math.max(cam.zoom, n._mz * mult, 0.7 * fitRadius() / n._r), zMin, zMax);
      tweenTo({ zoom: z, panX: W / 2 - n.x * z, panY: (H - FOOTER_H) / 2 - n.y * z },
              ms == null ? TRANSITION : ms);
    }

    function tweenTo(to, ms) {
      if (ms <= 0) { cam.zoom = to.zoom; cam.panX = to.panX; cam.panY = to.panY; invalidate(); return; }
      tween = { from: { zoom: cam.zoom, panX: cam.panX, panY: cam.panY }, to: to,
                t0: performance.now(), ms: ms || TRANSITION };
      invalidate();
    }

    function resetView() {
      tweenTo({ zoom: homeZoom(), panX: W / 2, panY: (H - FOOTER_H) / 2 }, TRANSITION * 1.4);
    }

    // ── 交互 ────────────────────────────────────────────────────────────
    var dragging = false, dragMoved = 0, lastX = 0, lastY = 0;

    function pos(e) {
      var r = canvas.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    }

    canvas.addEventListener('wheel', function (e) {
      e.preventDefault();
      tween = null;
      var dy = e.deltaY;
      if (e.deltaMode === 1) dy *= 33;          // 行 → 近似像素
      else if (e.deltaMode === 2) dy *= 100;    // 页
      var factor = Math.pow(WHEEL_STEP, -dy / 100);
      factor = clamp(factor, 0.5, 2);           // 触摸板的高频小步长不至于一次跳穿
      var p = pos(e);
      zoomAt(p[0], p[1], cam.zoom * factor);
      if (hooks.onCamera) hooks.onCamera();
    }, { passive: false });

    canvas.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      dragging = true; dragMoved = 0;
      lastX = e.clientX; lastY = e.clientY;
      tween = null;
      canvas.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', function (e) {
      var p = pos(e);
      if (dragging) {
        var dx = e.clientX - lastX, dy = e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY;
        dragMoved += Math.abs(dx) + Math.abs(dy);
        cam.panX += dx; cam.panY += dy;
        invalidate();
        if (hooks.onCamera) hooks.onCamera();
        return;
      }
      if (p[0] < 0 || p[1] < 0 || p[0] > W || p[1] > H) return;
      var hit = hitTest(p[0], p[1]);
      var id = hit ? hit.id : null;
      canvas.style.cursor = hit ? 'pointer' : 'grab';
      if (id !== hoverId) {
        hoverId = id;
        invalidate();
        if (hooks.onHover) hooks.onHover(id, hit, p[0], p[1]);
      } else if (hooks.onHover && id) {
        hooks.onHover(id, hit, p[0], p[1]);
      }
    });

    window.addEventListener('mouseup', function () {
      dragging = false;
      canvas.style.cursor = hoverId ? 'pointer' : 'grab';
    });

    canvas.addEventListener('click', function (e) {
      if (dragMoved > 5) return;                // 是拖拽，不是点击
      var p = pos(e);
      var hit = hitTest(p[0], p[1]);
      selectedId = hit ? hit.id : null;
      invalidate();
      if (hooks.onSelect) hooks.onSelect(selectedId, hit);
    });

    canvas.addEventListener('dblclick', function (e) {
      var p = pos(e);
      var hit = hitTest(p[0], p[1]);
      if (!hit) { resetView(); return; }
      selectedId = hit.id;
      focusOn(hit.id, 1.6, TRANSITION * 1.4);
      if (hooks.onSelect) hooks.onSelect(hit.id, hit);
    });

    window.addEventListener('resize', resize);

    // ── 对外接口 ────────────────────────────────────────────────────────
    var api = {
      camera: cam,
      zMin: zMin, zMax: zMax,
      get zHome() { return homeZoom(); },
      get homeLayer() { return homeLayer(); },
      stats: stats,
      NODES: NODES, byId: byId, SEM: SEM,
      resize: resize,
      invalidate: invalidate,
      draw: draw,
      hitTest: hitTest,
      enterAt: enterAt,
      alphaOf: function (id) { var n = byId.get(id); return n ? alphaOf(n) : 0; },
      // 兼容别名：payload 字段 reveal 已改名 r（世界半径）
      revealOf: function (id) { var n = byId.get(id); return n ? n.r : 0; },
      minzoomOf: function (id) { var n = byId.get(id); return n ? n._mz : 0; },
      descOf: function (id) { var n = byId.get(id); return n ? n._d : 0; },
      visibleLayerOf: function (id) { var n = byId.get(id); return n ? visibleLayer(n) : 0; },
      setZoom: setZoom,
      zoomBy: function (f) { setZoom(cam.zoom * f); },
      zoomToDepth: function (L) {
        var z = (ENTER[L - 1] || zMax) * 1.05;
        tweenTo({ zoom: clamp(z, zMin, zMax), panX: W / 2, panY: (H - FOOTER_H) / 2 }, TRANSITION);
      },
      focusOn: focusOn,
      tweenTo: tweenTo,
      resetView: resetView,
      get hover() { return hoverId; },
      set hover(v) { hoverId = v; invalidate(); },
      get selected() { return selectedId; },
      set selected(v) { selectedId = v; invalidate(); },
      get filterSet() { return filterSet; },
      set filterSet(v) { filterSet = v; invalidate(); },
      get matchSet() { return matchSet; },
      set matchSet(v) { matchSet = v; invalidate(); },
      get labelMode() { return labelMode; },
      set labelMode(v) { labelMode = v; invalidate(); },
      centerScreen: function () { return [W / 2, (H - FOOTER_H) / 2]; },
      size: function () { return [W, H]; }
    };

    resize();
    cam.panX = W / 2;
    cam.panY = (H - FOOTER_H) / 2;
    cam.zoom = homeZoom();
    invalidate();
    return api;
  }

  window.createRenderer = createRenderer;
})();
