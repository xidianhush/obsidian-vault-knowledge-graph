# 交接文档 —— 知识笔记语义缩放可视化系统

> 写给接手「看图验证 + 改进优化」的编程智能体。先读这份，再读 `README.md`
> （§4 语义缩放机制、§8 关键实现决定是同一批内容的用户视角版本）。

---

## 0. 一句话现状

**布局重构（同心环 → circle packing）与用户的四条新要求都已实现并提交**，数据侧
（`build.py verify`）与浏览器侧（`browser_check.py`，53 项断言）自动校验全绿，截图人眼复看过。
剩下的都是有意的待办（`annotations.yaml` 还是空的、候选边还没审核）。

图现在是 **Canvas2D 自绘 + circle packing 嵌套圆 + 10 层深度轴 + per-node 连续淡入淡出**：
深度 = 嵌套层数，规模 = 圆半径，子圆严格落在父圆内部、兄弟圆互不相交。LOD 退化成一个公式
`minzoom = lod.min_px / r`。

本轮的需求来源是用户这四条要求，对应实现：

| 要求 | 实现 |
|---|---|
| 同级里包含内容多的元素，圆应该更大 | 目标半径 ∝ 子树**叶子数** ^ `layout.size_exponent`(0.5) |
| 不同层级间大小要有区分（文件夹 > 笔记 > 标题；h1 > h4） | `layout.level_ratio`(1.5) 硬上界：父圆半径 ≥ 最大子圆 × 1.5。这是**包含式分档**，不是全局按深度分档——理由见 `kg/layout.py` 开头 docstring |
| 子元素落在父元素圆内，且颜色一致 | packing 构造保证（verify 实测：包含越界 0 个 / 兄弟相交 0 对）+ 同 `domain` 配色 + `mixWhite(0.4)` 描边把父子分开 |
| 类比地图：放大时省级淡出、市级界线淡入 | `alphaOf` smoothstep 逐节点淡入淡出 + `fillAlphaOf` 把父圆填充压暗到 `zoom.parent_dim`(0.22) + wash 趟的 `maxzoom`（父圆铺满视口就停画填充，只留界线弧） |

改造前的两版都已整体替换：最早那版（Cytoscape + 省界轮廓 + 5 层离散 LOD + 坏掉的滚轮），
以及后来的同心环版（每个深度摊在一圈圆周上 + 三个 LOD 补丁函数）。同心环时代的
`_reveal` / `_clamp_to_ancestors` / `_apply_depth_floor` 与 `layout.base_radius` / `ring_ratio` /
`angle_power` / `min_gap` **全部已删除**，别照着旧文档去找（备忘见 §4.15）。

提交链（本地仓库，**未 push，也不该 push**）：

```
ecdbf92  改造前基线：滚轮已知损坏
99164d0  止血：修复滚轮失效（wheel_step / level_span 幽灵配置键）
b9b0407  第 2 步：数据侧改造 —— 标题提升为一等节点、heading→heading 真边、等比半径 + reveal LOD
38c8764  第 3 步：渲染侧重写 —— canvas 自绘渲染器替换 Cytoscape
58a2e77  第 4 步：同步方案 —— sync-graph.ps1
ec76210  第5步：文档重写 + 浏览器回归套件入仓
a71a929  第 6 步：布局重构 —— 同心环 → circle packing（Python 侧）
44a1c4f  第7步：渲染侧适配 circle packing —— 世界半径 + 四趟绘制 + wash 的 maxzoom
2e1d0e9  第8步：浏览器回归套件适配 circle packing + 顶栏/hover 打磨
```

```bash
cd D:/obsidian_vault/knowledge-graph
python build.py build        # 生成 dist/knowledge-graph.html（单文件，实测 8702 KB ≈ 8.5 MB）
python build.py verify       # 数据侧自动校验，应全绿
python browser_check.py      # 浏览器侧 53 项断言 + 截图，应全绿
python build.py watch        # 开发时挂上，改笔记/配置自动重建
```

**`python build.py` 不带子命令只跑 scan、不写 dist** —— 重建必须写 `build`。
改了 `web/*.js` 或 `web/template.html` **必须重建 dist 再跑 `browser_check.py`**：这三个文件在
构建时被完整内联，不重建等于没改。这两条本轮真踩过。

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
| 本项目计划任务 | `sync-graph.ps1`，每 30 分钟从 :07 起算（:07 / :37）——与上面那个错开 17 分钟避免撞车。**注册/取消命令给用户自己执行**（见 §7） |

### 自动化看页面的正路（已换掉）

**直接用 `browser_check.py`。** 它用 Playwright `channel="chrome"`，
`page.goto("file:///D:/obsidian_vault/knowledge-graph/dist/knowledge-graph.html")` 就能开——
`file://` 对 Playwright 没有障碍（障碍只存在于**页面自己 fetch 本地文件**，而我们全内联了）。
截图落在 `%TEMP%\kg_*.png`（`KG_SHOT_DIR` 可改）。

```bash
python browser_check.py            # 全跑
KG_SHOT_DIR=/d/tmp python browser_check.py
```

**看完截图要用 ReadMediaFile 真的看一眼**，别只信断言全绿。本轮人眼复看过
`kg_01_home.png`（home 视角）与 `kg_07_blank.png`（空白兜底提示），此前看过
`kg_02_zmin.png`（地板处六个学科根）、`kg_03_up16/30/48.png`（48 格上滚的中间态与天花板）。
其余截图对应判据：`kg_03_up05`（上滚第 5 格）、`kg_04_sidebar.png`（点节点后的侧栏面包屑+
入边出边+标题清单）、`kg_05_search.png`（搜索命中列表）、`kg_06_final.png`（双击空白回 home）、
`kg_08_lod.png`（放大后目标子树解锁）。

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

`KG.revealOf(id)` 现在是 **`r`（世界半径）的兼容别名**——payload 字段早已从 `reveal` 改名成
`r`（`rings` 也改名成 `layers`），这个函数名留着只是为了不打断旧脚本，返回的就是 `n.r`。
`KG.zMin / KG.zMax / KG.zHome` 照旧。

---

## 2. 文件职责

```
knowledge-graph/
├── config.yaml          ← 唯一维护入口：公开范围 / zoom / weight / candidates / layout / lod / theme
├── build.py             CLI：scan | suggest | build | verify | watch | all   （303 行）
├── verify.py            数据侧自动校验（断言式，无测试框架）                   （460 行）
├── browser_check.py     浏览器侧自动回归：53 项断言 + 截图                     （468 行）
├── sync-graph.ps1       计划任务包装：防重入 lock + UTF-8 + 日志裁剪 400 行     （47 行）
├── kg/config.py         配置加载与校验（非法配置给中文报错）                    （174 行）
├── kg/scan.py           白名单 glob 扫描（include/exclude/exclude_notes）       （93 行）
├── kg/parse.py          frontmatter / 标题树（跳过代码块）/ wiki 链接 / 摘要     （186 行）
├── kg/graph.py          层级树、语义边、按层聚合边、标题级链接                   （464 行）
├── kg/candidates.py     候选边挖掘（3 条启发式）                                （302 行）
├── kg/layout.py         circle packing 布局 + 世界半径 r / minzoom              （435 行）
│                        ↑ 开头 docstring 是布局的权威叙述，改布局前先读它
├── kg/ioutils.py        stdout UTF-8（`setup_stdout()`）                        （18 行）
├── kg/emit.py           输出 dist/graph.json 与自包含单文件 HTML                 （66 行）
├── web/template.html    骨架 + CSS（顶栏/侧栏/画布 + 右下角绝对定位的 `#footer`）（206 行）
├── web/app.js           状态机、搜索过滤、侧栏、层级胶囊、事件绑定、window.KG     （551 行）
├── web/render.js        Canvas2D 渲染器：相机、四趟绘制、聚合边、拾取、标签竞争   （882 行）
├── annotations.yaml     用户手工标注（权重/掌握度/别名/手工边）—— **目前是空的**
├── candidates.yaml      候选边（待审核）
├── sync-graph.log/.lock 运行时产物，gitignore
└── dist/{graph.json, knowledge-graph.html}   构建产物，gitignore
```

`#footer` 是**右下角绝对定位块**（`right:12px; bottom:12px`，没有写死高度）。
`web/render.js` 顶部的 `FOOTER_H = 46` 是另一回事：canvas 的**底部预留带**，
内容视口按 `H - FOOTER_H` 算（适配半径、`farCornerDist` 都用它）——template.html 第 27 行
注释说明了这两者的约定关系。

数据流：vault → `kg/*` → `graph.json` → 内联进单文件 HTML → Canvas2D 自绘。
**`web/` 下三个文件在构建时被完整内联**，改完必须重跑 `build.py build` 才生效。

---

## 3. 已实测验证的部分

### 构建摘要（当前数据）

```
文件夹 35 个 / 笔记 108 篇 / 标题 3339 个  →  共 3482 个节点
深度轴 10 层（文件系统本身 5 层 + 标题层级）
语义边 92 条 / 层级包含边 3476 条 / 图上 heading→heading 语义边 3024 条
标题级链接 66 处命中（锚点未命中 12 处）
布局根半径 layout_root_radius = 1000.0；标称视口半径 nominal_fit_radius = 427px
home 停在第 1 层，home_zoom = 0.4612
HTML 8702 KB
```

六个学科根的世界半径 `r`（**spread 16.22×**——这是自顶向下等比缩放 + `size_exponent` 0.5
钉出来的，自底向上打包会到 79.6×，见 `kg/layout.py` docstring）：

```
Science and Tech                   717.20
Projects                           171.99
Literature History Philosophy       89.82
Economy and Finance                 74.99
Interest                            69.92
Medical and Health                  44.22     ← zMin 由它决定
```

每层 `r` 中位数与 `enter`（该层的解锁门槛 zoom）：

```
层    节点数    r中位    r最小    r最大    minzoom中位    enter
 1      6      82.40    44.22   717.20      0.2202     0.2202
 2     22      21.89    10.31   391.18      0.8251     0.8251
 3     63      18.03     6.74   173.70      0.9984     0.9984
 4    193       9.83     4.50    64.28      1.8316     1.8316
 5    558       3.83     3.00    41.15      4.7023     4.7023
 6    939       2.54     1.87    16.08      7.1000     7.1000
 7    862       1.68     1.22     9.23     10.7031    10.7031
 8    585       1.16     0.83     4.33     15.5467    15.5467
 9    212       0.80     0.54     1.90     22.5071    22.5071
10     42       0.51       —        —          —      35.329
```

缩放轴：`zMin = 0.4274`（最小根 × `zoom_out_floor` 1.05）、`zMax = 66.3753`（最挤节点
minzoom × `zoom_in_ceiling` 1.35）、`zHome = 0.4612`（`home_fit` 1.08）。总跨度 155×，
`wheel_step` 1.12 ⇒ **约 45 格滚轮走完 10 层**。

扫描侧：vault 内 `.md` 共 134 篇、纳入 108、排除 26；文件夹 35 个，最大深度 5；
笔记所在层 `{2:9, 3:40, 4:55, 5:4}`；`[[链接]]` 735 = 附件 652 + 笔记→笔记 40 + 自链接 42 +
解析失败 1（`[[My tech log]]`）；标题 3339 个，平均 30.9 个/篇，无标题笔记 16 篇；
带 frontmatter 3 篇（`nep笔试题` / `nep面试` / `Linear Algebra`）；
`annotations.yaml` 0 篇笔记、0 条边（仍是空的）。

**深度轴的定义**：`heading.depth = 所属笔记 depth + 标题级别`（`kg/graph.py:157`）。
所以 depth 6..10 不是固定的「h1..h5」，而是「笔记深度 + 标题级别」的连续展开——
放在深层文件夹里的笔记，它的标题也自然更深。这比用户原话里那条固定 10 级列表更自洽。

### 浏览器实测

| 项 | 实测 | 备注 |
|---|---|---|
| home 初始视角 | zoom 0.4612 / level 1 / 节点 55 / 边 24 / 标签 26 | 画布非底色采样点 3936（判据 >50） |
| 标签三模式 | auto 26 → off 0 → on >0 → 回 auto 26 | `on` 另受每帧 400 条预算限制 |
| 20 格下滚到地板 | zoom 命中 `zMin` 0.4274 / level 1 | 6 个学科根全部可见，shownNodes 落在 40..120 |
| 48 格上滚到顶 | zoom 66.3750 / level 10 / 节点 1 | zoom 与 level 全程单调，无 NaN |
| 天花板中心 → 平移 (290,65) | shownNodes 1 → 0 | 兜底提示像素 [89,95,109]，与底色 [15,17,22] 可区分 |
| 双击屏上最小圆 | zoom 1.0480 → 22.7850 | |
| 双击空白（先把视口拖出所有内容） | level 1 / zoom 0.4610 | vs `zHome` 0.4612，容差 2% |
| 搜索「微分方程」 | 16 命中 | |
| 学科过滤 | shownNodes 55 → 2 | 取消过滤后回到 55 |
| 同屏圆数峰值 | 134 | 常数上界 `(视口半径/min_px)²`，见 §4.5 |
| 单格滚轮最大涌入 | 18% | 同心环时代是 66% 齐刷刷弹出 |
| 帧率 | idle rAF 58~63 fps | |
| 20 格滚轮 | 1092 ms | 含淡入淡出重绘 |
| console error / pageerror | 0 | |
| `browser_check.py` | **53 [ok] / 0 FAIL** | ALL BROWSER CHECKS PASSED |

`python build.py verify` → `✓ 全部自动校验通过`。其中最该盯的几条：
3482 个节点里坐标重合的 355 对**全是父子关系**（独子链同心；非父子重合 0 对）；
包含越界 0 个；父半径 < 子半径 × 1.5 的 0 个；6639 对兄弟圆重叠 0 对；
`r` 沿包含链严格递减（违反 0 个）；343 条独子链的父子半径比精确落在 1.500；
3741 条聚合边的 `minlayer` 都等于它首次出现的层级（不符 0 条）；
`home_layer=1` 确实是 `home_zoom=0.4612` 下已解锁的最深一层。

### 截图人眼验收结论

- **嵌套圆成立**：父圆套着子圆，内容处处填充，没有同心环时代那个空洞的圆心。
- **父子同色但分得清**：子圆继承所属学科的 `domain` 色，靠 `mixWhite(0.4)` 的描边划出界线；
  已经有孩子浮现的父圆退化成压暗的浅色面（wash 趟）+ 一条清晰界线弧——「省 = 浅色面、
  市 = 清晰界线」。
- **深缩放不再有整屏平蓝**：铺满视口的父圆停画填充、只留还没铺满的最内层圆当界线弧。
- 语义边是细线，标签清晰不糊；hover 气泡 + 图例正常；侧栏详情的面包屑、入边、出边、
  标题清单都完整。
- **顶栏在 1440px 下保持单行**，brand 不折行（宁可 `#readout` 折两行）。
- 深层空白处有兜底提示：「此处没有内容 · 向下滚回到更粗的层级，或双击空白处回到默认视角」，
  同时 tooltip 仍显示所在的「省」（有意为之，见 §4.10）。
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

5. **packing 下的密度账：同屏圆数有常数上界，别再想着「调疏密」。**
   浮现的圆两两不相交、且屏幕半径 ≥ `lod.min_px`，于是
   `同屏圆数 ≤ (视口半径 / min_px)²`——实测峰值 134 个。同心环时代这笔账根本算不平：
   同一圈的相邻间距 ≈ 视口半径 × Δθ，只跟角度分配有关、跟半径无关，所以「把某圈撑大」
   丝毫改善不了它自己的疏密（光第 6 层就有 939 个节点）。packing 下这 939 个节点分散在
   各自的父圆里，只有放大到对应父圆时才出现，同屏数被 `min_px` 钉成常数。
   三个旋钮各管一件事，别串着用：`layout.level_ratio` 管**层级间的缩放跨度**、
   `lod.min_px` 管**同屏圆数上限**（也就是「多小算看不见」）、
   `layout.padding` 管**兄弟圆之间的留白**（它同时是 `zoom.home_fit` 的硬上限）。

6. **「让每层刚好适配视口」不能用来定义层级。** 由节点数反推 zoom 会让
   「层级」变成「节点数的函数」，加一篇笔记就整张图跳。这条教训与布局无关，换 packing
   之后照样成立。正解是 per-node 门槛：**`minzoom = lod.min_px / r`**，`r` 是节点自己的
   世界半径（构建期一次算定，渲染期不重算）。

7. **为什么换 packing —— 而且别再往回加深度门控补丁。**
   同心环把深度编码成**半径**，地图把细节编码成**尺度**，两者不同构：光有 per-node 门槛
   也保证不了「放大 = 更深」，所以旧版必须再叠一层按深度的单调封顶（`_apply_depth_floor`），
   代价是「同心圆的圆心是空的」「缩到 `zMin` 只剩 6 个节点」这两条当时只能写进已知限制的
   毛病——packing 下两条都不再成立（见 §3 的截图结论与 §8 的 `setZoom(KG.zMin)` 判据）。
   **结论已经反转**：circle packing 与地图同构
   （深度 = 嵌套层数、规模 = 半径），子圆严格落在父圆内部且半径更小 ⇒ `minzoom` 沿包含链
   严格递增 ⇒ 单调性是**几何构造出来的**，不需要任何补丁。`_apply_depth_floor` 已删。
   如果哪天你发现自己在写「按 depth 限制可见性」的代码，停下来——那说明布局的包含性被破坏了，
   去修布局，不要加门控。

8. **`parent_dim` 压暗与标签门槛不能共用一个 alpha。**（踩过的 bug C）
   祖先层被压暗后永远够不到 0.55 的标签门槛，结果最粗视图（最该有标签的视图）一个标签都没有。
   标签门槛必须读**未被压暗的淡入进度**，这就是 `lod.label_alpha` 存在的理由。
   packing 下 `parent_dim` 的角色还更重了：**父圆填充是子圆的「底色」**，
   0.5 会把同色的子圆整体压暗吃掉，0.22 才留得住「省 = 浅色面、市 = 清晰界线」的层次。
   对应的函数是 `render.js` 的 `fillAlphaOf`——它和 `alphaOf` 的区别是压暗跟着**最先浮现的
   那个孩子**同步渐变，而不是一次性跳变（跳变会让父圆在中间态变成不透明色块）。

9. **`r` 沿包含链严格递减——这条现在是布局构造保证的，不用你人为维护。**
   旧版要靠 `_clamp_to_ancestors` 把 reveal 沿链取前缀最小值，否则会出现「子节点已浮现、
   父节点还没浮现」的空心结构。packing 下父圆必须装下子圆还要 ×`level_ratio`，
   半径天然严格更大，`minzoom` 天然严格递增（verify 实测违反 0 个），那个函数已删。
   **但如果将来你要改布局（换算法、加约束、改半径分配），这是首先要重新验证的不变量**——
   它一破，「放大 = 更深」和「子在父内」会一起崩。

10. **`hitTest` 有意保留已停画的祖先——别「修」它。**
    圆铺满视口后 wash 趟会停画它的填充（地图瓦片的 `maxzoom` 语义），但节点**仍留在
    `lastDrawn` 里**供命中测试与标签。效果就是：点圆之间的空隙 = 选中所在的那个「省」，
    tooltip 显示所在省。这**不是 stale bug**，是地图的做法（空白海域也标省名）。
    验收时我差点把它当成「命中测试没跟上重绘」误判掉。

11. **父子同色，必须靠 `mixWhite(0.4)` 的描边区分。** 用户要求 3 明确要「子元素与父元素
    颜色一致」，所以整条包含链共用一个学科色。没有那道描边，嵌套圆就是一片同色糊，
    看不出任何层级。改配色时**别给子节点单独配色**去「解决这个问题」。
    顺带：独子链会让父子**同心**（`verify` 里 355 对坐标重合全是这种，非父子重合 0 对），
    全靠 `level_ratio` 1.5 的半径差 + 这道描边才没塌成看不出的靶环——看到同心圆别当成 bug。

12. **顶栏 brand 必须 `white-space:nowrap; flex:0 0 auto`。** 否则 1440px 宽度下 brand
    会折成三行顶破 46px 的顶栏。空间不够时宁可让 `#readout`（`min-width:0; flex:0 1 auto`）
    折两行，也不许挤压 brand。`#search` 固定 150px、`#levelbar` `flex:0 0 auto` 同理。

13. **`parse.py` 有意不排除行内代码里的 `[[Foo]]`。** 会多出少量假链接，
    但排除行内代码会连带干掉大量正文里合法的链接写法。别"修"它。

14. **历史坑（Cytoscape 已删，仅备忘）：** `rendered = model × zoom + pan`；
    节点 `data` 里出现 `parent` 键会被当成复合节点重算全部坐标（当时用 `parentId`）；
    `cy.$('#id')` 是子串匹配不是精确匹配。

15. **历史坑（同心环布局已删，仅备忘）：** 半径 = `base_radius × ring_ratio^(L-1)`，
    角度按子树规模的次线性权重（`angle_power`）分配，`min_gap` 是想要的屏幕间距。
    那个模型里半径只能用来**分圈**，压根不携带子树规模的信息——把某圈半径撑大丝毫不能
    改善该圈自己的疏密（「从想要的 min_gap 反解半径」是范畴错误，早期版本就是这么绕进
    死胡同的）。LOD 靠 `_reveal` / `_clamp_to_ancestors` / `_apply_depth_floor` 三个补丁硬凑。
    **这些配置键和函数都已不存在**，`grep` 不到是正常的；payload 字段也从 `reveal` / `rings`
    改名成了 `r` / `layers`。

16. **Shell / 工具侧：** Bash heredoc 写中文会乱码 → 用 Write 写临时文件再 `git commit -F`；
    Python 打印中文前要 `sys.stdout.reconfigure(encoding='utf-8')`（`kg/ioutils.py` 已封装）；
    Git Bash 的 `/d/…` 路径 Windows python 不认，Python 代码里要写 `D:/…`；
    Read 工具带 `line_offset` 会报 "must be integer" 假错 → 改用 `sed -n 'A,Bp'`；
    `node --check` 一次只查一个文件；
    PowerShell 全路径 `/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`；
    `schtasks` 在 Git Bash 下参数要双斜杠（`//Query`）；
    `grep -c` 零匹配返回 exit 1，会让命令链尾部报 "failed" 但其实无害。
    构建侧那两条（`build.py` 不带子命令只 scan、改 `web/` 必须重建 dist）见 §0。

17. **半径是「相对父节点分到的份额」，不是「绝对内容量」——别拿跨分支的圆比大小。**
    深层两个叶子数相同的节点，半径可以差几倍，取决于各自路径上的累积缩放。这是有意为之：
    用户要的是**包含关系**（文件夹 > 其内笔记 > 其内标题）与**同级相对大小**（同层里内容多的
    更大），这两条都完整保留；跨分支比较绝对大小从来不是这张图的读法。
    如果你想把它「修」成半径 = f(叶子数) 的全局函数，先回去读 `kg/layout.py` 开头 docstring
    里那笔账：自底向上递推会让 10 层累积出 10⁵~10⁶ 倍半径比、要 100+ 格滚轮才走得完。

18. **相机自己动过之后必须重算 hover。** 鼠标没动、相机在 tween，hover 态就会停在旧节点上。
    `render.js` 为此有 `lastMouse` + `evalHover(px, py)`：`window` 的 `mousemove` 末尾与
    `draw()` 收尾各调一次，`mouseleave` 清空。改相机或改 `draw()` 时别把这两处调用摘掉。

---

## 5. 调参地图

### `config.yaml`

| 想改什么 | 键（当前值） | 调它会发生什么 |
|---|---|---|
| 公开范围 | `include` / `exclude` / `exclude_notes` | 节点数直接变，`r`、`zMin/zMax/zHome` 全部重算 |
| 滚轮手感 | `zoom.wheel_step`（1.12） | 一格的缩放倍率（以光标为锚点）。10 层走完约 45 格，调大则层级切换更粗 |
| 换层/跳转动画时长 | `zoom.transition_ms`（260） | 点层级胶囊 / 搜索结果跳转的相机动画 |
| 子节点浮现后父圆压暗到多少 | `zoom.parent_dim`（0.22） | 父圆填充是子圆的底色，调到 0.5 会把同色子圆整体压暗（§4.8） |
| 缩到最外层的余量 | `zoom.zoom_out_floor`（1.05） | **必须 ≥ 1**。`zMin` 由最小那个学科根（Medical and Health，8 个叶子）决定，取 0.9 会让它在最外层只剩 16.2px < `min_px`，「缩到最外层看见全部 6 个学科」当场破掉。1.05 留 5% 余量抵消落盘时 `r` 只保留 4 位小数的舍入 |
| 放大上界的余量 | `zoom.zoom_in_ceiling`（1.35） | 最挤节点完全浮现所需的 zoom × 此值 = `zMax` |
| 初始视图松紧 | `zoom.home_fit`（1.08） | 刚好装下全图的 zoom × 此值。**上限是 `layout.padding` = 1.12**，再大就会把 Science and Tech 裁出屏幕。1.08 时六个学科全部完整落在视口内（最小根 20.4px，最大根包围盒 411.7px / 视口半高 427px） |
| **同级里的大小差** | `layout.size_exponent`（0.5） | 目标半径 ∝ 叶子数 ^ 此值。**0.5 是无标度不动点**（`√(ΣTᵢ²) = √(ΣLᵢ) = T_parent`），每层缩放退化成与分支数无关的常数 ≈0.85。调大 → 深层膨胀、根 spread 上升（0.6 时 16.2× → 28.3×，最小学科在 home 只剩 18.2px，贴着 `min_px` 没余量）；调小 → 深层急剧缩小、`zMax` 爆掉、缩放跨度拉长 |
| **层级间的大小差** | `layout.level_ratio`（1.5） | 父圆半径 ≥ 最大子圆 × 此值。独子链打包出的包围圆就等于子圆自己，光靠 `padding` 只有 1.12×，肉眼分不出父子；1.5 才看得出（实测 343 条独子链的比值精确落在 1.500） |
| 兄弟圆之间的留白 | `layout.padding`（1.12） | 父圆半径 ≥ 子圆包围圆 × 此值。它同时是 `zoom.home_fit` 的硬上限 |
| 世界坐标量级 | `layout.norm_root_radius`（1000.0） | 虚拟根归一化后的半径。钉住坐标量级，使 JSON 体积可控、`zMin/zMax` 不随 vault 增长而漂移。改它等于等比缩放整个世界（观感不变，但落盘精度与 JSON 体积会变） |
| 退化子树 / 孤点的兜底半径 | `layout.leaf_radius`（1.0） | 正常叶子的半径由缩放链决定，这个只兜底 |
| 整体旋转 | `layout.start_angle`（-90） | 打包完再整体旋转的角度。**同输入必得同输出**是同步任务的硬要求，别引入随机性 |
| **浮现早晚（最小屏幕半径）** | `lod.min_px`（18） | 一个圆值得被画出来所需的最小屏幕**半径**（不是间距）。它同时决定 `zMin`（最小学科根在 `zMin` 处恰好是 `min_px × zoom_out_floor`）与同屏圆数上界 `(视口半径/min_px)²`。调小 → 同屏更挤、缩放跨度整体拉长 |
| 淡入带宽 | `lod.fade_span`（1.35） | zoom 从 `minzoom/fade_span` 升到 `minzoom`，alpha 从 0 走到 1。滚轮每格 1.12 ⇒ 约 2.6 格淡完，不会突兀 |
| 标签参与竞争的门槛 | `lod.label_alpha`（0.55） | 读的是**未被 `parent_dim` 压暗的**淡入进度（§4.8）。标签另受 24px 碰撞网格与每帧 400 条预算限制 |
| 弱聚合边压暗阈值 | `lod.weak_edge_min_count`（2） | 聚合边 `count` 低于此值时压到 45% 不透明度（关系弱，别抢戏） |
| 链接权重 | `weight.wiki_link` 1.0 / `heading_link_bonus` 0.5 / `embed_factor` 0.6 / `annotation_default` 3.0 | |
| 边的来源优先级 | `precedence: [annotation, frontmatter, wiki]` | 靠前的先决定 `weight` / `mastery` |
| 学科配色 / 边配色 | `theme.domains` / `theme.fallback` / `theme.edges` | 父子同色是刻意的（整条包含链继承学科色），别给子节点单独配色（§4.11） |
| 候选边挖掘松紧 | `candidates.min_score` 0.45 / `min_term_len` 4 / `max_doc_freq_ratio` 0.25 / `min_shared_terms` 2 / `max_suggestions` 400 / `generic_headings` | |

### `web/render.js` 顶部常量

| 常量 | 值 | 作用 |
|---|---|---|
| `FOOTER_H` | 46 | canvas 的底部预留带：内容视口 = `H - FOOTER_H`，适配半径与 `farCornerDist`（判定「圆铺满视口」）都按它算。`#footer` 本身是右下角绝对定位块，改这个值等于改铺满判定，别随手调（§2） |
| `LABEL_CELL` | 24 | 标签碰撞网格边长（屏幕像素） |
| `LABEL_BUDGET` | 400 | 每帧最多考虑多少个标签候选 |
| `CULL_MARGIN` | 32 | 视口外扩余量。裁剪必须**按半径外扩**：大圆的中心常常在屏幕外，圆本身却铺满整屏 |
| `LABEL_INSIDE_PX` | 28 | 屏幕半径超过这个值的容器，标签压在圆内顶部而不是圆心 |

旧表里的 `HIT_CELL` **已不存在**：拾取不再用网格，`hitTest` 就是对 `lastDrawn` 的线性扫描
（同屏圆数被 `min_px` 钉成常数上界，最多一百多个，不需要空间索引）。

---

## 6. 待办清单（按建议顺序）

**P0 — 已完成**：看图验收；两个改进需求（同步方案、实心圆/细线/跨层级链接淡入淡出）；
**布局重构（同心环 → circle packing）+ 用户四条新要求**（同级内容多者圆更大 / 层级间大小
有区分 / 子在父内且同色 / 地图式淡入淡出），Python 侧、渲染侧、浏览器回归套件都已适配。

**P1 — 让「掌握度/重要度」真正起作用**
`annotations.yaml` 是空的，108 篇笔记 `mastery` 全是 0，暗色细边看不出来。
可选：提示用户填几条；或做 `build.py suggest-annotations`，按「标题数 / 链接数 / 行数」
给出初始 `weight` 建议草稿供人工审核。**绝对不要自动写进用户的笔记。**

**P2 — 候选边审核流程**
`candidates.yaml` 手工改 `status` 很累。可在页面里加「审核模式」：列出候选边，
点 accept/reject 后**导出 YAML 文本**给用户自己粘回文件（保持工具不写用户文件的边界）；
或写 `build.py review` 交互式命令行逐条确认。

**P3 — 规模压测**
当前 3482 节点、idle rAF 58~63 fps。没测过上限。可做：临时放宽 `include` 到全 vault
（含 Logs/Excalidraw）；或造 1 万节点合成数据测深层渲染与拾取。已知热点是标签竞争与
聚合边重建；拾取现在是线性扫描 `lastDrawn`，规模上去后也要回头看一眼。

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
  改前端要改 `web/`，然后 `python build.py build`。
- 不要把「自动校验全绿」当作「视觉没问题」。这两件事无关，必须自己看截图。
- 不要在没跟用户确认的情况下新增第三方依赖（前端尤其：现在**零**运行时依赖）。
- **不要在没跟用户确认的情况下改 `alphaOf` 的函数体**——那条淡入淡出曲线
  （`smoothstep(minzoom/fade_span, minzoom, zoom)`）用户已经人眼验收过，一字未改。
  要调观感先动 `lod.fade_span` / `zoom.parent_dim` 这些系数。

---

## 8. 回归基准（改坏了怎么发现）

```bash
python build.py build      # 笔记 108 / 文件夹 35 / 标题 3339 / 节点 3482
                           # 深度轴 10 / 语义边 92 / 包含边 3476 / 标题级链接 66（未命中 12）
                           # layout_root_radius 1000.0 / nominal_fit_radius 427px / HTML 8702 KB
python build.py verify     # 必须 ✓ 全部自动校验通过
python browser_check.py    # 必须 53 [ok] / 0 FAIL / ALL BROWSER CHECKS PASSED
node --check web/app.js && node --check web/render.js   # 前端语法（一次只查一个文件）
```

`verify` 里最该盯的三条不变量——它们破了，「子在父内」和「放大 = 更深」就都不成立了：

1. **包含越界 0 个**（每个节点都完整落在父节点圆内）；
2. **兄弟相交 0 对**（当前 6639 对）；
3. **`r` 沿包含链严格递减**（违反 0 个）⇒ `minzoom` 严格递增 ⇒ 孩子绝不会比祖先先浮现。

浏览器里再确认（数字应与 §3 的表一致）：

```js
KG.state()                 // zoom 0.4612 / level 1 / shownNodes 55 / shownEdges 24 / shownLabels 26
KG.zMin                    // 0.4274   （最小学科根决定 × zoom_out_floor 1.05）
KG.zMax                    // 66.3753  （最挤节点 minzoom × zoom_in_ceiling 1.35）
KG.zHome                   // 0.4612   （home_fit 1.08）
KG.renderer.setZoom(KG.zMin); KG.visible()
                           // 6 个学科根全部可见，**且它们的子圆也仍在画面里** ——
                           // 不再「只剩 6 个节点」，这正是 packing 与同心环的根本区别
```

改完视觉**必须重新截图并人眼看**：`python browser_check.py` 后 ReadMediaFile `%TEMP%\kg_0*.png`。
