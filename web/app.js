/* 知识笔记语义缩放可视化 —— 前端
 *
 * 设计要点：
 *  1) zoom 是唯一真源：层级由 zoom 连续派生（depthFromZoom → 滑动窗口），换层
 *     从不反向改相机 —— 所以不存在「视角收窄→zoom 变大→又跳回深层」的正反馈
 *     震荡（那需要换层去改相机才会发生）。
 *     方向注意：布局半径 ∝ 深度（kg/layout.py 的 radius_step），第 d 层要装进
 *     屏幕需要 zoom ≲ 顶层适配缩放 / d。所以 **zoom 越大看到的层越浅，往深处走
 *     要往外滚**。
 *  2) 节点坐标全部在构建期算定，前端只切换 display / opacity —— 位置永不变。
 *  3) 相邻两层交叉淡化（窗口 lo..hi + 插值 t），不是硬切；t=1 时 lo 层恰好降到
 *     0，所以跨窗口连续无跳变。
 *  4) 标题层是「按需展开」：不展开就完全不渲染，避免一次画几千个节点。展开期间
 *     冻结 LOD（否则展开时的相机动画会把窗口冲掉）。
 */
(function () {
  'use strict';

  // ── 数据 ──────────────────────────────────────────────────────────────
  const DATA = JSON.parse(document.getElementById('graph-data').textContent);
  const META = DATA.meta;
  const ZCFG = META.zoom;
  const THEME = META.theme || {};
  const MAX_DEPTH = META.max_depth;
  const VAULT = META.vault_name;

  const NODES = DATA.nodes;
  const NODE = new Map(NODES.map((n) => [n.id, n]));
  const EDGES = DATA.edges;
  const AGG = DATA.aggregates || {};
  const FRAMES = DATA.frames || {};
  const HEADINGS = DATA.headings || {};
  const HEADING_LINKS = DATA.heading_links || [];
  const LEVELS = DATA.levels || {};

  const domainColor = (d) => (THEME.domains && THEME.domains[d]) || THEME.fallback || '#8B949E';
  const EDGE_COLOR = Object.assign(
    { prerequisite: '#8B949E', derives: '#4C8DFF', contrast: '#E3B341', contains: '#30363D' },
    THEME.edges || {}
  );
  const TYPE_LABEL = { prerequisite: '前置', derives: '引用', contrast: '并列', contains: '包含' };
  const TYPE_HINT = {
    prerequisite: 'source 是 target 的前置',
    derives: 'source 引用了 target',
    contrast: '并列/对比，方向未知',
    contains: '层级包含',
  };
  const ORIGIN_LABEL = {
    wiki: '来自正文 [[链接]]',
    annotation: '来自 annotations.yaml',
    candidate: '来自 candidates.yaml（你已审核通过）',
    frontmatter: '来自笔记 frontmatter',
    hierarchy: '来自目录结构',
    mixed: '多来源聚合',
  };

  // ── 状态 ──────────────────────────────────────────────────────────────
  let level = Math.min(2, MAX_DEPTH);
  let cameras = {};
  let filterDomain = 'all';
  let filterMastery = 'all';
  let filterSet = null;
  let searchQ = '';
  let matchSet = new Set();
  let selectedId = null;
  let hoveredId = null;
  let expanded = null;
  let expandedHeadings = [];
  let expandAllLevels = false;
  let lastLevelStep = 0;
  let labelMode = 'auto';
  const shownIds = new Set();
  const shownEdgeIds = new Set();

  const $ = (id) => document.getElementById(id);
  const container = $('cy');
  const tooltip = $('tooltip');
  const toastEl = $('toast');

  // ── 元素构建 ──────────────────────────────────────────────────────────
  const elements = [];

  NODES.forEach((n) => {
    elements.push({
      group: 'nodes',
      data: {
        id: n.id,
        label: n.label,
        kind: n.kind,
        depth: n.depth,
        domain: n.domain,
        mastery: n.mastery || 0,
        note_count: n.note_count || 0,
        weight: n.weight || 0,
        heading_count: n.heading_count || 0,
        // 注意：这里绝不能叫 parent —— Cytoscape 会把 data.parent 当成复合节点的父子关系，
        // 从而重算全部坐标。必须换个名字。
        parentId: n.parent || '',
        path: n.path || '',
        excerpt: n.excerpt || '',
        color: domainColor(n.domain),
      },
      position: { x: n.x, y: n.y },
      classes: 'node-' + n.kind,
    });
  });

  // 「省界」轮廓：每层一批，只在当前层显示
  Object.keys(FRAMES).forEach((lv) => {
    FRAMES[lv].forEach((f) => {
      elements.push({
        group: 'nodes',
        data: {
          id: f.id,
          label: f.label + '  ·  ' + f.note_count + ' 篇',
          kind: 'frame',
          depth: f.depth,
          level: parseInt(lv, 10),
          frame_of: f.frame_of,
          domain: f.domain,
          color: domainColor(f.domain),
          w: f.x2 - f.x1,
          h: f.y2 - f.y1,
        },
        position: { x: (f.x1 + f.x2) / 2, y: (f.y1 + f.y2) / 2 },
        classes: 'frame',
      });
    });
  });

  // 各层的聚合边全部预建，切换层级只切 display
  Object.keys(AGG).forEach((lv) => {
    AGG[lv].forEach((e, i) => {
      elements.push({
        group: 'edges',
        data: {
          id: 'a' + lv + '_' + i,
          source: e.s,
          target: e.t,
          type: e.type,
          weight: e.weight,
          count: e.count,
          origin: e.origin,
          level: parseInt(lv, 10),
          color: EDGE_COLOR[e.type] || '#8B949E',
          arrow: e.type === 'contrast' ? 'none' : (e.type === 'contains' ? 'none' : 'triangle'),
          lstyle: e.type === 'contrast' ? 'dashed' : (e.type === 'contains' ? 'dotted' : 'solid'),
        },
      });
    });
  });

  // ── 样式 ──────────────────────────────────────────────────────────────
  const STYLE = [
    {
      selector: 'node',
      style: {
        shape: 'ellipse',
        'background-color': 'data(color)',
        'border-width': 1.5,
        'border-color': '#0f1116',
        label: 'data(label)',
        color: '#cdd4e0',
        'font-size': 11,
        'text-wrap': 'wrap',
        'text-max-width': 130,
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 7,
        'overlay-opacity': 0,
        'z-index': 10,
      },
    },
    {
      selector: 'node.node-folder',
      style: {
        shape: 'round-rectangle',
        'text-valign': 'center',
        'text-margin-y': 0,
        'font-size': 12,
        color: '#eef1f6',
      },
    },
    {
      selector: 'node.node-heading',
      style: { shape: 'ellipse', 'font-size': 9, 'text-margin-y': 5, color: '#aab2c2' },
    },
    {
      selector: 'node.frame',
      style: {
        shape: 'round-rectangle',
        width: 'data(w)',
        height: 'data(h)',
        'background-color': 'data(color)',
        'background-opacity': 0.05,
        'border-color': 'data(color)',
        'border-opacity': 0.55,
        'border-style': 'dashed',
        'border-width': 1.2,
        label: 'data(label)',
        'text-valign': 'top',
        'text-halign': 'left',
        'text-margin-x': 10,
        'text-margin-y': 8,
        'font-size': 11,
        color: '#98a1b3',
        events: 'no',
        'z-index': 0,
      },
    },
    {
      selector: 'edge',
      style: {
        'curve-style': 'bezier',
        'line-color': 'data(color)',
        'target-arrow-color': 'data(color)',
        'target-arrow-shape': 'data(arrow)',
        'line-style': 'data(lstyle)',
        'arrow-scale': 0.9,
        opacity: 0.7,
        'overlay-opacity': 0,
        'z-index': 5,
      },
    },
    { selector: 'node.dimmed', style: { opacity: 0.12 } },
    { selector: 'edge.dimmed', style: { opacity: 0.05 } },
    { selector: 'node.hit', style: { 'border-width': 3, 'border-color': '#ffd166' } },
    {
      selector: 'node.selected',
      style: { 'border-width': 4, 'border-color': '#ffffff' },
    },
  ];

  const cy = cytoscape({
    container: container,
    elements: elements,
    style: STYLE,
    layout: { name: 'preset' },
    minZoom: ZCFG.min,
    maxZoom: ZCFG.max,
    wheelSensitivity: 0.2,
    boxSelectionEnabled: false,
    userZoomingEnabled: false,
    autounselectify: true,
    textureOnViewport: false,
    hideEdgesOnViewport: false,
  });

  // ── 相机：每层一个预设视角 ────────────────────────────────────────────
  function viewportSize() {
    return { w: container.clientWidth || 1200, h: container.clientHeight || 800, top: 46 };
  }

  function fitBox(ids, pad) {
    let x1 = Infinity;
    let y1 = Infinity;
    let x2 = -Infinity;
    let y2 = -Infinity;
    ids.forEach((id) => {
      const n = NODE.get(id);
      if (!n) return;
      const r = 40;
      x1 = Math.min(x1, n.x - r);
      x2 = Math.max(x2, n.x + r);
      y1 = Math.min(y1, n.y - r);
      y2 = Math.max(y2, n.y + r);
    });
    if (x1 === Infinity) return null;
    const { w, h, top } = viewportSize();
    const availW = w - 2 * pad;
    const availH = h - top - 2 * pad;
    const z = Math.min(availW / Math.max(x2 - x1, 1), availH / Math.max(y2 - y1, 1));
    const zc = Math.max(ZCFG.min, Math.min(ZCFG.max, z));
    const cx = (x1 + x2) / 2;
    const cyy = (y1 + y2) / 2;
    // rendered = model * zoom + pan（实测确认），要让 cx 落在视口中心：
    // w/2 = cx * zc + pan.x  →  pan.x = w/2 - cx * zc
    return { zoom: zc, pan: { x: w / 2 - cx * zc, y: (h + top) / 2 - cyy * zc } };
  }

  function visibleIdsFor(lv) {
    return NODES.filter((n) => n.depth <= lv).map((n) => n.id);
  }

  function rebuildCameras() {
    cameras = {};
    for (let lv = 1; lv <= MAX_DEPTH; lv += 1) {
      const cam = fitBox(visibleIdsFor(lv), 56);
      if (cam) cameras[lv] = cam;
    }
  }

  function applyCamera(animate) {
    const cam = cameras[level];
    if (!cam) return;
    if (animate) {
      cy.animate({ zoom: cam.zoom, pan: cam.pan }, { duration: ZCFG.transition_ms, easing: 'ease-in-out-cubic' });
    } else {
      cy.viewport({ zoom: cam.zoom, pan: cam.pan });
    }
  }

  // ── 可见性 ────────────────────────────────────────────────────────────
  function frameHasKept(folderId) {
    if (!filterSet) return true;
    return filterSet.has(folderId);
  }

  function shouldShow(data) {
    if (data.kind === 'heading') {
      return expanded !== null && data.note === expanded;
    }
    if (data.kind === 'frame') {
      return data.level === level && level >= 2 && frameHasKept(data.frame_of);
    }
    if (data.depth > level) return false;
    if (filterSet && !filterSet.has(data.id)) return false;
    return true;
  }

  function applyVisibility() {
    // 只写「状态真的变了」的元素 —— 切层时绝大多数元素不变，这样一次切换从
    // 600+ 次样式写入降到几十次。
    const prevNodes = new Set(shownIds);
    const prevEdges = new Set(shownEdgeIds);
    shownIds.clear();
    shownEdgeIds.clear();
    cy.batch(() => {
      cy.nodes().forEach((el) => {
        const d = el.data();
        const on = shouldShow(d);
        const was = prevNodes.has(d.id);
        if (on) shownIds.add(d.id);
        if (on !== was) el.style('display', on ? 'element' : 'none');
      });
      cy.edges().forEach((el) => {
        const d = el.data();
        const on = d.level === level && shownIds.has(d.source) && shownIds.has(d.target);
        const was = prevEdges.has(d.id);
        if (on) shownEdgeIds.add(d.id);
        if (on !== was) el.style('display', on ? 'element' : 'none');
      });
    });
    recomputeLabelBudget();
  }

  // ── 尺寸 / 透明度（含反缩放补偿，让屏幕上的大小基本恒定） ─────────────
  function baseSize(d) {
    if (d.kind === 'folder') {
      return 13 + 3.4 * Math.log2(1 + d.note_count) + 2.0 * Math.log2(1 + d.depth);
    }
    return 8.5 + 1.2 * Math.min(d.weight, 6);
  }

  function isFocused(id) {
    return id === selectedId || id === hoveredId;
  }

  function dimFactor(id, data) {
    if (data && data.kind === 'frame') return 1;
    if (searchQ && !matchSet.has(id)) return 0.13;
    if (selectedId && id !== selectedId && !neighbours.has(id)) return 0.3;
    return 1;
  }

  let neighbours = new Set();

  function refreshNeighbours() {
    neighbours = new Set();
    if (!selectedId) return;
    EDGES.forEach((e) => {
      if (e.type === 'contains') return;
      if (e.s === selectedId) neighbours.add(e.t);
      else if (e.t === selectedId) neighbours.add(e.s);
    });
  }

  function crowded() {
    return labelBudgetExceeded;
  }

  let labelBudgetExceeded = false;

  function recomputeLabelBudget() {
    // 笔记标签在密集时会糊成一片：可见笔记超过阈值就只保留悬停/选中/命中的标签，
    // 顶栏可以强制「全部 / 隐藏」。这个判断一次遍历算好，绝不在每节点循环里调用。
    let notes = 0;
    shownIds.forEach((id) => {
      const n = NODE.get(id);
      if (n && n.kind === 'note') notes += 1;
    });
    labelBudgetExceeded = notes > 35;
  }

  // 笔记标签在节点密集时会让整张图糊成一片。默认自动：稀疏时全部显示，密集时
  // 只在悬停/选中/搜索命中时显示；也可以在顶栏强制「全部 / 隐藏」。
  function shouldShowLabel(d) {
    if (d.kind === 'frame') return false;
    if (d.kind !== 'note') return true;
    if (labelMode === 'all') return true;
    if (labelMode === 'none') return isFocused(d.id) || matchSet.has(d.id);
    return !crowded() || isFocused(d.id) || matchSet.has(d.id);
  }

  function labelOpacityFor(d, dim) {
    if (!shouldShowLabel(d)) return 0;
    return (d.kind === 'folder' ? 0.95 : 0.85) * dim;
  }

  // 只改一个属性，供悬停使用 —— 悬停绝不能触发全量样式重算
  function applyLabelFor(id) {
    if (!id) return;
    const el = getEl(id);
    if (!el.length || el.style('display') === 'none') return;
    const d = el.data();
    if (d.kind === 'frame') return;
    el.style('text-opacity', labelOpacityFor(d, dimFactor(d.id, d)));
  }

  let labelFrame = 0;
  function applyLabelVisibility() {
    if (labelFrame) return;
    labelFrame = requestAnimationFrame(() => {
      labelFrame = 0;
      cy.batch(() => {
        cy.nodes().forEach((el) => {
          const d = el.data();
          if (!shownIds.has(d.id) || d.kind === 'frame') return;
          el.style('text-opacity', labelOpacityFor(d, dimFactor(d.id, d)));
        });
      });
    });
  }

  const styleKeys = new Map();

  function applySizing() {
    // 尺寸按「该层的适配缩放」补偿，而不是按实时 zoom —— 这样滚动缩放期间
    // 完全不需要重算样式，相机动画才能跑满帧。
    const cam = cameras[level];
    const z = (cam && cam.zoom) || cy.zoom() || 1;
    const k = Math.max(0.5, Math.min(3.4, 1.15 / z));
    cy.batch(() => {
      cy.nodes().forEach((el) => {
        const d = el.data();
        if (!shownIds.has(d.id)) return;
        const dim = dimFactor(d.id, d);
        if (d.kind === 'frame') {
          const fkey = 'f|' + dim;
          if (styleKeys.get(d.id) !== fkey) {
            styleKeys.set(d.id, fkey);
            el.style({ opacity: 0.9 * dim });
          }
          return;
        }
        const gap = Math.max(0, Math.min(level - (d.depth || 0), 4));
        const boost = 1 + 0.10 * gap;
        const isFolder = d.kind === 'folder';
        const mastery = d.mastery || 0;
        const showLabel = shouldShowLabel(d);
        const key = [k.toFixed(2), dim, gap, mastery, showLabel ? 1 : 0, isFolder ? 1 : 0].join('|');
        if (styleKeys.get(d.id) === key) return;
        styleKeys.set(d.id, key);
        const size = baseSize(d) * k * boost;
        el.style({
          width: isFolder ? size * 1.55 : size,
          height: size,
          'font-size': Math.max(6, Math.min(26, (isFolder ? 12 : 11) * k)),
          opacity: dim,
          'text-opacity': showLabel ? (isFolder ? 0.95 : 0.85) * dim : 0,
          'border-width': (mastery > 0 ? 1 + mastery * 0.75 : 1) * Math.min(k, 2),
          'border-style': mastery > 0 && mastery <= 3 ? 'dashed' : 'solid',
          'border-color': mastery > 0 ? '#e8ecf3' : '#0f1116',
        });
      });
      cy.edges().forEach((el) => {
        if (!shownEdgeIds.has(el.id())) return;
        const d = el.data();
        const dim = d.type === 'contains' ? 0.5 : 1;
        const bothDim = dimFactor(d.source, {}) * dimFactor(d.target, {});
        const ekey = 'e|' + k.toFixed(2) + '|' + dim + '|' + bothDim;
        if (styleKeys.get(el.id()) === ekey) return;
        styleKeys.set(el.id(), ekey);
        const w = d.type === 'contains' ? 1.1 : 0.9 + 1.5 * Math.log2(1 + (d.weight || 1));
        el.style({
          width: Math.max(0.6, Math.min(w * Math.min(k, 1.8), 7)),
          opacity: (d.type === 'contains' ? 0.45 : 0.78) * dim * bothDim,
          'arrow-scale': Math.min(1.4, 0.7 * Math.min(k, 2)),
        });
      });
    });
  }

  // ── 层级切换 ──────────────────────────────────────────────────────────
  function setLevel(next, opts) {
    const o = opts || {};
    const target = Math.max(1, Math.min(MAX_DEPTH, next));
    if (target !== level || o.force) {
      level = target;
    }
    if (expanded && !o.keepExpanded) collapseHeadings(true);
    applyVisibility();
    applySizing();
    applyCamera(o.animate !== false);
    updateHud();
  }

  // ── HUD ───────────────────────────────────────────────────────────────
  function levelLabel(lv) {
    const row = LEVELS[String(lv)] || {};
    return (
      'LOD ' + lv + '/' + MAX_DEPTH +
      ' · 文件夹 ' + (row.folders == null ? '-' : row.folders) +
      ' · 笔记 ' + (row.notes == null ? '-' : row.notes) +
      ' · 边 ' + (row.edges == null ? '-' : row.edges)
    );
  }

  function updateHud() {
    $('readout').innerHTML = levelLabel(level) +
      (level < MAX_DEPTH ? ' <span style="color:#7e879a">— 滚轮或「+」继续深入</span>' : '');
    Array.prototype.forEach.call($('pills').children, (el) => {
      el.classList.toggle('on', parseInt(el.dataset.level, 10) === level);
    });
    $('subtitle').textContent = META.note_count + ' 篇笔记 · ' + META.heading_total + ' 个标题';
  }

  function buildPills() {
    const box = $('pills');
    box.innerHTML = '';
    for (let lv = 1; lv <= MAX_DEPTH; lv += 1) {
      const b = document.createElement('span');
      b.className = 'pill';
      b.dataset.level = lv;
      b.textContent = lv;
      b.title = levelLabel(lv);
      b.addEventListener('click', () => setLevel(lv, { animate: true }));
      box.appendChild(b);
    }
  }

  function buildLegend() {
    const box = $('legend-domains');
    box.innerHTML = '';
    const seen = [];
    NODES.forEach((n) => {
      if (n.kind === 'folder' && n.depth === 1 && seen.indexOf(n.domain) < 0) seen.push(n.domain);
    });
    seen.forEach((d) => {
      const row = document.createElement('div');
      row.className = 'row';
      const sw = document.createElement('span');
      sw.className = 'dot';
      sw.style.background = domainColor(d);
      row.appendChild(sw);
      const label = document.createElement('span');
      label.textContent = d;
      row.appendChild(label);
      box.appendChild(row);
    });
  }

  function buildFilters() {
    const sel = $('domain');
    const seen = [];
    NODES.forEach((n) => {
      if (n.domain && seen.indexOf(n.domain) < 0) seen.push(n.domain);
    });
    seen.sort();
    seen.forEach((d) => {
      const o = document.createElement('option');
      o.value = d;
      o.textContent = d;
      sel.appendChild(o);
    });
  }

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove('show'), 2600);
  }

  // ── 提示气泡 ──────────────────────────────────────────────────────────
  function showTooltip(evt, id) {
    const d = NODE.get(id) || (getEl(id).data() || {});
    if (!d || !d.label) return;
    const bits = [];
    if (d.kind === 'note') {
      bits.push('笔记 · ' + (d.heading_count || 0) + ' 个标题');
      bits.push('所属：' + (d.parentId || '').split('/').slice(-1)[0]);
      bits.push('掌握度：' + (d.mastery ? d.mastery + '/5' : '未标注'));
    } else if (d.kind === 'folder') {
      bits.push('文件夹 · ' + (d.note_count || 0) + ' 篇笔记');
    } else if (d.kind === 'heading') {
      bits.push('知识点 · h' + d.level);
    }
    const rect = container.getBoundingClientRect();
    tooltip.innerHTML =
      '<b>' + escapeHtml(d.label) + '</b>' +
      '<div class="sub">' + escapeHtml(bits.join(' · ')) + '</div>' +
      (d.excerpt ? '<div class="sub">' + escapeHtml(String(d.excerpt).slice(0, 120)) + '</div>' : '');
    tooltip.style.display = 'block';
    const origin = evt.originalEvent || {};
    const x = evt.renderedPosition ? evt.renderedPosition.x : (origin.offsetX || 0);
    const y = evt.renderedPosition ? evt.renderedPosition.y : (origin.offsetY || 0);
    tooltip.style.left = Math.min(x + 16, rect.width - tooltip.offsetWidth - 10) + 'px';
    tooltip.style.top = Math.min(y + 16, rect.height - tooltip.offsetHeight - 10) + 'px';
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function pathOf(id) {
    const d = NODE.get(id);
    return d && d.path ? d.path : id;
  }

  // ── 侧栏 ──────────────────────────────────────────────────────────────
  function edgesOf(id) {
    const out = [];
    const inc = [];
    EDGES.forEach((e) => {
      if (e.type === 'contains') return;
      if (e.s === id) out.push(e);
      else if (e.t === id) inc.push(e);
    });
    return { out: out, inc: inc };
  }

  function renderSidebar(id) {
    const side = $('sidebar');
    const d = NODE.get(id);
    if (!d) {
      side.classList.remove('open');
      return;
    }
    const isNote = d.kind === 'note';
    const { out, inc } = isNote ? edgesOf(id) : { out: [], inc: [] };
    const heads = HEADINGS[id] || [];
    let html = '';
    html += '<h2>' + escapeHtml(d.label) + '</h2>';
    html += '<div class="path">' + escapeHtml(d.path || id) + '</div>';
    html += '<div class="meta">';
    html += '<span class="chip">' + escapeHtml(isNote ? '笔记' : '文件夹') + '</span>';
    if (d.domain) html += '<span class="chip" style="border-color:' + domainColor(d.domain) + '">' + escapeHtml(d.domain) + '</span>';
    if (isNote) {
      html += '<span class="chip">深度 ' + d.depth + '</span>';
      html += '<span class="chip">' + heads.length + ' 个标题</span>';
      html += '<span class="chip">重要度 ' + (d.weight || 1) + '</span>';
      html += '<span class="chip">掌握度 ' + (d.mastery ? d.mastery + '/5' : '未标注') + '</span>';
    } else {
      html += '<span class="chip">' + (d.note_count || 0) + ' 篇笔记</span>';
      html += '<span class="chip">合计权重 ' + Math.round(d.weight || 0) + '</span>';
    }
    html += '</div>';
    html += '<div class="actions">';
    if (isNote) {
      html += '<button data-act="expand">' + (expanded === id ? '收起知识点' : '展开知识点') + '</button>';
      html += '<button data-act="obsidian">在 Obsidian 打开</button>';
      html += '<button data-act="focus">居中</button>';
    } else {
      html += '<button data-act="focus">居中</button>';
      html += '<button data-act="drill">进入该层</button>';
    }
    html += '</div>';
    if (isNote && d.excerpt) {
      html += '<div class="excerpt">' + escapeHtml(d.excerpt) + '</div>';
    }
    if (isNote) {
      html += '<h3>状态：' + (d.metric_source === 'annotation' ? '来自 annotations.yaml'
        : d.metric_source === 'frontmatter' ? '来自笔记 frontmatter' : '默认（未手工标注）') + '</h3>';
      html += '<h3>入边 · 谁指向它（' + inc.length + '）</h3>' + edgeListHtml(inc, 'in');
      html += '<h3>出边 · 它指向谁（' + out.length + '）</h3>' + edgeListHtml(out, 'out');
      if (heads.length) {
        html += '<h3>知识点（笔记内标题，' + heads.length + ' 个）</h3>';
        html += '<ul class="elist hlist">';
        heads.slice(0, 60).forEach((h) => {
          html += '<li data-heading="' + escapeHtml(h.id) + '">' +
            '<span class="hdepth">h' + h.level + '</span> ' + escapeHtml(h.title) +
            '<span class="tag">L' + h.line + '</span></li>';
        });
        if (heads.length > 60) {
          html += '<li style="color:#7e879a">…另有 ' + (heads.length - 60) + ' 个，展开后可见</li>';
        }
        html += '</ul>';
      }
    }
    side.innerHTML = html;
    side.classList.add('open');

    side.querySelectorAll('button[data-act]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const act = btn.dataset.act;
        if (act === 'expand') toggleHeadings(id);
        else if (act === 'obsidian') openInObsidian(id);
        else if (act === 'focus') centerOn(id);
        else if (act === 'drill') setLevel(Math.min(MAX_DEPTH, d.depth + 1), { animate: true });
      });
    });
    side.querySelectorAll('[data-target]').forEach((li) => {
      li.addEventListener('click', () => select(li.dataset.target));
    });
    side.querySelectorAll('[data-heading]').forEach((li) => {
      li.addEventListener('click', () => {
        if (expanded !== id) toggleHeadings(id);
        const el = getEl(li.dataset.heading);
        if (el && el.length) {
          el.select();
          centerOn(li.dataset.heading);
          toast(li.textContent.trim());
        }
      });
    });
  }

  function edgeListHtml(list, dir) {
    if (!list.length) return '<ul class="elist"><li style="color:#7e879a">—</li></ul>';
    list.sort((a, b) => (b.weight || 0) - (a.weight || 0));
    let html = '<ul class="elist">';
    list.forEach((e) => {
      const other = dir === 'in' ? e.s : e.t;
      const name = (NODE.get(other) || { label: other }).label;
      html += '<li data-target="' + escapeHtml(other) + '">' +
        '<span class="arrow">' + (dir === 'in' ? '←' : '→') + '</span>' +
        escapeHtml(name) +
        '<span class="tag" title="' + escapeHtml(TYPE_HINT[e.type] || '') + '">' +
        escapeHtml(TYPE_LABEL[e.type] || e.type) + ' ×' + (e.hits || 1) + '</span></li>';
    });
    html += '</ul>';
    return html;
  }

  function openInObsidian(id) {
    const d = NODE.get(id);
    if (!d || !d.path) return;
    const file = d.path.replace(/\.md$/i, '');
    const url = 'obsidian://open?vault=' + encodeURIComponent(VAULT) + '&file=' + encodeURIComponent(file);
    window.location.href = url;
  }

  function fitCollection(col, pad) {
    const bb = col.boundingBox();
    const { w, h, top } = viewportSize();
    const z = Math.max(ZCFG.min, Math.min(ZCFG.max,
      Math.min((w - 2 * pad) / Math.max(bb.w, 1), (h - top - 2 * pad) / Math.max(bb.h, 1))));
    const cx = bb.x1 + bb.w / 2;
    const cyy = bb.y1 + bb.h / 2;
    return { zoom: z, pan: { x: w / 2 - cx * z, y: (h + top) / 2 - cyy * z } };
  }

  function centerOn(id) {
    const el = getEl(id);
    if (!el.length) return;
    const bb = el.boundingBox();
    const { w, h, top } = viewportSize();
    const z = Math.max(ZCFG.min, Math.min(ZCFG.max, Math.max(cy.zoom(), 1.1)));
    const cx = (bb.x1 + bb.x2) / 2;
    const cyy = (bb.y1 + bb.y2) / 2;
    cy.animate({
      zoom: z,
      pan: { x: w / 2 - cx * z, y: (h + top) / 2 - cyy * z },
    }, { duration: ZCFG.transition_ms, easing: 'ease-in-out-cubic' });
  }

  // Cytoscape 的 #id 选择器是「包含子串」匹配，不是精确匹配：标题节点 id 里含有
  // 所属笔记的 id，轮廓节点 id 里含有文件夹路径，直接查会误命中。这里强制精确。
  function getEl(id) {
    if (!id) return cy.collection();
    return cy.getElementById(id).filter((e) => e.id() === id);
  }

  function select(id) {
    cy.nodes('.selected').removeClass('selected');
    selectedId = id;
    if (id) {
      const el = getEl(id);
      if (el.length) el.addClass('selected');
    }
    refreshNeighbours();
    applySizing();
    if (id) renderSidebar(id);
    else $('sidebar').classList.remove('open');
  }

  // ── 标题层（知识点） ──────────────────────────────────────────────────
  function pickHeadings(noteId) {
    const all = HEADINGS[noteId] || [];
    if (!all.length) return { list: [], note: '该笔记还没有任何标题。在笔记里加上标题后重新构建（或开着 watch）就会出现。' };
    let list;
    if (expandAllLevels) {
      list = all.slice(0, 220);
      if (all.length > 220) return { list: list, note: '该笔记有 ' + all.length + ' 个标题，只展开了前 220 个。' };
      return { list: list };
    }
    list = all.filter((h) => h.level <= 2);
    if (!list.length) list = all.filter((h) => h.level <= 3);
    if (list.length > 60) {
      const only1 = all.filter((h) => h.level <= 1);
      if (only1.length) return { list: only1, note: '该笔记标题较多（' + all.length + ' 个），默认只展开一级标题。点侧栏「展开全部层级」可看全部。' };
    }
    return { list: list };
  }

  function toggleHeadings(noteId) {
    if (expanded === noteId) {
      collapseHeadings();
      return;
    }
    collapseHeadings(true);
    const note = NODE.get(noteId);
    if (!note) return;
    const picked = pickHeadings(noteId);
    if (!picked.list.length) {
      toast(picked.note || '没有标题');
      return;
    }
    const allowed = new Set(picked.list.map((h) => h.id));
    // 父标题若被裁剪，就挂到笔记本体上
    const fixed = picked.list.map((h) => Object.assign({}, h, {
      parent: allowed.has(h.parent) ? h.parent : noteId,
    }));

    // 局部径向/扇形布局：以笔记为圆心，朝「图的外侧」展开，不动全局坐标
    const baseAngle = Math.atan2(note.y, note.x) || 0;
    const roots = fixed.filter((h) => h.parent === noteId);
    const baseRadius = 120 + 15 * Math.max(roots.length, 1);
    const step = 0.62 * baseRadius;
    const positions = {};
    const arcs = {};
    const centre = { x: note.x, y: note.y };

    function place(parentId, a0, a1, radius, depth) {
      const kids = fixed.filter((h) => h.parent === parentId);
      if (!kids.length) return;
      const w = (a1 - a0) / kids.length;
      kids.forEach((h, i) => {
        const a0i = a0 + w * i;
        const a1i = a0i + w;
        const mid = (a0i + a1i) / 2;
        positions[h.id] = { x: centre.x + radius * Math.cos(mid), y: centre.y + radius * Math.sin(mid) };
        arcs[h.id] = [a0i, a1i];
        if (depth < 6) place(h.id, a0i, a1i, radius + step, depth + 1);
      });
    }
    const spread = roots.length > 3 ? 1.15 : 0.85;
    place(noteId, baseAngle - spread, baseAngle + spread, baseRadius, 1);

    const newEls = [];
    fixed.forEach((h) => {
      if (!positions[h.id]) return;
      newEls.push({
        group: 'nodes',
        data: {
          id: h.id,
          label: h.title,
          kind: 'heading',
          note: noteId,
          level: h.level,
          depth: note.depth + 1,
          domain: note.domain,
          mastery: 0,
          weight: 1,
          color: domainColor(note.domain),
        },
        position: positions[h.id],
        classes: 'node-heading',
      });
      newEls.push({
        group: 'edges',
        data: {
          id: 'hc_' + h.id,
          source: h.parent,
          target: h.id,
          type: 'contains',
          level: level,
          weight: 0.5,
          color: EDGE_COLOR.contains,
          arrow: 'none',
          lstyle: 'dotted',
        },
      });
    });
    HEADING_LINKS.forEach((hl, i) => {
      if (!allowed.has(hl.heading)) return;
      newEls.push({
        group: 'edges',
        data: {
          id: 'hl_' + i,
          source: hl.source,
          target: hl.heading,
          type: 'derives',
          level: level,
          weight: 2,
          color: EDGE_COLOR.derives,
          arrow: 'triangle',
          lstyle: 'solid',
        },
      });
    });

    cy.add(newEls);
    expanded = noteId;
    expandedHeadings = newEls.map((e) => e.data.id);
    applyVisibility();
    applySizing();
    const col = cy.collection();
    newEls.forEach((e) => { col.merge(getEl(e.data.id)); });
    col.merge(getEl(noteId));
    const cam = fitCollection(col, 70);
    cy.animate({ zoom: cam.zoom, pan: cam.pan },
      { duration: ZCFG.transition_ms, easing: 'ease-in-out-cubic' });
    if (picked.note) toast(picked.note);
    renderSidebar(noteId);
  }

  function collapseHeadings(silent) {
    if (!expanded) return;
    const ids = expandedHeadings.slice();
    expanded = null;
    expandedHeadings = [];
    ids.forEach((id) => {
      const el = getEl(id);
      if (el.length) el.remove();
    });
    if (!silent) {
      applyVisibility();
      applySizing();
      applyCamera(true);
      if (selectedId) renderSidebar(selectedId);
    } else {
      applyVisibility();
    }
  }

  // ── 过滤与搜索 ────────────────────────────────────────────────────────
  function computeFilterSet() {
    if (filterDomain === 'all' && filterMastery === 'all') return null;
    const keep = new Set();
    NODES.forEach((n) => {
      if (n.kind !== 'note') return;
      if (filterDomain !== 'all' && n.domain !== filterDomain) return;
      if (filterMastery === 'known' && !(n.mastery >= 3)) return;
      if (filterMastery === 'weak' && !(n.mastery >= 1 && n.mastery <= 2)) return;
      if (filterMastery === 'none' && n.mastery !== 0) return;
      keep.add(n.id);
      let p = n.parent;
      while (p) {
        keep.add(p);
        const pn = NODE.get(p);
        p = pn ? pn.parent : null;
      }
    });
    return keep;
  }

  function applyFilters() {
    filterSet = computeFilterSet();
    applyVisibility();
    applySizing();
  }

  function runSearch(q) {
    searchQ = q;
    matchSet = new Set();
    cy.nodes('.hit').removeClass('hit');
    const hits = $('hits');
    if (!q) {
      hits.style.display = 'none';
      hits.innerHTML = '';
      applySizing();
      return;
    }
    const needle = q.toLowerCase();
    const out = [];
    NODES.forEach((n) => {
      if (n.label.toLowerCase().indexOf(needle) >= 0) {
        matchSet.add(n.id);
        out.push({ id: n.id, label: n.label, why: n.kind === 'note' ? '笔记 · ' + (n.parent || '') : '文件夹' });
      }
    });
    Object.keys(HEADINGS).forEach((noteId) => {
      HEADINGS[noteId].forEach((h) => {
        if (h.title.toLowerCase().indexOf(needle) >= 0) {
          matchSet.add(h.id);
          if (out.length < 200) {
            out.push({ id: h.id, label: h.title, why: '知识点 · 在《' + (NODE.get(noteId) || {}).label + '》h' + h.level, note: noteId });
          }
        }
      });
    });
    matchSet.forEach((id) => {
      if (!NODE.has(id)) matchSet.delete(id);
    });
    // 命中的节点直接加 .hit 类高亮（黄色边框）
    matchSet.forEach((id) => {
      const el = getEl(id);
      if (el.length) el.addClass('hit');
    });
    out.sort((a, b) => a.label.length - b.label.length);
    hits.innerHTML = out.slice(0, 30).map((h) =>
      '<div class="hit" data-id="' + escapeHtml(h.id) + '" data-note="' + escapeHtml(h.note || '') + '">' +
      escapeHtml(h.label) + '<div class="why">' + escapeHtml(h.why) + '</div></div>').join('')
      || '<div class="hit" style="color:#7e879a">没有匹配</div>';
    hits.style.display = 'block';
    hits.querySelectorAll('.hit[data-id]').forEach((el) => {
      el.addEventListener('click', () => {
        const id = el.dataset.id;
        if (el.dataset.note) {
          reveal(el.dataset.note);
          if (expanded !== el.dataset.note) toggleHeadings(el.dataset.note);
          centerOn(id);
        } else {
          reveal(id);
        }
      });
    });
    applySizing();
  }

  function reveal(id) {
    const d = NODE.get(id);
    if (!d) return;
    if (d.depth > level) setLevel(d.depth, { animate: true });
    select(id);
    centerOn(id);
  }

  // ── 事件绑定 ──────────────────────────────────────────────────────────
  cy.on('mouseover', 'node', (evt) => {
    const d = evt.target.data();
    if (d.kind === 'frame') return;
    const prev = hoveredId;
    hoveredId = d.id;
    showTooltip(evt, d.id);
    // 悬停只更新两个节点的标签透明度，绝不做全量重算（否则每次 50ms 以上）
    if (prev && prev !== d.id) applyLabelFor(prev);
    applyLabelFor(d.id);
  });
  cy.on('mouseout', 'node', () => {
    const prev = hoveredId;
    hoveredId = null;
    tooltip.style.display = 'none';
    applyLabelFor(prev);
  });
  cy.on('tap', 'node', (evt) => {
    const d = evt.target.data();
    if (d.kind === 'frame') return;
    select(d.id);
  });
  cy.on('tap', (evt) => {
    if (evt.target === cy) select(null);
  });
  cy.on('dbltap', 'node', (evt) => {
    const d = evt.target.data();
    if (d.kind === 'note') toggleHeadings(d.id);
    else if (d.kind === 'folder') setLevel(Math.min(MAX_DEPTH, d.depth + 1), { animate: true });
  });
  // 缩放期间只切换标签显隐（单属性 + rAF 合并），尺寸按层级预补，不再逐帧重算
  cy.on('zoom', () => {
    if (labelMode === 'auto') applyLabelVisibility();
  });

  container.addEventListener('wheel', (evt) => {
    evt.preventDefault();
    const cam = cameras[level];
    if (!cam) return;
    const dirIn = evt.deltaY < 0;
    const factor = dirIn ? ZCFG.wheel_step : 1 / ZCFG.wheel_step;
    const target = cy.zoom() * factor;
    const hi = cam.zoom * ZCFG.level_span;
    const lo = cam.zoom / ZCFG.level_span;
    if (target > hi) {
      if (level < MAX_DEPTH) {
        const now = Date.now();
        if (now - lastLevelStep > 200) {
          lastLevelStep = now;
          setLevel(level + 1, { animate: true });
        }
      }
      return;
    }
    if (target < lo) {
      if (level > 1) {
        const now = Date.now();
        if (now - lastLevelStep > 200) {
          lastLevelStep = now;
          setLevel(level - 1, { animate: true });
        }
      }
      return;
    }
    const z = Math.max(ZCFG.min, Math.min(ZCFG.max, target));
    const x = evt.offsetX;
    const y = evt.offsetY;
    const pan = cy.pan();
    const oldZoom = cy.zoom();
    const m = { x: (x - pan.x) / oldZoom, y: (y - pan.y) / oldZoom };
    cy.viewport({ zoom: z, pan: { x: x - m.x * z, y: y - m.y * z } });
  }, { passive: false });

  document.addEventListener('keydown', (evt) => {
    const tag = (evt.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select') {
      if (evt.key === 'Escape') {
        evt.target.blur();
        $('hits').style.display = 'none';
      }
      return;
    }
    if (evt.key === ']' || evt.key === '+') setLevel(level + 1, { animate: true });
    else if (evt.key === '[' || evt.key === '-') setLevel(level - 1, { animate: true });
    else if (evt.key === 'Escape') {
      if (expanded) collapseHeadings();
      else select(null);
    } else if (evt.key === 'Enter' && $('search').value) {
      runSearch($('search').value);
    }
  });

  $('zoomin').addEventListener('click', () => setLevel(level + 1, { animate: true }));
  $('zoomout').addEventListener('click', () => setLevel(level - 1, { animate: true }));
  $('reset').addEventListener('click', () => applyCamera(true));
  $('search').addEventListener('input', (e) => runSearch(e.target.value.trim()));
  $('search').addEventListener('focus', (e) => { if (e.target.value.trim()) runSearch(e.target.value.trim()); });
  $('search').addEventListener('blur', () => setTimeout(() => { $('hits').style.display = 'none'; }, 180));
  $('domain').addEventListener('change', (e) => { filterDomain = e.target.value; applyFilters(); });
  $('mastery').addEventListener('change', (e) => { filterMastery = e.target.value; applyFilters(); });
  $('labels').addEventListener('change', (e) => { labelMode = e.target.value; applySizing(); });
  window.addEventListener('resize', () => {
    rebuildCameras();
    applyCamera(false);
    applySizing();
  });

  // ── 启动 ──────────────────────────────────────────────────────────────
  buildPills();
  buildLegend();
  buildFilters();
  rebuildCameras();
  setLevel(level, { animate: false, force: true });
  if (MAX_DEPTH > 1) {
    setTimeout(() => toast('滚轮或「+」放大会逐层展开：学科 → 子学科 → 课程 → 笔记 → 知识点'), 700);
  }

  // 调试 / 自动化验证入口 —— 也可以直接在浏览器控制台里用 KG.state() 查状态
  window.KG = {
    cy: cy,
    data: DATA,
    setLevel: setLevel,
    select: select,
    centerOn: centerOn,
    toggleHeadings: toggleHeadings,
    collapseHeadings: collapseHeadings,
    runSearch: runSearch,
    applyFilters: applyFilters,
    state: () => ({
      level: level,
      shownNodes: shownIds.size,
      shownEdges: shownEdgeIds.size,
      zoom: Math.round(cy.zoom() * 1000) / 1000,
      expanded: expanded,
      selected: selectedId,
      search: searchQ,
      labelMode: labelMode,
      filterSet: filterSet ? filterSet.size : null,
    }),
  };
})();
