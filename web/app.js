/* 知识笔记语义缩放可视化 —— 前端交互层
 *
 * 分工：web/render.js 负责「画什么、怎么淡入淡出、怎么响应滚轮/拖拽」，
 * 本文件只负责 DOM 侧的一切 —— 顶栏、侧栏、搜索、过滤、图例、键盘快捷键。
 * 两者通过 createRenderer 的 hooks（onHover / onSelect / onCamera / onFrame）
 * 与 api（selected / filterSet / matchSet / labelMode / edgeMode / focusOn /
 * zoomToDepth）通信。
 *
 * 设计要点：
 *  1) zoom 是唯一真源，层级由 zoom 连续派生（R.enterAt(zoom)）。换层从不反向改
 *     相机，所以不存在「视角收窄 → zoom 变大 → 又跳回深层」的正反馈震荡。
 *     方向：**放大 = 更深**（与地图一致）。旧版「zoom 越大看到的层越浅」是 bug。
 *  2) 节点坐标全部在构建期算定，前端只做连续淡入淡出 —— 位置永不变，也没有
 *     「展开标题层」这种按需增删元素的操作：标题从构建期起就是一等节点。
 *  3) 淡入淡出的门槛由构建期写入每个节点的世界半径 r 决定（minzoom =
 *     lod.min_px / r，就是地图矢量瓦片那个 minzoom 字段）。circle packing 保证
 *     沿包含链 r 严格递减，于是 minzoom 严格递增 ——「放大一定只会看到更细的
 *     东西」这条方向性是被几何锁住的，不靠前端临场判断。
 */
(function () {
  'use strict';

  // ── 数据 ──────────────────────────────────────────────────────────────
  const DATA = JSON.parse(document.getElementById('graph-data').textContent);
  const META = DATA.meta;
  const THEME = META.theme || {};
  const MAX_DEPTH = META.max_depth;
  const VAULT = META.vault_name;
  const LEVELS = DATA.levels || {};

  const NODES = DATA.nodes;
  const NODE = new Map(NODES.map((n) => [n.id, n]));
  const EDGES = DATA.edges;

  const domainColor = (d) => (THEME.domains && THEME.domains[d]) || THEME.fallback || '#8B949E';
  const TYPE_LABEL = { prerequisite: '前置', derives: '引用', contrast: '并列', contains: '包含' };
  const TYPE_HINT = {
    prerequisite: 'source 是 target 的前置',
    derives: 'source 引用了 target',
    contrast: '并列/对比，方向未知',
    contains: '层级包含',
  };
  const ORIGIN_LABEL = {
    wiki: '来自笔记正文的 [[wikilink]]',
    annotation: '来自 annotations.yaml 手工标注',
    frontmatter: '来自笔记 frontmatter',
    candidate: '启发式候选（未人工确认）',
    hierarchy: '文件夹/标题的包含结构',
    mixed: '多种来源合并',
  };
  const KIND_LABEL = { folder: '文件夹', note: '笔记', heading: '知识点' };

  // 父子索引：过滤时要「留下这篇笔记的全部标题」，得能顺着往下走
  const KIDS = new Map();
  NODES.forEach((n) => {
    if (!n.parent) return;
    let list = KIDS.get(n.parent);
    if (!list) { list = []; KIDS.set(n.parent, list); }
    list.push(n.id);
  });

  // ── DOM ───────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const canvas = $('cv');
  const tooltip = $('tooltip');
  const toastEl = $('toast');

  // ── 状态 ──────────────────────────────────────────────────────────────
  let filterDomain = 'all';
  let filterMastery = 'all';
  let searchQ = '';
  let labelMode = 'auto';      // 'auto' | 'on' | 'off'，与渲染器同词汇
  let edgeMode = 'raw';        // 'raw'（逐条链接，不随缩放聚合）| 'agg'（按尺度聚合）

  // 用户选的连线模式要记住：这份 HTML 是 file:// 直接打开的，Chrome 下
  // localStorage 可能抛 SecurityError，所以两个方向都整段兜住，失败就退回默认值。
  function readStored(key, fallback) {
    try {
      const v = window.localStorage.getItem(key);
      return v == null ? fallback : v;
    } catch (err) { return fallback; }
  }

  function writeStored(key, value) {
    try { window.localStorage.setItem(key, value); } catch (err) { /* 存不下就算了 */ }
  }

  const storedEdgeMode = readStored('kg.edgeMode', null);
  if (storedEdgeMode === 'raw' || storedEdgeMode === 'agg') edgeMode = storedEdgeMode;

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove('show'), 2600);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function pathOf(id) {
    const d = NODE.get(id);
    return d && d.path ? d.path : id;
  }

  // 从任意节点回溯到根的包含链（含自己），侧栏面包屑与「上级」跳转都用它
  function chainOf(id) {
    const out = [];
    let cur = id;
    let guard = 0;
    while (cur && guard++ < 64) {
      out.push(cur);
      const n = NODE.get(cur);
      cur = n ? n.parent : null;
    }
    return out.reverse();
  }

  // ── HUD ───────────────────────────────────────────────────────────────
  // 该层「累积可见了什么」的读数。拆成两半用：levelLabel 给层级胶囊的 title（有空间，
  // 带上 LOD 前缀），levelCounts 给顶栏 #readout（空间紧张，LOD 与 z 由调用处另拼）。
  function levelCounts(lv) {
    const row = LEVELS[String(lv)] || {};
    return '文件夹 ' + (row.folders == null ? '-' : row.folders) +
      ' · 笔记 ' + (row.notes == null ? '-' : row.notes) +
      ' · 标题 ' + (row.headings == null ? '-' : row.headings) +
      ' · 边 ' + (row.edges == null ? '-' : row.edges);
  }

  function levelLabel(lv) {
    return 'LOD ' + lv + '/' + MAX_DEPTH + ' · ' + levelCounts(lv);
  }

  let lastReadout = '';
  let lastLevel = -1;

  function updateHud() {
    const zoom = R.camera.zoom;
    const lv = R.enterAt(zoom);
    if (lv !== lastLevel) {
      lastLevel = lv;
      Array.prototype.forEach.call($('pills').children, (el) => {
        el.classList.toggle('on', parseInt(el.dataset.level, 10) === lv);
      });
    }
    // ⚠️ 顺序有意为之：1440px 下顶栏是超额分配的（见 template.html 顶栏注释），
    // #readout 只拿得到约 200px，折两行后装不满整串文字。所以把最关键的
    // 「第几层 + z」放最前面，被省略掉的只会是末尾的计数与提示，而不是缩放值。
    const text = 'LOD ' + lv + '/' + MAX_DEPTH + ' · z=' + zoom.toFixed(3) +
      ' · ' + levelCounts(lv);
    // 第 11 带（第五轮：圆即入口）：不占层级数字（enter[] 仍是 10 项），只在提示位说一句。
    // 药丸层已删除 → 文案必须教会用户「Ctrl + 悬停标题圆」，否则功能等于不存在。
    let hint;
    const pvHint = 'Ctrl + 悬停标题圆可预览正文';
    if (lv < MAX_DEPTH) {
      hint = ' <span style="color:#7e879a">— 继续向上滚可深入 · ' + pvHint + '</span>';
    } else {
      hint = ' <span style="color:#7e879a">— ' + pvHint + '</span>';
    }
    if (text !== lastReadout) {
      lastReadout = text;
      $('readout').innerHTML = text + hint;
    }
  }

  let lastStats = '';
  function updateStats(stats) {
    // 选中一个元素时把焦点读数亮出来：「相关的有几条 / 一共几条 · 相邻几个元素」。
    // 没选中、或全都相关时保持原样 —— 读数不该在无事发生时也跟着变。
    const rel = stats.focusEdges;
    const edgeTxt = (R.selected && rel != null && rel < stats.edges)
      ? '关系 ' + rel + '/' + stats.edges + ' · 相邻 ' + (stats.focusNeighbors || 0)
      : '关系 ' + stats.edges;
    const text = '节点 ' + stats.nodes + ' · ' + edgeTxt + ' · 标签 ' + stats.labels;
    if (text === lastStats) return;
    lastStats = text;
    $('footer').innerHTML = text +
      '<br>生成于 ' + escapeHtml(META.generated || '') + ' · 数据来自 Obsidian vault（本地构建，无服务器）';
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
      b.addEventListener('click', () => R.zoomToDepth(lv));
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

  // 两套「关系」图例互斥：聚合模式下线宽代表合并了多少条原始链接，逐条模式下
  // 线宽是恒定的、条数本身才代表强度 —— 说明文字必须跟着模式换，否则会误导。
  function applyEdgeLegend() {
    const raw = edgeMode !== 'agg';
    const rawBox = $('legend-rel-raw');
    const aggBox = $('legend-rel-agg');
    if (rawBox) rawBox.hidden = !raw;
    if (aggBox) aggBox.hidden = raw;
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

  // ── 提示气泡 ──────────────────────────────────────────────────────────
  function showTooltip(node, sx, sy) {
    const bits = [];
    if (node.kind === 'note') {
      bits.push('笔记 · ' + (node.heading_count || 0) + ' 个标题');
      bits.push('掌握度：' + (node.mastery ? node.mastery + '/5' : '未标注'));
    } else if (node.kind === 'folder') {
      bits.push('文件夹 · ' + (node.note_count || 0) + ' 篇笔记');
    } else {
      bits.push('知识点 · h' + node.level + ' · L' + node.line);
    }
    bits.push('第 ' + node.depth + ' 层');
    const parent = node.parent ? NODE.get(node.parent) : null;
    if (parent) bits.push('属于：' + parent.label);
    const size = R.size();
    tooltip.innerHTML =
      '<b>' + escapeHtml(node.label) + '</b>' +
      '<div class="sub">' + escapeHtml(bits.join(' · ')) + '</div>' +
      (node.excerpt ? '<div class="sub">' + escapeHtml(String(node.excerpt).slice(0, 120)) + '</div>' : '');
    tooltip.style.display = 'block';
    tooltip.style.left = Math.min(sx + 16, size[0] - tooltip.offsetWidth - 10) + 'px';
    tooltip.style.top = Math.min(sy + 16, size[1] - tooltip.offsetHeight - 10) + 'px';
  }

  function hideTooltip() {
    tooltip.style.display = 'none';
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

  function edgeListHtml(list, dir, selfId) {
    if (!list.length) return '<ul class="elist"><li style="color:#7e879a">—</li></ul>';
    list.sort((a, b) => (b.weight || 0) - (a.weight || 0));
    let html = '<ul class="elist">';
    list.slice(0, 60).forEach((e) => {
      const other = dir === 'in' ? e.s : e.t;
      const name = (NODE.get(other) || { label: other }).label;
      // data-self 记录「这行边属于哪个元素的边列表」：点边行的语义是「我要看这条链接」，
      // 需要把两端一起框进屏幕（fitPair），而不是只跳去目标。标题行（hlist）不写这个
      // 属性，点击仍走旧的「跳转目标元素」语义
      html += '<li data-target="' + escapeHtml(other) + '"' +
        (selfId ? ' data-self="' + escapeHtml(selfId) + '"' : '') + '>' +
        '<span class="arrow">' + (dir === 'in' ? '←' : '→') + '</span>' +
        escapeHtml(name) +
        '<span class="tag" title="' +
        escapeHtml([TYPE_HINT[e.type], ORIGIN_LABEL[e.origin]].filter(Boolean).join(' · ')) + '">' +
        escapeHtml(TYPE_LABEL[e.type] || e.type) + ' ×' + (e.hits || 1) + '</span></li>';
    });
    if (list.length > 60) {
      html += '<li style="color:#7e879a">…另有 ' + (list.length - 60) + ' 条</li>';
    }
    html += '</ul>';
    return html;
  }

  function renderSidebar(id) {
    const side = $('sidebar');
    const d = NODE.get(id);
    if (!d) {
      side.classList.remove('open');
      return;
    }
    const kind = d.kind;
    const isNote = kind === 'note';
    const isHeading = kind === 'heading';
    const { out, inc } = edgesOf(id);
    const heads = isNote
      ? NODES.filter((n) => n.kind === 'heading' && n.note === id)
      : [];
    const chain = chainOf(id);
    const desc = R.descOf(id);

    let html = '';
    html += '<h2>' + escapeHtml(d.label) + '</h2>';
    html += '<div class="path">' + escapeHtml(d.path || id) + '</div>';
    html += '<div class="meta">';
    html += '<span class="chip">' + escapeHtml(KIND_LABEL[kind] || kind) + '</span>';
    if (d.domain) {
      html += '<span class="chip" style="border-color:' + domainColor(d.domain) + '">' +
        escapeHtml(d.domain) + '</span>';
    }
    html += '<span class="chip">第 ' + d.depth + ' 层</span>';
    if (isHeading) {
      html += '<span class="chip">h' + d.level + '</span>';
      html += '<span class="chip">L' + d.line + '</span>';
    } else if (isNote) {
      html += '<span class="chip">' + heads.length + ' 个标题</span>';
      html += '<span class="chip">重要度 ' + (d.weight || 1) + '</span>';
      html += '<span class="chip">掌握度 ' + (d.mastery ? d.mastery + '/5' : '未标注') + '</span>';
    } else {
      html += '<span class="chip">' + (d.note_count || 0) + ' 篇笔记</span>';
      html += '<span class="chip">合计权重 ' + Math.round(d.weight || 0) + '</span>';
    }
    if (desc) html += '<span class="chip">下辖 ' + desc + ' 个元素</span>';
    html += '</div>';

    // 面包屑：文件夹 / 笔记 / 标题都是「人为规定的存储结构」，但它是唯一能把
    // 一个深层知识点送回上下文的线索，所以在侧栏里显式给一条可点的链。
    if (chain.length > 1) {
      html += '<div class="path" style="margin-bottom:10px">';
      html += chain.map((cid, i) =>
        (i ? ' › ' : '') +
        (cid === id
          ? '<b>' + escapeHtml((NODE.get(cid) || {}).label) + '</b>'
          : '<a href="#" data-goto="' + escapeHtml(cid) + '" style="color:var(--accent);text-decoration:none">' +
            escapeHtml((NODE.get(cid) || {}).label) + '</a>')
      ).join('');
      html += '</div>';
    }

    html += '<div class="actions">';
    html += '<button data-act="focus">居中</button>';
    html += '<button data-act="drill">深入下一层</button>';
    if (isNote || isHeading) html += '<button data-act="obsidian">在 Obsidian 打开</button>';
    html += '</div>';

    if (isNote && d.excerpt) {
      html += '<div class="excerpt">' + escapeHtml(d.excerpt) + '</div>';
    }
    if (isNote) {
      html += '<h3>状态：' + (d.metric_source === 'annotation' ? '来自 annotations.yaml'
        : d.metric_source === 'frontmatter' ? '来自笔记 frontmatter' : '默认（未手工标注）') + '</h3>';
    }
    html += '<h3>入边 · 谁指向它（' + inc.length + '）</h3>' + edgeListHtml(inc, 'in', id);
    html += '<h3>出边 · 它指向谁（' + out.length + '）</h3>' + edgeListHtml(out, 'out', id);

    if (isNote && heads.length) {
      heads.sort((a, b) => a.line - b.line);
      html += '<h3>知识点（笔记内标题，' + heads.length + ' 个）</h3>';
      html += '<ul class="elist hlist">';
      heads.slice(0, 60).forEach((h) => {
        html += '<li data-target="' + escapeHtml(h.id) + '">' +
          '<span class="hdepth">h' + h.level + '</span> ' + escapeHtml(h.title) +
          '<span class="tag">L' + h.line + '</span></li>';
      });
      if (heads.length > 60) {
        html += '<li style="color:#7e879a">…另有 ' + (heads.length - 60) + ' 个，向上滚可见</li>';
      }
      html += '</ul>';
    }

    side.innerHTML = html;
    side.classList.add('open');

    side.querySelectorAll('button[data-act]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const act = btn.dataset.act;
        if (act === 'focus') R.focusOn(id, 1.0);
        else if (act === 'drill') R.focusOn(id, 1.6, 380);
        else if (act === 'obsidian') openInObsidian(id);
      });
    });
    side.querySelectorAll('[data-target]').forEach((li) => {
      li.addEventListener('click', () => {
        // 边行（带 data-self）：点击语义是「我要看这条链接」—— 选中目标但不单点跳视，
        // 改为把链接两端一起框进屏幕（fitPair），让连接它们的箭头直接可见；
        // 标题行（hlist，无 data-self）保持旧的「跳去目标元素」语义
        if (li.dataset.self != null && !li.closest('.hlist')) {
          select(li.dataset.target, false);
          R.fitPair(li.dataset.self, li.dataset.target);
        } else {
          select(li.dataset.target, true);
        }
      });
    });
    side.querySelectorAll('[data-goto]').forEach((a) => {
      a.addEventListener('click', (evt) => {
        evt.preventDefault();
        select(a.dataset.goto, true);
      });
    });
  }

  function openInObsidian(id) {
    let d = NODE.get(id);
    if (!d) return;
    if (d.kind === 'heading') d = NODE.get(d.note) || d;   // 标题没有自己的文件
    if (!d.path) { toast('这个元素没有对应的文件'); return; }
    const file = d.path.replace(/\.md$/i, '');
    const url = 'obsidian://open?vault=' + encodeURIComponent(VAULT) + '&file=' + encodeURIComponent(file);
    window.location.href = url;
  }

  function select(id, focus) {
    R.selected = id;
    if (id) {
      renderSidebar(id);
      if (focus) R.focusOn(id, 1.25);
    } else {
      $('sidebar').classList.remove('open');
    }
  }

  // ── 过滤 ──────────────────────────────────────────────────────────────
  // 判据只落在笔记上（学科、掌握度都是笔记的属性），命中的笔记要把它的全部
  // 标题一起留下，再沿 parent 链一路补到根 —— 否则淡入淡出会因为祖先不可见
  // 而把整条链掐断（渲染器里「可见层级」是沿包含链取前缀的）。
  function computeFilterSet() {
    if (filterDomain === 'all' && filterMastery === 'all') return null;
    const keep = new Set();
    const addSubtree = (id) => {
      keep.add(id);
      (KIDS.get(id) || []).forEach(addSubtree);
    };
    NODES.forEach((n) => {
      if (n.kind !== 'note') return;
      if (filterDomain !== 'all' && n.domain !== filterDomain) return;
      if (filterMastery === 'known' && !(n.mastery >= 3)) return;
      if (filterMastery === 'weak' && !(n.mastery >= 1 && n.mastery <= 2)) return;
      if (filterMastery === 'none' && n.mastery !== 0) return;
      addSubtree(n.id);
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
    const set = computeFilterSet();
    R.filterSet = set;
    if (!set) { toast('已取消过滤'); return; }
    let notes = 0;
    set.forEach((id) => { if ((NODE.get(id) || {}).kind === 'note') notes += 1; });
    toast(notes ? '过滤后保留 ' + notes + ' 篇笔记及其标题' : '没有笔记符合这个条件');
  }

  // ── 搜索 ──────────────────────────────────────────────────────────────
  // 标题已经是一等节点，所以一次遍历 NODES 就同时覆盖「笔记 / 文件夹 / 知识点」，
  // 不再需要单独扫一份标题表。
  function runSearch(q) {
    searchQ = q;
    const matchSet = new Set();
    const hits = $('hits');
    if (!q) {
      hits.style.display = 'none';
      hits.innerHTML = '';
      R.matchSet = matchSet;
      return;
    }
    const needle = q.toLowerCase();
    const out = [];
    NODES.forEach((n) => {
      if (n.label.toLowerCase().indexOf(needle) < 0) return;
      matchSet.add(n.id);
      let why;
      if (n.kind === 'heading') {
        const note = NODE.get(n.note) || {};
        why = '知识点 · 在《' + (note.label || n.note) + '》h' + n.level;
      } else if (n.kind === 'note') {
        why = '笔记 · ' + (n.parent || '');
      } else {
        why = '文件夹 · ' + (n.note_count || 0) + ' 篇笔记';
      }
      out.push({ id: n.id, label: n.label, why: why });
    });
    R.matchSet = matchSet;
    out.sort((a, b) => a.label.length - b.label.length);
    hits.innerHTML = out.slice(0, 30).map((h) =>
      '<div class="hit" data-id="' + escapeHtml(h.id) + '">' +
      escapeHtml(h.label) + '<div class="why">' + escapeHtml(h.why) + '</div></div>').join('')
      || '<div class="hit" style="color:#7e879a">没有匹配</div>';
    hits.style.display = 'block';
    hits.querySelectorAll('.hit[data-id]').forEach((el) => {
      el.addEventListener('click', () => select(el.dataset.id, true));
    });
    toast('匹配 ' + matchSet.size + ' 个元素，列出前 ' + Math.min(30, out.length) + ' 个');
  }

  // ── 渲染器 ────────────────────────────────────────────────────────────
  const R = window.createRenderer(canvas, DATA, {
    onHover: (id, node, sx, sy) => {
      // Ctrl 模式下不弹 hover 气泡：那时是「预览模式」，气泡和预览浮层会打架
      if (ctrlDown || !id || !node) { hideTooltip(); return; }
      showTooltip(node, sx, sy);
    },
    onSelect: (id) => select(id, false),
    onCamera: updateHud,
    onFrame: updateStats,
  });

  canvas.addEventListener('mouseleave', () => { R.hover = null; hideTooltip(); });

  // ── Obsidian 式预览：Ctrl + 悬停「实心圆」（2026-10-24 第五轮）──────────────
  // 药丸层已经整个删除 —— **圆自己就是入口**：
  //   * 悬停在**标题**圆上 → 预览该笔记，并从**这一节**（锚点 `pv-hN`）滚起；
  //   * 悬停在**文件夹 / 笔记**圆上 → 不预览，toast 提示「还没到标题层」；
  //   * Ctrl 松开 / 移到空白 / Esc → 收起。
  // 预览内容沿用构建期的 HTML 片段（markdown 排版 + 运行时 KaTeX + 按路径引用的图片；
  // 标题本身就是片段里的 `<hN>`，所以从这一节滚起时标题是渲染出来的）。
  const PV = $('preview');
  const pvCache = new Map();       // note id → 已含 KaTeX 结果的 innerHTML
  let ctrlDown = false;
  let pvNote = null;
  let pvLast = null;               // 最近一次鼠标位置（按下 Ctrl 那一刻要用）
  let hintNode = null;             // 上一次提示过的节点 id（避免每次移动都 toast）
  let pvPinned = false;            // 单击标题圆 = 固定预览（可以慢慢滚，Esc 关）

  function hidePreview() {
    if (!PV.classList.contains('show')) return;
    PV.classList.remove('show');
    PV.innerHTML = '';
    pvNote = null;
    pvPinned = false;
  }

  function canvasPoint(evt) {
    const rect = canvas.getBoundingClientRect();
    return [evt.clientX - rect.left, evt.clientY - rect.top];
  }

  function buildPreviewHtml(note) {
    if (pvCache.has(note.id)) return pvCache.get(note.id);
    PV.innerHTML = '<div class="pv-crumbs"></div>' + note.preview +
      '<div class="pv-hint">单击标题圆固定预览（Esc 关闭）· Ctrl + 悬停临时预览 · 浮层内链接可点</div>';
    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(PV, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: '\\[', right: '\\]', display: true },
            { left: '$', right: '$', display: false },
            { left: '\\(', right: '\\)', display: false },
          ],
          throwOnError: false,
          ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
        });
      } catch (e) { /* 单个坏公式不该炸掉整个浮层 */ }
    }
    const html = PV.innerHTML;
    pvCache.set(note.id, html);
    return html;
  }

  function showPreviewFor(node, cx, cy, pinned) {
    const note = node.kind === 'note' ? node : NODE.get(node.note);
    if (!note || !note.preview) { hidePreview(); return; }
    if (pvNote !== note.id) {
      PV.innerHTML = buildPreviewHtml(note);
      pvNote = note.id;
    }
    pvPinned = !!pinned;
    hideTooltip();
    PV.classList.add('show');
    // 面包屑：滚深了也知道「哪篇笔记 › 哪一节」
    const crumbs = PV.querySelector('.pv-crumbs');
    if (crumbs) {
      crumbs.textContent = node.kind === 'heading'
        ? (note.label || note.id) + '  ›  ' + (node.label || '')
        : (note.label || note.id);
    }
    // 从这一节滚起：锚点是构建期给每个标题打的 id（拿不到就退回顶部）。
    // 注意要**给 sticky 面包屑让位** —— 只减 12px 的话，标题正好被面包屑盖住，
    // 看起来就是「预览里没有标题」（2026-10-24 实测踩到）。
    const anchorEl = node.anchor ? PV.querySelector('#' + node.anchor) : null;
    const crumbEl = PV.querySelector('.pv-crumbs');
    const crumbH = (crumbEl ? crumbEl.offsetHeight : 0) || 0;
    const padTop = parseFloat(getComputedStyle(PV).paddingTop) || 16;
    // offsetTop 是相对面板 border box 的（含 padding），sticky 面包屑又占住顶部，
    // 所以要让「padding + 面包屑 + 8px」这块空间：只减面包屑的话标题会被压住半截。
    PV.scrollTop = anchorEl ? Math.max(0, anchorEl.offsetTop - (padTop + crumbH + 8)) : 0;
    const w = PV.offsetWidth, h = PV.offsetHeight;
    let x = cx + 18, y = cy + 18;
    if (x + w > window.innerWidth - 12) x = cx - w - 18;
    if (y + h > window.innerHeight - 12) y = cy - h - 18;
    PV.style.left = Math.max(12, Math.min(x, window.innerWidth - w - 12)) + 'px';
    PV.style.top = Math.max(12, Math.min(y, window.innerHeight - h - 12)) + 'px';
  }

  function evalPreview(evt) {
    pvLast = [evt.clientX, evt.clientY];
    if (evt.target && evt.target.closest && evt.target.closest('#preview')) return;
    if (!ctrlDown) {
      // 固定预览（单击打开）只有 Esc / 点别处才收；普通移动不打断阅读
      if (!pvPinned) { hidePreview(); hintNode = null; }
      return;
    }
    const p = canvasPoint(evt);
    const node = R.hitTest(p[0], p[1]);
    if (!node) { if (!pvPinned) hidePreview(); hintNode = null; return; }
    if (node.kind === 'heading') {
      hintNode = null;
      if (!pvPinned) showPreviewFor(node, evt.clientX, evt.clientY, false);
      return;
    }
    // 固定预览中：随手划过别的圆不打断阅读
    if (pvPinned) return;
    // 文件夹 / 笔记：这一层还没有「标题」，没有可读的正文
    hidePreview();
    if (hintNode !== node.id) {
      hintNode = node.id;
      toast(node.kind === 'folder'
        ? '这一层是文件夹，还没到标题 —— 继续放大到标题圆'
        : '这是笔记本身，还没到标题 —— 继续放大到标题圆');
    }
  }

  window.addEventListener('mousemove', evalPreview, true);
  window.addEventListener('keydown', (evt) => {
    if (evt.key === 'Control' && !ctrlDown) {
      ctrlDown = true;
      R.setCtrlMode(true);
      if (pvLast) {
        const rect = canvas.getBoundingClientRect();
        const node = R.hitTest(pvLast[0] - rect.left, pvLast[1] - rect.top);
        if (node && node.kind === 'heading') {
          showPreviewFor(node, pvLast[0], pvLast[1], false);
        } else if (node) {
          // 光标已经停在文件夹/笔记圆上：按下 Ctrl 立刻给提示（不用等鼠标再动）
          hidePreview();
          hintNode = node.id;
          toast(node.kind === 'folder'
            ? '这一层是文件夹，还没到标题 —— 继续放大到标题圆'
            : '这是笔记本身，还没到标题 —— 继续放大到标题圆');
        }
      }
    }
  }, true);
  window.addEventListener('keyup', (evt) => {
    if (evt.key === 'Control') {
      ctrlDown = false;
      R.setCtrlMode(false);
      // 固定预览（Ctrl 悬停中单击打开的）不因松开 Ctrl 而消失 —— 否则长笔记没法读
      if (!pvPinned) hidePreview();
      hintNode = null;
    }
  });
  window.addEventListener('blur', () => { ctrlDown = false; R.setCtrlMode(false); if (!pvPinned) hidePreview(); });

  // 单击 = **把已经打开的预览固定住**（Ctrl 悬停中单击标题圆）。
  // 注意：不抢普通单击 —— 画布单击本来就是「选中节点」，侧栏/顶栏的点击更不能吞，
  // 所以只在预览已经开着、且点在画布上的标题圆时才接管。
  document.addEventListener('click', (evt) => {
    if (evt.target !== canvas) return;               // 侧栏/顶栏的点击不碰
    if (!PV.classList.contains('show')) return;      // 预览没开 → 单击照旧是选中
    const p = canvasPoint(evt);
    const node = R.hitTest(p[0], p[1]);
    if (node && node.kind === 'heading') {
      evt.preventDefault();
      evt.stopPropagation();
      showPreviewFor(node, evt.clientX, evt.clientY, true);
      return;
    }
    if (pvPinned) hidePreview();                     // 点别处 → 收掉固定预览
  }, true);

  // 预览状态（自动化回归 / 控制台排查用；挂在文件末尾的 window.KG 上）
  function pvState() {
    return {
      open: PV.classList.contains('show'),
      pinned: pvPinned,
      ctrl: ctrlDown,
      note: pvNote,
    };
  }

  // 浮层里的 [[链接]] 点击 → 选中目标（与画布上点圆一致）
  PV.addEventListener('click', (e) => {
    const wl = e.target.closest ? e.target.closest('.pv-wl[data-wl]') : null;
    if (!wl) return;
    e.stopPropagation();
    select(wl.dataset.wl, true);
  });

  // ── 事件绑定 ──────────────────────────────────────────────────────────
  function stepLevel(delta) {
    const lv = Math.max(1, Math.min(MAX_DEPTH, R.enterAt(R.camera.zoom) + delta));
    R.zoomToDepth(lv);
  }

  document.addEventListener('keydown', (evt) => {
    const tag = (evt.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select') {
      if (evt.key === 'Escape') {
        evt.target.blur();
        $('hits').style.display = 'none';
      }
      return;
    }
    // 方向键平移画布。放在 input/select 守卫之后，所以搜索框里按方向键仍然是移动光标。
    // 它不碰选中态 —— 这正是它存在的理由：看远处的连线时不必按住鼠标拖，也就不会因为
    // 一次不到 5px 的抖动被判成点击、把选中切到别的大父圆上，让想看的箭头被焦点过滤掉。
    const PAN = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const panDir = PAN[evt.key];
    if (panDir) {
      evt.preventDefault();                     // 别让浏览器把方向键当滚动/焦点移动
      const [vx, vy] = R.panStep(evt.shiftKey);
      R.panBy(panDir[0] * vx, panDir[1] * vy);
      return;
    }
    // Home = 回到默认视角。自由缩放之后「缩丢了」变得可能，键盘操作时不该逼人去摸鼠标。
    if (evt.key === 'Home') { evt.preventDefault(); R.resetView(); toast('已回到默认视角'); return; }
    if (evt.key === ']' || evt.key === '+' || evt.key === '=') stepLevel(1);
    else if (evt.key === '[' || evt.key === '-' || evt.key === '_') stepLevel(-1);
    else if (evt.key === 'Escape') { hidePreview(); select(null); hideTooltip(); }
    else if (evt.key === 'l' || evt.key === 'L') toggleLegend();
    else if (evt.key === '/' ) { evt.preventDefault(); $('search').focus(); }
    else if (evt.key === 'Enter' && $('search').value) runSearch($('search').value);
  });

  $('zoomin').addEventListener('click', () => stepLevel(1));
  $('zoomout').addEventListener('click', () => stepLevel(-1));
  $('reset').addEventListener('click', () => { R.resetView(); toast('已回到默认视角'); });
  $('search').addEventListener('input', (e) => runSearch(e.target.value.trim()));
  $('search').addEventListener('focus', (e) => { if (e.target.value.trim()) runSearch(e.target.value.trim()); });
  $('search').addEventListener('blur', () => setTimeout(() => { $('hits').style.display = 'none'; }, 180));
  $('search').addEventListener('keydown', (e) => { if (e.key === 'Enter') runSearch(e.target.value.trim()); });
  $('domain').addEventListener('change', (e) => { filterDomain = e.target.value; applyFilters(); });
  $('mastery').addEventListener('change', (e) => { filterMastery = e.target.value; applyFilters(); });
  $('labels').addEventListener('change', (e) => {
    const v = e.target.value;
    labelMode = v === 'all' ? 'on' : v === 'none' ? 'off' : 'auto';
    R.labelMode = labelMode;
  });
  $('edgemode').addEventListener('change', (e) => {
    edgeMode = e.target.value === 'agg' ? 'agg' : 'raw';
    R.edgeMode = edgeMode;
    writeStored('kg.edgeMode', edgeMode);
    applyEdgeLegend();
  });

  // ── 图例收起 / 展开 ────────────────────────────────────────────────────
  // 图例的说明文字很长（可见约 24 行），挡住画布左下角时可以折成一条。状态记进
  // localStorage，下次打开还是那个状态。**只切 .collapsed 类**，不碰
  // #legend-rel-agg / #legend-rel-raw 的 hidden —— 那两个属性归 applyEdgeLegend()
  // 管，是「当前连线模式用哪套图例」的状态，浏览器回归的 1c 段直接读它。
  function applyLegendCollapsed(collapsed) {
    $('legend').classList.toggle('collapsed', collapsed);
    const btn = $('legend-toggle');
    btn.textContent = collapsed ? '展开' : '收起';
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  function toggleLegend() {
    const next = !$('legend').classList.contains('collapsed');
    applyLegendCollapsed(next);
    writeStored('kg.legendCollapsed', next ? '1' : '0');
  }

  $('legend-toggle').addEventListener('click', toggleLegend);

  // ── 启动 ──────────────────────────────────────────────────────────────
  $('subtitle').textContent = META.note_count + ' 篇笔记 · ' + META.heading_total + ' 个标题';
  // 先把记住的连线模式灌进渲染器和下拉框，再建图例 —— 顺序反了会闪一下错的图例。
  R.edgeMode = edgeMode;
  $('edgemode').value = edgeMode;
  buildPills();
  buildLegend();
  applyEdgeLegend();
  // 图例收起状态：默认展开（老行为和截图基线都不变），只有用户自己收过才记住。
  applyLegendCollapsed(readStored('kg.legendCollapsed', '0') === '1');
  buildFilters();
  updateHud();

  setTimeout(() => toast('光标放在目标区域向上滚 = 逐层深入（学科 → 子学科 → 课程 → 笔记 → 知识点），向下滚 = 回到更粗的层级'), 700);

  // 调试 / 自动化验证入口 —— 也可以直接在浏览器控制台里用 KG.state() 查状态
  window.KG = {
    data: DATA,
    renderer: R,
    camera: R.camera,
    zMin: R.zMin,
    zMax: R.zMax,
    zHome: R.zHome,
    select: select,
    previewState: pvState,
    runSearch: runSearch,
    applyFilters: applyFilters,
    setLevel: (lv) => R.zoomToDepth(lv),
    zoomToDepth: (lv) => R.zoomToDepth(lv),
    revealOf: (id) => R.revealOf(id),
    alphaOf: (id) => R.alphaOf(id),
    enterAt: (z) => R.enterAt(z),
    visible: () => R.stats,
    state: () => ({
      zoom: Math.round(R.camera.zoom * 1000) / 1000,
      level: R.enterAt(R.camera.zoom),
      shownNodes: R.stats.nodes,
      // 真正按 PAINT_MIN 以上不透明度落了笔、且几何上穿过视口的节点数。
      // 判「视口是不是空的」要看它，不能看 shownNodes（那是候选集大小，可能含
      // 中心远在屏外的大圆 —— 那种圆候选集里有、屏幕上什么都没有）。
      painted: R.stats.painted,
      shownEdges: R.stats.edges,
      focusEdges: R.stats.focusEdges,
      focusNeighbors: R.stats.focusNeighbors,
      marks: R.stats.marks,
      chips: R.stats.chips,
      shownLabels: R.stats.labels,
      selected: R.selected,
      hovered: R.hover,
      search: searchQ,
      labelMode: labelMode,
      // 连线模式报的是渲染器的真值（而不是 app.js 自己的副本）：调试/自动化时
      // 可以直接改 window.KG.renderer.edgeMode，读数必须跟着变。
      edgeMode: R.edgeMode,
      filterSet: R.filterSet ? R.filterSet.size : null,
      camera: { zoom: R.camera.zoom, panX: R.camera.panX, panY: R.camera.panY },
    }),
  };
})();
