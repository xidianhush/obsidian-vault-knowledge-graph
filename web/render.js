/* 渲染层：Canvas2D 语义缩放地图。
 *
 * 只干一件事：给定相机 {zoom, panX, panY}，把 payload 画出来。所有「该不该画、
 * 画多透明」都来自构建期算好的 reveal（→ minzoom = lod.min_px / reveal），
 * 渲染期不做任何布局计算 —— 坐标一次算定，所以缩放时节点永不跳动。
 *
 * 方向：**放大（zoom 变大）= 看到更深的层级**，和地图一致。
 * 这个方向不是自动成立的，是 kg/layout.py `_apply_depth_floor` 按深度封顶封出来的。
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
  var HIT_CELL = 64;          // 拾取网格边长（屏幕像素）
  var LABEL_CELL = 24;        // 标签碰撞网格边长（屏幕像素）
  var LABEL_BUDGET = 400;     // 每帧最多考虑多少个标签候选

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

  function createRenderer(canvas, DATA, hooks) {
    hooks = hooks || {};

    var META = DATA.meta;
    var LOD = META.lod || {};
    var ZC = META.zoom || {};
    var THEME = META.theme || {};
    var NODES = DATA.nodes;
    var EDGES = DATA.edges;
    var AGG = DATA.aggregates;
    var RINGS = DATA.rings;

    var MIN_PX = LOD.min_px || 6;
    // 标签门槛是「淡入进度」而不是「世界像素间距」：_r 是屏幕像素半径，绘制时不随
    // zoom 缩放，所以「世界尺寸超过多少 px 才给标签」在这个渲染器里根本没有对应量。
    // 而且它不能读压暗后的 alpha —— 祖先层被 parent_dim 压到 0.5 之后就永远够不到
    // 门槛，最粗视图（最该有标签的视图）会一个标签都没有。
    var LABEL_A = LOD.label_alpha == null ? 0.55 : LOD.label_alpha;
    var FADE = LOD.fade_span || 1.35;
    var WEAK = LOD.weak_edge_min_count || 2;
    var PARENT_DIM = ZC.parent_dim == null ? 0.5 : ZC.parent_dim;
    var WHEEL_STEP = ZC.wheel_step || 1.12;
    var TRANSITION = ZC.transition_ms || 260;
    var ENTER = LOD.enter || [];
    var MAXD = META.max_depth || ENTER.length || 1;

    var EDGE_RGB = {};
    Object.keys(THEME.edges || {}).forEach(function (k) { EDGE_RGB[k] = hexToRgb(THEME.edges[k]); });
    var FALLBACK_RGB = hexToRgb(THEME.fallback);
    var DOMAIN_RGB = {};
    Object.keys(THEME.domains || {}).forEach(function (k) { DOMAIN_RGB[k] = hexToRgb(THEME.domains[k]); });

    var radiusOf = {};
    RINGS.forEach(function (r) { radiusOf[r.depth] = r.radius; });

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

    // 后代数量：标题节点在构建期没有子树规模字段，这里沿 parent 链一次遍历补出来。
    // 圆点半径按它取对数 —— 地图上的 POI 也是「越重要越大」，而不是按层级定大小。
    var desc = new Map();
    NODES.forEach(function (n) { desc.set(n.id, 0); });
    NODES.slice().sort(function (a, b) { return b.depth - a.depth; }).forEach(function (n) {
      if (n.parent && desc.has(n.parent)) {
        desc.set(n.parent, desc.get(n.parent) + 1 + desc.get(n.id));
      }
    });

    NODES.forEach(function (n) {
      n._mz = MIN_PX / n.reveal;                        // minzoom
      n._d = desc.get(n.id) || 0;
      n._r = clamp(2.4 + 1.9 * Math.log(1 + n._d) / Math.LN2, 2.4, 16);
      n._rgb = DOMAIN_RGB[n.domain] || FALLBACK_RGB;
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
    // 预计算门槛，绘制时每节点只比一次。
    kids.forEach(function (list, pid) {
      var p = byId.get(pid);
      if (!p) return;
      var g = 0;
      for (var i = 0; i < list.length; i++) {
        var c = byId.get(list[i]);
        if (c && c._mz > g) g = c._mz;
      }
      p._gate = g;
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

    // ── 缩放边界：全部从 reveal / enter 现算，不写死任何绝对值 ────────────
    var rootNeed = 0, maxMz = 0;
    NODES.forEach(function (n) {
      if (n.depth === 1 && n._mz > rootNeed) rootNeed = n._mz;
      if (n._mz > maxMz) maxMz = n._mz;
    });
    var zMin = rootNeed * (ZC.zoom_out_floor == null ? 0.9 : ZC.zoom_out_floor);
    var zMax = maxMz * (ZC.zoom_in_ceiling == null ? 1.35 : ZC.zoom_in_ceiling);

    var W = 0, H = 0, dpr = 1;
    var cam = { zoom: zMin, panX: 0, panY: 0 };
    var tween = null;
    var dirty = true, rafId = 0;
    var hoverId = null, selectedId = null;
    var filterSet = null, matchSet = null, labelMode = 'auto';
    var stats = { nodes: 0, edges: 0, labels: 0 };
    var hitGrid = new Map();
    var textW = new Map();
    var ctx = canvas.getContext('2d');

    function fitRadius() {
      return Math.max(40, Math.min(W / 2, (H - FOOTER_H) / 2));
    }

    // home 层：既已完全解锁（enter[L] ≤ fit/r_L）、又能整圈装进屏幕（fit/r_L ≥ enter[L]）
    // 的最深一圈。构建期按标称视口算了一个 home_layer 落盘，这里用真实视口复算。
    function homeLayer() {
      var R = fitRadius(), best = 1;
      for (var L = 1; L <= MAXD; L++) {
        var r = radiusOf[L];
        if (!r || !ENTER[L - 1]) continue;
        if (ENTER[L - 1] <= R / r) best = L;
      }
      return best;
    }

    function homeZoom() {
      var r = radiusOf[homeLayer()] || radiusOf[1] || 300;
      return clamp(fitRadius() / r, zMin, zMax);
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

    // HUD 上的层级读数：max{ L : enter[L] ≤ zoom }
    function enterAt(zoom) {
      var L = 0;
      for (var i = 0; i < ENTER.length; i++) { if (ENTER[i] <= zoom) L = i + 1; else break; }
      return Math.max(1, L);
    }

    // 端点沿祖先链「当前浮现在哪一层」：alpha 沿链单调不增（reveal 沿链单调不增），
    // 所以从浅往深扫，遇到第一个不可见的就停。
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
    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = '#0f1116';
      ctx.fillRect(0, 0, W, H);

      hitGrid.clear();
      var zoom = cam.zoom;
      var margin = 24;
      var wx0 = s2wx(-margin), wx1 = s2wx(W + margin);
      var wy0 = s2wy(-margin), wy1 = s2wy(H + margin);

      // 先算一遍可见节点的 alpha，边要用两端点的 alpha
      var alpha = new Map();
      var drawn = [];
      for (var i = 0; i < NODES.length; i++) {
        var n = NODES[i];
        if (n.x < wx0 || n.x > wx1 || n.y < wy0 || n.y > wy1) continue;
        var a = alphaOf(n);
        if (a <= 0) continue;
        alpha.set(n.id, a);
        drawn.push(n);
      }
      stats.nodes = drawn.length;

      drawEdges(alpha);
      drawChainHighlight(alpha);
      drawNodes(drawn, alpha);
      drawLabels(drawn, alpha);

      // 全空白兜底：同心圆布局的圆心是空的，在空白处一路放大就会什么都看不见
      // （stats.nodes 是按世界视口裁剪后真正画出的数量，不是丢数据）。
      // 地图软件在这种情况下会提示「此区域暂无详情」，这里照做，免得用户以为坏了。
      if (!drawn.length) {
        ctx.globalAlpha = 1;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = '13px -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif';
        ctx.fillStyle = 'rgba(126,135,154,0.9)';
        ctx.fillText('此处没有内容 · 向下滚回到更粗的层级，或双击空白处回到默认视角',
                     W / 2, (H - FOOTER_H) / 2);
        ctx.textAlign = 'left';
      }

      if (hooks.onFrame) hooks.onFrame(stats);
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
          // 箭头贴着目标圆点边缘
          var tr = (byId.get(p.sb)._r || 4) + 2;
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
    function drawChainHighlight(alpha) {
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

    function drawNodes(drawn, alpha) {
      for (var i = 0; i < drawn.length; i++) {
        var n = drawn[i];
        var a = alpha.get(n.id);
        var sx = w2sx(n.x), sy = w2sy(n.y);
        var r = n._r;

        ctx.globalAlpha = a;
        ctx.fillStyle = rgba(n._rgb, 1);
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, 6.283185307);
        ctx.fill();

        // 掌握度用描边环表达：1..5 越粗越实，≤3 用虚线表示「还没吃透」
        if (n.kind === 'note' && n.mastery > 0) {
          var m = clamp(n.mastery, 1, 5);
          ctx.lineWidth = 1 + m * 0.75;
          ctx.strokeStyle = 'rgba(255,255,255,0.85)';
          if (m <= 3) ctx.setLineDash([2, 2]);
          ctx.beginPath();
          ctx.arc(sx, sy, r + ctx.lineWidth * 0.7, 0, 6.283185307);
          ctx.stroke();
          ctx.setLineDash([]);
        }

        if (matchSet && matchSet.has(n.id)) {
          ctx.lineWidth = 2;
          ctx.strokeStyle = 'rgba(227,179,65,0.95)';
          ctx.beginPath();
          ctx.arc(sx, sy, r + 4, 0, 6.283185307);
          ctx.stroke();
        }
        if (n.id === selectedId || n.id === hoverId) {
          ctx.lineWidth = n.id === selectedId ? 2 : 1.4;
          ctx.strokeStyle = n.id === selectedId ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.6)';
          ctx.beginPath();
          ctx.arc(sx, sy, r + 2.5, 0, 6.283185307);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;

        // 屏幕空间拾取网格：只收画得出来的
        if (a > 0.05) {
          var gx = Math.floor(sx / HIT_CELL), gy = Math.floor(sy / HIT_CELL);
          var k = gx + ',' + gy;
          var cell = hitGrid.get(k);
          if (!cell) { cell = []; hitGrid.set(k, cell); }
          cell.push(n);
        }
      }
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
      ctx.textAlign = 'left';
      for (var j = 0; j < cands.length; j++) {
        var m = cands[j];
        var font = (m.depth <= 2 ? '600 13px ' : '12px ') +
                   '-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif';
        var text = m.label || m.id;
        var wpx = measure(text, font) + 6;
        var hpx = 16;
        var sx = w2sx(m.x) + m._r + 4, sy = w2sy(m.y);
        var x0 = Math.floor(sx / LABEL_CELL), x1 = Math.floor((sx + wpx) / LABEL_CELL);
        var y0 = Math.floor((sy - hpx / 2) / LABEL_CELL), y1 = Math.floor((sy + hpx / 2) / LABEL_CELL);
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
        ctx.globalAlpha = al * 0.9;
        ctx.fillStyle = 'rgba(15,17,22,0.85)';
        ctx.fillText(text, sx + 1, sy + 1);
        ctx.globalAlpha = al;
        ctx.fillStyle = rank === 0 ? '#ffffff' : rank === 1 ? '#E3B341' : '#d6dbe4';
        ctx.fillText(text, sx, sy);
        ctx.globalAlpha = 1;
        placed++;
      }
      stats.labels = placed;
    }

    function hitTest(sx, sy) {
      var gx = Math.floor(sx / HIT_CELL), gy = Math.floor(sy / HIT_CELL);
      var best = null, bestD = 1e9;
      for (var i = -1; i <= 1; i++) {
        for (var j = -1; j <= 1; j++) {
          var cell = hitGrid.get((gx + i) + ',' + (gy + j));
          if (!cell) continue;
          for (var k = 0; k < cell.length; k++) {
            var n = cell[k];
            var dx = w2sx(n.x) - sx, dy = w2sy(n.y) - sy;
            var d = Math.sqrt(dx * dx + dy * dy);
            var rr = n._r + 4;
            if (d <= rr && d < bestD) { bestD = d; best = n; }
          }
        }
      }
      return best;
    }

    function focusOn(id, mult, ms) {
      var n = byId.get(id);
      if (!n) return;
      mult = mult || 1.25;
      var z = clamp(Math.max(cam.zoom, n._mz * mult), zMin, zMax);
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
      revealOf: function (id) { var n = byId.get(id); return n ? n.reveal : 0; },
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
