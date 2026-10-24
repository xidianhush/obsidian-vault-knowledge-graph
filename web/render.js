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
 * ── 链接线：只有一种画法「逐条链接」 ──────────────────────────────────────
 *
 * 每条语义链接各画一条细线，**端点恒为真实节点自己的位置，绝不沿 parent 链上移**；
 * 颜色与不透明度恒定，缩放/平移只改线的长度和形状，不减少条数。唯一的门是几何的：
 * 整条线段的屏幕 bbox 与视口不相交才不画。于是圆在当前尺度上没浮现、或整体平移出屏
 * 时，线照样从它的世界坐标出发，粗尺度下会看到一条线**穿进**父级圆的内部 —— 这正是
 * 想要的暗示：「这里面还有更深的知识点」。同一对父圆之间线的**条数**就是关联强度：
 * 真实端点本来就散在父圆内部的不同位置，一束线天然散开。放大时看得清单条链接的箭头，
 * 缩小时「LTI analysis → Calculus」之间那一束细线比任何一根粗线都更能说明这两篇笔记
 * 有多纠缠。所有链接统一用 theme.raw_edge 的近白色；关系类型由线型（contrast = 虚线）
 * 与端点标记（只有 derives / prerequisite 画箭头）表达。
 *
 * 2026-10-24 删掉了原来的「按尺度聚合（agg）」画法：它把多条链接合并成一条粗线、按
 * 关系类型分色，但既增加理解成本，又让 payload 多背 49% 的 aggregates 体积。现在只有
 * 这一种画法。焦点/悬停对无关连线的压暗保留 —— 那是「我选中的是什么」的语义，与缩放
 * 无关。屏外 chip：焦点链接一端在屏外时挂一枚名字（两端都出屏、且这一帧真落了笔时也挂
 * 一枚，命名非焦点端）。
 */

(function () {
  'use strict';

  var FOOTER_H = 46;          // 与 template.html 里 #footer 的高度一致
  var LABEL_CELL = 24;        // 标签碰撞网格边长（屏幕像素）
  var LABEL_BUDGET = 400;     // 每帧最多考虑多少个标签候选
  var CULL_MARGIN = 32;       // 视口外扩余量（屏幕像素）
  var LABEL_INSIDE_PX = 28;   // 屏幕半径超过这个值的容器，标签压在圆内顶部
  // 「这一笔算不算画出来了」的最低不透明度。低于它的落笔在 8 位画布上合成后与背景
  // 完全同值（≈0.2/255，四舍五入成 0），肉眼与像素都看不见 —— 判「视口是不是空的」
  // 必须按这个门槛算，而不能按「候选集是否为空」，否则会出现「画布上一片漆黑、
  // 却因为候选集非空而不画兜底提示」的死局（放开缩放后放大到极端就会撞上）。
  var PAINT_MIN = 0.02;
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

  // 压暗：domain 色乘一个系数。2026-10-24 视觉改版用来给实心圆做「边缘更暗」的
  // 径向渐变，让平涂色块有玻璃片的厚度感。
  function darken(rgb, f) {
    return [Math.round(rgb[0] * f), Math.round(rgb[1] * f), Math.round(rgb[2] * f)];
  }

  function createRenderer(canvas, DATA, hooks) {
    hooks = hooks || {};

    var META = DATA.meta;
    var LOD = META.lod || {};
    var ZC = META.zoom || {};
    var THEME = META.theme || {};
    var NODES = DATA.nodes;
    var EDGES = DATA.edges;

    var MIN_PX = LOD.min_px || 18;
    // 标签门槛是「淡入进度」。2026-10-21 起标签与圆**同进同出**（用户要求）：门槛降到
    // 0.02，且落笔浓度直接用圆这一帧的 alpha（见 drawLabels 里的 alpha.get）。
    // 仍然不能读压暗后的 alpha 当门槛 —— 祖先层被 parent_dim 压到底图浓度之后永远够不到。
    var LABEL_A = LOD.label_alpha == null ? 0.02 : LOD.label_alpha;
    // 标签字号（2026-10-21，方案「丙」）：
    //   fs = clamp(min(label_font_scale × 屏幕半径, 塞得进圆的最大字号), 下限, 上限)
    // 旧版是对数插值封顶 22px —— 实测一个直径 3000px 的圆里那行字只占 4%，满屏只剩
    // 纯色。现在字号跟着圆长大，长标题再被「塞得下」这一项自动缩小。
    // 一律 == null 兜默认（0 是合法值，|| 会把它吃掉）。
    var LABEL_FS_MIN = LOD.label_font_min == null ? 11 : LOD.label_font_min;
    var LABEL_FS_MAX = LOD.label_font_max == null ? 64 : LOD.label_font_max;
    var LABEL_FS_SCALE = LOD.label_font_scale == null ? 0.3 : LOD.label_font_scale;
    // 圆内可用宽度占直径的比例。0.8 × 直径 = 竖直方向居中处弦长的 0.8 倍，
    // 左右各留 10% 让文字不贴到描边上。
    var LABEL_AVAIL = 0.8;
    var LABEL_BOLD_DEPTH = LOD.label_bold_depth == null ? 2 : LOD.label_bold_depth;
    var FADE = LOD.fade_span || 1.35;
    // 焦点模式的压暗系数。必须用 == null 而不是 ||：0（彻底不画无关连线）是合法值，
    // 会被 || 当成假值吃掉。
    var FOCUS_DIM = LOD.focus_edge_dim == null ? 0.07 : LOD.focus_edge_dim;
    var HOVER_DIM = LOD.hover_edge_dim == null ? 0.75 : LOD.hover_edge_dim;
    // 静息态（既没选中、也没悬停）的连线浓度。2026-10-21 起与 hover 分开：原先两者共用
    // HOVER_DIM(0.75)，于是「刚打开界面」也是满屏 0.75 的白线，首屏显得很吵。
    // 用户要的是：首屏安静，**只有选中浅层大元素时**才靠 1.0 vs FOCUS_DIM 的对比出网线感。
    var IDLE_DIM = LOD.idle_edge_dim == null ? 0.45 : LOD.idle_edge_dim;
    // 端点标记。TRIM 是连线在两端圆边界处截断后留的间隙；TINT 是标记向浅色提亮的比例，
    // 必须提亮：derives 的边色 #4C8DFF 和 Science and Tech 的节点色是同一个 hex，
    // 同色标记落在同色圆边上等于隐形。
    var TRIM = LOD.edge_trim_clearance == null ? 2 : LOD.edge_trim_clearance;
    var MARK_TINT = LOD.edge_marker_tint == null ? 0.55 : LOD.edge_marker_tint;
    var MARK_LIGHT = hexToRgb('#d6dbe4');
    // 焦点链接的「屏外目标」chip 上限。选中元素的链接有一端在当前尺度屏外时，视口边缘
    // 挂一枚写着目标名的 chip；超出上限的折叠成右下角一枚「+k」
    var CHIP_MAX = LOD.focus_offscreen_chips == null ? 8 : LOD.focus_offscreen_chips;
    // ghost 下一层（2026-10-24 视觉改版）：当前「前沿层 + 1」的圆与描边固定用很低的不透明度
    // 画一层，让人隐约看到当前层内部的下一层结构（像透出磨砂玻璃）。它与层级带 LOD 完全
    // 解耦 —— 不参与 alphaOf / painted / 标签碰撞 / 命中测试，只是纯视觉景深。
    // 0 = 关闭，回到「只看得到当前层」的旧观感。
    var GHOST_A = LOD.ghost_alpha == null ? 0.08 : LOD.ghost_alpha;
    var GHOST_LABEL_A = LOD.ghost_label_alpha == null ? 0.12 : LOD.ghost_label_alpha;
    var GHOST_LABEL_PX = LOD.ghost_label_min_px == null ? 56 : LOD.ghost_label_min_px;
    var GHOST_LABEL_MAX = 40;   // 字号上限，也用来限制 ghost 文字别抢主标签
    var PARENT_DIM = ZC.parent_dim == null ? 0.22 : ZC.parent_dim;
    var WHEEL_STEP = ZC.wheel_step || 1.12;
    var TRANSITION = ZC.transition_ms || 260;
    var HOME_FIT = ZC.home_fit == null ? 1.08 : ZC.home_fit;
    // zoom 的**硬护栏**：只为拦住「任何 bug 把 zoom 推到 0 / Infinity 让画布静默失效」，
    // 不是可用范围。滚轮**不受**下面 zMin / zMax 限制 —— 那两个是地标：
    //   zMin = 最小的顶层学科刚好看得见的那一档（缩到底能看见全部学科）
    //   zMax = 最挤的节点舒服淡入的那一档
    // 它们仍然被 HUD、层级胶囊、focusOn / fitPair / zoomToDepth 使用（工具自己去某个
    // 地方时不该跑出地标范围），但不再夹住用户自己的滚轮。见 §「地标不是墙」。
    var ZOOM_HARD_LO = 1e-6, ZOOM_HARD_HI = 1e6;
    var ENTER = LOD.enter || [];
    var MAXD = META.max_depth || ENTER.length || 1;
    // 第五轮（2026-10-24）：药丸层删除 —— **实心圆自己就是入口**。
    // Ctrl + 悬停某个圆 → app.js 用 hitTest 取到节点：标题圆就弹预览并从那一节滚起，
    // 文件夹/笔记圆则提示「还没到标题层」。
    // 虚拟根的世界半径（构建期落盘）。home 视角 = 让整个根正好铺满可视半径。
    var ROOT_R = META.layout_root_radius || 1000;

    // 端点标记的颜色表：链接线色向浅色混合 MARK_TINT。构建期算一次，绘制循环里只查表。
    // 必须提亮 —— derives 的边色和 Science and Tech 的节点色同源，同色标记落在同色
    // 圆边上等于隐形。
    function tintLight(c) {
      return [
        Math.round(c[0] + (MARK_LIGHT[0] - c[0]) * MARK_TINT),
        Math.round(c[1] + (MARK_LIGHT[1] - c[1]) * MARK_TINT),
        Math.round(c[2] + (MARK_LIGHT[2] - c[2]) * MARK_TINT)
      ];
    }
    // ── 链接线配色（2026-10-24 视觉改版，方案 A）────────────────────────────
    // 同域链接 = 该学科的 domain 色向白提亮 theme.edge_tint；跨学科链接 = 从源学科色
    // 到目标学科色的线性渐变。这样线“属于”它两端的圆，同时跨学科连接一眼可辨。
    // 关系类型仍只由线型（contrast = 虚线）与端点标记（只有 derives / prerequisite
    // 画箭头）表达，**存储粒度仍然不参与配色**（坑 34 的原则没有变）。
    // theme.edge_color = "flat" 可退回旧行为（所有链接统一 theme.raw_edge 近白）。
    var EDGE_DOMAIN = (THEME.edge_color || 'domain') !== 'flat';
    var EDGE_TINT = THEME.edge_tint == null ? 0.62 : THEME.edge_tint;
    // flat 模式的统一色；domain 模式下它只作为没有 domain 的兜底。
    var RAW_EDGE_RGB = hexToRgb(THEME.raw_edge || '#E6EDF3');
    // 线宽与端点标记门槛。线宽**刻意不含 zoom 因子**：契约就是「缩放只改长度，不改粗细
    // 浓淡」。标记门槛也很小：端点是真实节点自己，低缩放下大量线只有几 px，门槛大了
    // 会让它们全都没箭头，等于违背「细线箭头不随缩放消失」。填 0 = 恒画标记。
    var RAW_LW = LOD.raw_edge_width == null ? 1 : LOD.raw_edge_width;
    var RAW_MARK_MIN = LOD.raw_marker_min_len == null ? 6 : LOD.raw_marker_min_len;
    // 邻居环的颜色。用一个比学科色更浅的冷蓝（2026-10-24 视觉改版）：和白色的选中环
    // 同轨但更细，一眼能分清「哪个是我选的」；不按边类型着色，也刻意避开暖琥珀（搜索命中）。
    var NB_RGB = hexToRgb('#7FB2E8');
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
    // 父圆压暗与「何时浮现」已经整体交给下面的层级带（levelFade / dimFactor），
    // 不再按「孩子自己的 minzoom」算 _gate / _cLo / _cHi —— 那套是 per-node 门槛
    // 时代的产物，会让同层的兄弟因为半径不同而各自为政（见 HANDOFF §4 坑 39）。

    // 语义边（contains 不画：包含关系已经由半径几何表达，画出来只会糊成一团）
    var SEM = EDGES.filter(function (e) { return e.type !== 'contains'; });
    // _nl = note-level，两端都是整篇笔记的链接。只在焦点补画的分组键里用：否则
    // 「LTI→Calculus」和「LTI#CTFT→Calculus#定积分」在文件级会解析到同一对锚点、
    // 同一种关系类型，被并成一条线，focusEdges 会少算一条。
    SEM.forEach(function (e) {
      var A = byId.get(e.s), B = byId.get(e.t);
      e._nl = !!(A && B && A.kind === 'note' && B.kind === 'note');
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
var ctrlMode = false;   // Ctrl 按住时给标题圆画虚线圈（可预览提示）
    var lastMouse = null;
    var filterSet = null, matchSet = null, labelMode = 'auto';
    var stats = { nodes: 0, edges: 0, labels: 0, focusEdges: 0, focusNeighbors: 0, marks: 0, chips: 0,
                  // painted = 真正按 PAINT_MIN 以上不透明度落了笔的节点数。nodes 是「候选
                  // 集大小」，painted 才是「屏幕上到底有没有东西」—— 兜底提示按 painted 判。
                  painted: 0,
                  // Ctrl 模式：这一帧给多少个标题圆画了「可预览」虚线圈
                  ctrlRings: 0,
                  // ghost 下一层：这一帧画了几个 ghost 圆 / 几行 ghost 文字（只给调试与回归看，
                  // 不进 painted、不进标签统计）
                  ghost: 0, ghostLabels: 0 };
    // 本帧与选中元素直接相连的**真实端点** id。drawEdges 主循环就地收集，
    // drawEmphasis 读它画蓝环。只用于绘制与计数，不落盘、不参与布局。
    var hotNeighbors = new Set();
    // 本帧要画的端点标记（源端圆点 / 目标端箭头）。drawEdges 只往这里塞任务不落笔：
    // draw() 里 drawNodes(front) 排在 drawEdges 之后，就地画的话标记会被紧贴的邻圆
    // 整个盖掉（packing 布局里圆是相切的）。真正落笔在 drawEdgeMarkers。
    // k: 0 = 圆点，1 = 箭头；ux/uy = 箭头指向的单位向量；s = 尺寸；c/a = 颜色与不透明度
    var markJobs = [];
    // 屏外目标 chip：写着屏外端点名字的小标签，钉在连线穿出视口的那一点上。
    // 线由 drawEdges 主循环一路画到屏外，chip 由主循环挂在它穿出视口处。
    // 三处只塞任务，真正落笔在 drawChips —— 屏幕空间的 UI 覆盖层，排在所有世界内容之后。
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

    // 以屏幕点 (sx, sy) 为锚改缩放：该点下的世界坐标保持不动。
    // 这里**不**夹在 [zMin, zMax] 里 —— 那是地标不是墙：用户可以自由缩到比 zMin 更小
    // （画面会渐渐清空，靠全空白兜底提示 + 双击/重置/Home 找回）或比 zMax 更大
    // （只是圆变大、标签字号早已饱和）。只留 ZOOM_HARD 那道远离正常范围的护栏。
    function zoomAt(sx, sy, z) {
      z = clamp(z, ZOOM_HARD_LO, ZOOM_HARD_HI);
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

    // ── 层级带（2026-10-21）──────────────────────────────────────────────
    // 浮现时机不再看节点自己的半径，而看它**属于第几层**：
    //   ENTER[L-1]        = 第 L 层开始淡入的 zoom（构建期按 home 锚定的等比阶梯算好）
    //   ENTER[L-1] * FADE = 第 L 层完全成熟的 zoom
    // 同一层的所有节点共用这条带 ⇒ 同时出现、同时变深、成熟后颜色完全一致；
    // 父圆在自己下一层成熟时被压暗（「省淡出、市淡入」的交接点也统一到同一个 zoom）。
    // 半径从此只决定「同层里画多大」，不再决定「什么时候出现」。
    function levelFade(depth, z) {
      var e = ENTER[Math.max(0, depth - 1)];
      if (e == null) return 1;                 // 超出表就不管（理论上不会）
      return smoothstep(e, e * FADE, z);
    }
    // 该层「成熟」的 zoom = 该层全部满不透明的那一档。跳层落点、focusOn、
    // fitPair 都用它 —— 用 _mz 会落到「本层还没开始淡入」的地方。
    function levelMature(depth) {
      var e = ENTER[Math.max(0, depth - 1)];
      return e == null ? 0 : e * FADE;
    }
    // 该深度的节点在哪个 zoom 上被压暗 = 下一层的成熟点。
    function levelDimAt(depth) {
      var e = ENTER[depth];                    // ENTER[depth] = M[depth+1] / FADE
      return e == null ? Infinity : e * FADE;
    }
    function dimFactor(depth, z) {
      var at = levelDimAt(depth);
      if (at === Infinity) return 1;
      // 压暗跟着**下一层的淡入带**同步渐变（起点 at/FADE、终点 at），
      // 于是「父圆退成底图」和「孩子长出来」是同一个动作的两个面，不会跳。
      return 1 - smoothstep(at / FADE, at, z) * (1 - PARENT_DIM);
    }


    function alphaOf(n) {
      var a = levelFade(n.depth, cam.zoom) * dimFactor(n.depth, cam.zoom);
      if (a <= 0.01) return 0;
      if (filterSet && !filterSet.has(n.id)) return 0;
      return a;
    }

    // 填充用的 alpha。层级带之后它与 alphaOf 已经是同一条曲线（压暗不再是
    // 「孩子全浮现」的跳变，而是跟着下一层的淡入带渐变），保留独立函数只为让
    // 调用点语义清楚：读填充的走这个，读「这个节点算不算在屏」的走 alphaOf。
    function fillAlphaOf(n) {
      return alphaOf(n);
    }

    // HUD 上的层级读数：max{ L : enter[L] ≤ zoom }
    function enterAt(zoom) {
      var L = 0;
      for (var i = 0; i < ENTER.length; i++) { if (ENTER[i] <= zoom) L = i + 1; else break; }
      return Math.max(1, L);
    }

    // 端点沿祖先链「当前浮现在哪一层」：层级带下 alpha 沿链天然单调不增
    // （深度越大越晚成熟），所以从浅往深扫，遇到第一个未开始的就停。
    function visibleLayer(n) {
      var ch = n._chain, L = 1;
      for (var i = 0; i < n.depth; i++) {
        var a = byId.get(ch[i]);
        if (!a) break;
        if (filterSet && !filterSet.has(a.id)) break;
        if (levelFade(a.depth, cam.zoom) <= 0.01) break;
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

    // 未被压暗的淡入进度。给强调环用：alphaOf 会把「已经有下一层在展开」的祖先
    // 乘上 PARENT_DIM，而粗尺度下的邻居代表**几乎总是**这种祖先 ⇒ 直接读 alpha
    // 会让环掉到两成浓度、基本看不见（pitfall 19）。层级带下它就是本层的 levelFade，
    // 与压暗解耦，正好是环需要的量。
    function fadeInOf(n) {
      return levelFade(n.depth, cam.zoom);
    }

    function measure(s, font) {
      var k = font + '|' + s;
      var v = textW.get(k);
      if (v == null) { ctx.font = font; v = ctx.measureText(s).width; textW.set(k, v); }
      return v;
    }

    // 标签字号（2026-10-21 重写，方案「丙」）：
    //   fs = clamp(min(label_font_scale × 屏幕半径, 塞得进这个圆的最大字号), 下限, 上限)
    // 两条腿各管一件事：
    //   * `scale × sr` 让字号跟着圆长大 —— 旧版对数插值封顶 22px，实测直径 3135px 的
    //     圆里那行字只占 4%，看着就是一整片纯色（用户报的「满屏大片实心圆」）。
    //   * 「塞得进这个圆」保证长标题（heading 常二三十字）不溢出圆，短名字在大圆里
    //     则会被放大到接近上限、把那块空地填满。
    // 仍然**不按 depth 分档**：depth 是复合轴（heading.depth = 笔记 depth + 标题级别），
    // 而同为 depth-1 的六个学科根世界半径能差十几倍，按 depth 分档会让铺满全屏的根和
    // 20px 小圆点用同一个字号。
    // **必须取整**：measure() 的缓存 key 是 font 字符串，连续字号会让缓存条目和
    // measureText 调用量随帧数无界增长；取整同时消除缩放过程中的字形抖动。
    function fitFontFor(sr, text, weight) {
      if (!(sr > 0)) return LABEL_FS_MIN;
      var availW = LABEL_AVAIL * 2 * sr;
      var want = Math.round(clamp(sr * LABEL_FS_SCALE, LABEL_FS_MIN, LABEL_FS_MAX));
      while (want > LABEL_FS_MIN &&
             measure(text, weight + want + 'px ' + FONT) + 6 > availW) want--;
      return want;
    }

    // 圆内标签的超宽收口：字号降到下限仍塞不进这个圆，就截断加省略号。
    // 不截断的话一条六十字的标题会以 11px 横向溢出、「压过」自己的圆描边和邻圆。
    // 完整名字仍在悬停 tooltip 与搜索里，信息不丢。
    // 结果按 (节点, font, 可用宽) 缓存：可用宽由屏幕半径取整而来，同屏标签的
    // 字号档位有界，所以缓存条目有界；不缓存的话二分过程里每个前缀都会进 measure
    // 缓存，随帧数无界增长。
    var clipCache = new Map();
    function clipToWidth(id, text, font, availW) {
      var key = id + '|' + font + '|' + (availW | 0);
      var hit = clipCache.get(key);
      if (hit !== undefined) return hit;
      var out = text;
      if (measure(text, font) + 6 > availW) {
        var lo = 0, hi = text.length;
        while (lo < hi) {
          var mid = (lo + hi + 1) >> 1;
          if (measure(text.slice(0, mid) + '…', font) + 6 <= availW) lo = mid;
          else hi = mid - 1;
        }
        out = text.slice(0, lo) + '…';
      }
      clipCache.set(key, out);
      return out;
    }

    // ── 绘制 ────────────────────────────────────────────────────────────
    // 趟次：① 容器底图 → ② 前景实心圆 → ③ 语义边 → ④ 祖先点线 → ⑤ 端点标记 →
    //       ⑥ 强调环 → ⑦ 标签 → ⑧ 屏外 chip。
    // 语义边画在实心圆**之上**（2026-10-21，用户要求）：原先线在圆下，浅层时 68 条里
    // 有 53 条整条躺在不透明圆底下、只剩箭头孤零零浮着，违背了「每处链接各画一条细线，
    // 任何缩放尺度都在」的契约。端点仍在各自圆的边界处截断，所以线不会插进自己的圆。
    // 祖先点线（悬停/选中的包含链）跟在连线之后，两者是一起读的。
    // 标记必须排在实心圆之后（否则被相切邻圆盖掉）、强调环之前（让选中白环压过箭头）。
    // 强调环（命中/选中/邻居）单独一趟，永远在世界内容之上、标签之下。
    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // 背景交给 CSS（template.html 的 body：深青径向渐变 + 极淡颗粒），画布只负责
      // 内容、每帧清成透明。这样换背景不会污染「画布空不空」的像素判据 ——
      // browser_check 的像素探针也相应改成 alpha 判据（2026-10-24 视觉改版）。
      ctx.clearRect(0, 0, W, H);

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
        // 可读性地板：同层同时开始浮现之后，层里最小那批的屏幕半径可能远小于
        // min_px。低于 0.5×min_px 的直接不画（否则是一片亚像素点），
        // 从 0.5×min_px 到 min_px 线性淡入 —— 它们比同层兄弟晚一点变实，但不会硬跳。
        if (sr < MIN_PX * 0.5) continue;
        a *= smoothstep(MIN_PX * 0.5, MIN_PX, sr);
        if (a <= 0.01) continue;
        n._sr = sr;
        alpha.set(n.id, a);
        drawn.push(n);
        // 地图矢量瓦片的 maxzoom：圆铺满整个内容视口后，它的填充只是一层均匀色
        // 罩、界线也在屏幕外，继续画只会和更外层的罩子叠成不透明色块。停画它，
        // 由还没铺满视口的最内层圆提供「你在哪个区域里」的界线 —— 省界退出屏幕
        // 后只剩市界，正是地图的做法。节点仍留在 drawn 里供命中测试与标签。
        if (sr >= farCornerDist(cx, cy)) continue;
        // 「区域」还是「点」也按层级算：下一层已经开始淡入 ⇒ 本层退成底图。
        // 同一层的所有节点在同一帧里一起切换，不会出现半层是面、半层是点。
        if (n.depth < MAXD && levelFade(n.depth + 1, zoom) > 0.01) wash.push(n);
        else front.push(n);
      }
      // 子盖父：深度升序，同深度大圆先画
      function byDepth(p, q) { return p.depth - q.depth || q._r - p._r; }
      wash.sort(byDepth);
      front.sort(byDepth);

      lastDrawn = drawn;
      // drawn 含「铺满视口而停画」的祖先（命中测试还要用它们）；nodes 是候选集大小，
      // painted 由下面几个绘制函数在**真的落笔**时累加，兜底提示按它判（见 PAINT_MIN）。
      stats.nodes = wash.length + front.length;
      stats.painted = 0;

      drawWash(wash);
      drawNodes(front, alpha);
      // ghost 下一层：压在实心圆**之上**才看得见（下一层的圆都在父圆内部，画在下面会被
      // 父圆填充整个盖掉）。它只是景深，不进命中测试与任何统计。
      drawGhost();
      drawCtrlRings(front, alpha);
      // 语义边画在实心圆之上：端点仍在各自圆的边界处截断（rawAnchor + TRIM），
      // 所以线不会插进自己的圆。
      drawEdges();
      // 祖先点线（悬停/选中时的包含链）同样提到圆之上：它和连线是一起读的，
      // 留在圆下会只剩连线可见、点线消失。
      drawChainHighlight();
      drawEdgeMarkers();
      drawEmphasis(drawn, alpha);
      drawLabels(drawn, alpha);
      // ⑥ 屏外 chip：屏幕空间的 HUD 覆盖层，压在所有世界内容之上
      drawChips();

      // 全空白兜底：地图软件在这种情况下会提示「此区域暂无详情」，这里照做。
      // 判据用 stats.painted（真的按 PAINT_MIN 以上落了笔的节点数），**不能**用
      // wash/front 是否为空：候选集非空但这些圆全在视口外、或落笔 alpha 低于
      // PAINT_MIN 而合成后与背景同值时，画布上其实一无所有 —— 那时用候选集判定就会
      // 出现「一片漆黑且没有任何提示」的死局。放开缩放之后放大到极端正好撞上这个坑
      // （实测 public 在 z ≥ 5000 时 0 个非背景像素、stats.nodes 却是 1）。
      if (!stats.painted) {
        ctx.globalAlpha = 1;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = '13px ' + FONT;
        ctx.fillStyle = 'rgba(126,135,154,0.9)';
        // 措辞要两个方向都管用：放开缩放后「空视口」既可能是缩得太远（要往回滚、
        // 即往上滚放大），也可能是放大到极端（连最小的圆都铺满视口 → maxzoom 停画，
        // 要往下滚）。原来只写「向下滚」在缩太远时是反的。
        ctx.fillText('此处没有内容 · 往回滚一点，或按 Home / 双击空白回到默认视角',
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

    // 圆心到内容视口矩形**最近**点的距离（圆心在视口内则为 0）。和 farCornerDist 配对，
    // 就能精确回答「这一笔到底会不会落在画布上」：
    //   圆盘穿过视口 ⟺ near < sr        → 填充可见
    //   圆环穿过视口 ⟺ near ≤ sr ≤ far  → 界线可见
    // 这个区分是必需的：一个圆心远在屏外、半径极大的 wash 圆，`sr < far` 那道 maxzoom 门
    // 会放它过去（远处的 far 同样很大），但视口整个陷在它内部、填充又被 fade 压到看不见，
    // 于是它的界线弧整条在画布之外 —— 只按「有没有发起绘制调用」计数就会误判成「画了东西」，
    // 兜底提示就不画了，用户看到一片漆黑而没有任何解释（放开缩放后放大到极端即触发）。
    function nearDist(sx, sy) {
      var Hc = H - FOOTER_H;
      var dx = sx < 0 ? -sx : (sx > W ? sx - W : 0);
      var dy = sy < 0 ? -sy : (sy > Hc ? sy - Hc : 0);
      return Math.sqrt(dx * dx + dy * dy);
    }

    // 实心圆的材质（2026-10-24 视觉改版）：径向渐变（左上受光 → 边缘压暗）+ 内侧暗环 +
    // 外缘高光，让原本的平涂色块有玻璃片的厚度感。**色相不动**，只加明暗；不引入图片资源。
    function nodeGradient(n, sx, sy, sr) {
      var g = ctx.createRadialGradient(
        sx - sr * 0.22, sy - sr * 0.28, Math.max(1, sr * 0.04),
        sx, sy, Math.max(1, sr * 1.01));
      g.addColorStop(0, rgba(mixWhite(n._rgb, 0.30), 1));
      g.addColorStop(0.48, rgba(n._rgb, 1));
      g.addColorStop(0.92, rgba(darken(n._rgb, 0.88), 1));
      g.addColorStop(1, rgba(darken(n._rgb, 0.62), 1));
      return g;
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
        var dNear = nearDist(sx, sy);
        var fade = 1 - smoothstep(dFar * 0.7, dFar, sr);
        if (fade <= 0.004) continue;
        var fa = fillAlphaOf(n) * fade;
        var sa = clamp(fa * 1.2 + 0.18 * fade, 0, 0.8);
        // 只有**几何上真的穿过视口**的那一笔才算数：填充看圆盘（near < sr），界线看圆环
        // （near ≤ sr ≤ dFar）。fade 刚好越过 0.004 这一档时两者都 ≈0，合成后与背景同值；
        // 中心远在屏外的大圆则填充被跳过、界线整条在画布外 —— 两种都是「候选集里有、
        // 屏幕上没有」，都不能让兜底提示闭嘴。
        if ((fa > PAINT_MIN && dNear < sr) ||
            (sa > PAINT_MIN && dNear <= sr && sr <= dFar)) stats.painted++;
        if (fa > 0.004) {
          ctx.globalAlpha = fa;
          // wash 是压暗的底图，渐变几乎看不出来 —— 用平涂省掉每帧一次大圆渐变填充。
          ctx.fillStyle = rgba(n._rgb, 1);
          ctx.beginPath();
          ctx.arc(sx, sy, sr, 0, TAU);
          ctx.fill();
        }
        ctx.globalAlpha = sa;
        ctx.strokeStyle = rgba(n._brgb, 1);
        ctx.lineWidth = sr > 60 ? 1.6 : 1;
        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, TAU);
        ctx.stroke();
        // 界线内侧再压一道极淡高光：远看是「玻璃边缘」，近看不会抢过实心圆
        if (sr > 28) {
          ctx.globalAlpha = clamp(sa * 0.5, 0, 1);
          ctx.strokeStyle = 'rgba(255,255,255,0.09)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(sx, sy, Math.max(0.5, sr - 2.5), 0, TAU);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }

    // ── 逐条链接：每处 [[链接]] 各画一条细线，任何尺度都在 ────────────────────
    // 三条契约：
    //   1) 端点**恒为真实节点自己**（rawAnchor），绝不沿 parent 链上移。圆在当前尺度
    //      上没画出来时，线照样从它的世界坐标出发 —— 于是粗尺度下会看到一条线**穿进**
    //      父级圆的内部，这正是想要的暗示：「这里面还有更深的知识点」。缩放/平移只改
    //      线的长度和形状，不换端点、不减少条数。
    //   2) alpha 恒为 1，不乘端点淡入进度、不按条数打折 —— 缩放只改长度，不改浓淡。
    //   3) 线宽恒为 RAW_LW、恒为直线。关联强度由「同一对父圆之间有几条线」表达：真实
    //      端点本来就散在父圆内部的不同位置，一束线天然散开，不需要扇形展开。
    // 唯一的门是几何的：整条线段的屏幕 bbox 与内容视口不相交才不画。两端都在屏外但
    // 横跨视口的长边照样画 —— 线穿过屏幕就该看得见。
    // 焦点/悬停的压暗（FOCUS_DIM / HOVER_DIM）保留，理由见文件头注释。
    function drawEdges() {
      hotNeighbors.clear();
      stats.focusEdges = 0;
      markJobs.length = 0;
      chipJobs.length = 0;
      stats.chips = 0;
      var selN = byId.get(selectedId), hovN = byId.get(hoverId);
      var droppedFocus = [];
      var Hc = H - FOOTER_H;
      var drawn = 0;
      ctx.lineCap = 'round';
      for (var i = 0; i < SEM.length; i++) {
        var e = SEM[i];
        var A = byId.get(e.s), B = byId.get(e.t);
        if (!A || !B) continue;
        var sF = isFocusSide(A, selN), tF = isFocusSide(B, selN);
        var hs = !!(sF || tF);
        // 真自链接没有方向可画。焦点相关的仍记下来，交 drawFocusEdges 计数兜底，
        // 免得「面板说有链接、画布没画、计数也没记」。
        if (A.id === B.id) {
          if (hs) droppedFocus.push({ e: e, A: A, B: B });
          continue;
        }
        var aA = rawAnchor(A), aB = rawAnchor(B);
        if (Math.max(aA.sx, aB.sx) < -CULL_MARGIN || Math.min(aA.sx, aB.sx) > W + CULL_MARGIN ||
            Math.max(aA.sy, aB.sy) < -CULL_MARGIN || Math.min(aA.sy, aB.sy) > Hc + CULL_MARGIN) {
          if (hs) droppedFocus.push({ e: e, A: A, B: B });
          continue;
        }
        // 邻居环装**真实端点**：环只在它自己被画出来的那一帧出现，于是「线连到 A、
        // 环画在 B」这种错位从根上不可能发生（代价是粗尺度下没有环 —— 但那时线正穿进
        // 父圆内部，位置信息由线承担，见 drawEmphasis 的注释）。
        if (sF !== tF) hotNeighbors.add(sF ? B.id : A.id);
        var hot = selN ? hs : !!(isFocusSide(A, hovN) || isFocusSide(B, hovN));
        var dim = hot ? 1 : (selN ? FOCUS_DIM : (hovN ? HOVER_DIM : IDLE_DIM));
        if (hs) stats.focusEdges++;
        // 链接配色（2026-10-24 视觉改版，方案 A）：同域 = 该学科色提亮；跨域 = 两端渐变。
        // 端点没有 domain 时兜底用 theme.raw_edge；flat 模式两者都用统一近白。
        var ca = RAW_EDGE_RGB, cb = RAW_EDGE_RGB;
        if (EDGE_DOMAIN) {
          ca = A._rgb ? mixWhite(A._rgb, EDGE_TINT) : RAW_EDGE_RGB;
          cb = B._rgb ? mixWhite(B._rgb, EDGE_TINT) : RAW_EDGE_RGB;
        }
        var laid = drawSegment(aA, aB, dim, hot ? RAW_LW + 0.8 : RAW_LW,
                               ca, cb, tintLight(ca), tintLight(cb), e.type);
        if (laid) drawn++;
        // 屏外焦点端挂名字 chip。线本来就已经画到屏外了，缺的只是「这条线指向谁」
        // 这个名字。chip 钉在线穿出视口的那一点上、沿线方向朝外，读作「顺着这条线出去
        // 就是它」。
        // 只给焦点边挂：96 条冷边全挂会把屏幕边缘糊满，而折叠取的是前 CHIP_MAX 枚，
        // 冷边的 chip 会把真正想看的焦点 chip 挤掉。
        if (hs && (aA.on !== aB.on)) {
          var S = aA.on ? aA : aB, T = aA.on ? aB : aA;
          var vx = T.sx - S.sx, vy = T.sy - S.sy;
          var vl = Math.sqrt(vx * vx + vy * vy);
          if (vl > 1e-6) {
            var ux = vx / vl, uy = vy / vl, tBest = Infinity;
            if (ux > 1e-9) tBest = Math.min(tBest, (W - S.sx) / ux);
            if (ux < -1e-9) tBest = Math.min(tBest, (0 - S.sx) / ux);
            if (uy > 1e-9) tBest = Math.min(tBest, (Hc - S.sy) / uy);
            if (uy < -1e-9) tBest = Math.min(tBest, (0 - S.sy) / uy);
            if (isFinite(tBest) && tBest > 0) {
              chipJobs.push({ px: S.sx + ux * tBest, py: S.sy + uy * tBest, dx: ux, dy: uy,
                              id: T.node.id, count: 1, text: chipLabel(T.node) });
            }
          }
        }
        // 两端都在屏外、但线横穿视口的那种，也挂**一枚**：线一进一出、方向本来就看得见，
        // 缺的仍然只是名字，而「平移一下选中项就整圆出屏、名字牌跟着消失」正是用户报的
        // 那个痛点。名字给**非焦点的那一端** —— 选中 A 时答「这条线通向谁」，选中 B 时答
        // 「这条线来自谁」；两端同属焦点子树（选中项的祖先链上互链）时无从区分，退回
        // 目标端 B，与单端分支「命名屏外那一端」的习惯一致。
        // 挂一枚不挂两枚：两枚只会加剧上一条注释里的挤占。
        // 额外要求这一帧真落了笔（laid）：两端都出屏时线段 bbox 与视口相交 ≠ 真穿过视口
        // （斜角擦过的会被 drawSegment 自己判掉），没画出来的线不该有一枚指向虚空的
        // 名字牌。单端分支不加这道门 —— 那时必有一端在屏内，线一定落笔。
        if (hs && laid && !aA.on && !aB.on) {
          var N = sF !== tF ? (sF ? aB : aA) : aB, O = N === aA ? aB : aA;
          var ent = entryToward(N, O);
          if (ent) {
            chipJobs.push({ px: ent.px, py: ent.py, dx: ent.ux, dy: ent.uy,
                            id: N.node.id, count: 1, text: chipLabel(N.node) });
          }
        }
      }
      ctx.globalAlpha = 1;
      // edges 是主循环落笔的线数（焦点补画只进 focusEdges），focusNeighbors 要等
      // 补画往 hotNeighbors 里加完再计。
      stats.edges = drawn;
      if (selN && droppedFocus.length) drawFocusEdges(droppedFocus);
      foldChips();
      // hotNeighbors 可能含当前尺度上没画出来的真实端点，页脚的「相邻 N」只数
      // 屏幕上真有环的那些，免得数字与观感对不上。
      var vis = 0;
      for (var q = 0; q < lastDrawn.length; q++) {
        if (hotNeighbors.has(lastDrawn[q].id)) vis++;
      }
      stats.focusNeighbors = vis;
    }

    // 一条链接线段。alpha 与线宽都由调用方给死（不随缩放变）；**恒为直线**（端点是
    // 真实节点自己，同一父圆内部的多条线天然散在不同位置，不需要控制点偏移）。
    // ca / cb = 源/目标端的学科色（已提亮）；ma / mb = 两端端点标记的颜色。
    // 跨学科链接用 ca→cb 的线性渐变，同色则纯色。
    // 返回是否真的落了笔 —— 两圆贴死时屏幕上没有可见长度，硬画会得到一条方向反掉的
    // 短线段，比不画更乱。
    function drawSegment(aA, aB, dim, lw, ca, cb, ma, mb, type) {
      var x1 = aA.sx, y1 = aA.sy, x2 = aB.sx, y2 = aB.sy;
      var dx = x2 - x1, dy = y2 - y1;
      var dl = Math.sqrt(dx * dx + dy * dy) || 1;
      var ux = dx / dl, uy = dy / dl;
      var r1 = aA.sr + TRIM, r2 = aB.sr + TRIM;
      var ex1 = x1 + ux * r1, ey1 = y1 + uy * r1;
      var ex2 = x2 - ux * r2, ey2 = y2 - uy * r2;
      var gx = ex2 - ex1, gy = ey2 - ey1;
      var glen = Math.sqrt(gx * gx + gy * gy);
      if (glen < 0.5) return false;

      var a = clamp(dim, 0, 1);
      var dash = type === 'contrast' ? [5, 4] : [];
      // ① 暗底描边：让亮色细线压在同色亮圆上仍然读得出来（只在外侧多 1.8px，
      //    视觉上像一层薄影，不会把线加粗）。压暗/焦点模式下跟着一起变淡。
      ctx.globalAlpha = a * 0.28;
      ctx.strokeStyle = 'rgba(0,0,0,1)';
      ctx.lineWidth = lw + 1.8;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.moveTo(ex1, ey1);
      ctx.lineTo(ex2, ey2);
      ctx.stroke();
      // ② 主色线：同色纯色、跨学科两端渐变
      var same = ca[0] === cb[0] && ca[1] === cb[1] && ca[2] === cb[2];
      var stroke;
      if (same) {
        stroke = rgba(ca, 1);
      } else {
        var grd = ctx.createLinearGradient(ex1, ey1, ex2, ey2);
        grd.addColorStop(0, rgba(ca, 1));
        grd.addColorStop(1, rgba(cb, 1));
        stroke = grd;
      }
      ctx.globalAlpha = a;
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lw;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.moveTo(ex1, ey1);
      ctx.lineTo(ex2, ey2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      // 标记门槛很小：端点是真实节点，粗尺度下大量线只有几 px，门槛大了会让它们全都
      // 没箭头，违背「细线箭头不随缩放消失」。
      if (glen < RAW_MARK_MIN) return true;
      // 冷边的 alpha 就是 dim（焦点模式 0.07 / 悬停模式 0.75），过不了 0.1 的门槛，
      // 于是被压暗的无关边不会冒出标记来添乱。
      if (a < 0.1) return true;
      // ⚠️ 标记**不**要求端点圆这一帧被画出来。曾经试过「端点没落笔就不挂标记」
      // （2026-10-21，层级带第一版），结果是浅缩放下所有语义边的端点都还没浮现，
      // 箭头全灭 —— 「看不出线从谁到谁」正是用户当初要求箭头要解决的原始痛点。
      // 代价是粗尺度下会出现「指向虚空的箭头」，这是 raw 契约（圆可消失、线要留下）
      // 的固有后果，接受它，别拿功能换观感。
      var dot = clamp(1.6 + lw * 0.5, 2, 4);
      var s = clamp(5 + lw * 1.6, 7, 14);
      // 箭头只给 derives / prerequisite；contrast 是无向的（见 annotations.yaml 的
      // 字段说明），两端都只画点。id 是标记**附着的节点**：就是真实端点自己
      // （锚点不上移），自动化验证量的是屏幕上那个圆的几何。
      // 颜色：目标端用 mb，源端用 ma —— 跨学科时两端各带自己的学科色。
      if (type === 'derives' || type === 'prerequisite') {
        markJobs.push({ k: 1, x: ex2, y: ey2, ux: ux, uy: uy, id: aB.node.id,
                        s: s, c: mb, a: a });
      } else {
        markJobs.push({ k: 0, x: ex2, y: ey2, ux: 0, uy: 0, id: aB.node.id,
                        s: dot, c: mb, a: a });
      }
      markJobs.push({ k: 0, x: ex1, y: ey1, ux: 0, uy: 0, id: aA.node.id,
                      s: dot, c: ma, a: a });
      return true;
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

    // 端点锚点：永远是节点自己，不沿 parent 链上移。on 只表示「这个点还在内容视口内
    // （外扩 CULL_MARGIN）」，供 drawEdges 主循环决定「屏外的那一端」挂不挂 chip 用
    // （一端屏外命名那一端，两端都屏外命名非焦点端）；它**不**决定线画不画（那由线段
    // bbox 判定）。sr 用节点自己的世界半径 × zoom，粗尺度下可能亚像素，于是线端落在
    // 父圆内部 —— 正是「这里面还有更深知识点」的暗示。
    function rawAnchor(n) {
      var sx = w2sx(n.x), sy = w2sy(n.y);
      var Hc = H - FOOTER_H;
      var on = !(sx < -CULL_MARGIN || sx > W + CULL_MARGIN ||
                 sy < -CULL_MARGIN || sy > Hc + CULL_MARGIN);
      return { on: on, node: n, sx: sx, sy: sy, sr: n._r * cam.zoom };
    }

    // 两端都在屏外时，求线段 N→O **进入**内容视口的那一点，以及指向 N 的朝外单位向量
    // （drawChips 靠 dx/dy 把 chip 沿反方向内移进屏，所以这里必须给 -u）。
    // 不能复用单端那套 tBest=min(正 t)：那个式子假定起点在矩形内、算出来的是**出口**；
    // 起点在屏外时它会返回远侧交点，把名字牌钉到线离开视口的那一头去。所以这里用 slab
    // 裁剪（Liang–Barsky）求真正的入口。视口取内容区 [0,W]×[0,Hc]、不外扩 CULL_MARGIN，
    // 与单端分支同一口径。返回 null = 这条线段根本没穿过视口。
    function entryToward(N, O) {
      var Hc = H - FOOTER_H;
      var vx = O.sx - N.sx, vy = O.sy - N.sy;
      var vl = Math.sqrt(vx * vx + vy * vy);
      if (vl <= 1e-6) return null;
      var ux = vx / vl, uy = vy / vl;
      var tEnter = -Infinity, tExit = Infinity, t1, t2;
      if (Math.abs(ux) > 1e-9) {
        t1 = (0 - N.sx) / ux; t2 = (W - N.sx) / ux;
        tEnter = Math.max(tEnter, Math.min(t1, t2));
        tExit = Math.min(tExit, Math.max(t1, t2));
      } else if (N.sx < 0 || N.sx > W) return null;
      if (Math.abs(uy) > 1e-9) {
        t1 = (0 - N.sy) / uy; t2 = (Hc - N.sy) / uy;
        tEnter = Math.max(tEnter, Math.min(t1, t2));
        tExit = Math.min(tExit, Math.max(t1, t2));
      } else if (N.sy < 0 || N.sy > Hc) return null;
      if (tEnter > tExit || tExit <= 0 || tEnter > vl) return null;
      var t = tEnter > 0 ? tEnter : 0;
      return { px: N.sx + ux * t, py: N.sy + uy * t, ux: -ux, uy: -uy };
    }

    // 被主循环跳过的焦点边兜底计数。
    // 主循环只为两种输入跳过绘制：真自链接（没有方向可画）、整条线段出屏（bbox 与
    // 视口不相交）。这两种在屏幕上本来就没有线可补，但「面板说有链接」的读数不能少
    // 算一条，所以这里只做两件事：focusEdges +1、把与焦点直接相连的另一端加进邻居环。
    // **不补画线、不挂 chip、不产箭头** —— 屏外那一端的方向线索由主循环的 chip 负责。
    function drawFocusEdges(dropped) {
      var selN = byId.get(selectedId);
      var groups = new Map();
      for (var i = 0; i < dropped.length; i++) {
        var d = dropped[i];
        var aA = rawAnchor(d.A), aB = rawAnchor(d.B);
        var kA = aA.on ? aA.node.id : ' ' + d.A.id;
        var kB = aB.on ? aB.node.id : ' ' + d.B.id;
        // 粒度后缀：note 级边「LTI→Calculus」和 heading 级边「LTI#CTFT→Calculus#
        // 定积分」在文件级会解析到同一对锚点、同为 derives，不加后缀就被并成一条，
        // focusEdges 会少算一条（7b/7d 的读数会整体漂移）。
        var nl = !!d.e._nl;
        var key = kA + '\u0000' + kB + '\u0000' + d.e.type + (nl ? '\u0000n' : '');
        var g = groups.get(key);
        if (!g) {
          g = { aA: aA, aB: aB, idA: d.A.id, idB: d.B.id };
          groups.set(key, g);
        }
      }
      groups.forEach(function (g) {
        stats.focusEdges += 1;
        var nA = byId.get(g.idA), nB = byId.get(g.idB);
        var sF = isFocusSide(nA, selN), tF = isFocusSide(nB, selN);
        if (sF !== tF) {
          var nb = sF ? g.aB : g.aA;
          if (nb && nb.on) hotNeighbors.add(nb.node.id);
        }
      });
    }

    // chip 上限折叠。由 drawEdges 主循环在挂完 chip 后调一次。
    function foldChips() {
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

    // ⑥ 屏外 chip：屏幕空间 HUD 覆盖层（drawLabels 之后、最顶层）。每枚 chip 挂在连线
    // 穿出视口的那一点、沿线的反方向内移 14px，读作「顺着这条线出去就是这个标签」；
    // 折叠的「+k」钉在右下角。
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
        // 前景实心圆：不透明度够、而且圆盘真的穿过视口，才算屏幕上看得见。
        // （只判 alpha 会被「中心远在屏外的大圆」骗到 —— 那种圆铺满画布却什么都没露出来）
        if (a > PAINT_MIN && nearDist(sx, sy) < sr) stats.painted++;
        // 玻璃片的投影：先在右下偏移处画一个暗圆，再用本体填充盖住其余部分，
        // 只留出右下方的月牙暗边 —— 让每一层圆从父圆上「浮」起来（零模糊成本）。
        // 只给「看得清边界」的中等圆加：巨大的祖先圆铺满屏时投影既看不见又最贵。
        if (sr > 18 && sr < 700) {
          ctx.globalAlpha = clamp(a * 0.26, 0, 1);
          ctx.fillStyle = 'rgba(0,0,0,1)';
          ctx.beginPath();
          ctx.arc(sx + Math.min(7, sr * 0.02), sy + Math.min(9, sr * 0.026), sr, 0, TAU);
          ctx.fill();
        }
        ctx.globalAlpha = a;
        // 小圆用平涂（渐变几乎看不出来、却要每帧建一次），大圆才用渐变材质
        ctx.fillStyle = sr >= 24 ? nodeGradient(n, sx, sy, sr) : rgba(n._rgb, 1);
        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, TAU);
        ctx.fill();
        // 边缘材质：外圈 1px 压暗（厚度）+ 内侧 1px 高光（玻璃边）。小圆不画，
        // 否则会变成一圈噪点；`_brgb`（domain 提亮 40%）留给 wash 与极小圆兜底。
        if (sr > 12) {
          ctx.globalAlpha = clamp(a * 0.85, 0, 1);
          ctx.strokeStyle = 'rgba(0,0,0,0.22)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(sx, sy, Math.max(0.5, sr - 0.5), 0, TAU);
          ctx.stroke();
          ctx.globalAlpha = clamp(a * 0.72, 0, 1);
          ctx.strokeStyle = 'rgba(255,255,255,0.15)';
          ctx.beginPath();
          ctx.arc(sx, sy, Math.max(0.5, sr - 1.8), 0, TAU);
          ctx.stroke();
        } else {
          ctx.globalAlpha = clamp(a * 0.85, 0, 1);
          ctx.strokeStyle = rgba(n._brgb, 1);
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(sx, sy, sr, 0, TAU);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }

    // ── ghost 下一层（2026-10-24 视觉改版）────────────────────────────────
    // 把「当前最深层 + 1」的圆用固定低透明度画一层，像透着磨砂玻璃看到下一层的结构。
    // 与层级带完全解耦：不参与 alphaOf / painted / 标签碰撞 / 命中测试，纯粹是景深。
    // base 取 lastDrawn 的最大深度（含被 maxzoom 停画的祖先）；什么都没画时不画。
    function drawGhost() {
      stats.ghost = 0;
      stats.ghostLabels = 0;
      if (GHOST_A <= 0) return;
      var baseDepth = 0;
      for (var i = 0; i < lastDrawn.length; i++) {
        if (lastDrawn[i].depth > baseDepth) baseDepth = lastDrawn[i].depth;
      }
      if (!baseDepth || baseDepth >= MAXD) return;
      var gd = baseDepth + 1;
      var zoom = cam.zoom;
      var Hc = H - FOOTER_H;
      var labels = [];
      for (var j = 0; j < NODES.length; j++) {
        var n = NODES[j];
        if (n.depth !== gd) continue;
        var sr = n._r * zoom;
        if (sr < 1.5) continue;
        var sx = w2sx(n.x), sy = w2sy(n.y);
        if (sx + sr < 0 || sx - sr > W || sy + sr < 0 || sy - sr > Hc) continue;
        ctx.globalAlpha = GHOST_A;
        ctx.fillStyle = rgba(mixWhite(n._rgb, 0.26), 1);
        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, TAU);
        ctx.fill();
        if (sr > 2.5) {
          ctx.globalAlpha = Math.min(1, GHOST_A * 1.8);
          ctx.strokeStyle = rgba(mixWhite(n._rgb, 0.62), 1);
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(sx, sy, Math.max(0.5, sr - 0.5), 0, TAU);
          ctx.stroke();
        }
        stats.ghost++;
        if (GHOST_LABEL_A > 0 && sr >= GHOST_LABEL_PX && labels.length < 40) {
          labels.push([n, sx, sy, sr]);
        }
      }
      // ghost 文字：只给够大的圆，极淡、无阴影；不进标签预算 / 碰撞网格
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (var k = 0; k < labels.length; k++) {
        var m = labels[k][0], msx = labels[k][1], msy = labels[k][2], msr = labels[k][3];
        var fs = Math.round(clamp(msr * 0.30, 12, GHOST_LABEL_MAX));
        var font = fs + 'px ' + FONT;
        var full = m.label || m.id;
        var txt = clipToWidth(m.id, full, font, LABEL_AVAIL * 2 * msr);
        if (!txt || (txt.length <= 2 && txt !== full)) continue;
        ctx.font = font;
        ctx.globalAlpha = GHOST_LABEL_A;
        ctx.fillStyle = rgba(mixWhite(m._rgb, 0.75), 1);
        ctx.fillText(txt, msx, msy);
        stats.ghostLabels++;
      }
      ctx.globalAlpha = 1;
      ctx.textAlign = 'left';
    }

    // ③′ 强调环：搜索命中 / hover / 选中 / 相邻。单独一趟画在所有圆之上，
    //      否则会被后画的兄弟圆盖掉一半。
    function drawEmphasis(list, alpha) {
      for (var i = 0; i < list.length; i++) {
        var n = list[i];
        var isSel = n.id === selectedId, isHov = n.id === hoverId;
        var isMatch = matchSet && matchSet.has(n.id);
        // hotNeighbors 装的是**真实端点自己**（drawEdges 主循环就地收集），于是环只在
        // 它本帧真被画出来时才出现；粗尺度下没有环，位置信息改由「线穿进父圆内部」
        // 承担 —— 不会出现「线连到 A、环画在 B」的错位。
        var isNb = hotNeighbors.has(n.id) && !isSel;
        if (!(isSel || isHov || isMatch || isNb)) continue;
        var sx = w2sx(n.x), sy = w2sy(n.y), sr = n._sr;
        var a = alpha.get(n.id);

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
          // 用未被压暗的淡入进度（= 本层的 levelFade）做门槛。压暗是「把视觉重量
          // 让给细节」的手段，不是藏标签的手段 —— 共用带压暗的 alpha 会让祖先层
          // 在任何 zoom 下都拿不到标签（pitfall 8）。
          if (levelFade(n.depth, cam.zoom) < LABEL_A) continue;
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
        // ── 只画在圆内（2026-10-21，用户要求）──────────────────────────
        // 圆外标签会压到兄弟圆上（「有的还进入了其他元素内部」），而且看上去像是
        // 一堆浮在圆边上的小字。现在一律压在圆内、水平垂直都居中，把那块空地填满。
        // 半径小到放不下哪怕最小字号的圆**不挂标签** —— 它会在放大过程中自己长够；
        // 这比在圆外挂一串互相打架的小字干净得多。
        if (sr < LABEL_INSIDE_PX) continue;
        // 粗细是「类别」信号（浅层骨架 vs 深层细节），字号是「尺度」信号，两者不冲突。
        var weight = m.depth <= LABEL_BOLD_DEPTH ? '600 ' : '';
        var availW = LABEL_AVAIL * 2 * sr;
        var fs = fitFontFor(sr, text, weight);
        var font = weight + fs + 'px ' + FONT;
        // 字号已经压到下限还塞不进圆 → 截断加省略号（完整名字在 tooltip / 搜索里）
        var full = text;
        text = clipToWidth(m.id, text, font, availW);
        // 截到只剩一个字符 + 省略号就不是标签了，是噪声（圆太小 / 名字太长）→ 不画。
        // 原本就很短的名字（「模电」「DSP」）不受影响：它们没被截断，不会带省略号。
        if (text.length <= 2 && text !== full) continue;
        var wpx = measure(text, font) + 6;
        var hpx = fs + 4;
        // 居中：文字压在圆心。大圆里的字号也大（fitFontFor 的正比项），于是标签会
        // 跟着圆一起长大、把那片空地填住，不再出现「直径 3000px 的圆里一行 22px 小字」。
        var sx = w2sx(m.x), sy = w2sy(m.y);
        var bx0 = sx - wpx / 2, bx1 = sx + wpx / 2;
        var x0 = Math.floor(bx0 / LABEL_CELL), x1 = Math.floor(bx1 / LABEL_CELL);
        var y0 = Math.floor((sy - hpx / 2) / LABEL_CELL), y1 = Math.floor((sy + hpx / 2) / LABEL_CELL);
        // 锚点落在屏幕外的标签（铺满视口停画的容器、圆心在屏外的大圆）既不该占
        // LABEL_BUDGET，也不该进碰撞网格把真标签挤掉
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
        // 浓度直接取**圆这一帧的 alpha**（同进同出，用户要求）：圆淡到多少，字就淡到
        // 多少。这个值已经含了层级带淡入与可读性地板，不再单独乘压暗系数。
        var al = clamp(alpha.get(m.id), 0, 1);
        ctx.font = font;
        ctx.textAlign = 'center';
        ctx.globalAlpha = al * 0.9;
        ctx.fillStyle = 'rgba(15,17,22,0.85)';
        ctx.fillText(text, sx + 1, sy + 1);
        ctx.globalAlpha = al;
        ctx.fillStyle = rank === 0 ? '#ffffff' : rank === 1 ? '#E8C88A' : '#E7E3D7';
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
    // Ctrl 模式：按住 Ctrl 时给「标题圆」加一圈细虚线 —— 药丸删除后，这是唯一的
    // 可发现性线索（否则用户不知道哪些圆可以悬停预览）。
    function drawCtrlRings(drawn, alpha) {
      if (!ctrlMode) { stats.ctrlRings = 0; return; }
      stats.ctrlRings = 0;
      ctx.save();
      ctx.setLineDash([5, 5]);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = 'rgba(190,214,255,0.9)';
      for (var i = 0; i < drawn.length; i++) {
        var n = drawn[i];
        if (n.kind !== 'heading' || !n.anchor) continue;
        var sr = n._sr;
        if (!(sr >= 12)) continue;
        var a = (alpha.get(n.id) || 0) * 0.5;
        if (a <= 0.05) continue;
        ctx.globalAlpha = Math.min(0.45, a);
        ctx.beginPath();
        ctx.arc(w2sx(n.x), w2sy(n.y), sr - 1.5, 0, Math.PI * 2);
        ctx.stroke();
        stats.ctrlRings++;
      }
      ctx.restore();
    }

    function setCtrlMode(v) {
      v = !!v;
      if (ctrlMode !== v) { ctrlMode = v; invalidate(); }
    }

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
      // 两个下限：它那一层得**成熟**（M[depth] × mult），而且得占满大半屏（0.7 × fit / r）
      // —— 后者是新几何带来的：一个 r 很大的文件夹光「浮现」远不够看清它。
      // ⚠️ 这里必须用 M[depth] 而不是 n._mz：层级带之后 _mz 只决定「它在本层里多大」，
      // 与可见性脱钩了；拿 _mz 当落点会跳到一个它所在层还没开始淡入的 zoom（alpha≈0）。
      var z = clamp(Math.max(cam.zoom, levelMature(n.depth) * mult, 0.7 * fitRadius() / n._r),
                    zMin, zMax);
      tweenTo({ zoom: z, panX: W / 2 - n.x * z, panY: (H - FOOTER_H) / 2 - n.y * z },
              ms == null ? TRANSITION : ms);
    }

    // 框住链接两端：zoom 先取两端所在层「都已成熟」的 zoom ×1.15，
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
      // 同样以「层成熟」为准，否则两端可能在屏幕上根本还没浮现
      var z = clamp(Math.max(levelMature(a.depth), levelMature(b.depth)) * 1.15, zMin, zMax);
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

    // ── 程序化平移（键盘方向键走这里）────────────────────────────────────
    // 语义与鼠标拖拽**完全一致**：取消进行中的 tween、挪相机、通知 onCamera。
    // 刻意不碰 selectedId / hoverId —— 这正是它的用处：看远处的连线时不必点任何东西，
    // 也就不会因为手抖把选中切到别的元素上、让焦点过滤把想看的箭头一起滤掉。
    function panBy(dx, dy) {
      if (!dx && !dy) return;
      tween = null;
      cam.panX += dx; cam.panY += dy;
      invalidate();
      if (hooks.onCamera) hooks.onCamera();
    }

    // 一「步」平移多少屏幕 px：由视口现算，缩放无关（屏幕空间里的距离）。
    // 竖向用可视高度（扣掉页脚），横向用整宽 —— 本来就不同宽高比，各按各的算。
    // fast（按住 Shift）= 半个视口，用来快速跨过很长的连线。
    // 下限 40px 兜住极小窗口，免得一步挪不动。
    function panStep(fast) {
      var vx = fast ? 0.5 * W : Math.max(40, W / 8);
      var vy = fast ? 0.5 * (H - FOOTER_H) : Math.max(40, (H - FOOTER_H) / 8);
      return [vx, vy];
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
      setCtrlMode: setCtrlMode,
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
        // 层级胶囊 / KG.setLevel / [ ] 的落点：该层**成熟**的 zoom（= M[L]），
        // 不是「刚开始淡入」的 zoom —— 后者落下去该层几乎还是透明的（alpha≈0.06）。
        var z = ENTER[L - 1] == null ? zMax : levelMature(L);
        tweenTo({ zoom: clamp(z, zMin, zMax), panX: W / 2, panY: (H - FOOTER_H) / 2 }, TRANSITION);
      },
      // 键盘平移（方向键）。panBy 收屏幕 px 增量，panStep 给出「一步」有多远。
      panBy: panBy,
      panStep: panStep,
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
