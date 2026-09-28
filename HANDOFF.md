# 交接文档 —— 知识笔记语义缩放可视化系统

> 写给接手「看图验证 + 改进优化」的编程智能体。先读这份，再读 `README.md`
> （§4 语义缩放机制、§8 关键实现决定是同一批内容的用户视角版本）。

---

## 0. 一句话现状

**用户的两个改进需求都已实现并提交**，数据侧与浏览器侧的自动校验全绿，截图已人眼验收过。
剩下的都是有意的待办（`annotations.yaml` 还是空的、候选边还没审核）。

改造前的旧版（Cytoscape + 省界轮廓 + 5 层离散 LOD + 坏掉的滚轮）已整体替换为
**Canvas2D 自绘 + 同心圆 10 层深度轴 + per-node 连续淡入淡出**。

提交链（本地仓库，**未 push，也不该 push**）：

```
ecdbf92  改造前基线：滚轮已知损坏
99164d0  止血：修复滚轮失效（wheel_step / level_span 幽灵配置键）
b9b0407  第 2 步：数据侧改造 —— 标题提升为一等节点、heading→heading 真边、等比半径 + reveal LOD
38c8764  第 3 步：渲染侧重写 —— canvas 自绘渲染器替换 Cytoscape
58a2e77  第 4 步：同步方案 —— sync-graph.ps1
(最新)   第 5 步：browser_check.py 入仓 + README/HANDOFF 重写
```

```bash
cd D:/obsidian_vault/knowledge-graph
python build.py build        # 生成 dist/knowledge-graph.html（约 8.7 MB 单文件）
python build.py verify       # 数据侧自动校验，应全绿
python browser_check.py      # 浏览器侧 52 项断言 + 截图，应全绿
python build.py watch        # 开发时挂上，改笔记/配置自动重建
```

依赖：`PyYAML`（已装）；`browser_check.py` 另需 `playwright`（已装，用 `channel="chrome"`
驱动本机 Chrome，**不需要下载 chromium**）。

---

## 1. 环境事实（别重复踩）

| 项 | 值 |
|---|---|
| 系统 | Windows，Bash 工具走 Git Bash（用 Unix 语法、正斜杠） |
| Python | 3.11.8，`PyYAML 6.0.3` |
| Node | v24.18.0（只用来 `node --check web/*.js` 做语法检查） |
| 浏览器 | 本机 Chrome（Playwright `channel="chrome"`） |
| vault | `D:/obsidian_vault/hush-ob-bucket`（**不要修改里面的笔记**） |
| 本项目 | `D:/obsidian_vault/knowledge-graph`（vault 同级，不在 vault 内） |
| 已有计划任务 | `Quartz Site Auto Sync`：每 30 分钟，从 :24 起算（:24 / :54） |

### 自动化看页面的正路（已换掉）

**直接用 `browser_check.py`。** 它用 Playwright `channel="chrome"`，
`page.goto("file:///D:/obsidian_vault/knowledge-graph/dist/knowledge-graph.html")` 就能开——
`file://` 对 Playwright 没有障碍（障碍只存在于**页面自己 fetch 本地文件**，而我们全内联了）。
截图落在 `%TEMP%\kg_*.png`（`KG_SHOT_DIR` 可改）。

```bash
python browser_check.py            # 全跑
KG_SHOT_DIR=/d/tmp python browser_check.py
```

**看完截图要用 ReadMediaFile 真的看一眼**，别只信断言全绿。当前这几张已验收：
`kg_01/02`（初始视角与放大）、`kg_04_sidebar.png`（侧栏面包屑+入边出边+标题清单）、
`kg_07_blank.png`（深层空白处兜底提示）、`kg_08_lod.png`（实心圆/细线边/标签/hover 气泡+图例）。

Kimi WebBridge（`http://127.0.0.1:10086`）作为备选保留，但它有两个坑：
扩展默认不能导航到 `file://`（要先在 `dist/` 起 `python -m http.server`），
且 Windows 下请求体必须写文件再 `curl.exe --data-binary "@文件"`（内联 JSON 里的中文会被 shell 破坏）。
**现在没有理由用它。**

### 页面内置调试入口

```js
KG.data / KG.renderer / KG.camera          // 内联 payload、渲染器、相机
KG.state()      // {zoom, level, shownNodes, shownEdges, shownLabels, selected, hovered, search, labelMode, filterSet, camera}
KG.visible()    // = renderer.stats
KG.setLevel(n) / KG.zoomToDepth(n)          // 跳到第 n 层（1..10）
KG.select(id) / KG.runSearch(q) / KG.applyFilters()
KG.revealOf(id) / KG.alphaOf(id) / KG.enterAt(z)
KG.zMin / KG.zMax / KG.zHome
// renderer 上还有：NODES byId hitTest minzoomOf descOf visibleLayerOf
//                   setZoom zoomBy focusOn tweenTo resetView
//                   hover selected filterSet matchSet labelMode centerScreen size
```

---

## 2. 文件职责

```
knowledge-graph/
├── config.yaml          ← 唯一维护入口：公开范围 / zoom / weight / candidates / layout / lod / theme
├── build.py             CLI：scan | suggest | build | verify | watch | all   （295 行）
├── verify.py            数据侧自动校验（断言式，无测试框架）                   （364 行）
├── browser_check.py     浏览器侧自动回归：52 项断言 + 截图                     （382 行）
├── sync-graph.ps1       计划任务包装：防重入 lock + UTF-8 + 日志裁剪 400 行     （47 行）
├── kg/config.py         配置加载与校验（非法配置给中文报错）
├── kg/scan.py           白名单 glob 扫描（include/exclude/exclude_notes）
├── kg/parse.py          frontmatter / 标题树（跳过代码块）/ wiki 链接 / 摘要
├── kg/graph.py          层级树、语义边、按层聚合边、标题级链接、reveal
├── kg/candidates.py     候选边挖掘（3 条启发式）
├── kg/layout.py         同心圆布局 + reveal/minzoom + `_apply_depth_floor` 深度封顶
├── kg/ioutils.py        stdout UTF-8（`setup_stdout()`）
├── kg/emit.py           输出 dist/graph.json 与自包含单文件 HTML
├── web/template.html    骨架 + CSS（顶栏/侧栏/画布/footer，footer 高 46px）
├── web/app.js           状态机、搜索过滤、侧栏、层级胶囊、事件绑定、window.KG
├── web/render.js        Canvas2D 渲染器：相机、淡入淡出、聚合边、拾取、标签竞争
├── annotations.yaml     用户手工标注（权重/掌握度/别名/手工边）—— **目前是空的**
├── candidates.yaml      候选边（待审核）
├── sync-graph.log/.lock 运行时产物，gitignore
└── dist/{graph.json, knowledge-graph.html}   构建产物，gitignore
```

数据流：vault → `kg/*` → `graph.json` → 内联进单文件 HTML → Canvas2D 自绘。
**`web/` 下三个文件在构建时被完整内联**，改完必须重跑 `build.py build` 才生效。

---

## 3. 已实测验证的部分

### 构建摘要（当前数据）

```
文件夹 35 / 笔记 107 / 标题 3339  →  共 3481 个节点
深度轴 10 层（文件系统本身 5 层 + 标题层级）
语义边 92 条 / 层级包含边 3475 条
标题级链接 66 处命中（锚点未命中 12 处）
圈半径：300 → 510 → 867 → 1474 → 2506 → 4260 → 7241 → 12310 → 20927 → 35576
HTML 8713 KB
```

扫描侧：vault 内 `.md` 共 133 篇、纳入 107、排除 26；笔记所在层 `{2:9, 3:40, 4:54, 5:4}`；
`[[链接]]` 735 = 附件 652 + 笔记→笔记 40 + 自链接 42 + 解析失败 1（`[[My tech log]]`）。

**深度轴的定义**：`heading.depth = 所属笔记 depth + 标题级别`（`kg/graph.py:157`）。
所以 depth 6..10 不是固定的「h1..h5」，而是「笔记深度 + 标题级别」的连续展开——
放在深层文件夹里的笔记，它的标题也自然更深。这比用户原话里那条固定 10 级列表更自洽。

### 浏览器实测

| 项 | 实测 | 备注 |
|---|---|---|
| 初始视角 | zoom 0.29 / level 4 / 节点 232 / 边 34 / 标签 65 | 视口裁剪后的真实绘制数 |
| 标签三模式 | auto 65 → off 0 → on 66 → 回 auto 65 | |
| `zMin` 视角 | 节点 6 / 边 1 / 标签 1 | 只剩顶层学科，见 §10 已知限制 |
| 逐层扫描标签数 | 2, 2, 16, 62, 74, 30, 12, 0, 0 | depth 5 附近是拥挤峰 |
| 搜索 | 16 命中 | |
| 学科过滤 | 232 → 22 | |
| 双击空白回 home | 0.1540 → 0.2900 | |
| 帧率 | 62 fps | |
| 20 格滚轮 | 1090 ms | 含淡入淡出重绘 |
| console error / pageerror | 0 | |
| `browser_check.py` | **52 [ok] / 0 FAIL** | 跑过两次，均全绿 |

`python build.py verify` → `✓ 全部自动校验通过`。

### 截图人眼验收结论

- 所有层级都是**不同颜色的实心圆**，语义边是细线，标签清晰不糊。
- hover 气泡 + 图例正常；侧栏详情的面包屑、入边、出边、标题清单都完整。
- 深层空白处有兜底提示：「此处没有内容 · 向下滚回到更粗的层级，或双击空白处回到默认视角」。
- 边上的 `.tag` 悬浮说明同时给出**类型**与**来源**
  （`wiki` / `annotation` / `frontmatter` / `candidate` / `hierarchy` / `mixed`）。

---

## 4. 必须知道的坑（不读会重犯）

1. **单文件必须全内联。** Chrome 在 `file://` 下禁止页面自己 `fetch`/XHR 读本地文件。
   不要为了「减小体积」把数据改成外链 JSON——那会让双击打开直接失败。
   注意这跟 Playwright 能不能打开 `file://` 是两件事，后者没问题。

2. **`<canvas>` 是替换元素。** CSS 必须 `width:100%; height:100%`，
   同时 JS 里把 `canvas.width/height` 设成设备像素（含 devicePixelRatio）。
   缺一半就会模糊、或尺寸与命中测试错位。

3. **相机 tween 每一帧都必须回调 `onCamera`。** 漏了就是「动画期间画布不重绘」，
   看起来像卡死。`browser_check.py` 用连续两帧快照比对来兜这类问题。

4. **换层从不反向改相机 —— 连续派生才安全。**
   `enter[]` 只在「向更细方向」用；向粗方向走时保留用户当前相机。
   旧版那条「换层后自动适配视角」叠上连续 zoom 会形成正反馈震荡，
   **别顺手加回去**。

5. **同一圈的疏密与半径无关。** 屏幕上相邻节点间距 ≈ 视口半径 × Δθ，只跟角度分配有关。
   「太挤」要调 `layout.angle_power`（角度按子树规模的次线性权重），
   「圈与圈分不开」才调 `layout.ring_ratio`。
   **从「想要的 min_gap」反解半径是范畴错误**——早期版本就是这么绕进死胡同的。

6. **「让每圈刚好适配视口」不能用来定义层级。** 由 `2πR/N` 反推 zoom 会让
   「层级」变成「节点数的函数」，加一篇笔记就整张图跳。
   正解是 per-node `reveal` → `minzoom = lod.min_px / reveal`。

7. **同心圆与地图不同构。** 地图把细节编码成**尺度**，同心圆把深度编码成**半径**。
   光有 `reveal` 不能保证「放大 = 更深」，必须再叠一层按深度的单调封顶
   （`kg/layout.py` 的 `_apply_depth_floor`）。

8. **`parent_dim` 压暗与标签门槛不能共用一个 alpha。**（踩过的 bug C）
   祖先层被压到 0.5 后永远够不到 0.55 的标签门槛，结果最粗视图一个标签都没有。
   标签门槛必须读**未被压暗的淡入进度**，这就是 `lod.label_alpha` 存在的理由。

9. **`reveal` 必须沿包含链取前缀最小值。** 否则会出现「子节点已浮现、父节点还没浮现」
   的空心结构。

10. **`parse.py` 有意不排除行内代码里的 `[[Foo]]`。** 会多出少量假链接，
    但排除行内代码会连带干掉大量正文里合法的链接写法。别"修"它。

11. **历史坑（Cytoscape 已删，仅备忘）：** `rendered = model × zoom + pan`；
    节点 `data` 里出现 `parent` 键会被当成复合节点重算全部坐标（当时用 `parentId`）；
    `cy.$('#id')` 是子串匹配不是精确匹配。

12. **Shell 侧：** Bash heredoc 写中文会乱码 → 用 Write 写临时文件再 `git commit -F`；
    Python 打印中文前要 `sys.stdout.reconfigure(encoding='utf-8')`（`kg/ioutils.py` 已封装）；
    PowerShell 全路径 `/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`；
    `schtasks` 在 Git Bash 下参数要双斜杠（`//Query`）；
    `grep -c` 零匹配返回 exit 1，会让命令链尾部报 "failed" 但其实无害。

---

## 5. 调参地图

### `config.yaml`

| 想改什么 | 键 |
|---|---|
| 公开范围 | `include` / `exclude` / `exclude_notes` |
| 滚轮手感 | `zoom.wheel_step`（1.12） |
| 换层/跳转动画时长 | `zoom.transition_ms`（260） |
| 子节点浮现后父节点压暗到多少 | `zoom.parent_dim`（0.5） |
| 缩放上下界的余量 | `zoom.zoom_in_ceiling`（1.35）/ `zoom.zoom_out_floor`（0.9） |
| 链接权重 | `weight.wiki_link` 1.0 / `heading_link_bonus` 0.5 / `embed_factor` 0.6 / `annotation_default` 3.0 |
| 边的来源优先级 | `precedence: [annotation, frontmatter, wiki]` |
| 圈半径起点 / 圈间倍率 | `layout.base_radius`（300）/ `layout.ring_ratio`（1.7） |
| **同圈疏密** | `layout.angle_power`（0.5，越小越平均、越大越偏向大子树） |
| 起算角度 | `layout.start_angle`（-90） |
| **浮现早晚（最小屏幕间距）** | `lod.min_px`（6） |
| 淡入带宽 | `lod.fade_span`（1.35） |
| 标签参与竞争的门槛 | `lod.label_alpha`（0.55） |
| 弱聚合边压暗阈值 | `lod.weak_edge_min_count`（2） |
| 学科配色 / 边配色 | `theme.domains` / `theme.fallback` / `theme.edges` |
| 候选边挖掘松紧 | `candidates.min_score` 0.45 / `min_term_len` 4 / `max_doc_freq_ratio` 0.25 / `min_shared_terms` 2 / `max_suggestions` 400 / `generic_headings` |

### `web/render.js` 顶部常量

| 常量 | 值 | 作用 |
|---|---|---|
| `FOOTER_H` | 46 | 必须与 `template.html` 里 `#footer` 高度一致，否则中心点偏 |
| `HIT_CELL` | 64 | 拾取网格边长（屏幕像素） |
| `LABEL_CELL` | 24 | 标签碰撞网格边长 |
| `LABEL_BUDGET` | 400 | 每帧最多考虑多少个标签候选 |

---

## 6. 待办清单（按建议顺序）

**P0 — 已完成**：看图验收 + 两个改进需求（同步方案、实心圆/细线/跨层级链接淡入淡出）。

**P1 — 让「掌握度/重要度」真正起作用**
`annotations.yaml` 是空的，107 篇笔记 `mastery` 全是 0，白色描边看不出来。
可选：提示用户填几条；或做 `build.py suggest-annotations`，按「标题数 / 链接数 / 行数」
给出初始 `weight` 建议草稿供人工审核。**绝对不要自动写进用户的笔记。**

**P2 — 候选边审核流程**
`candidates.yaml` 手工改 `status` 很累。可在页面里加「审核模式」：列出候选边，
点 accept/reject 后**导出 YAML 文本**给用户自己粘回文件（保持工具不写用户文件的边界）；
或写 `build.py review` 交互式命令行逐条确认。

**P3 — 规模压测**
当前 3481 节点、62fps。没测过上限。可做：临时放宽 `include` 到全 vault（含 Logs/Excalidraw）；
或造 1 万节点合成数据测深层渲染与拾取。已知热点是标签竞争与聚合边重建。

**P4 — 语义质量**
- **12 处 `[[笔记#标题]]` 锚点未命中**：Obsidian 的锚点匹配更宽松。
  放宽逻辑在 `kg/graph.py` 的 `_normalize_heading()`。先打印出这 12 处看看是什么再决定。
- **中文不分词**，候选边只覆盖英文术语与 LaTeX 符号。引入 jieba 是新增依赖，需先问用户。
- **`derives` 方向语义模糊**：可在侧栏加「改这条边的类型」并导出 `annotations.yaml` 片段。

**P5 — 可选：统一公开范围定义**
`quartz-setup/` 里那份（junction `Study/`、`Tech/`）已失效，那两个目录在当前 vault 里不存在。
若想让 Quartz 发布与图谱共用一份 `include`，需单独确认后再动。

---

## 7. 明确不要做的事

- **不要修改 vault 里的任何笔记**（含批量注入 frontmatter）。标注走 `annotations.yaml`。
- 不要动 `.obsidian/`；**不要读 `Utilities/API Key.md`**（敏感凭证）；
  不要碰 `remotely-save` 的加密配置。
- 不要 `git push`（本项目是本地仓库；vault 那边由 obsidian-git 自己备份）。
- **不要替用户注册/删除 Windows 计划任务**——把 `schtasks` 命令给用户，让他自己执行。
- 不要把 `dist/` 当源码维护，它是构建产物，可随时重建（已 gitignore）。
- 不要把「自动校验全绿」当作「视觉没问题」。这两件事无关，必须自己看截图。
- 不要在没跟用户确认的情况下新增第三方依赖（前端尤其：现在**零**运行时依赖）。

---

## 8. 回归基准（改坏了怎么发现）

```bash
python build.py build      # 笔记 107 / 文件夹 35 / 标题 3339 / 节点 3481
                           # 深度轴 10 / 语义边 92 / 包含边 3475 / 标题级链接 66（未命中 12）
python build.py verify     # 必须 ✓ 全部自动校验通过
python browser_check.py    # 必须 52 [ok] / 0 FAIL / ALL BROWSER CHECKS PASSED
node --check web/app.js && node --check web/render.js   # 前端语法
```

浏览器里再确认（数字应与 §3 的表一致）：

```js
KG.state()                 // zoom 0.29 / level 4 / shownNodes 232 / shownEdges 34 / shownLabels 65
KG.renderer.setZoom(KG.zMin); KG.visible()   // nodes 6 / edges 1 / labels 1
```

改完视觉**必须重新截图并人眼看**：`python browser_check.py` 后 ReadMediaFile `%TEMP%\kg_0*.png`。
