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
    // 标签字号绑「屏幕半径」而不是 depth —— 见 labelFontSize 的注释。
    // 一律 == null 兜默认（0 是合法值，|| 会把它吃掉）。
    var LABEL_FS_MIN = LOD.label_font_min == null ? 11 : LOD.label_font_min;
    var LABEL_FS_MAX = LOD.label_font_max == null ? 22 : LOD.label_font_max;
    var LABEL_FS_REF = LOD.label_font_ref == null ? 300 : LOD.label_font_ref;
    var LABEL_BOLD_DEPTH = LOD.label_bold_depth == null ? 2 : LOD.label_bold_depth;
    var LABEL_MAX_W = LOD.label_max_width == null ? 180 : LOD.label_max_width;
    var LABEL_SMOOTH_DIM = LOD.label_smooth_dim == null ? true : LOD.label_smooth_dim;
    var FADE = LOD.fade_span || 1.35;
    var WEAK = LOD.weak_edge_min_count || 2;
    // 焦点模式的压暗系数。必须用 == null 而不是 ||：0（彻底不画无关连线）是合法值，
    // 会被 || 当成假值吃掉。
    var FOCUS_DIM = LOD.focus_edge_dim == null ? 0.07 : LOD.focus_edge_dim;
    var HOVER_DIM = LOD.hover_edge_dim == null ? 0.75 : LOD.hover_edge_dim;
    // 端点标记。TRIM 是连线在两端圆边界处截断后留的间隙；MARK_MIN 是「短到不画标记」
    // 的屏幕长度门槛；TINT 是标记向浅色提亮的比例 —— 必须提亮，因为 derives 的边色
    // 和 Science and Tech 的节点色是同一个 hex，同色标记落在同色圆边上等于隐形。
    var TRIM = LOD.edge_trim_clearance == null ? 2 : LOD.edge_trim_clearance;
    var MARK_MIN = LOD.edge_marker_min_len == null ? 20 : LOD.edge_marker_min_len;
    var MARK_TINT = LOD.edge_marker_tint == null ? 0.55 : LOD.edge_marker_tint;
    var MARK_LIGHT = hexToRgb('#d6dbe4');
    // 焦点链接的「屏外目标」chip 上限。选中元素的链接有一端在当前尺度屏外时，
    // 连线止于视口边缘并挂一枚写着目标名的 chip；超出上限的折叠成右下角一枚「+k」
    var CHIP_MAX = LOD.focus_offscreen_chips == null ? 8 : LOD.focus_offscreen_chips;
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
    // 端点标记的颜色表：边色向浅色混合 MARK_TINT。构建期算一次，绘制循环里只查表
    var MARK_RGB = {};
    Object.keys(EDGE_RGB).forEach(function (k) {
      var c = EDGE_RGB[k];
      MARK_RGB[k] = [
        Math.round(c[0] + (MARK_LIGHT[0] - c[0]) * MARK_TINT),
        Math.round(c[1] + (MARK_LIGHT[1] - c[1]) * MARK_TINT),
        Math.round(c[2] + (MARK_LIGHT[2] - c[2]) * MARK_TINT)
      ];
    });
    // 邻居环的颜色。跟着 derives 的边色走（= CSS --accent），和白色的选中环同轨但
    // 更细，一眼能分清「哪个是我选的」。不按边类型着色：contrast 的金色会和搜索
    // 命中环撞色。
    var NB_RGB = EDGE_RGB.derives || hexToRgb('#4C8DFF');
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
    var lastMouse = null;
    var filterSet = null, matchSet = null, labelMode = 'auto';
    var stats = { nodes: 0, edges: 0, labels: 0, focusEdges: 0, focusNeighbors: 0, marks: 0, chips: 0 };
    // 本帧与选中元素直接相连的**代表**节点 id。drawEdges 的挑边循环里就地收集
    // （那里才知道每条原始边塌到了哪一层的哪个代表上），drawEmphasis 读它画蓝环。
    // 只用于绘制与计数，不落盘、不参与布局。
    var hotNeighbors = new Set();
    // 本帧要画的端点标记（源端圆点 / 目标端箭头）。drawEdges 只往这里塞任务不落笔：
    // draw() 里 drawNodes(front) 排在 drawEdges 之后，就地画的话标记会被紧贴的邻圆
    // 整个盖掉（packing 布局里圆是相切的）。真正落笔在 drawEdgeMarkers。
    // k: 0 = 圆点，1 = 箭头；ux/uy = 箭头指向的单位向量；s = 尺寸；c/a = 颜色与不透明度
    var markJobs = [];
    // 屏外目标 chip：焦点边被门挡掉后连线止于视口边缘，边缘处挂一枚写着屏外端点名字
    // 的小标签。drawEdges / drawFocusEdges 只塞任务，真正落笔在 drawChips —— 屏幕空间
    // 的 UI 覆盖层，排在所有世界内容之后。
    var chipJobs = [];
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

    // F 是 n 本身、或 n 的某个祖先吗？_chain[k] = n 在第 k+1 层的祖先 id，
    // 且 j >= n.depth 时 _chain[j] = n.id，所以深度对不上时天然返回 false。
    // 一次数组下标比较，比 _chain.indexOf 的线性扫还便宜 —— 焦点过滤每帧要对
    // 每条原始边的两个端点各判一次，不能贵。
    // 用它判「这条边与焦点相关吗」：拿**原始端点**问「焦点是它的本身或祖先吗」，
    // 一条规则同时覆盖三种情况 —— 焦点就是端点自己、焦点是端点的祖先（如选中
    // 一篇笔记而边挂在它的 heading 上）、焦点是聚合代表的后代（旧写法在这里漏判）。
    function isFocusSide(n, F) {
      return !!n && !!F && n._chain[F.depth - 1] === F.id;
    }

    // 未被 parent_dim 压暗的淡入进度。给强调环用：alphaOf 在 cam.zoom >= n._gate
    // 时会乘 PARENT_DIM，而粗尺度下的邻居代表**几乎总是**这种「孩子全浮现了的
    // 祖先」⇒ 直接读 alpha 会让环掉到两成浓度、基本看不见。同 pitfall 8
    // （fillAlphaOf 与 alphaOf 不能共用），也同 label_alpha 那条注释讲的道理：
    // 压暗只是降低视觉重量，不该顺带把强调藏掉。
    function fadeInOf(n) {
      return smoothstep(n._mz / FADE, n._mz, cam.zoom);
    }

    function measure(s, font) {
      var k = font + '|' + s;
      var v = textW.get(k);
      if (v == null) { ctx.font = font; v = ctx.measureText(s).width; textW.set(k, v); }
      return v;
    }

    // 标签字号 = 屏幕半径的函数，**不是 depth 的函数**。两条理由，都别改回去：
    //  1) depth 是复合轴 —— heading.depth = 所属笔记 depth + 标题级别（kg/graph.py），
    //     所以 depth 6..10 并不对应固定的 h1..h5，同一档里混着不同类别的东西；
    //  2) 同 depth 的屏幕尺寸能差 16.22 倍 —— 六个学科根都是 depth-1，世界半径却是
    //     Science and Tech 717.2 / Projects 172.0 / ... / Medical and Health 44.2。
    //     按 depth 分档会让「铺满全屏的根」和「20px 小圆点」用同一个字号，
    //     正是这套字号要消除的不协调。
    // 屏幕半径本来就是系统既有的屏幕空间 LOD 语义（minzoom、圆内/圆外摆放、视口裁剪
    // 都读它），再加一个消费者是一致的；又因 r 沿包含链严格递减 ⇒ 屏幕半径档位天然
    // 就是层级档位，「字号与层级绑定」自动成立，只是测量方式更准。
    // 对数插值 ⇒ 尺度不变，和本项目「无量纲系数、不写死绝对 zoom」的做法一致。
    // **必须取整**：measure() 的缓存 key 是 font 字符串，连续字号会让缓存条目和
    // measureText 调用量随帧数无界增长；取整同时消除缩放过程中的字形抖动。
    function labelFontSize(sr) {
      if (!(sr > 0) || LABEL_FS_REF <= MIN_PX) return LABEL_FS_MIN;
      var t = Math.log(sr / MIN_PX) / Math.log(LABEL_FS_REF / MIN_PX);
      var fs = LABEL_FS_MIN + (LABEL_FS_MAX - LABEL_FS_MIN) * t;
      return Math.round(clamp(fs, LABEL_FS_MIN, LABEL_FS_MAX));
    }

    // 字宽收口：字号再大也不许让文字溢出它所属的圆（「文字与圆形元素的相对大小」）。
    // 整数逐级下调，下限停在 LABEL_FS_MIN —— 宁可让 24px 碰撞网格去淘汰它，
    // 也不要把字缩到读不了。weight 必须一起进 key：600 半粗比常规宽，
    // 拿常规宽度去判半粗标签会漏判溢出。
    function fitFont(text, fs, weight, availW) {
      while (fs > LABEL_FS_MIN && measure(text, weight + fs + 'px ' + FONT) + 6 > availW) fs--;
      return fs;
    }

    // 圆外标签的硬收口：字号缩到下限还超 label_max_width 就截断加省略号。不截断的
    // 话一条六十字的标题会以 11px 横扫半屏、压过邻圆和连线 —— 正是「文字与圆形元素
    // 相对大小」要防的乱。完整名字仍在悬停 tooltip 与搜索里，信息不丢。
    // 结果按 (节点, font) 缓存：圆外可用宽是常数 label_max_width，而圆外字号只落在
    // 屏幕半径 < LABEL_INSIDE_PX 对应的少数几档上，缓存条目有界；不缓存的话二分过程
    // 里每个前缀都会进 measure 缓存，随帧数无界增长。
    var clipCache = new Map();
    function clipLabel(id, text, font) {
      var key = id + '|' + font;
      var hit = clipCache.get(key);
      if (hit !== undefined) return hit;
      var out = text;
      if (measure(text, font) + 6 > LABEL_MAX_W) {
        var lo = 0, hi = text.length;
        while (lo < hi) {
          var mid = (lo + hi + 1) >> 1;
          if (measure(text.slice(0, mid) + '…', font) + 6 <= LABEL_MAX_W) lo = mid;
          else hi = mid - 1;
        }
        out = text.slice(0, lo) + '…';
      }
      clipCache.set(key, out);
      return out;
    }

    // ── 绘制 ────────────────────────────────────────────────────────────
    // 六趟：① 容器底图 → ② 语义边 → ③ 前景实心圆 → ④ 端点标记 → ⑤ 标签 → ⑥ 屏外 chip。
    // 边夹在底图和实心圆之间：压在底图之上才看得见，被实心圆盖住又正好形成
    // 「线连到圆边上」的观感。标记必须排在实心圆之后（否则被相切邻圆盖掉）、
    // 强调环之前（让选中白环压过箭头）。强调环（掌握度/命中/选中）单独一趟，永远在最上面。
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
      drawEdgeMarkers();
      drawEmphasis(drawn, alpha);
      drawLabels(drawn, alpha);
      // ⑥ 屏外 chip：屏幕空间的 HUD 覆盖层，压在所有世界内容之上
      drawChips();

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

      // 相机一动（滚轮 / 拖拽 / tween），光标下的圆就换了；鼠标没动就不会再有
      // mousemove，悬停提示会停在旧节点上。落笔后用最近一次鼠标位置重算 hover。
      if (lastMouse && !dragging) evalHover(lastMouse[0], lastMouse[1]);

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
      hotNeighbors.clear();
      stats.focusEdges = 0;
      markJobs.length = 0;
      chipJobs.length = 0;
      stats.chips = 0;
      var selN = byId.get(selectedId), hovN = byId.get(hoverId);
      var picks = new Map();
      // 被三道门挡掉的焦点边。门只丢边不记录，要救的先记在这里，循环结束后交
      // drawFocusEdges 补画（脏帧规则同 markJobs：每帧开头清空）
      var droppedFocus = [];
      for (var i = 0; i < SEM.length; i++) {
        var e = SEM[i];
        // 注意：这里的 A/B 是**原始**端点，下面绘制循环里的 A/B 是聚合代表 —— 同名不同义
        var A = byId.get(e.s), B = byId.get(e.t);
        if (!A || !B) continue;
        // 这条边与焦点相关吗：门只丢边，要救的先记下来
        var hs0 = !!selN && (isFocusSide(A, selN) || isFocusSide(B, selN));
        var La = visibleLayer(A), Lb = visibleLayer(B);
        var L = Math.min(La, Lb);
        var m = aggIndex[L];
        if (!m) continue;
        var sa = A._chain[L - 1], sb = B._chain[L - 1];
        if (!sa || !sb || sa === sb) {
          if (hs0) droppedFocus.push({ e: e, A: A, B: B });
          continue;
        }
        var agg = m.get(sa + '\u0000' + sb + '\u0000' + e.type);
        if (!agg) {
          if (hs0) droppedFocus.push({ e: e, A: A, B: B });
          continue;
        }
        var aa = alpha.get(sa), ab = alpha.get(sb);
        if (!aa || !ab) {
          if (hs0) droppedFocus.push({ e: e, A: A, B: B });
          continue;
        }
        var key = sa + '\u0000' + sb + '\u0000' + e.type;
        var a = Math.min(aa, ab) * ((agg.count || 1) >= WEAK ? 1 : 0.45);
        // 焦点相关性只能在这一趟判：只有这里拿得到**原始**端点（代表端点已经沿祖先链
        // 抬升过了，判不出「焦点是代表的后代」那种情况）。多条原始边会塌成同一条代表边，
        // 所以标志要 OR 累积，不能被后来的覆盖。
        var sF = isFocusSide(A, selN), tF = isFocusSide(B, selN);
        var hs = !!(sF || tF);
        var hh = !!(isFocusSide(A, hovN) || isFocusSide(B, hovN));
        // sF === tF 说明两端都在焦点子树内 —— 这是焦点的**内部**边（比如同一篇笔记里
        // 两个 heading 互链），对面没有「别的元素」，不该加邻居环。
        if (hs && sF !== tF) hotNeighbors.add(sF ? sb : sa);
        var prev = picks.get(key);
        if (!prev) picks.set(key, { e: agg, a: a, sa: sa, sb: sb, hs: hs, hh: hh });
        else {
          if (a > prev.a) prev.a = a;
          prev.hs = prev.hs || hs;
          prev.hh = prev.hh || hh;
        }
      }
      // stats.edges 的含义不变：无关边是被**压暗**而不是被删除，落笔的代表边一条不少。
      // focusEdges 才是「与焦点相关的有几条」。两个新计数都要写在早退之前，
      // 否则空帧会留下上一帧的脏值。
      stats.edges = picks.size;
      // 被门挡掉的焦点边补画：必须排在早退之前 —— 全被门挡的帧（picks 为空）
      // 正是用户「面板说有链接、画布却一条线都没有」的帧，最需要补画。
      // 补画会往 hotNeighbors 加邻居，所以 focusNeighbors 要在补画之后计数。
      if (selN && droppedFocus.length) drawFocusEdges(droppedFocus, alpha);
      stats.focusNeighbors = hotNeighbors.size;
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
        // 焦点过滤：有选中时由选中说了算（悬停让位 —— 否则鼠标扫过别的圆会把刚建立
        // 起来的焦点视图搅乱）；没选中时退回悬停的软强调。无关边只是**压暗**，不删：
        // 「位置稳定 + 上下文稳定」是这个渲染器的设计契约，硬删边会丢掉「这片区域
        // 连得多密」的环境感知。
        var hot = selN ? p.hs : p.hh;
        var dim = hot ? 1 : (selN ? FOCUS_DIM : HOVER_DIM);
        if (p.hs) stats.focusEdges++;
        var ea = clamp(p.a * dim, 0, 1);
        ctx.globalAlpha = ea;
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

        // ── 两端截断 ────────────────────────────────────────────────────
        // 圆心到圆心画的话，线的两头都插进圆里、又和圆同色，看不出「从哪个圆出发、
        // 到哪个圆结束」。改成沿切向各退让「屏幕半径 + TRIM」，让线停在圆的边缘外侧。
        // 退让方向：弯曲边取「圆心 → 控制点」，直边取「圆心 → 圆心」，取错标记会歪。
        var ra = A._r * zoom + TRIM, rb = B._r * zoom + TRIM;
        var sdx = off ? mx - x1 : dx, sdy = off ? my - y1 : dy;
        var tdx = off ? x2 - mx : dx, tdy = off ? y2 - my : dy;
        var sl = Math.sqrt(sdx * sdx + sdy * sdy) || 1;
        var tl = Math.sqrt(tdx * tdx + tdy * tdy) || 1;
        sdx /= sl; sdy /= sl; tdx /= tl; tdy /= tl;
        var ex1 = x1 + sdx * ra, ey1 = y1 + sdy * ra;
        var ex2 = x2 - tdx * rb, ey2 = y2 - tdy * rb;
        // 两圆贴死（或截断过了头）→ 屏幕上没有可见长度，整条不落笔。硬画的话
        // moveTo/lineTo 会得到一条方向反掉的短线段，比不画更乱。
        var gx = ex2 - ex1, gy = ey2 - ey1;
        var glen = Math.sqrt(gx * gx + gy * gy);

        if (glen >= 0.5) {
          ctx.setLineDash(p.e.type === 'contrast' ? [5, 4] : []);
          ctx.beginPath();
          ctx.moveTo(ex1, ey1);
          if (off) ctx.quadraticCurveTo(mx, my, ex2, ey2);
          else ctx.lineTo(ex2, ey2);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // ── 端点标记任务（读作「• 出 ——— ▶ 入」）─────────────────────────
        // 短于 MARK_MIN 就不画标记：密集簇里几十个小箭头糊成噪点，比没有更难读。
        if (glen < MARK_MIN) return;
        // 热边设 0.75 的地板值 —— 「我选中的链接」方向必须读得清；冷边完全继承连线
        // 自己的 alpha，于是焦点模式下被压到 7% 的无关边不会冒出标记来添乱。
        var ma = hot ? Math.max(ea, 0.75) : ea;
        if (ma < 0.1) return;
        var mrgb = MARK_RGB[p.e.type] || MARK_RGB.derives || rgb;
        var dot = clamp(1.6 + lw * 0.5, 2, 4);
        // 箭头只给 derives / prerequisite；contrast 是无向的（见 annotations.yaml
        // 的字段说明），两端都只画点。id 是这个标记**附着的节点**，让标记清单自描述
        // （控制台里能直接问「这个点贴在谁身上」，自动化验证也据此量几何）。
        if (p.e.type === 'derives' || p.e.type === 'prerequisite') {
          markJobs.push({ k: 1, x: ex2, y: ey2, ux: tdx, uy: tdy, id: B.id,
                          s: clamp(5 + lw * 1.6, 7, 14), c: mrgb, a: ma });
        } else {
          markJobs.push({ k: 0, x: ex2, y: ey2, ux: 0, uy: 0, id: B.id,
                          s: dot, c: mrgb, a: ma });
        }
        markJobs.push({ k: 0, x: ex1, y: ey1, ux: 0, uy: 0, id: A.id,
                        s: dot, c: mrgb, a: ma });
      });
      ctx.globalAlpha = 1;
    }

    // 端点标记落笔。单独一趟，排在 drawNodes 之后（理由见 markJobs 的声明处），
    // 排在 drawEmphasis 之前 —— 让选中白环 / 邻居蓝环仍然压过标记，延续
    // 「哪个是我选的」永远一目了然的优先级。
    function drawEdgeMarkers() {
      stats.marks = markJobs.length;
      if (!markJobs.length) return;
      for (var i = 0; i < markJobs.length; i++) {
        var j = markJobs[i];
        ctx.globalAlpha = j.a;
        ctx.fillStyle = rgba(j.c, 1);
        ctx.beginPath();
        if (j.k) {
          var s = j.s, ux = j.ux, uy = j.uy;
          ctx.moveTo(j.x, j.y);
          ctx.lineTo(j.x - ux * s - uy * s * 0.5, j.y - uy * s + ux * s * 0.5);
          ctx.lineTo(j.x - ux * s + uy * s * 0.5, j.y - uy * s - ux * s * 0.5);
          ctx.closePath();
        } else {
          ctx.arc(j.x, j.y, j.s, 0, TAU);
        }
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    // 沿 parent 链向上找第一个「在屏且没铺满视口」的祖先：alpha.has 说明它过了本帧
    // 视口裁剪与淡入门；sr < farCornerDist 说明它的边界还在屏内。铺满视口的 wash 不能
    // 当锚点 —— 它的边界全在屏外，trim 到边界等于把端点放到屏外，等于没画（用户 z=28
    // 的场景里 Science and Tech 根就是这种铺满屏的罩子）。整链都没有合格者时返回
    // on:false，调用方按「这一端在屏外」处理。
    function resolveAnchor(n, alpha) {
      var cur = n;
      while (cur) {
        var sx = w2sx(cur.x), sy = w2sy(cur.y), sr = cur._r * cam.zoom;
        if (alpha.has(cur.id) && sr < farCornerDist(sx, sy)) {
          return { on: true, node: cur, sx: sx, sy: sy, sr: sr };
        }
        cur = cur.parent ? byId.get(cur.parent) : null;
      }
      return { on: false, node: n };
    }

    // 补画线段：两个在屏锚点之间的 trim 直线 + 两端标记。形状照抄 drawEdges 的截断与
    // 标记几何（源端圆点 / 目标端箭头），区别只有两处：恒为直线（补画线是「方向线索」，
    // 直比弯好读），标记走 markJobs 排队到 drawNodes 之后落笔 —— 就地画会被相切邻圆盖掉。
    function drawFocusSegment(aA, aB, ea, lw, rgb, mrgb, type, dot) {
      var dx = aB.sx - aA.sx, dy = aB.sy - aA.sy;
      var dist = Math.sqrt(dx * dx + dy * dy) || 1;
      var ux = dx / dist, uy = dy / dist;
      var r1 = aA.sr + TRIM, r2 = aB.sr + TRIM;
      var ex1 = aA.sx + ux * r1, ey1 = aA.sy + uy * r1;
      var ex2 = aB.sx - ux * r2, ey2 = aB.sy - uy * r2;
      var glen = Math.sqrt((ex2 - ex1) * (ex2 - ex1) + (ey2 - ey1) * (ey2 - ey1));
      if (glen >= 0.5) {
        ctx.lineCap = 'round';
        ctx.globalAlpha = ea;
        ctx.strokeStyle = rgba(rgb, 1);
        ctx.lineWidth = lw;
        ctx.setLineDash(type === 'contrast' ? [5, 4] : []);
        ctx.beginPath();
        ctx.moveTo(ex1, ey1);
        ctx.lineTo(ex2, ey2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }
      if (glen < MARK_MIN) return;
      var ma = Math.max(ea, 0.75);
      var s = clamp(5 + lw * 1.6, 7, 14);
      if (type === 'derives' || type === 'prerequisite') {
        markJobs.push({ k: 1, x: ex2, y: ey2, ux: ux, uy: uy, id: aB.node.id, s: s, c: mrgb, a: ma });
      } else {
        markJobs.push({ k: 0, x: ex2, y: ey2, ux: 0, uy: 0, id: aB.node.id, s: dot, c: mrgb, a: ma });
      }
      markJobs.push({ k: 0, x: ex1, y: ey1, ux: 0, uy: 0, id: aA.node.id, s: dot, c: mrgb, a: ma });
    }

    // 被门挡掉的焦点边补画。三道门各有各的理由（同容器聚合、本层无聚合代表、端点不在屏），
    // 但对用户来说都是「面板说有链接、画布没画」。于是焦点相关的边被门挡掉之后，降级成
    // 「画在两端点的在屏代表之间」：
    //   双端在屏   → 两个代表之间直线 + 端点标记（形状同普通边）；
    //   一在一不在 → 线止于视口边缘、箭头落在边上指方向，边缘挂一枚写着屏外端点名的 chip；
    //   双端屏外   → 只计数不画（两端都看不见的线是纯噪声）。
    // 去重：同 (锚A, 锚B, type) 的多条原始边塌成一条线、count 累加；屏外端按原始 id 做键、
    // 彼此不合并（各挂各的 chip）。
    function drawFocusEdges(dropped, alpha) {
      var selN = byId.get(selectedId);
      var groups = new Map();
      for (var i = 0; i < dropped.length; i++) {
        var d = dropped[i];
        var aA = resolveAnchor(d.A, alpha), aB = resolveAnchor(d.B, alpha);
        var kA = aA.on ? aA.node.id : ' ' + d.A.id;
        var kB = aB.on ? aB.node.id : ' ' + d.B.id;
        var key = kA + '\u0000' + kB + '\u0000' + d.e.type;
        var g = groups.get(key);
        if (!g) {
          g = { aA: aA, aB: aB, type: d.e.type, count: 0, idA: d.A.id, idB: d.B.id };
          groups.set(key, g);
        }
        g.count += 1;
      }
      groups.forEach(function (g) {
        stats.focusEdges += 1;
        var nA = byId.get(g.idA), nB = byId.get(g.idB);
        var sF = isFocusSide(nA, selN), tF = isFocusSide(nB, selN);
        if (sF !== tF) {
          var nb = sF ? g.aB : g.aA;
          if (nb.on) hotNeighbors.add(nb.node.id);
        }
        if (!g.aA.on && !g.aB.on) return;
        if (g.aA.on && g.aB.on && g.aA.node.id === g.aB.node.id) return;
        var rgb = EDGE_RGB[g.type] || EDGE_RGB.derives || [76, 141, 255];
        var mrgb = MARK_RGB[g.type] || MARK_RGB.derives || rgb;
        var lw = Math.min(4, 0.6 + 1.8 * Math.log(1 + g.count) / Math.LN2) + 0.8;
        var dot = clamp(1.6 + lw * 0.5, 2, 4);
        if (g.aA.on && g.aB.on) {
          var ea = clamp(Math.min(alpha.get(g.aA.node.id), alpha.get(g.aB.node.id)) *
                         (g.count >= WEAK ? 1 : 0.45), 0, 1);
          drawFocusSegment(g.aA, g.aB, ea, lw, rgb, mrgb, g.type, dot);
          return;
        }
        // 一在一不在：S = 在屏锚点，T = 屏外原始端点。
        // dir 从 S 中心指向 T 的屏幕投影（可能在屏外 —— 那正是方向线索）
        var S = g.aA.on ? g.aA : g.aB;
        var T = g.aA.on ? g.aB : g.aA;
        var outgoing = g.aA.on;
        var tx = w2sx(T.node.x), ty = w2sy(T.node.y);
        var ddx = tx - S.sx, ddy = ty - S.sy;
        var dl = Math.sqrt(ddx * ddx + ddy * ddy);
        var ux = dl > 1e-6 ? ddx / dl : 1, uy = dl > 1e-6 ? ddy / dl : 0;
        var Hc = H - FOOTER_H;
        var tBest = Infinity;
        if (ux > 1e-9) tBest = Math.min(tBest, (W - S.sx) / ux);
        if (ux < -1e-9) tBest = Math.min(tBest, (0 - S.sx) / ux);
        if (uy > 1e-9) tBest = Math.min(tBest, (Hc - S.sy) / uy);
        if (uy < -1e-9) tBest = Math.min(tBest, (0 - S.sy) / uy);
        if (!isFinite(tBest) || tBest <= 0) return;
        var px = S.sx + ux * tBest, py = S.sy + uy * tBest;
        var rS = S.sr + TRIM;
        var ea2 = clamp(alpha.get(S.node.id) * (g.count >= WEAK ? 1 : 0.45), 0, 1);
        var ma = Math.max(ea2, 0.75);
        var as = clamp(5 + lw * 1.6, 7, 14);
        if (tBest - rS >= 0.5) {
          ctx.lineCap = 'round';
          ctx.globalAlpha = ea2;
          ctx.strokeStyle = rgba(rgb, 1);
          ctx.lineWidth = lw;
          ctx.setLineDash(g.type === 'contrast' ? [5, 4] : []);
          ctx.beginPath();
          ctx.moveTo(S.sx + ux * rS, S.sy + uy * rS);
          ctx.lineTo(px, py);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.globalAlpha = 1;
        }
        // 箭头无论如何都落：视口边箭头是本帧唯一的方向线索。
        // 出边：箭头在视口边朝外、圆点在在屏端圆边界；入边：圆点在视口边、箭头在在屏端圆边界朝它
        if (outgoing) {
          markJobs.push({ k: 1, x: px, y: py, ux: ux, uy: uy, id: T.node.id, s: as, c: mrgb, a: ma });
          markJobs.push({ k: 0, x: S.sx + ux * rS, y: S.sy + uy * rS, ux: 0, uy: 0, id: S.node.id, s: dot, c: mrgb, a: ma });
        } else {
          markJobs.push({ k: 1, x: S.sx + ux * rS, y: S.sy + uy * rS, ux: -ux, uy: -uy, id: S.node.id, s: as, c: mrgb, a: ma });
          markJobs.push({ k: 0, x: px, y: py, ux: 0, uy: 0, id: T.node.id, s: dot, c: mrgb, a: ma });
        }
        chipJobs.push({ px: px, py: py, dx: ux, dy: uy, id: T.node.id, count: g.count, text: chipLabel(T.node) });
      });
      if (chipJobs.length > CHIP_MAX) {
        var over = chipJobs.length - CHIP_MAX;
        chipJobs.length = CHIP_MAX;
        chipJobs.push({ px: W - 12, py: H - FOOTER_H - 12, dx: 0, dy: 0,
                        id: null, count: over, text: '+' + over, right: true });
      }
      stats.chips = chipJobs.length;
    }

    function chipLabel(n) {
      var t = n.label || n.id;
      return t.length > 18 ? t.slice(0, 18) + '…' : t;
    }

    // ⑥ 屏外 chip：屏幕空间 HUD 覆盖层（drawLabels 之后、最顶层）。每枚 chip 挂在线停住的
    // 视口边缘、沿线的反方向内移 14px，读作「线指向这个标签」；折叠的「+k」钉在右下角。
    // chip 只指示方向与名字，点击无行为 —— 导航是侧栏边行的事（点边行 fitPair 框住两端）。
    function drawChips() {
      if (!chipJobs.length) return;
      var Hc = H - FOOTER_H;
      ctx.font = '11px ' + FONT;
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      for (var i = 0; i < chipJobs.length; i++) {
        var j = chipJobs[i];
        var w = measure(j.text, '11px ' + FONT) + 12;
        var h = 18;
        var x0, y0;
        if (j.right) {
          x0 = j.px - w; y0 = j.py - h;
        } else {
          x0 = clamp(j.px - j.dx * 14 - w / 2, 4, W - w - 4);
          y0 = clamp(j.py - j.dy * 14 - h / 2, 4, Hc - h - 4);
        }
        ctx.globalAlpha = 1;
        ctx.fillStyle = 'rgba(22,27,34,0.92)';
        ctx.strokeStyle = 'rgba(139,148,158,0.35)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x0, y0, w, h, 4);
        else ctx.rect(x0, y0, w, h);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = '#d6dbe4';
        ctx.fillText(j.text, x0 + 6, y0 + h / 2 + 0.5);
      }
      ctx.globalAlpha = 1;
    }

    // 包含关系不画成线，但 hover / 选中时把祖先链点出来，弥补放大后失去的上下文。
    // 样式刻意和链接线区分开：链接是**实线 + 端点标记**，这条是**灰色点线**、无端点
    // 标记、也不带方向 —— 它表达的是「你在哪个文件夹/笔记里」（树），不是「谁链接
    // 谁」（图）。两者都画成线，就一定会被误读成同一种关系。
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
      ctx.lineWidth = 1.2;
      ctx.lineCap = 'round';
      // [1,4] + round 线帽 = 一串圆点。和 contrast 链接边的 [5,4] 长划虚线明显不同
      ctx.setLineDash([1, 4]);
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
        // hotNeighbors 装的是**当前层级的代表**（drawEdges 就地收集），所以粗尺度下
        // 被链接的 heading 还没浮现时，环会正确地画在它的祖先 note/folder 上 ——
        // 和连线的端点层级天然一致，不会出现「线连到 A、环画在 B」。
        var isNb = hotNeighbors.has(n.id) && !isSel;
        if (!(isSel || isHov || isMatch || isNb || (n.kind === 'note' && n.mastery > 0))) continue;
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
        // 邻居环：画在选中/悬停环**之前**，同轨重叠时让白环压过蓝环，
        // 「哪个是我选的」永远一目了然。比选中环细、比它淡。
        // alpha 用 fadeInOf 而不是 a —— 见 fadeInOf 的注释（pitfall 8）。
        if (isNb) {
          ctx.globalAlpha = clamp(fadeInOf(n) * 0.85, 0, 1);
          ctx.lineWidth = 1.4;
          ctx.strokeStyle = rgba(NB_RGB, 1);
          ctx.beginPath();
          ctx.arc(sx, sy, sr + 2.5, 0, TAU);
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
        var text = m.label || m.id;
        var sr = m._sr;
        // 大容器：标签居中压在圆内顶部（省名写在省的范围内，地图就这么干）；
        // 小圆点：标签挂在右侧，免得盖住圆本身。
        var inside = sr >= LABEL_INSIDE_PX;
        // 粗细是「类别」信号（浅层骨架 vs 深层细节），字号是「尺度」信号，两者不冲突。
        // 可用宽度：圆内标签不许溢出自己的圆（1.8 × sr ≈ 内接弦的九成）；
        // 圆外标签没有圆的约束，受 label_max_width 收口，仍超宽的截断（clipLabel）。
        var weight = m.depth <= LABEL_BOLD_DEPTH ? '600 ' : '';
        // 圆内连下限字号都装不下的长名字改挂圆外：硬塞只会让字压过圆描边、盖住里面
        // 的子节点。改挂圆外后它受 label_max_width 收口，不会横扫半屏。
        if (inside && measure(text, weight + LABEL_FS_MIN + 'px ' + FONT) + 6 > 1.8 * sr) inside = false;
        var fs = fitFont(text, labelFontSize(sr), weight, inside ? 1.8 * sr : LABEL_MAX_W);
        var font = weight + fs + 'px ' + FONT;
        if (!inside) text = clipLabel(m.id, text, font);
        var wpx = measure(text, font) + 6;
        var hpx = fs + 4;
        var cxs = w2sx(m.x), cys = w2sy(m.y);
        var sx, sy, x0, x1;
        if (inside) {
          // 顶边距随字号走：sy - hpx/2 = cys - sr + 2，任何字号下文字上边界都离圆的
          // 描边 2px，不会被切到。fs=11 时偏移 9.5 ≈ 原来写死的 10
          sx = cxs; sy = cys - sr + fs * 0.5 + 4;
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
        // 渲染用的 alpha 走平滑压暗：alphaOf 在 cam.zoom 越过 _gate 时把祖先 alpha
        // 从 ~1.0 瞬跳到 parent_dim，文字会「啪」地变淡。fillAlphaOf 让压暗跟着最先
        // 浮现的那个孩子同步渐变（圆的填充早就这么干了，见 fillAlphaOf 的注释）。
        // 排序仍读 alpha.get()（含硬压暗）—— 那是「谁该抢到标签位」的既有语义，
        // 已人眼验收过，本轮只换落笔浓度、不换竞争顺序。
        var al = clamp(LABEL_SMOOTH_DIM ? fillAlphaOf(m) : alpha.get(m.id), 0, 1);
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

    // hover 的判定只有一处：mousemove 与 draw 收尾都走这里，保证相机自己动
    // （滚轮 / tween / 程序化 tweenTo）之后悬停态也跟着光标下的新内容走。
    function evalHover(px, py) {
      var hit = hitTest(px, py);
      var id = hit ? hit.id : null;
      canvas.style.cursor = id ? 'pointer' : 'grab';
      if (id !== hoverId) {
        hoverId = id;
        invalidate();
        if (hooks.onHover) hooks.onHover(id, hit, px, py);
      } else if (hooks.onHover && id) {
        hooks.onHover(id, hit, px, py);
      }
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

    // 框住链接两端：zoom 先取两端里较大的浮现 zoom ×1.15（保证两端都过了淡入门），
    // 再用「两个包围圆一起进视口」封顶 —— 在屏优先于淡入。给侧栏边行点击用：
    // 用户点一条边就是想亲眼看「这条链接连的是哪两个元素」，一次 tween 框住两端。
    function fitPair(idA, idB, ms) {
      var a = byId.get(idA), b = byId.get(idB);
      if (!a || !b) return;
      var minX = Math.min(a.x - a._r, b.x - b._r), maxX = Math.max(a.x + a._r, b.x + b._r);
      var minY = Math.min(a.y - a._r, b.y - b._r), maxY = Math.max(a.y + a._r, b.y + b._r);
      var cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
      var rx = (maxX - minX) / 2, ry = (maxY - minY) / 2;
      var rr = Math.sqrt(rx * rx + ry * ry) || 1;
      var z = clamp(Math.max(a._mz, b._mz) * 1.15, zMin, zMax);
      z = clamp(Math.min(z, 0.9 * fitRadius() / rr), zMin, zMax);
      tweenTo({ zoom: z, panX: W / 2 - cx * z, panY: (H - FOOTER_H) / 2 - cy * z },
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
      lastMouse = (p[0] < 0 || p[1] < 0 || p[0] > W || p[1] > H) ? null : p;
      if (dragging) {
        var dx = e.clientX - lastX, dy = e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY;
        dragMoved += Math.abs(dx) + Math.abs(dy);
        cam.panX += dx; cam.panY += dy;
        invalidate();
        if (hooks.onCamera) hooks.onCamera();
        return;
      }
      if (lastMouse) evalHover(p[0], p[1]);
    });

    canvas.addEventListener('mouseleave', function () { lastMouse = null; });

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
      // 双击空白 = 回到默认视角，顺手清掉选中 —— 否则焦点过滤还挂着，用户会以为
      // 「回到首页了怎么连线还是稀的」。和单击空白、Esc 的行为对齐。
      if (!hit) {
        selectedId = null;
        invalidate();
        if (hooks.onSelect) hooks.onSelect(null, null);
        resetView();
        return;
      }
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
      // 端点标记的落笔清单（每帧在 drawEdges 里重建）。暴露出来只为自动化验证能直接
      // 量「标记有没有落在圆外」这类几何不变式，不必在测试里复刻截断公式。
      markJobs: markJobs,
      chipJobs: chipJobs,
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
      fitPair: fitPair,
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
