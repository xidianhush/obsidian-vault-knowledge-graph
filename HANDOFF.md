# 交接文档 —— 知识笔记语义缩放可视化系统

> 写给接手「看图验证 + 改进优化」的编程智能体。先读这份，再读 `README.md`
> （§4 语义缩放机制、§8 关键实现决定是同一批内容的用户视角版本）。

---

## 0. 一句话现状

**布局重构（同心环 → circle packing）与用户的四条新要求都已实现并提交**；其后的**焦点模式**
（选中即过滤连线 + 邻居蓝环，见 §4 坑 19、§5 调参表、§8 回归基准）已落地并提交（第10步），
**连线端点标记**（两端截断 + 源点/箭头，见 §4 坑 20）也已落地并提交（第11步），
**屏外焦点边兜底**（视口边箭头/圆点 + 屏外端点名字 chip + 侧栏边行点击 fitPair 框住两端，
见 §4 坑 21/22、§5 调参表、§8 回归基准）已落地并提交（第12步）。
**标签字号绑屏幕半径 + 淡入淡出平滑**（见 §4 坑 23、§5 调参表）已落地并提交（第13步）。
数据侧（`build.py verify`）与浏览器侧
（`browser_check.py`，162 项断言）自动校验全绿，截图人眼复看过。
剩下的都是有意的待办（`annotations.yaml` 还是空的、候选边还没审核）。

**紧跟其后是「公开范围统一成一份真源」这一轮**（见 §1「范围真源」、§2、§4 坑 26–30、§5）：
`config.yaml` 里不再有 `include` / `exclude` / `exclude_notes` / `output`，范围全部来自 vault 里的
`quartz-setup/public-scope.yaml`；CLI 每条子命令都接受 `--scope private|public|all`（`-s`，
`all` 只对会遍历范围的子命令有意义 —— `watch --scope all` 会被直接拒绝）；
产出两份（private 沿用旧文件名 `graph.json` / `knowledge-graph.html`，public 加 `.public` 后缀）；
站点侧的同步脚本（当时还在 `quartz-sync-task\sync.ps1`，2026-10-14 已搬进 vault 的
`quartz-setup\sync.ps1`）也改成读同一份真源、读不到就整轮放弃（fail-closed）。
`python build.py verify --scope private` 与 `--scope public` 两份都全绿。
⚠️ **这轮改动还在工作区里没提交**（`git status` 里代码侧 `build.py` / `config.yaml` /
`kg/config.py` / `kg/scan.py` / `kg/graph.py` / `sync-graph.ps1` / `verify.py` /
`browser_check.py` 都还是 modified），别当成已入库。

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
51d338b  第9步：文档重写 —— README/HANDOFF 跟上 circle packing
e8a48a8  第10步：焦点模式 —— 选中即过滤连线，无关节点不压暗
60f7b3c  第11步：连线端点标记 —— 这条线从谁到谁，一眼读得出来
0c65afd  第12步：屏外焦点边兜底 —— 视口边箭头 + 名字 chip，侧栏边行点击框住两端
b528d2d  第13步：标签字号绑屏幕半径 + 淡入淡出平滑 —— 字有大小层次，淡入不再跳变
7954dfb  文档：计划任务电池条件坑 —— 注册了也可能一次都不跑（HANDOFF 坑 25）
（工作区未提交）公开范围统一成 public-scope.yaml 一份真源 + --scope + 站点侧 fail-closed 同步
```

```bash
cd D:/obsidian_vault/knowledge-graph
python build.py build        # 不出 --scope 时 = private：生成 dist/knowledge-graph.html
                             # （单文件，示例快照 2026-10-17 00:07 实测 8957 KB ≈ 8.7 MB；
                             #   该值随 vault 内容漂移，不是固定不变量）
python build.py build --scope all    # 两份都建（public → dist/knowledge-graph.public.html，同快照 8871 KB）
python build.py verify       # 数据侧自动校验，应全绿（--scope private 与 --scope public 都要绿）
python browser_check.py      # 浏览器侧 162 项断言 + 截图，应全绿（默认查 private 那份 HTML；
                             #   想看 public 那份：KG_HTML=knowledge-graph.public.html …）
python build.py watch        # 开发时挂上，改笔记/配置/范围定义自动重建
```

**`python build.py` 不带子命令只跑 scan、不写 dist** —— 重建必须写 `build`。
不带 `--scope` 时所有子命令都作用于 `config.yaml` 的 `scopes` 里排第一的那份（= private）。
改了 `web/*.js` 或 `web/template.html` **必须重建 dist 再跑 `browser_check.py`**：这三个文件在
构建时被完整内联，不重建等于没改。这两条本轮真踩过。

改 `public-scope.yaml` 也算「改配置」：`watch` 的 snapshot 里已经包含 `cfg["scope_file_path"]`，
所以改范围定义会触发重建（见 `build.py:cmd_watch`）。

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
| 范围真源 | `D:/obsidian_vault/hush-ob-bucket/quartz-setup/public-scope.yaml`（唯一真源；本项目与站点同步脚本都读它。`config.yaml` 里只记它的路径 `scope_file`） |
| 本项目 | `D:/obsidian_vault/knowledge-graph`（vault 同级，不在 vault 内） |
| 站点仓库 | `D:/obsidian_vault/quartz-site`（公开 Quartz 站点，发布分支 `v5`） |
| 站点同步脚本 | `D:/obsidian_vault/hush-ob-bucket/quartz-setup/sync.ps1`（142 行；2026-10-14 从 `quartz-sync-task/` 搬进 vault，交给 obsidian-git 备份）：读 `public-scope.yaml` 的 `mirror` 清单 → robocopy /MIR →（**仅当 `publish_graph: true`**）建公开图谱并复制进 `content/` → commit/push。**依赖 `python` 在 PATH 上**。脚本用 `$PSCommandPath` 现算自己的目录、不写死绝对路径，所以再搬家只需改计划任务里的 `-File`；`sync.log` / `sync.lock` / `marker.log` 就放在它旁边，三份都在 vault 的 `.gitignore` 里 |
| 已有计划任务 | `Quartz Site Auto Sync`：每 30 分钟，从 :24 起算（:24 / :54）；`-File` 参数已指向上面那个新位置 |
| 本项目计划任务 | `sync-graph.ps1`，每 30 分钟从 :07 起算（:07 / :37）——与上面那个错开 17 分钟避免撞车。**注册/取消命令给用户自己执行**（见 §7）。⚠️ `schtasks /Create` 默认带 `DisallowStartIfOnBatteries=true` + `StopIfGoingOnBatteries=true`：**笔记本只要在用电池，这个任务就一次都不会跑**（请求返回成功、进程根本不启动、日志不写、`上次结果` 仍是 0）——极难发现，注册后必须按 §4 坑 25 把这两条关掉 |

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
KG.state()      // {zoom, level, shownNodes, painted, shownEdges, shownLabels, selected, hovered,
                //  search, labelMode, filterSet, camera, focusEdges, focusNeighbors, marks, chips}
                //  ⚠️ 判「视口是不是空了」读 painted（真的落笔的节点数），不读 shownNodes
                //     —— 后者只是候选集大小，可能非空而屏上什么都没有（§4 坑 33）
KG.visible()    // = renderer.stats
KG.setLevel(n) / KG.zoomToDepth(n)          // 跳到第 n 层（1..10）
KG.select(id) / KG.runSearch(q) / KG.applyFilters()
KG.revealOf(id) / KG.alphaOf(id) / KG.enterAt(z)
KG.zMin / KG.zMax / KG.zHome
// renderer 上还有：NODES byId hitTest minzoomOf descOf visibleLayerOf
//                   setZoom zoomBy focusOn fitPair tweenTo resetView
//                   panBy(dx, dy) panStep(fast)（方向键平移走这两个；panStep 返回 [vx, vy]）
//                   hover selected filterSet matchSet labelMode centerScreen size
//                   markJobs chipJobs（排队未落笔的端点标记与屏外 chip，回归断言直接读）
```

`KG.revealOf(id)` 现在是 **`r`（世界半径）的兼容别名**——payload 字段早已从 `reveal` 改名成
`r`（`rings` 也改名成 `layers`），这个函数名留着只是为了不打断旧脚本，返回的就是 `n.r`。
`KG.zMin / KG.zMax / KG.zHome` 照旧，但**别再拿 `KG.zMin` / `KG.zMax` 当「可用缩放的上下限」**：
它们现在是地标不是墙（见 §4 坑 32），滚轮可以越过它们。

---

## 2. 文件职责

```
knowledge-graph/
├── config.yaml          ← 构建入口：scope_file / scopes（建哪几份、各输出到哪）/ zoom / weight / candidates / layout / lod / theme
│                          ⚠️ **公开范围不在这里**，去 vault 的 quartz-setup/public-scope.yaml 改
├── build.py             CLI：scan | suggest | build | verify | watch | scope（都吃 --scope/-s）（381 行）
├── verify.py            数据侧自动校验（断言式，无测试框架；含 scope 范围一致性断言）（483 行）
├── browser_check.py     浏览器侧自动回归：162 项断言 + 截图（默认查 private；`KG_HTML` 可切 public）（1499 行）
├── sync-graph.ps1       计划任务包装：防重入 lock + python 检查 + UTF-8 + 日志裁剪 400 行；建本地的两份（`build --scope all`）（49 行）
├── kg/config.py         读 public-scope.yaml、解析各 scope、配置校验（中文报错） （336 行）
├── kg/scan.py           白名单 glob 扫描 + 落地名（remap）前缀重写               （118 行）
├── kg/parse.py          frontmatter / 标题树（跳过代码块）/ wiki 链接 / 摘要     （186 行）
├── kg/graph.py          层级树、语义边、按层聚合边、标题级链接、重映射路径的别名索引（476 行）
├── kg/candidates.py     候选边挖掘（3 条启发式）                                （302 行）
├── kg/layout.py         circle packing 布局 + 世界半径 r / minzoom              （435 行）
│                        ↑ 开头 docstring 是布局的权威叙述，改布局前先读它
├── kg/ioutils.py        stdout UTF-8（`setup_stdout()`）                        （18 行）
├── kg/emit.py           输出 graph.json 与自包含单文件 HTML                      （83 行）
├── web/template.html    骨架 + CSS（顶栏/侧栏/画布 + 右下角绝对定位的 `#footer`）（226 行）
├── web/app.js           状态机、搜索过滤、侧栏、层级胶囊、事件绑定（含方向键/Home）、window.KG（633 行）
├── web/render.js        Canvas2D 渲染器：相机、五趟绘制、两条画边路径（`drawRawEdges` 逐条链接 /
│                        `drawEdges` 按尺度聚合，顶栏下拉框运行时可切）、端点标记、屏外 chip、
│                        fitPair、拾取、标签竞争、键盘平移 `panBy`/`panStep`（1721 行）
│                        ⚠️ 两条路径各有自己的锚点函数：`rawAnchor` **恒返回这条边真实的两个端点节点**，
│                        `resolveAnchor` 才沿 `parent` 链上移找「此刻在屏的代表圆」—— 后者只服务 agg
├── annotations.yaml     用户手工标注（权重/掌握度/别名/手工边）—— **目前是空的**
├── candidates.yaml      候选边（待审核）
├── sync-graph.log/.lock 运行时产物，gitignore
└── dist/                构建产物，gitignore
    ├── graph.json / knowledge-graph.html              private（旧文件名，示例快照 2026-10-17 00:07 实测 10355 KB / 8957 KB）
    └── graph.public.json / knowledge-graph.public.html public （同快照 10240 KB / 8871 KB）
```

vault 那边还有一份（**唯一真源**，本项目只读）：

```
D:/obsidian_vault/hush-ob-bucket/quartz-setup/public-scope.yaml
  content: [{from, as?, scopes: [public|private]}]   # 内容目录；public 上站+进公开图，private 只进私有图
  assets:  [{from, as?, scopes: [...]}]              # 只镜像上站，永不进图（Attachment）
  exclude / exclude_notes                            # 两份范围共用
  publish_graph: false                               # 公开图谱 HTML 要不要真的发到站点（见 §4 坑 30）
```

`#footer` 是**右下角绝对定位块**（`right:12px; bottom:12px`，没有写死高度）。
`web/render.js` 顶部的 `FOOTER_H = 46` 是另一回事：canvas 的**底部预留带**，
内容视口按 `H - FOOTER_H` 算（适配半径、`farCornerDist` 都用它）——template.html 第 27 行
注释说明了这两者的约定关系。

数据流：vault →（按 `public-scope.yaml` 取当前 scope 的范围）→ `kg/*` → `graph.json`
→ 内联进单文件 HTML → Canvas2D 自绘。
**`web/` 下三个文件在构建时被完整内联**，改完必须重跑 `build.py build` 才生效。

---

## 3. 已实测验证的部分

> ⚠️ **下面所有绝对数字都是某一次 payload 的「示例快照」**，快照时间 = `dist/graph.json` 里的
> `meta.generated`。计划任务每 30 分钟重建一次 `dist/`，vault 内容一改这些数就漂。
> 本节全部读数钉在下面这四批上（四批是同一份数据，`nodeCount` 3558、`zMax` 68.9753、
> `enter[10]` 39.956、语义边 97 / 96 逐位吻合）：
>
> | 来源 | 快照批次 | 生成时间 |
> |---|---|---|
> | `build.py build --scope all` | build5 | **2026-10-16 23:02** |
> | `dist/` 尺寸 | 计划任务重建（与 build5 逐字节同尺寸） | **2026-10-17 00:07** |
> | `build.py verify` | verify6（两份 EXIT=0，尾行「✓ 全部自动校验通过」） | **2026-10-17 00:15** |
> | `browser_check.py` | bc8 private **162 `[ok]` / 0 `FAIL` / 2 `WARN`**（2026-10-18 22:46）/ bc7 public **162 `[ok]` / 0 `FAIL` / 2 `WARN`**（2026-10-18 22:42） | **2026-10-18 22:46** |
>
> 漂得有多快，有两个现成的标本（取证见 `README.md` §9，本节下面的 `zMin` / `zMax` 也留了一份漂移史）。
> **标本一**：写这一节时 `dist/` 已经被重建过好几批（09:37 → 10:07 → 10:37），起因只是 vault 里一次
> 笔记改名（`电路分析基础.md` → `Basics of circuit analysis.md`），语义边就从 99 / 98 变成 97 / 96、
> 标题级链接从 69 变成 68；那条改名留下的悬空引用至今还挂在两份 verify 的「解析失败」里
> （private 3 条、public 4 条，都含 `电路分析基础`）。
> **标本二**：本节定稿后过了一夜，`dist/` 又被重建（**2026-10-18 12:37**），语义边再变成 **98 / 97**、
> 标题级链接 **69**、节点 3559 / 3519、depth≤10 边 3651 / 3613、聚合边 3837 / 3799 —— 起因只是 vault 里
> 多写了一个 depth-4 的标题（标题级别分布 `4: 605→606`）。`zMin` / `zMax` / `enter[]` 一格没动，
> 两份 verify 仍全绿。**代码一行没改，本节所有绝对数就都对不上你屏幕上的了。**
>
> **任何绝对数都不要当不变量写进断言**；要复现就现跑 `python build.py verify` /
> `python browser_check.py`，别追着最新一次重建改文档。

### 构建摘要（示例快照 build5 = 2026-10-16 23:02；文件尺寸取自 2026-10-17 00:07 那批 `dist/`）

private（默认那份，沿用旧文件名）：

```
文件夹 35 个 / 笔记 111 篇 / 标题 3412 个  →  共 3558 个节点
深度轴 10 层（文件系统本身 5 层 + 标题层级）
语义边 97 条（全是 derives）/ 层级包含边 3552 条（= 3558 − 6 个根；合计 3649 条边）
标题级链接 68 处命中（锚点未命中 14 处；命中处全部能归属到源标题）
heading → heading 的语义边 3087 条；附件链接丢弃 669 处、解析失败 3 处
    （`- 大脑-控制框图映射.html`、`电路分析基础`、`My tech log` 各 1 处；
      中间那条就是标本一那次改名留下的悬空引用，至今还在）
布局根半径 layout_root_radius = 1000.0；标称视口半径 nominal_fit_radius = 427px
home 停在第 1 层，home_zoom = 0.4612（home 下可见 46 个节点，zMin 下 31 个）
标题级别分布 {1:368, 2:1027, 3:1144, 4:605, 5:212, 6:56}
HTML 8957 KB / graph.json 10355 KB
```

public（与站点共用范围，产物带 `.public` 后缀）：

```
文件夹 23 个 / 笔记 91 篇 / 标题 3404 个  →  共 3518 个节点
最深层 3611 条边（含 96 条语义边 —— ⚠️ 不再与 private 的 97 条相同：
    有一处笔记→笔记链接的端点落在公开范围之外，那条边整条没了）
标题级链接 68 处命中（锚点未命中 14 处）；heading → heading 3082 条
附件链接丢弃 659 处、解析失败 4 处（`Finance` ×2、`电路分析基础`、`My tech log` 各 1）
home 停在第 2 层（顶层只有 3 个根，骨架更浅一层就够）；home 下可见 43 个节点，zMin 下 9 个
标题级别分布 {1:346, 2:1001, 3:1138, 4:646, 5:213, 6:60}
HTML 8871 KB / graph.public.json 10240 KB
```

六个学科根的世界半径 `r`（**spread 13.97×** —— 这是自顶向下等比缩放 + `size_exponent` 0.5
钉出来的：叶子数 spread 是 2147/11 = **195.2×**，开平方正好 **13.97×**，与下表最大/最小根
717.82/51.38 = 13.97× 逐位吻合。旧读数说「自底向上打包会到 79.6×」，
**那是更早一批 payload 的数，未随本次快照重跑**；见 `kg/layout.py` docstring）：

```
Science and Tech                   717.82     （5 个孩子，最大 392.65，父子比 1.83）
Projects                           170.41     （2 个孩子，最大 113.61，比 1.50）
Literature History Philosophy       88.99     （5 个孩子，最大  43.53，比 2.04）
Economy and Finance                 74.30     （4 个孩子，最大  46.97，比 1.58）
Interest                            69.28     （1 个孩子，最大  46.19，比 1.50）
Medical and Health                  51.38     （6 个孩子，最大  19.66，比 2.61）  ← zMin 由它决定
```

（public 的 3 个根：Science and Tech / Projects / Study log —— `Study log` 是
`Logs/Study log` 的落地名，见 §4 坑 29。）

每层 `r` 中位数与 `enter`（该层的解锁门槛 zoom）—— **示例快照 verify6 = 2026-10-17 00:15**，private：

```
层    节点数    r中位    r最小    r最大    minzoom中位    enter
 1      6      81.64    51.38   717.82      0.2223     0.2223
 2     23      19.66     9.83   392.65      0.9157     0.9157
 3     66      17.49     6.42   175.66      1.0296     1.0296
 4    199       8.98     4.31    64.85      2.0042     2.0042
 5    570       3.72     2.69    39.02      4.8440     4.8440
 6    956       2.43     1.73    16.02      7.4025     7.4025
 7    888       1.61     1.09     8.16     11.1954    11.1954
 8    589       1.10     0.77     3.83     16.3399    16.3399
 9    217       0.75     0.48     1.83     23.9234    23.9234
10     44       0.45     0.35     0.67     39.9556    39.9556
```

（`minzoom中位` 与 `enter` 逐行同值，这是 `minzoom = min_px / r` 的直接后果。
`r` 全域区间 [0.352, 717.82]，跨度 2038×；父/子半径比 最小 1.500 / 中位 3.060 / 最大 48.97。
公开那份的 `enter` 是 [0.10541, 0.181948, 0.750554, 1.695402, 4.847179, 7.382498,
11.074878, 16.305825, 23.790642, 39.86711]，前两层明显更低 —— 它的顶层只有 3 个根。）

缩放轴：`zMin = 0.36784526`（= `min_px` 18 / 最小根 51.38，再 × `zoom_out_floor` 1.05）、
`zMax = 68.97530514`（最挤节点 minzoom × `zoom_in_ceiling` 1.35）、`zHome = 0.4612`（`home_fit` 1.08）。
总跨度 **187.5×**（verify6 自己四舍五入打印成 188 倍），`wheel_step` 1.12 ⇒ **约 46 格滚轮走完 10 层**。
公开那份：`zMin = 0.14249589` / `zMax = 68.83852691` / `zHome = 0.4612`，跨度 **483.1×**、**约 55 格**。
渲染侧这两个边界是**从 payload 里每个节点的 `minzoom` 现算**的（`render.js` 里
`zMin = rootNeed × zoom_out_floor`、`zMax = maxMz × zoom_in_ceiling`），不依赖窗口尺寸 ——
所以浏览器里的 `KG.zMin / KG.zMax` 与数据侧**同值**（本次快照实测
`0.36784526` / `68.97530514`，逐位命中）。
只有 `KG.zHome` 会因为 `fitRadius()` 读真实视口而略有浮动（1440×900 下是 0.46116）。
⚠️ **`zMin` / `zMax` 是随 payload 漂的**（vault 增删笔记、改标题都会动最小根与最挤节点）：
2026-10-12 那批是 0.4241 / 66.5753，放开缩放后一度重测到 0.4493 / 68.8385，
本次快照（verify6 = 2026-10-17 00:15）是 0.36784526 / 68.97530514。
**但它们只是「地标」，不再是滚轮的夹取上下限** —— 滚轮过去就空、`Home` 回来，
为什么放开、哪些地方还夹着、怎么找回，见 §4 坑 32。

扫描侧（private）：vault 内 `.md` 共 137 篇、纳入 111、排除 26；文件夹 35 个，最大深度 5；
笔记所在层 `{2:10, 3:42, 4:55, 5:4}`；`[[链接]]` 758 = 附件 666 + 笔记→笔记 46 + 自链接 44 +
解析失败 2（`My tech log`、`- 大脑-控制框图映射.html`）；标题 3412 个，平均 30.7 个/篇，
无标题笔记 15 篇；带 frontmatter 5 篇（`nep笔试题` / `nep面试` / `Analytic geometry` /
`Elementary geometry` / `Linear Algebra`）；
`annotations.yaml` 0 篇笔记、0 条边（仍是空的）。

扫描侧（public）：同样 137 篇里纳入 91、排除 46；文件夹 23 个，最大深度 5；
笔记所在层 `{2:1, 3:38, 4:48, 5:4}`；`[[链接]]` 748 = 附件 656 + 笔记→笔记 45 + 自链接 44 +
解析失败 3（`Finance` ×2、`My tech log`）；标题 3404 个，平均 37.4 个/篇，无标题 8 篇。

**深度轴的定义**：`heading.depth = 所属笔记 depth + 标题级别`（`kg/graph.py`）。
所以 depth 6..10 不是固定的「h1..h5」，而是「笔记深度 + 标题级别」的连续展开——
放在深层文件夹里的笔记，它的标题也自然更深。这比用户原话里那条固定 10 级列表更自洽。

### 浏览器实测（`browser_check.py` 实跑，1440×900）

**示例快照 bc6 = 2026-10-17 23:05**（`KG_HTML=` 默认 private 那份 + `KG_HTML=knowledge-graph.public.html`
各跑一遍；跑的是 2026-10-17 00:07 那批 `dist/`）。下表默认给 private 读数，公开那份只在**不同**的地方标出来。
连线模式默认是 `raw`（逐条链接），所以「边 / marks」这类读数**必须先问是哪种模式**——
同一 home 视角下 raw 96 条 / 130 marks、agg 22 条 / 28 marks，差四倍多。
⚠️ 表里每个绝对数都是**这一批快照**的读数，跑一次就变（计划任务每 30 分钟重建 `dist/`，
vault 里多一个标题就漂）。要引用请连生成时间一起引，别当不变量。

| 项 | 实测 | 备注 |
|---|---|---|
| home 初始视角 | zoom 0.4610 / level 1 / 节点 55 / 边 96（raw；agg 22）/ 标签 26 | 画布非底色采样点 3944（判据 >50）。公开那份：level **2** / 节点 **52** / 边 **95**（raw；agg 同为 22）/ 标签 **25** |
| 标签三模式 | auto 26 → off 0 → on 27 → 回 auto 26 | `on` 另受每帧预算限制（`label budget` 实测 **27**）。公开那份 auto **25** → 0 → **27** → **25** |
| `setZoom(zMin)` 落到地板 | zoom 精确等于 `KG.zMin` **0.36784526** / level 1 | **机制**：clamp 拆掉之后「往下滚 N 格」会一路滚过地板进空白，所以改成显式落点。判据：每个顶层学科都在画面上（6 个全部可见，其中带标签的 **20** 个），shownNodes **47** 落在 payload 自述的可读带 **[31..47]** 内（total 3558）。公开那份可读带 **[9..12]**、shownNodes **12**、3 根全可见（带标签 **6** 个）、`zMin` **0.14249589** |
| 上滚到天花板 | private **50 格**到 zoom **106.3080**（span 187.5×，vs `zMax` 68.9753）/ level 10 | zoom 与 level 全程单调、无 NaN；每 6 格取样一次。公开那份 **58 格**到 **101.9640**（span 483.1×，vs `zMax` 68.8385） |
| 天花板处找空视口（bug B） | **条件跳过**（warn，两份都跳） | 天花板中心 shownNodes=**4**（private）/ **3**（public）、平移后仍有内容，找不到真正的空白视口。这项跳过已经**不再**是覆盖缺口：空视口由 2b（缩太远）、3c（放太大）与 **3d**（任何缩放 × 任何平移，36 组整画布探针）三段直接钉住，兜底提示也有专门断言 |
| 双击屏上最小圆 | zoom **1.0810 → 23.1890** | fixture = `Science and Tech/IC and semiconductor manufacture/DSP#5. Finite-Length Discrete Transforms`（depth 5，sr 14px）。公开那份 fixture = `Mathematics Basic/Complex functions#1 复变函数基础`（depth 4，sr 14px），**0.7880 → 17.0640** |
| 双击空白（先把视口拖出所有内容） | level 1 / zoom 0.4610 | vs `zHome` 0.4612，容差 2%。公开那份 level **2** |
| 搜索「微分方程」 | 14 命中 | 首条「微分方程知识点 · 在《Calculus》h1」 |
| 学科过滤 | shownNodes **55 → 2** | 取消过滤后回到 55。公开那份 **52 → 4** |
| 上滚扫描里 shownNodes 峰值 | **168** | 出现在第 25 个取样点（zoom 6.2530 / level 5）；常数上界 `(视口半径/min_px)²`，见 §4.5。公开那份峰值 **135**（第 31 格，zoom 4.7810 / level 4） |
| 单格滚轮最大涌入 | 11% | verify 数据侧实测（376/3558，共 47 格，峰值在第 27 格）；同心环时代是 66% 齐刷刷弹出。公开那份 9%（306/3518，共 55 格，峰值在第 39 格） |
| 帧率 | idle rAF **63** fps（1 秒采样） | 公开那份 **62** |
| 20 格滚轮 | **1104** ms | 含淡入淡出重绘。公开那份 **1091** ms |
| 端点标记（home） | **raw** marks 130 / edges 96（箭头 65 + 源点 65）；**agg** marks 28 / edges 22（14 + 14） | 每个标记到所附圆边的间隙恒为 2px（= `edge_trim_clearance`，minGap == maxGap == 2）、落在圆内 **0** 个；tint 0.55、zoom 0.4612。**minLen 按模式分开**：agg 走 `edge_marker_min_len` = **20**，raw 走 `lod.raw_marker_min_len` = **6**（见 §8 坑 20）。公开那份 marks 同为 130 / 28，edges 是 **95** / 22 |
| 端点标记（焦点模式，选中 `…/Electronic engineering basic`，depth 3 / sr 81px） | **raw** shownEdges 96 / focusEdges **38** / focusNeighbors **8** / 冷边 marks **66**；**agg** shownEdges 22 / focusEdges **17** / nb **10** / 冷边 marks **22** | 冷边（压到 7%）不产生可见标记；焦点后 shownEdges 一点没变（96 / 22）—— 焦点只改浓淡，不增删边。探针：private 53 个在屏节点 / 36 个带相关边；公开那份 50 / 35，focusEdges 同为 38（raw）与 17（agg） |
| 端点标记（zoom 阶梯逐层，10 档） | private **raw** L=7：32 边 / 64 marks（agg 同档 1 边 / 2 marks） | 判据是 **`long_rungs`**：至少存在某一档 `marks < 2×edges`（证明短边确实被标记最小长度挡掉过），加上每档都验硬不变式 `marks ≤ 2×edges`。bc6 里 raw 满足 `marks < 2×edges` 的档：`[(6,72,76),(5,80,84),(4,100,114),(3,150,184),(2,150,182),(1,120,192)]`。（**当时那批快照**的取证：agg L=9 有 2 条边、0 个标记 —— 两条代表边被两端圆截断后各只剩 **4.01px** 弦长 < `MARK_MIN` 20；bc6 里这一档已变成 0 边 / 0 marks，只当历史例子看。）⚠️ 别写成等式断言（`marks == 2×edges` 或 `long == edges` 都**不是**不变量，见 §8 1c 节 ③） |
| 屏外焦点边（**(a)** 深缩放选中 fixture，**一端**在屏外） | focusEdges 1 / chips 1 | 线止于视口边、挂朝外箭头（`edgeArrow true`）+ 选中圆边源点（`selDot true`）；chip 文 = 屏外目标标题截 18 字，实测 `["5.1.2 定积分的定义(本质是求和…"]`（`kg_11_chip.png`）。这条 fixture **两种连线模式读数相同**（raw / agg 各跑一遍，都是 1 / 1） |
| 屏外焦点边（**(a2)** **两端都**在屏外，bc8 = 2026-10-18 22:46） | **raw** focusEdges 1 / chips **1** / shownEdges 16 / `anchored true`；**agg** chips **0** / shownEdges 0 / `anchored false` | raw 侧 `bothOff true / crosses true`、tgtChips `["5.1.2 定积分的定义(本质是求和…"]`、selChips `[]` —— 名字给**非焦点端**，所以选中 SEL 时挂的是 TGT 的名字；线段横穿视口就照画，chip 由 `entryToward` 钉在线段**进入**视口的那一点。agg 两端都出屏时既不产线也不产 chip（设计差异，不是漏测）。⚠️ 这条 fixture 的平移方向必须「远离另一端」，否则两端同侧、线段压根不进视口 —— 见 §4 坑 35 |
| 侧栏边行点击 | fitPair 一次 tween 框住两端 | 框住后 selected 切到对端：**agg** focusEdges 1 / marks 2（`kg_13_fitpair_agg.png`）；**raw** focusEdges **2** / marks **4**（`kg_13_fitpair_raw.png`，两条细线各有各的箭头，okA/okB 都 true）。这正是「细线条数 = 关联强度」的现场证据 |
| chip 上限 | **18 组**缩放×选中组合 chips ≤ CHIP_MAX+1（`chip_max` 8）；**raw 侧 2 组**触发 `+k` 折叠、**agg 侧 0 组** | raw 触发 `+k` 的两组：`…/Electronic engineering basic/LTI analysis`（mult 8 / deg 7 → n=9，last=`'+7'`）与 `…/Mathematics Basic/Calculus`（mult 8 / deg 5 → n=9，last=`'+1'`），都 right-anchored。agg 侧最狠一组 `deg=7 / mult=8 → chips=1`（last=`LLM`），够不到折叠门槛 → 那边 warn 条件跳过（这是剩下 2 条 warn 里的第 ② 条） |
| 缩放地标：往下滚过地板（2b） | **27 格**后 zoom **0.017250** / shownNodes 0 | 要越过 `zMin`（0.36784526）20 倍以上才真的整屏都空（世界半径 1000 的那个根是最后消失的）；空视口**不是死黑屏** —— 兜底提示确实落笔（中心带非背景像素 **2476**）。公开那份只需 **18 格**（zoom **0.018530**，它的 `zMin` 更低：0.14249589），提示像素 **2474** |
| 缩放地标：放到 maxzoom 停画（3c） | **两份现在都空于 z=472.2**（1024.0× home） | 放大侧也会空 —— 圆的屏幕半径 ≥ `farCornerDist` 就停画填充，**这条规则本来就有**，只是以前被 clamp 挡在门外；提示照画（private 中心带非背景像素 **18733**、public **2329**），`Home` 精确回到 `zHome` **0.461160**。private 那档约 **6.8× `zMax`**、public **6.9× `zMax`**。⚠️ **空在哪一档取决于 payload 形状 + 当批快照，别当常数** —— 这一条历史上写反过一次（说 public 更早、0.4×，错的），bc5 那批 public 还空在 z=1888.9（4096× home、27.3× `zMax`），bc6 已经和 private 同档。⚠️ break 条件读的是 **`stats.painted == 0`**，**不是** `stats.nodes == 0` —— 候选集里可能一直挂着 1 个圆却一个像素都不画，按候选数判就永远等不到「空」（见 §4 坑 33） |
| 空白画布兜底（3d） | 9 档缩放 × 4 种平移 = **36 组**，空白且无提示 **0 组**（两份都 0） | 整画布探针 `CANVAS_LIT`（数遍全屏与背景色不同的像素）。修「画布全黑却没有提示」那个 bug 之前，它在 public 上能扫出违规组（z ≥ 5000 时 0 个非背景像素而兜底不画），修完 0 组。⚠️ 收尾用**瞬时**相机归位（`setZoom(zHome)` + 居中 + `draw()`），**不能**调 `resetView()` —— 那是 364ms 的 tween，下一段的 LOD 契约会在相机还在飞时取样 |
| 方向键平移（5b） | ArrowRight panX 720.0 → 900.0（= `panStep` **180.0**）、ArrowDown **106.75**、Shift+ArrowRight **720.0**（= 4×） | 缩放一点不动；鼠标拖拽 (120,80) → panX 720→840 / panY 427→507 且选中未变；选中 `Medical and Health`（fx=1；公开那份选 `Projects`，fx=2）后按两次 ArrowLeft，panX 1620.0 → 1260.0 而 sel 与 focusEdges **纹丝不动**、挪回来 panX 逐位复原 1620.0（**平移只动相机，从不改焦点状态**）；搜索框有焦点时方向键不平移；`panBy` 会取消在飞的 tween（实测 tween 途中 zoom private **0.584464** / public **0.604015** 被打断） |
| console error / pageerror | 0 | |
| `browser_check.py` | **162 [ok] / 2 warn / 0 FAIL**（private 与 public 两份都是 162） | ALL BROWSER CHECKS PASSED；2 条 warn 都是条件跳过、不是失败，原文：① `no empty viewport found at the zoom ceiling -> bug B tested only via 2b/3c`；② `no hub probe exceeded CHIP_MAX in agg mode -> +k chip untested there`。⚠️ 第 ② 条**只剩 agg 一侧**：bc6 里 raw 侧真测到了 `+k` 折叠（2 组），早先「raw / agg 各一条 → 3 条 warn」的说法已过期 |

（这张表是**跑一次就变**的快照：节点数、marks、搜索命中数都随 vault 内容漂移。
要刷新就重跑 `python browser_check.py`；公开那份要 `KG_HTML=knowledge-graph.public.html python browser_check.py`
—— **它没有 `--scope` 参数**，传了会静默跑成 private（历史上真踩过的坑，导致 public 从没被真正测过）。
别把这里的数字当不变量。⚠️ 也别在 browser_check 跑的时候并行做 CPU 重活 ——
fps 与滚轮 ms 两个 perf 读数会被污染。）

`python build.py verify --scope private` 与 `--scope public` 都是 `✓ 全部自动校验通过`
（**示例快照 verify6 = 2026-10-17 00:15** 那批 payload 上实跑）。其中最该盯的几条（private 那份）：
**3558** 个节点里坐标重合的 **367** 对**全是父子关系**（独子链同心；非父子重合 0 对）；
包含越界 0 个；父半径 < 子半径 × 1.5 的 0 个；**6841** 对兄弟圆重叠 0 对；
`r` 沿包含链严格递减（违反 0 个）；**355** 条独子链的父子半径比精确落在 1.500；
**3833** 条聚合边的 `minlayer` 都等于它首次出现的层级（不符 0 条）；
`home_layer=1` 确实是 `home_zoom=0.4612` 下已解锁的最深一层；
范围一致性断言也全绿：depth=1 的根 == 该 scope 声明的目录（private 6 个 / public 3 个）、
越界节点 0 个、**重写过的路径前缀没有残留成节点 id**（残留 0 个）。
（公开那份同批的对应读数：3518 节点 / 重合 **351** 对 / 兄弟圆 **7062** 对 / 独子链 **340** /
聚合边 **3795** 条 / `home_layer=2`。）

> ⚠️ `browser_check.py` 与 `verify.py` 是**两件事**：上面这两组数字（数据侧 / 浏览器侧）
> 各自跑各自的；改了 `web/*.js` 必须重建 dist 再跑浏览器侧，否则测的是旧 HTML。
> 本轮两次都实跑过：`verify --scope private` / `--scope public` 全绿、
> `browser_check.py` **162 [ok] / 2 warn / 0 FAIL（两份都是 162）**。

#### 1c 段：连线模式切换（`raw` / `agg`）为什么这样断言

**这一节是全文所有「见 §8 的 1c 节说明」的落点。** `browser_check.py` 的 **1c 段**专测顶栏
那个「连线」下拉框（`web/template.html:165` 的 `#edgemode`），跑在 1b（标签模式）之后、
焦点 / 端点标记 / 屏外兜底三段之前 —— 后面那三段 **raw / agg 各跑一遍**，断言名带
`[raw]` / `[agg]` 后缀，跑完把页面留在默认的 `raw`。1c 自己覆盖六件事：

1. `select_option('#edgemode', …)` 之后 `state()` 跟着变（下拉框真的驱动渲染器，不是摆设）；
   赋一个未知值会归一化回 `raw`（`web/app.js:571-574` 的 `e.target.value === 'agg' ? 'agg' : 'raw'`，
   以及 `:88-89` 读 localStorage 时只认白名单里的两个值）。
2. 两套关系图例 `#legend-rel-raw` / `#legend-rel-agg` **互斥显隐**（`web/app.js:205-207`）——
   用户看到的图例必须跟当前画法对得上，否则「近白 = 整篇级」那套说明会挂在聚合线上。
3. 选择记进 localStorage 键 **`kg.edgeMode`**，两份 HTML（private / public）共用同一个键，
   所以在一份里切了模式，另一份打开也是那个模式。
4. **相机确定性先验**：同一档 `zoomToDepth(L)` 两次落点逐位相同。这条排在比较之前是必须的 ——
   相机若不确定，两种模式的边数就没有可比性，后面第 5 条判据会变成噪声。
5. 核心判据：**同一档缩放下 `raw` 画出的边数 ≥ `agg`**（合并只可能减少线数，这是硬不变量）。
   「严格更多」只要求 **home 或阶梯任一档**成立，**不绑定具体哪一档** —— 那是某张图的形状
   （实测 private：home 96 vs 22、10 档阶梯全部严格更多；public：home 95 vs 22、10 档也全部
   严格更多。示例快照 bc6 = 2026-10-17 23:05）。
6. `raw → agg → raw` 往返后边数逐位复原，证明切换不留残余状态（没有「切回来但旧画法还在」）。

两条**别改回去**的判据：

+ **绝不断言「raw 任何一档都非 0」**。**曾经出现过** public 在最深那档 raw 与 agg 同为 0，
  写成「恒 > 0」会假红；本次快照（bc6）private 的 `agg` 在最深三档 L=10/9/8 就真是 **0 条边**，
  那是数据形状不是不变量。
+ **绝不断言「`shownEdges` 恒定」**。它是视口绑定的，实测 private 的 raw 沿阶梯从 12 剧烈变到 96。
  用户要的「某一处链接不会因为缩小而消失」不由这两条覆盖，而是由 7d 的 `fitPair` 用例保证
  （那段两种模式各跑一遍：同一对 fixture agg 是 `focusEdges 1 / marks 2`、raw 是 `focusEdges 2 / marks 4`
  —— 两条细线各有各的箭头，正是「细线条数 = 关联强度」的现场证据）。

⚠️ 断言基线从 108 涨到 **156** 就是这么来的：1c 自己一节，加上焦点 / 标记 / 屏外兜底三段翻倍。
再往后的 156 → **162** 是加了 (a2)「两端都在屏外」这一段（3 条断言 × 2 种连线模式）。
以后改这三段，**两种模式都要过**；只跑 raw 就宣布通过等于漏掉一半（`agg` 那半边正是
「三道门 vs 一道门」差别最大的地方，见 §4 坑 21）。warn 只剩 **2** 条同理：`+k` chip 那条
现在**只在 agg 一侧**条件跳过（raw 侧 bc6 真测到 2 组折叠，早先「各触发一次 → 3 条」已过期）。

### 截图人眼验收结论

- **嵌套圆成立**：父圆套着子圆，内容处处填充，没有同心环时代那个空洞的圆心。
- **父子同色但分得清**：子圆继承所属学科的 `domain` 色，靠 `mixWhite(0.4)` 的描边划出界线；
  已经有孩子浮现的父圆退化成压暗的浅色面（wash 趟）+ 一条清晰界线弧——「省 = 浅色面、
  市 = 清晰界线」。
- **深缩放不再有整屏平蓝**：铺满视口的父圆停画填充、只留还没铺满的最内层圆当界线弧。
- 语义边是细线，标签清晰不糊；hover 气泡 + 图例正常；侧栏详情的面包屑、入边、出边、
  标题清单都完整。
- **顶栏在 1440px 下保持单行**，brand 不折行（宁可 `#readout` 折两行）。
- **空视口两侧都有兜底**：缩太远、或放大撞上 maxzoom，都会画「此处没有内容 · 往回滚一点，
  或按 Home / 双击空白回到默认视角」，同时 tooltip 仍显示所在的「省」（有意为之，见 §4.10）。
  措辞改成「往回滚」是因为缩放上下限已经放开（§4 坑 32）—— 老文案只写「向下滚回到更粗的
  层级」，缩太远那一侧方向正好是反的。
- 边上的 `.tag` 悬浮说明同时给出**类型**与**来源**
  （`wiki` / `annotation` / `frontmatter` / `candidate` / `hierarchy` / `mixed`）。
- **连线方向读得出来了**：线在两个圆的边界处截断，源端一个提亮圆点、目标端一个箭头
  （`•———▶`），标记比线亮所以压在底图 wash 上也认得出（截图 `kgv_A_arrow.png` /
  `kgv_A_dot.png`）。焦点模式下只有相关边带标记，实测 `hotMarks=4 / coldMarks=0`
  （`kgv_B_focus.png`）。
- **祖先链点线与链接实线不再混淆**：祖先链改成 `[1, 4]` 圆头点线，一眼能跟链接边分开；
  右下角图例也补了这两行的说明。
- **屏外端点也有去向**：焦点边一端在屏外时，线止于视口边缘、挂箭头/圆点，旁边一枚写着
  屏外端点名字的 chip（截 18 字）；**两端都在屏外时 `raw` 也照挂一枚**（线横穿视口就画，
  chip 钉在它进入视口的那一点，名字给非焦点的那一端），只有 `agg` 才既不产线也不产 chip；
  点侧栏对应边行则一次动画把链接两端框进屏幕
  （截图 `kg_11_chip.png` / `kg_13_fitpair.png`）。

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
   `同屏圆数 ≤ (视口半径 / min_px)²`——实测峰值 **168** 个（默认那份，50 格上滚、每 6 格取样）/
   **135** 个（公开那份，58 格），示例快照 bc6 = 2026-10-17 23:05。同心环时代这笔账根本算不平：
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
    顺带：独子链会让父子**同心**（`verify` 里 351 对坐标重合全是这种，非父子重合 0 对），
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
    用户要的是**包含关系**（文件夹 > 其内笔记 > 其内标题）与**同级相对大小**（同层内容多的
    更大），这两条都完整保留；跨分支比较绝对大小从来不是这张图的读法。
    如果你想把它「修」成半径 = f(叶子数) 的全局函数，先回去读 `kg/layout.py` 开头 docstring
    里那笔账：自底向上递推会让 10 层累积出 10⁵~10⁶ 倍半径比、要 100+ 格滚轮才走得完。

18. **相机自己动过之后必须重算 hover。** 鼠标没动、相机在 tween，hover 态就会停在旧节点上。
    `render.js` 为此有 `lastMouse` + `evalHover(px, py)`：`window` 的 `mousemove` 末尾与
    `draw()` 收尾各调一次，`mouseleave` 清空。改相机或改 `draw()` 时别把这两处调用摘掉。

19. **强调环（选中白环 / 搜索黄环 / 邻居蓝环）的 alpha 不能读 `alphaOf`。** `alphaOf` 在
    `cam.zoom >= n._gate` 时乘 `zoom.parent_dim`（0.22）——粗尺度下被强调的代表节点几乎总是
    这种「已解锁、子圆已浮现」的祖先，环会跟着掉到约 19% 基本看不见（焦点模式的邻居环第一版
    就死在这里）。正解是另写一个**未压暗**的淡入进度
    `fadeInOf(n) = smoothstep(n._mz / fade_span, n._mz, cam.zoom)` 给环用；
    `alphaOf` 函数体本身别动（§7）。同理，焦点模式判断「F 是 n 本身或 n 的祖先」用
    `n._chain[F.depth - 1] === F.id`（O(1)，不需要预建邻接索引）；`_chain` 只含自己和**祖先**，
    别拿它往下查后代——旧版 hover 高亮就是拿聚合端点往上查 `_chain`，漏判了
    「焦点是聚合端点的后代」这一整类边。

20. **箭头一直存在，「看不见」是四个原因叠加 —— 别再去加一个「显示箭头」的开关。**
    用户报「看不出连线从哪到哪」时，`drawEdges` 里其实早就在画箭头了。它看不见是：
    ① **边色 == 节点色**，`theme.edges.derives` 与 `theme.domains["Science and Tech"]`
      是同一个 `#4C8DFF`（`theme.edges.derives` 在 `config.yaml:224` vs
      `theme.domains["Science and Tech"]` 在 `:214`），箭头贴在圆边上等于隐形；
    ② 线是**圆心到圆心**画的，两端都插进圆里，箭头正好落在被实心圆盖住的区段上
      （边那趟在节点那趟之前）；
    ③ 箭头只有约 **5.4px**，还要再乘 0.45 的 alpha；
    ④ 画在 `drawNodes` **之前**，packing 里圆是相切的，紧贴的邻圆能把它整个盖掉。
    现在的解法对应四条：两端各截断 `lod.edge_trim_clearance` 像素（线不再进圆心）、
    标记改用 `MARK_RGB`（边色向 `#d6dbe4` 混白 `lod.edge_marker_tint`，与节点色拉开）、
    箭头尺寸跟线宽走并夹在 `[7,14]`、落笔单独一趟排在 `drawNodes` 之后。
    顺带：短于 `lod.edge_marker_min_len` 的边**整条不画**（线也不画），
    否则密集层会剩下一堆盖不住圆边的短箭头。
    还有一处「虚线」误认：用户看到的虚线是 `drawChainHighlight` 的**祖先链**（包含关系），
    不是链接边。它现在改成 `setLineDash([1, 4])` 的圆头点线，跟链接边彻底区分开；
    另两处虚线（contrast `[5,4]`、mastery≤3 `[2,2]`）当前**零数据**——contrast 0 条、
    111 篇笔记（private，示例快照 verify6 = 2026-10-17 00:15）的 mastery 全是 0，所以永远看不到。
    上面四条修的是聚合那趟（`drawEdges`）；逐条那趟（`drawRawEdges`，现在的默认，见坑 34）
    **照抄同一套**：两端同样截断 `lod.edge_trim_clearance`、标记同样用 `MARK_RGB`、同样单独
    一趟排在 `drawNodes` 之后。**只有标记门槛不一样**：raw 走自己的 `lod.raw_marker_min_len`
    （6 px，在 `render.js:183` 里读成 `RAW_MARK_MIN`），刻意独立于 agg 的 `edge_marker_min_len`
    （20）—— 沿用 20 会把粗尺度下大量只有几 px 的真实链接箭头一起压掉，而 raw 的契约恰恰是
    「每条链接都看得见」（理由同调参地图那一行）。而且 raw 短边**只跳标记、线照画**：
    `drawRawSegment`（`render.js:936/946`）里只有 `glen < 0.5` 才 return false，其余一律
    stroke，`glen < RAW_MARK_MIN` 与冷边 `a < 0.1` 只挡标记。agg 那边则是整条不画（见上）。
    `drawRawSegment`
    还多一条：**返回它到底有没有落笔** —— 两圆贴死时屏幕上没有可见长度，硬画只会得到一条
    方向反掉的短线段，比不画更乱（`stats.edges` 数的是真画出来的条数）。
    第 ③ 条的两个成因在 raw 下只剩一半：alpha **恒为 1**（不乘端点淡入进度、也不乘「弱边打
    45 折」），所以不再被压到 0.45；但线宽恒为 `lod.raw_edge_width`（1.0 px），标记尺寸
    `clamp(5 + lw * 1.6, 7, 14)` 就钉在下限 **7px**（热边 `lw = 1.8` → 7.9px），比 agg 里
    粗聚合边的大箭头小一号。这是有意的：raw 用**条数**表达关联强度，不用粗细。

21. **「侧栏有这条边、画布却没有线」是几道门叠加 —— 别加「全部显示」开关。**
    门数**随连线模式变**（模式本身见坑 34）：`agg` 三道、`raw` 只剩一道**几何门**。
    侧栏入边/出边列表读的是**原始边表**（app.js `edgesOf`），没有尺度概念；画布上这条链接
    要在当前尺度画出来，得过 `drawEdges`（`agg`）里的三道门：
    ① **聚合门**：聚合后两端落在**同一个祖先圆**里（`sa === sb`，包含关系已由嵌套圆表达，线不画）；
    ② **聚合索引门**：聚合索引在这一层**没有代表**；
    ③ **在屏门**：任一端点当帧**不在屏上**（`alpha.get(sa)` / `alpha.get(sb)` 取不到——
      `alpha` 只含本帧过了视口裁剪 + 淡入的节点）。
    `drawRawEdges`（`raw`，默认）**这三道一道都没有**。端点由 `rawAnchor` 给出，恒为这条边
    自己真实的两个端点节点：不查 `aggregates[L]`（② 不存在）、不沿 `parent` 链上移
    （① 那种「两端塌到同一个代表圆」因此不可能发生，只剩「一个元素链到它自己」这种真自链接
    会被 `A.id === B.id` 跳过）、也不读 `alpha`（③ 不存在，端点圆当帧没画出来也照样落笔）。
    唯一的门是**几何的**：线段的屏幕 bbox 与内容视口（外扩 `CULL_MARGIN`）不相交就不画
    —— 这比旧的「两端点都在屏」宽；以及截断后线段短于 0.5px 时无笔可落（`glen < 0.5`，
    只在两个元素贴得极近时发生，**放大立刻恢复**）。
    这正是「链接不该因为缩小而消失」的落点：实测最深那几档 agg 直接归零、raw 仍画出若干条
    （逐层数字见坑 34）。
    用户实测的死区正是 agg 三门叠加的三段（**当时只有 `agg`**）：home 时 `sa === sb`（两端聚进
    同一祖先）；中等缩放时选中圆还没淡入、箭头没有附着点；深缩放时目标必在屏外。
    用户曾提议「选中后不管缩放比，把它自己和它全部子孙元素的出/入边箭头全显示」——驳回，
    理由三条：屏外目标端的箭头**本身不可见**（指向虚空）；粗缩放比下选中圆还没淡入、
    箭头**没有附着点**；子孙元素的全量边在粗尺度是几十上百条线 = 回到最初抱怨的「太乱了」。
    正确的后路是坑 22 的兜底，而不是放宽那几道门。
    ⚠️ **别把 raw 的端点改回上移。** raw 曾经也调 `resolveAnchor`，于是「看见一条从 A 出去的
    箭头、想知道它指向谁」这个最常见的动作会被缩放和平移**双双打断**：一滚轮缩小（A 不满足
    浮现门槛）或一按方向键（A 整圆出屏），A 的实心圆不画了、那条线还沿 parent 链上移若干层，
    用户彻底提取不到「A 链接到 B」。用户明确要求：上移机制**只留在 agg**；raw 下圆可以消失、
    线必须留在原地，端点落进父圆内部反而是想要的暗示（「这里面还有更深的知识点」）。
    所以现在 raw 的门只剩几何那一道，**别再动门**。

22. **屏外焦点边兜底：视口边箭头 + 名字 chip + 侧栏边行 fitPair。**
    ⚠️ **这套兜底在两种连线模式下形态不同，别当成一件事**（旧文档在这里写过一句
    「raw 那趟自己产不出 chip」，那是扇形/端点上移时代的口径，现在**是错的**）。
    + `agg`：端点会沿 parent 链上移，焦点边一端在屏外时 `drawEdges` 根本产不出这条线，
      它被攒进 `droppedFocus` 交 `drawFocusEdges` 补画 —— 补画的线**止于视口边缘**，
      止点挂箭头/圆点指示方向（箭头 = 屏外那一端是被指向的，即屏外端 = target；
      圆点 = 屏外端 = source），另一端的标记照旧附着在屏内圆边；止点旁再挂一枚写着
      **屏外端点名字**的 chip（`chipLabel` 截 18 字 + `…`）。
    + `raw`：端点恒为真实节点，这条线**主绘制趟就已经画出来了**（一路画到屏外），
      所以「补一条止于视口边的线」在 raw 下是多余的 —— 缺的只是「这条线指向谁」这个名字。
      于是 chip 由 `drawRawEdges` **自己挂**，按「屏外的是哪一端」分两个分支：
      **恰好一端在屏外** → `web/render.js:882-897`，条件 `hs && (aA.on !== aB.on)`，钉在线
      穿出视口的那一点上、沿线方向朝外，读作「顺着这条线出去就是它」，命名**屏外那一端**；
      **两端都在屏外** → `web/render.js:898-914`（见下一条）。raw 的 `droppedFocus` 只收
      两种线：真自链接（没有方向可画，`web/render.js:854-857`）与整段 bbox 出屏（`859-862`）。
    + `raw` **两端都在屏外**（平移一下就会碰到：选中项整圆出屏，而它的链接对端本来就在远处）：
      线照画（横穿视口），并且**也挂一枚 chip**（`web/render.js:898-914`）。三个要点：
      * **命名给「非焦点的那一端」**，不是字面的「远端/目标端」—— 选中 A 时答「这条线通向谁」，
        选中 B 时答「这条线来自谁」；两端同属焦点子树（选中项祖先链上互链）时无从区分，
        退回目标端 B，与单端分支「命名屏外那一端」的习惯一致。
      * **几何走 `entryToward`（`web/render.js:1045-1065`），不能复用单端那套公式**：单端分支
        的 `tBest = min(正 t)` 假定起点在矩形内、算出来的是**出口**；起点在屏外时它会返回远侧
        交点，把名字牌钉到线**离开**视口的那一头去。所以两端分支用 slab 裁剪（Liang–Barsky）
        求线段真正**进入**内容视口 `[0,W]×[0,Hc]` 的那一点（不外扩 `CULL_MARGIN`，与单端同口径）。
      * **额外要求 `laid`**（这一帧真落了笔）：两端都出屏时「线段 bbox 与视口相交」≠「真穿过
        视口」，斜角擦过的会被 `drawRawSegment` 自己判掉（`glen < 0.5`），没画出来的线不该
        有一枚指向虚空的名字牌。单端分支不加这道门 —— 那时必有一端在屏内，线一定落笔。
      挂**一枚不挂两枚**：线一进一出、方向本来就看得见，两枚只会把真正想看的焦点 chip
      挤出 `CHIP_MAX`。
    共同的实现要点：`drawEdges` / `drawRawEdges` / `drawFocusEdges` 都只往 `chipJobs` 排队，
    真正落笔在 `drawChips`
    的**屏幕空间**趟（`drawLabels` 之后、最顶层，不参与世界坐标的遮挡关系）；chip 同时最多
    `CHIP_MAX` 枚（读 `lod.focus_offscreen_chips`，缺省 8），超出截断并在右下角补一枚右锚的
    `+k` 折叠 chip（定位避开 `FOOTER_H`）。**两端都在屏外时按模式分开**：`agg` 不画线也不挂
    chip（没有屏内附着点，画出来也是指向虚空）；`raw` **线照画**（横穿视口的那种一进一出、
    方向本来就看得见），**并且也挂一枚 chip**（`web/render.js:898-914`，命名非焦点端、几何走
    `entryToward`、要求 `laid`，三个要点的理由见上一条）。
    ⚠️ 旧文档在这里写过「raw 两端都出屏时按现设计不挂 chip，是已知边界不是 bug」——
    那是 **2026-10-18 之前的口径，已被用户否掉并改掉**。他报的痛点正是这个：平移一下让
    选中项整圆出屏，名字牌跟着消失，于是「这条线通向谁」这条信息彻底读不出来。现在
    `/tmp/user_example4.py` 的 camera C（真实按 5 次 `ArrowLeft` 把选中项整圆推出屏）
    + selected 读数是 `focusEdges 1 / chips **1**`、chip 钉在视口上边缘 `[349,0]`
    （改之前是 `chips 0`）；同视角 agg 三次全 `chips 0`。
    chip **不可点击**，`hitTest` 只认节点圆；导航走侧栏边行
    （`li` 带 `data-self` / `data-target`，点击 → `R.fitPair(idA, idB)` 一次 tween 框住两端，
    并把选中切到对端）。

23. **标签字号绑「屏幕半径」而不是绑 `depth`**（用户 2026-10-10 提的
    「文字大小和层级绑定」需求最终是这样落地的）：
    `depth` 是复合轴（`heading.depth = 笔记 depth + 标题级别`），而半径是内容驱动
    （circle packing 按同级内容多少给面积），两者不成正比。反例：zoom 地板那 6 个
    学科根同为 depth-1，世界半径却差 **13.97×**（Science and Tech 717.82 /
    Medical and Health 51.38，示例快照 verify6 = 2026-10-17 00:15）——按 depth 分档会让铺满全屏的根和一枚 20px 小圆点
    同字号。屏幕半径 `_sr` 才是既有的 LOD 轴（`minzoom`、圆内/圆外摆放、视口裁剪
    都读它），且半径沿包含链严格递减 ⇒ 屏幕半径档位天然就是层级档位。
    + 公式 `fs = round(clamp(F_MIN + (F_MAX-F_MIN)*ln(sr/min_px)/ln(ref/min_px), F_MIN, F_MAX))`
      —— 对数插值才有尺度不变性（缩放是乘法，线性插值会让字号在中间段跳得太快）。
    + **必须取整**：`measure()` 的缓存 key 是 font 字符串，不取整等于每帧每个标签
      都新造一条缓存；而且 `browser_check.py:194` 要求三模式切回 auto 后
      `shownLabels` 精确复现，亚像素字号会让碰撞网格的判定漂。
    + 两条**宽度不变量**，缺一不可：① 圆内标签宽度 `<= 1.8*sr`，装不下就把
      `inside` 翻成 false 挂圆外（判定时用最小字号试，避免大字号把能装下的挤出去）；
      ② 圆外标签宽度 `<= lod.label_max_width`，超宽用 `clipLabel` 二分出最长前缀 + `…`。
      完整名字不丢——tooltip 和搜索走的是 `m.name`，不受截断影响。
    + `clipCache` 的 key 是 `(节点 id, font)`，同一节点在不同字号下各存一条，
      上界是「同屏标签数 × 字号档位数」，有界不泄漏。
    + `lod.label_smooth_dim` 只换了标签**落笔浓度**的读取路径（`fillAlphaOf`
      替代 `alpha.get`），候选**排序**仍读 `alpha.get()`。这是有意的不对称：
      排序要的是稳定的优先级，落笔要的是连续过渡。

24. **回归套件的 fixture 不要写完整路径**（2026-10-10 踩到）：`browser_check.py` 的 7d/侧栏
    用例原先把 SEL/TGT 硬编码成 `…/信号与系统#分解信号/…` 这样的**全路径**，
    用户把笔记改名成 `LTI analysis.md` 之后路径失配，`have_pair` 为假 →
    整段 7d 被当成「条件跳过」warn 掉，套件依旧 `ALL BROWSER CHECKS PASSED`，
    **但屏外 chip / fitPair 那 12 条断言已经悄悄不再跑了**（`[ok]` 从 84 掉到 72，
    这是唯一的可见信号；那批的基准是 84，现在的基准是 162，见 §8）。
    现在改成按**后缀**解析：在 `R.byId` 里找 id 以
    `/TAIL` 或 `#TAIL` 结尾的节点，再确认两端确实有语义边，解析不出来才 warn。
    教训：**「warn 只允许条件跳过」这条规矩本身不够**，还得盯 `[ok]` 总数有没有掉 ——
    条件跳过和覆盖丢失长得一模一样。

25. **`schtasks /Create` 默认禁止在电池上运行计划任务**（2026-10-11 踩到，用户报的
    「并没有后台每 30 分钟重建一次」的第二层根因）。默认写入的设置是
    `DisallowStartIfOnBatteries=true` + `StopIfGoingOnBatteries=true`，
    而用户是笔记本：只要在用电池，任务就**一次都不会跑**，症状极具欺骗性 ——

    | 观察 | 表面读到的 |
    |---|---|
    | `schtasks /Run` 返回「成功: 已尝试运行」 | 以为跑了 |
    | 任务属性 `上次结果: 0` | 以为是成功 |
    | 其实：进程没起、lock 没建、日志没写、dist 没动 | 真正的信号 |
    | 任务 XML `<Settings>` 里 `...OnBatteries=true`；`(Get-CimInstance Win32_Battery).BatteryStatus = 1` | 确诊 |

    修法（PowerShell，**让用户自己执行**，见 §7）：改完有电池限制的这几条即可，
    顺手打开「错过了就补跑」，笔记本合盖/睡眠错过的点不会再白丢：

    ```powershell
    $t = Get-ScheduledTask -TaskName "Knowledge Graph Auto Sync"
    $t.Settings.DisallowStartIfOnBatteries = $false
    $t.Settings.StopIfGoingOnBatteries     = $false
    $t.Settings.StartWhenAvailable         = $true
    $t | Set-ScheduledTask
    ```

    自查顺序（照抄就行）：`schtasks /Query /TN "..." /XML` 看 `<Settings>`，
    或 `[xml](schtasks /Query /TN '...' /XML)` 后在 PowerShell 里读 `.Task.Settings`。
    **`TaskScheduler/Operational` 事件日志在本机是关的**（`IsEnabled=False`），
    别指望从它拿历史，只能靠「任务属性 + 进程 + lock + 日志时间戳」四个证据交叉判断。

26. **两个 `.ps1` 必须存成「UTF-8 **带 BOM**」，而且字符串字面量保持纯 ASCII（本轮新增）。**
    `D:\obsidian_vault\hush-ob-bucket\quartz-setup\sync.ps1` 与 `knowledge-graph\sync-graph.ps1` 的
    **字符串**现在一律写英文，中文只留在 `#` 注释里 —— 这是刻意的纵深防御，别「帮忙翻译回去」。
    理由：**Windows PowerShell 5.1 读一个没有 BOM 的 `.ps1` 时，会用系统 ANSI 代码页去解码**。
    非 ASCII 字节一旦落在字符串字面量里，引号配对就被打乱、直接解析失败
    （典型症状 `字符串缺少终止符`、`缺少右"}"`，而且报的行号指到别处，极难往编码上想），
    而计划任务是**静默停摆** —— `sync.log` 不再增长、不报错、任务属性还显示上次成功。
    两件事一起做才有上面那句话的效果：
    * **存成 UTF-8 with BOM**（现在两个文件都是 `EF BB BF` 开头）。
      别用会把 BOM 抹掉的工具重存：格式化、批量替换、`Out-File -Encoding utf8NoBOM`、
      某些编辑器的「UTF-8」默认档都可能干掉它。
    * **字符串只用 ASCII**。即使 BOM 被剥掉，脚本照样运行，代价只是中文**注释**变乱码。
    自查：

    ```bash
    cd D:/obsidian_vault
    head -c 3 hush-ob-bucket/quartz-setup/sync.ps1 | od -An -tx1  # 应输出 ef bb bf
    head -c 3 knowledge-graph/sync-graph.ps1 | od -An -tx1
    ```

    （引号里有没有中文只能肉眼看：本机 Git Bash 的 `grep -P` 用不了，`[^\x00-\x7F]`
    这类写法在基本正则里也不支持，别指望一条命令查出来。）

    修法：用「UTF-8 with BOM」另存（PowerShell 里 `Set-Content -Encoding UTF8` 就带 BOM），
    新增日志消息写成英文。

27. **`cmd_scope` 的 stdout 必须**只有** JSON —— 所以 `main` 给它把横幅让开了。**
    `sync.ps1` 是把 `python build.py scope --scope public` 的**整个 stdout** 喂给
    `ConvertFrom-Json` 的，任何一行「顺便打印」的人话都会让解析失败 → fail-closed → `ABORT`
    → 这一轮完全不同步。`build.py` 的 `main` 里因此有一句
    `if command != "scope": print(横幅)` —— 那是为这个契约留的，不是随手写的。
    **别往 `cmd_scope` 里加 print**；想给人看范围概览用 `python build.py scan`
    （`scan` 会同时打印配置路径和「范围：… → scope …」这一行）。
    同理别给它传 `--scope all`：`main` 会对每个 scope 各调一次 `cmd_scope`，stdout 上就成了
    两段 JSON 首尾相接，`ConvertFrom-Json` 照样解析不了。同步脚本永远只请求单个 scope。

28. **`robocopy /MIR` 是镜像：清单错一次就把 `content/` 删空 —— 所以站点侧同步是
    fail-closed。** `sync.ps1` 现在从真源读镜像清单，只要下面任一条成立就写 `ABORT: ...`
    并 **exit 1、一条都不镜像**（日志里能看到，`content/` 原封不动）：

    * `python build.py scope --scope public` 退出码非 0（`python` 不在计划任务的 PATH 上也算这条）
    * stdout 为空，或 `ConvertFrom-Json` 抛错（见坑 27）
    * `mirror` 缺失/为空
    * 任何一条缺 `from` 或 `to`

    **这是有意为之，不要「简化」成 warning 后继续。** 另外两条别再改回去的细节：
    ① robocopy 的**源用 `from`、目标用 `to`**（`to` 是落地名，`Logs/Study log` → `Study log`），
    不要从 `from` 去推 `to`；② 镜像后还有一步 **prune**，把 `content\` 下不在清单里的**顶层
    目录**删掉（真源才是权威，范围里删掉的目录不能留着变成幽灵），`index.md` 是文件所以不受影响，
    prune 只在清单非空（`keep.Count > 0`）时才跑。

29. **`Logs/Study log` → `Study log` 的重映射：节点 id 与 `path` 是故意不一致的。**
    链路是这样串起来的，改任何一环之前先看全：
    * `kg/config.py:_scope_entries` —— 条目没写 `as` 就用目录名当落地名；`src != dest` 时
      往 `scopes[scope]["remap"]` 里加一条 `{from, to}`（`as` 只改**落地**名）。
    * `kg/scan.py:_remap_rel` —— 按**长前缀优先**替换，产出 `NoteFile.display`；
      `NoteFile.id` / `parts`（= 节点 id、层级、标签）走落地名，
      `NoteFile.rel` / `source_id` 保留**真实 vault 路径**（`obsidian://` 跳转靠它）。
    * `kg/graph.py:GraphBuilder._build_index` —— 把 `source_id → id` 登记进 `self.alias`，
      `resolve()` 因此仍能让按真实路径写的 `[[Logs/Study log/xxx]]` 解析到重映射后的节点。
      （没有这个别名索引，笔记里所有写全路径的链接会一夜之间全部变成「解析失败」。）
    * `verify.py` 有一条专门的断言：**「重写过的路径前缀没有残留成节点 id」（残留 0 个）**——
      它就是在防「某处忘了重映射、节点 id 还是旧前缀」这类半拉子改动。
    ⚠️ **别为了「统一」把 note 节点的 `path` 也改成落地名**：图谱侧栏的「在 Obsidian 打开」
    按钮读的是 `path`（`web/app.js` 拼 `obsidian://open?…`），改成 `Study log/…` 就跳不过去了。

30. **公开图谱 HTML 的体积账 —— `publish_graph` 默认 `false` 是算过的，别顺手改成 `true`。**
    那份 HTML 约 **8.7 MB**（`build.py` 打印的是 `8871 KB`，同一个文件，只是 MB/MiB 口径差）；
    站点仓库 `quartz-site` 近 60 天实测 **144 次提交 ≈ 2.4 次/天**（最后一次 2026-10-15 10:47:42 +0800）。
    （以上都是**示例快照 build5 = 2026-10-16 23:02** 的读数；下面这笔账的量级不随快照变。）
    每次内容变动都往仓库里提交一整个 HTML 就是 8.7 MB × 2.4 × 365 ≈ **7.6 GB/年**，
    而 GitHub 对仓库体积的建议上限是 **~1 GB**、Pages 发布产物也约 **1 GB**。
    所以默认只在本地产出 `dist/knowledge-graph.public.html`（范围与站点完全一致，只是不上站）。
    `publish_graph: true` 时 `sync.ps1` 才把它复制成 `content\knowledge-graph.html`，
    于是出现在 https://xidianhush.github.io/knowledge-graph.html 。
    注意它落在 `content/` **根**上、不在任何被镜像的目录里，所以坑 28 的 prune 不会碰它；
    反过来，**git 历史一旦写进去就收不回来**，开关之前先想清楚。
    两个配套细节：`publish_graph: false` 时站点脚本**连 `build --scope public` 都不跑**
    （省一次全量构建，本地那份由 `sync-graph.ps1` 的 `build --scope all` 负责）；
    真的开了之后构建失败只记一行 WARN、本轮沿用 `content/` 里已有的那一份，站点同步照旧不中断。

31. **内联 JSON 里绝不能出现裸的 `<` —— 否则整页白屏，而构建侧一声不吭。**
    `kg/emit.py::build_html` 把 payload 塞进 `<script type="application/json" id="graph-data">`。
    早先这里用 JS 字面量那套转义法：`data.replace("</", "<\\/").replace("<!--", "<\\!--")`。
    `<\/` 在 JSON 里合法（`\/` 是标准转义），但 **`<\!--` 里的 `\!` 是非法转义** ——
    JSON 只认 `\" \\ \/ \b \f \n \r \t \uXXXX`。于是浏览器 `JSON.parse` 抛
    `SyntaxError: Bad escaped character in JSON at position N`，`template.html` 里那段
    初始化脚本整个中断、`window.KG` 从未建立、画布全空；而**构建照旧成功、日志照旧
    `sync ok`**，只有双击打开才发现是白屏（2026-10-14 早上就是这么发现的）。
    触发门槛低得离谱：笔记正文里出现**一次** `<!--` 就够。实测
    `Science and Tech/Mathematics Basic/` 下三篇笔记（Analytic geometry / Elementary
    geometry / Linear Algebra）的 excerpt 里就有，而且它们在公开范围内 —— 两份图谱一起中招。
    修法：`data = data.replace("<", "\\u003c")`。一个裸 `<` 都不留，`</script>` 提前闭合
    与 `<!--` 让分词器进入 script-data-escaped 这两个坑一起堵掉；`\u003c` 是合法 JSON、
    解析回来仍是 `<`（Django 的 `json_script` 就是这么干的）。注意别用 `\"<\"` 之外的单字符
    替换法去"只转义 `</`"，那又会漏掉 `<!--`。
    配套：`build_html` 转义之后会再 `json.loads` 一遍自证，不合法直接 `EmitError`，
    让这类失败在构建期炸出来，而不是留给双击的人。
    排查这类白屏（症状是画布全空、连片头文字都没有）：DevTools Console 里跑一句
    `JSON.parse(document.getElementById('graph-data').textContent)` 就知道是不是它；
    `browser_check.py` 现在也会在 `window.KG` 等不到时把收集到的 pageerror 原样打出来
    （以前只报一句 `wait_for_function` 超时，看不出所以然）。

32. **`zMin` / `zMax` 是地标，不是墙 —— 别再给滚轮加回 `clamp`。**
    这两个值原来就是 `zoomAt()` 的夹取上下限，现在那里只夹 `ZOOM_HARD_LO = 1e-6` /
    `ZOOM_HARD_HI = 1e6`（常量在 `web/render.js:152`，夹取在 `zoomAt()`：
    `web/render.js:387-388`）。那道护栏只负责拦住「任何 bug 把 zoom 推到 0 / Infinity
    让画布静默失效」，**不是可用范围**。
    **为什么要放开**：`zMin` / `zMax` 是构图结论（「最小那个顶层学科刚好看得见」
    「最挤的节点舒服淡入」），不是内容边界；夹住的代价是用户「缩到想看的细节就到头了」，
    而越界其实完全可恢复。放开之后缩过头**不是崩**，是画布渐渐清空 + 全空白兜底提示
    （`web/render.js:588-600`）：`此处没有内容 · 往回滚一点，或按 Home / 双击空白回到默认视角`。
    这句措辞是故意两个方向都管用的 —— 老文案只写「向下滚回到更粗的层级」，在**缩得太远**
    那一侧方向是反的（这正是它被改掉的原因）。
    * **仍然夹着的地方**（工具自己去某个地方，不该跑出地标）：`homeZoom()`（`web/render.js:326`）、
      `focusOn()`（`:1518`）、`fitPair()`（`:1532`）、`zoomToDepth()`（`:1683` —— 所以顶栏
      层级胶囊和 `[` `]` 仍然落在地标内）。`zMin` / `zMax` 本身照旧由 payload 现算
      （`:284-285`：`zMin = rootNeed × zoom_out_floor`、`zMax = maxMz × zoom_in_ceiling`），
      并照旧作为 `KG.zMin` / `KG.zMax` 导出（`:1661`）。注意 **HUD 的层级读数与顶栏胶囊不是
      直接读这两个值的**：它们走 `enterAt(zoom)`（`web/app.js:137`），层级由 zoom 单向派生。
    * **两个方向都会空**。往小滚：圆的屏幕半径掉到 `lod.min_px` 以下，圆一个个淡出，
      默认那份实测**要滚 27 格**才连世界半径 1000 的根也没了（公开那份 18 格，它的 `zMin` 更低）。
      往大滚：撞上**本来就存在**的 maxzoom 规则（`web/render.js:552-556`：圆的屏幕半径
      `>= farCornerDist(cx, cy)` 就停画填充，`farCornerDist` 在 `:611`），视口同样会空 ——
      默认那份实测 **≈6.8× `zMax`**（z=472.2），公开那份 **≈6.9× `zMax`** —— bc6 那批**两份同档 z=472.2**
      （示例快照 bc6 = 2026-10-17 23:05）。**空在哪一档取决于
      payload 的形状 + 当批快照，不是常数**，所以别把「几倍 zMax」「几格滚轮」写成断言，只能写「会空、提示会画、
      能回来」。（bc5 那批 public 还空在 z=1888.9 = 4096× home ≈ **27.3× `zMax`**，当历史标本看。这一条以前在文档里
      写反过：说公开那份更早、0.4× `zMax` —— 那是错的。）
    * **找回手段三个**：`Home` 键（`web/app.js:549`）、双击空白、顶栏「重置」，三者都走
      `R.resetView()` 回到 `zHome`。`browser_check.py` 的 3c 段直接断言 `Home` 精确恢复到
      `meta["zHome"]`（容差 1e-6）—— 判据用「恢复到 zHome」而不是「比某个阈值大」，是因为
      小视口下 `homeZoom()` 自己会被夹到 `zMin`，前者才是真契约。
    * **`stats.focusEdges` 是屏幕空间的视觉计数，不是逻辑焦点集合 —— 别把 5b 的断言「收紧」回去。**
      （这一条对两种连线模式都成立，语义一致。）
      主绘制趟按视口裁剪圆（`web/render.js:545-546`），被主绘制趟那几道门挡下的焦点边再由
      `drawFocusEdges()` 按「解析到的在屏锚点」分组（`web/render.js:1120-1143`；**门数随连线
      模式变** —— `raw` **一道**、`agg` 三道，见坑 21。分组键的粒度后缀 `\0n` 只在 raw 下加
      （`:1135-1136`），agg 那套分组不受影响），
      所以**平移本来就会改变这个数**（实测公开那份 2 → 1；这不是 bug，它数的就是屏幕上的东西）。
      正因如此 5b 段断言的是「挪出去再挪回来，`focusEdges` 与相机逐位相同」，
      **不是**「平移过程中计数不许变」—— 后者必然假红，改成它等于把这条覆盖废掉。
      同理，方向键平移刻意**不碰** `selectedId` / `hoverId`（`panBy`，`web/render.js:1569-1575`）：
      鼠标拖拽的抖动会被 `dragMoved > 5` 判成点击（`:1631`），选中就切到光标下的大父圆上、
      焦点模式把想看的箭头一起滤掉 —— 方向键把「平移」与「点击」解耦，`panStep` 给的步长是
      视口宽的 1/8（`Shift` = 半个视口，≈4×），由视口现算、与 zoom 无关（屏幕空间的距离）。

33. **「画布全黑、却一个字的提示都没有」是兜底判据用错了量 —— 必须判 `stats.painted`，
    不能判「候选集是否为空」（本轮实测找到并修掉的真 bug）。**
    症状：放到很深时画布上 **0 个非背景像素**，而兜底提示一个字都不画 —— 用户看到的是一片
    纯黑，没有任何解释。最刺眼的是 public 那份：本轮实测 z = 5000 / 30000 / 1e5 / 1e6 四档
    全是 **`stats.nodes = 1`、`stats.painted = 0`**、整块画布只剩兜底提示那 2329 个像素
    （private 那份同档位是 `nodes = 0`，所以只有公开那份会踩中）。
    * **根因是几何判据错位。** 兜底原来判 `!wash.length && !front.length`，即「候选集是不是空」。
      而候选集里可以有一个**圆心远在屏外、半径极大**的圆：它过了视口裁剪（裁剪按半径外扩，
      `CULL_MARGIN` 就是为「圆心在屏外、圆本身却铺满整屏」留的），也过了 maxzoom 那道门
      （坑 32：`sr >= farCornerDist(cx, cy)` 才停画 —— 而圆心离屏越远 `farCornerDist` 同样越大，
      这个比值反而更容易过关）。放进来之后它的**填充**被 `fade` 压到看不见、**界线弧**又整条落在
      画布之外。净效果：`stats.nodes ≥ 1`、画布上一个像素都没有、兜底不画。
    * **为什么以前撞不上**：滚轮过去被 `zMin` / `zMax` 夹住，zoom 到不了这种极端。放开缩放
      （坑 32）**不是**引入了这个 bug，是把它**暴露**了 —— 死局早就写在那里。
    * **修法三件套**（都在 `web/render.js`）：
      ① 新常量 **`PAINT_MIN = 0.02`**（`:66`）：「这一笔算不算画出来了」的最低不透明度。
         低于它的落笔在 8 位画布上合成后与背景完全同值（≈0.2/255，四舍五入成 0），
         肉眼与像素读回都看不见 —— 所以判「空」必须按这个门槛算，不能按「有没有发起绘制调用」。
      ② 新函数 **`nearDist(sx, sy)`**（`:625-630`，圆心到**内容视口矩形最近点**的距离，圆心在
         视口内则为 0）与既有的 `farCornerDist`（最远角）配对，把「这一笔到底会不会落在画布上」
         变成可判定的几何：**圆盘穿过视口 ⟺ `near < sr`（填充可见）；
         圆环穿过视口 ⟺ `near ≤ sr ≤ far`（界线可见）**。
      ③ 新计数 **`stats.painted`**：每帧清零（`:570`），只在 `drawWash`（`:650-651`，填充看圆盘、
         界线看圆环）与 `drawNodes`（`:1305`，函数在 `:1298`）里**同时**满足「alpha > `PAINT_MIN`」**且**
         「几何上真的穿过视口」时才 +1；兜底改成 `if (!stats.painted)`（`:588`）。
         `KG.state()` 也把它导出成 `painted` 了（`web/app.js:608-615`）。
    * **`painted` 才是「屏上到底有没有东西」，`shownNodes` 只是候选集大小。** 断言、调试、
      写文档都别再拿 `shownNodes == 0` 当「视口空了」的判据：public 那份在极端缩放下
      `shownNodes` **恒为 1**（就是上面那个幽灵候选圆），拿它当判据的用例永远不会红。
      `browser_check.py` 的 3c 段因此把 break 条件从 `stats.nodes == 0` 改成 `stats.painted == 0`
      （见 §8 基线）。
    * **回归覆盖**：新增 **3d** 段，9 档缩放（0.005 / 0.02 / 0.1 / 0.4612 / 3 / 30 / 1000 /
      30000 / 1e5）× 4 种平移共 **36 组**，每组用整画布探针 `CANVAS_LIT`（数遍全屏与背景色
      `#0f1116` 不同的像素）断言「**没有任何一组留下空白画布且没有提示**」。修之前它在 public
      上扫得出违规组，修完 **0 组**（`nodes` 与 `painted` 一并读出来，方便一眼看出是哪一侧
      骗了人）。**别把 3d 的收尾改回 `resetView()`**：那是 364ms 的 tween，而极端 zoom 下每帧要
      栅格化半径上百万像素的圆弧、rAF 被拖住，tween 迟迟走不完 —— 测试要的是确定的起始状态，
      不是动画（§8 基线有实测到的假红）。

34. **画边有两种模式，`raw`（逐条链接）是默认，`agg`（按尺度聚合）是保留的设置项 ——
    别再假设「边一定随缩放聚合」。**
    用户的原始要求是：标题→标题的链接在**任何**缩放尺度都在，颜色和浓淡不变，只变**形状**
    （线的长度和走向 —— 线宽也恒定，见下）。`agg` 那条路恰好反着来：缩小到文件级时 heading
    级的边被并进一条聚合边、`count` 变成线宽、`count < WEAK` 再打 45% 折扣 —— 链接会**变淡、
    变少、最后消失**（坑 21 那三道门就是这么来的）。所以现在多了第二条画边路径 `drawRawEdges`
    （`web/render.js:835`，紧跟前面 `:822-834` 有一段注释写清它与 `drawEdges` 的三处根本
    区别），`raw` 是默认值（`web/app.js:73`）。
    * **两个容器之间细线的条数才是关联强度，端点永不换代表。** `raw` **不查**
      `aggregates[L]`、也**不沿 `parent` 链上移端点**：每帧遍历全部 `SEM`、每条原始边各画
      一条线，两端恒为真实节点自己的世界坐标（`rawAnchor`，`web/render.js:1031-1037`）。
      沿 parent 链找「此刻在屏的代表圆」的那套 `resolveAnchor`（`web/render.js:1014-1024`）
      **只服务 `agg`**。于是缩到文件级时 heading 级的边仍然从两个标题的真实位置出发，看起来
      就是**一条线穿进父级圆的内部** —— 这正是用户要的效果（「这里面应该还有更深层次的
      知识点」），别把它当 bug 修掉。缩放/平移只改线的长度和形状，**不换端点、不减少条数**。
      线宽恒为 `lod.raw_edge_width`（1.0 px，不随缩放变）；标记门槛走独立的
      `lod.raw_marker_min_len`（6 px，读成 `RAW_MARK_MIN`，`web/render.js:182-183`），见坑 20。
    * **`raw` 现在没有任何分组，每条边各画一条恒直的线。** 早先版本按无向键
      `(小 id)\0(大 id)\0type` 把同一对元素之间的边并成一「束」、再按 `lod.raw_edge_spread`
      沿法向偏离中线排成扇形（束越宽关系越强）。**扇形机制已整体删除**，`raw_edge_spread`
      这个键在 `kg/config.py` / `config.yaml` 里也不存在了：真实端点本来就散在父圆内部的
      不同位置，一束线天然散开，用户「在某些视角看成一堆线」是可接受的（放大就查得清），
      换来的是「一条链接 = 一条线」这个不会被任何机制改写的契约。关联强度完全由条数表达。
    * **笔记级 vs 标题级用颜色区分粒度。** 近白 `theme.note_edge`（`#E6EDF3`）= 整篇级链接
      `[[笔记]]`，彩色 = 标题级链接 `[[笔记#标题]]`（按关系类型着色）。同一对元素之间的两种
      粒度**同时画**，靠颜色分辨（`NOTE_EDGE_RGB` / `NOTE_MARK_RGB`，`web/render.js:176-177`；
      补画那趟 `drawFocusEdges` 的分组键上还带一个粒度后缀 `\0n`，来自 `e._nl`，**只在 raw 下
      加**（`web/render.js:1135-1136`），agg 的分组不受影响 —— 必要性：note 级边
      「LTI→Calculus」和 heading 级边「LTI#CTFT→Calculus#定积分」在文件级会解析到同一对
      锚点、同为 derives，不加后缀就被并成一条）。
    * **`raw` 下 alpha 恒为 1，焦点/悬停压暗保留。** 不乘端点淡入进度、不乘弱边 45% 折扣
      （那两项都随 zoom 变，正是这里要去掉的东西）；`FOCUS_DIM` / `HOVER_DIM` 的压暗照旧。
      补画那趟 `drawFocusEdges` 也跟着分模式：`raw` 时线宽恒为 `RAW_LW + 0.8`、alpha 恒为 1
      （`web/render.js:1156-1158` 线宽、`1161-1162` alpha），`agg` 时才按 `count` 加粗打折。
    * **切换入口与持久化**：顶栏 `<select id="edgemode">`（`web/template.html:165-167`，
      两个 option `raw` / `agg`），change 时写 `R.edgeMode` 并存 `localStorage` 键
      `kg.edgeMode`（`web/app.js:572-574`），启动时读回并接线（`:581-582`）。**存了未知值就
      归一化回 `'raw'`** —— `web/app.js:88-89` 只接受这两个字面量。private / public 两份
      共用同一个键，所以在一边切了另一边也跟着变。图例也分两套：`#legend-rel-raw`
      （默认可见）与 `#legend-rel-agg`（`hidden`），由 `applyEdgeLegend()` 按
      `edgeMode !== 'agg'` 切（`web/app.js:205`）。`KG.state()` 导出 `edgeMode`
      （`web/app.js:628`），测试就是读它。
    * **`raw` 是两种模式里更重的那个**（落笔数明显更多）：实测 home 视角 private 那份
      raw 96 条边 / 130 个端点标记，agg 只有 22 / 28（示例快照 bc6 = 2026-10-17 23:05）。
      所以两种画法都留着，**别删 `agg`**。
      `stats.focusEdges` 这一条两种模式语义相同（坑 32 最后一条）。
    * **断言纪律**（`browser_check.py` 的 1c 段 + 7b/7c/7d 双轮，见 §8）：硬不变量只有
      **`raw >= agg`**；「严格更多」只要求在 home 或**某一层**成立，**绝不绑定到具体某层**，
      也**绝不断言 raw 在任一给定层非零**（**曾经出现过** public 最深那档两边同为 0 条；
      本次快照（bc6）private 的 `agg` 在最深三档 L=10/9/8 就真是 **0 条边**（同期 raw 是
      12/14/16 条）—— 那是数据形状，**不是不变量**，绑上去就是假红）。
      同样**绝不断言 `shownEdges` 跨缩放恒定** —— 它是视口绑定的（private raw 实测从 L=10 的
      12 条一路到 L=1 的 96 条，示例快照 bc6 = 2026-10-17 23:05）。用户真正要的那句保证
      （「缩小后链接不消失」）由 `fitPair`
      那条覆盖：同一对笔记 raw 画出 `focusEdges = 2 / marks = 4`，agg 只有
      `focusEdges = 1 / marks = 2`。

35. **(a2)「两端都在屏外」这条 fixture 必须沿「远离另一端」的方向推 —— 推错方向时 `chips=0`
    是正确行为，断言红得毫无信息量。**（2026-10-18 踩到）
    第一版写法是 `R.panBy(-(3000 + n._r*zoom), 0)`，只往左推：SEL 落到 x≈-2321，
    可 TGT 本来就在 SEL 的**左上方**（屏空间单位向量 `u≈(-0.778, +0.628)`，与 zoom 无关），
    于是 TGT 被推到 x≈-23870 —— **两端同在视口左侧、连线压根不与视口相交**，被 `drawRawEdges`
    的 bbox 门（`web/render.js:859-862`）挡掉、记进 `droppedFocus`；`drawFocusEdges` 对这类边
    **只计数不落笔** ⇒ `laid` 为假 ⇒ 两端 chip 分支（`:898-914`）不触发。
    正确写法是先求方向、再按视口对角线长度推：`u = (B-A)/|B-A|`、
    `push = hypot(W, Hc) + A._r*zoom + 60`、`R.panBy(-ux*push, -uy*push)` ——
    这样 A 出屏的同时 B 必在**另一侧**出屏，线段一定横穿视口。
    顺带记一个纯 Python 的坑：那段 fixture 原先写作 `b = page.evaluate(...)`，
    把 `browser_check.py` 顶部的 `b = p.chromium.launch(channel="chrome")` 覆盖掉了，
    一路跑到底才崩在 `b.close()` → `AttributeError: 'dict' object has no attribute 'close'`。
    变量已改名 `a2`；**别在同一个作用域里复用单字母的浏览器句柄名**。

36. **`#legend .row` 是 flex 容器 —— 行内文字必须整段包在 `<span class="tx">` 里。**
    （2026-10-20 修的真实 bug）`<div class="row">缩放<b>只改长度</b>，不改颜色…</div>` 这种
    写法里，浏览器会把**裸文本片段也各自变成匿名 flex item**：`缩放` / `<b>…</b>` / `，不改颜色…`
    就是三个 item，在 254px 宽里被挤成三列互相覆盖，整段说明不可读。
    现在每行固定两个子节点：图标（`.sw` / `.dot` / `svg`）+ `<span class="tx">`，
    `.row` 用 `align-items:flex-start`，图标靠 `margin-top` 对齐首行。
    自查：`document.querySelectorAll('#legend .row')` 里每个的 `childNodes.length` 必须是 1（纯文字行）
    或 2，且不能出现 `nodeType === 3` 的裸文本节点。
    ⚠️ 面板高度（展开态约 838px）**主要是内容量决定的**，不是这个 bug —— 别指望修完它面板就变矮。
    `#legend` 有一条 `max-height: calc(100% - 58px)` 的兜底，保证任何视口高度下都不钻到 46px 顶栏底下；
    行距（`.row` 的 `margin`）调到 2px 就会顶到这条上限、面板内部出现滚动条，所以留 1px。

37. **图例的折叠开关只能切 `.collapsed` 类，绝不许动 `#legend-rel-raw` / `#legend-rel-agg` 的 `hidden`。**
    （2026-10-20 新增功能）那两个 `hidden` 是「当前连线模式用哪套图例」的状态，
    `browser_check.py` 的 1c 段直接读 `element.hidden` 断言（`LEG = "(id) => document.getElementById(id).hidden"`）。
    折叠走 `#legend.collapsed #legend-body { display:none }`，与 `hidden` 正交，两条断言互不干扰。
    状态存 `localStorage` 键 `kg.legendCollapsed`，默认展开（不写 = 展开，截图基线与老行为都不变）；
    快捷键 `L` 走 `app.js` 的 keydown，和 `Esc`/`Home`/`[`/`]` 并列。

38. **`browser_check.py` 的 `PICK_NODE` 必须扫整数屏幕像素。**（2026-10-20 修）
    它原先按 `x += 5` 从 `W*0.28` 累加，坐标带小数（如 `483.2`）。`page.mouse.click()` 会把坐标截成
    整数（`483`），而 `hitTest` 的判据是 `d <= max(_sr,4)+3` —— 扫描点若落在某个圆的边缘 1px 内，
    截断后正好出圈、命中它的父圆，于是「探针说 A、真实点击选中 B」。
    症状极具欺骗性：private 那份恰好不踩（483→523 换了位置），**只有 public 那份红 2 条**
    （`click selected a node` 与 `breadcrumb has clickable ancestors`），而且退回提交版照样复现
    —— 是测试自身的问题，不是渲染缺陷。现在从 `Math.ceil(...)` 起算、步长 5 全是整数。
    教训：**凡是「先探针取坐标、再真实 mouse.click」的用例，坐标必须整数**，否则会在圆边缘随机假红。

---

## 5. 调参地图

### `config.yaml`

| 想改什么 | 键（当前值） | 调它会发生什么 |
|---|---|---|
| 公开范围 | **不在本文件里** | 去 vault 的 `quartz-setup/public-scope.yaml` 改（唯一真源，见 §4 坑 26–30）。改任何一条 `content`/`assets`/`exclude` 都会让节点数、`r`、`zMin/zMax/zHome` 全部重算 |
| 范围真源在哪 | `scope_file`（vault 里的 public-scope.yaml） | 文件缺失/写坏**直接报错退出**，不会静默退回某个默认范围。`config.yaml` 里那句 `# 想改「公开哪些文件夹和笔记」→ 不要改这里` 就是这条 |
| 建哪几份、各输出到哪 | `scopes:`（`private` / `public`，各自的 `output.json` / `output.html`） | 这里的**键就是 `--scope` 的合法取值**，顺序有意义：不指定 `--scope` 时建第一个（= private）。private 刻意沿用旧文件名 `dist/graph.json` / `dist/knowledge-graph.html`（用户双击的习惯），public 用 `.public` 后缀。加一个新 scope 只需在这里加一个键 + 在 `public-scope.yaml` 里给目录写上这个名字 |
| 公开图谱要不要上站 | `public-scope.yaml` 的 `publish_graph`（false） | 站点侧同步脚本据此决定要不要把 HTML 复制进 `content/`。体积账见 §4 坑 30 |
| 滚轮手感 | `zoom.wheel_step`（1.12） | 一格的缩放倍率（以光标为锚点）。10 层走完约 45 格，调大则层级切换更粗 |
| 换层/跳转动画时长 | `zoom.transition_ms`（260） | 点层级胶囊 / 搜索结果跳转的相机动画 |
| 子节点浮现后父圆压暗到多少 | `zoom.parent_dim`（0.22） | 父圆填充是子圆的底色，调到 0.5 会把同色子圆整体压暗（§4.8） |
| 缩到最外层的余量 | `zoom.zoom_out_floor`（1.05） | **必须 ≥ 1**。它把 `zMin` 定成「最小的那个顶层学科刚好看得见」的**地标**（不是滚轮下界，见 §4 坑 32），取 0.9 会让最小那个根在最外层只剩 16.2px < `min_px`，「缩到最外层看见全部 6 个学科」当场破掉。1.05 留 5% 余量抵消落盘时 `r` 只保留 4 位小数的舍入。也决定 2 号判定：地板处每个顶层学科都在画面上 |
| 放大上界的余量 | `zoom.zoom_in_ceiling`（1.35） | 最挤节点完全浮现所需的 zoom × 此值 = `zMax`，即「最挤的节点舒服淡入」那个**地标**（不是滚轮上界，见 §4 坑 32）。调大 → 上界更松；调小 → 还没淡完就到头 |
| 初始视图松紧 | `zoom.home_fit`（1.08） | 刚好装下全图的 zoom × 此值。**上限是 `layout.padding` = 1.12**，再大就会把 Science and Tech 裁出屏幕。1.08 时六个学科全部完整落在视口内（最小根 20.4px，最大根包围盒 411.7px / 视口半高 427px） |
| **同级里的大小差** | `layout.size_exponent`（0.5） | 目标半径 ∝ 叶子数 ^ 此值。**0.5 是无标度不动点**（`√(ΣTᵢ²) = √(ΣLᵢ) = T_parent`），每层缩放退化成与分支数无关的常数 ≈0.85。调大 → 深层膨胀、根 spread 上升（0.6 时 16.2× → 28.3×，最小学科在 home 只剩 18.2px，贴着 `min_px` 没余量）；调小 → 深层急剧缩小、`zMax` 爆掉、缩放跨度拉长 |
| **层级间的大小差** | `layout.level_ratio`（1.5） | 父圆半径 ≥ 最大子圆 × 此值。独子链打包出的包围圆就等于子圆自己，光靠 `padding` 只有 1.12×，肉眼分不出父子；1.5 才看得出（实测 340 条独子链的比值精确落在 1.500） |
| 兄弟圆之间的留白 | `layout.padding`（1.12） | 父圆半径 ≥ 子圆包围圆 × 此值。它同时是 `zoom.home_fit` 的硬上限 |
| 世界坐标量级 | `layout.norm_root_radius`（1000.0） | 虚拟根归一化后的半径。钉住坐标量级，使 JSON 体积可控、`zMin/zMax` 不随 vault 增长而漂移。改它等于等比缩放整个世界（观感不变，但落盘精度与 JSON 体积会变） |
| 退化子树 / 孤点的兜底半径 | `layout.leaf_radius`（1.0） | 正常叶子的半径由缩放链决定，这个只兜底 |
| 整体旋转 | `layout.start_angle`（-90） | 打包完再整体旋转的角度。**同输入必得同输出**是同步任务的硬要求，别引入随机性 |
| **浮现早晚（最小屏幕半径）** | `lod.min_px`（18） | 一个圆值得被画出来所需的最小屏幕**半径**（不是间距）。它同时决定 `zMin`（最小学科根在 `zMin` 处恰好是 `min_px × zoom_out_floor`）与同屏圆数上界 `(视口半径/min_px)²`。调小 → 同屏更挤、缩放跨度整体拉长 |
| 淡入带宽 | `lod.fade_span`（1.35） | zoom 从 `minzoom/fade_span` 升到 `minzoom`，alpha 从 0 走到 1。滚轮每格 1.12 ⇒ 约 2.6 格淡完，不会突兀 |
| 标签参与竞争的门槛 | `lod.label_alpha`（0.12） | 读的是**未被 `parent_dim` 压暗的**淡入进度（§4.8）。门槛是「低于它完全不画」的**硬开关**：0.55 会让文字在 55% 不透明度处啪地弹出，0.12 才拿到真正的 0→1 淡入淡出（多出的 zoom 带宽仅 1.096×，约 +24 个候选，远低于预算）。标签另受 24px 碰撞网格与每帧 400 条预算限制 |
| 标签字号下限/上限/参考半径 | `lod.label_font_min`（11）/ `label_font_max`（22）/ `label_font_ref`（300） | 字号绑**屏幕半径**而非 depth：`fs = round(min + (max−min) × ln(sr/min_px) / ln(ref/min_px))`，落点 18→11、40→14、100→17、≥300→22（§4.23）。**不要改成按 depth 分档** |
| 浅层标签半粗门槛 | `lod.label_bold_depth`（2） | depth ≤ 此值的标签用 600 半粗。粗细是「类别」信号、字号是「尺度」信号，两者不冲突 |
| 圆外标签最大宽度 | `lod.label_max_width`（180） | 缩到 `label_font_min` 还超宽就截断加 `…`（完整名字在 tooltip/搜索里）；圆内连下限字号都装不下的长名字自动改挂圆外再受本键收口（§4.23） |
| 标签压暗是否走平滑版 | `lod.label_smooth_dim`（true） | true = 标签不透明度跟 `fillAlphaOf`（随最先浮现的孩子同步渐变）；false = 回到 `alphaOf` 的硬跳变（越过 `_gate` 时祖先标签从 ~1.0 瞬跳到 `parent_dim`）。**只换落笔浓度**：候选排序仍读 `alpha.get()` |
| 弱聚合边压暗阈值 | `lod.weak_edge_min_count`（2） | 聚合边 `count` 低于此值时压到 45% 不透明度（关系弱，别抢戏）。**只对 `agg` 生效** —— raw 模式 alpha 恒为 1（§4 坑 34） |
| **raw 模式的连线线宽** | `lod.raw_edge_width`（1.0） | 屏幕像素，**刻意不含任何 zoom 因子**：raw 模式下缩放只改线的长度，粗细、颜色、透明度全部恒定 —— 用户要的就是「同一批线在任何尺度上都在，且看起来是同一批线」。想让整束线更醒目就调大它，**别去改 alpha**。校验要求必须是正数 |
| **raw 模式端点标记的最短线长** | `lod.raw_marker_min_len`（6） | 屏幕像素，**刻意独立于 agg 的 `edge_marker_min_len`（20）**：raw 的线恒为 1 px 细线、标记尺寸钉在下限 7px，沿用 20px 的门槛会把大量真实链接的箭头一起压掉，而 raw 的契约恰恰是「每条链接都看得见」。填 **0 = 恒画标记**，填 **20 = 与 agg 同门槛**。校验要求非负 |
| **raw 模式整篇级链接的颜色** | `theme.note_edge`（`#E6EDF3`） | 近白 = 笔记→笔记的整篇级链接 `[[笔记]]`，彩色（`theme.edges`）= 标题→标题的 `[[笔记#标题]]`；同一对元素之间两种粒度**同时画**、只靠颜色区分（§4 坑 34）。选近白是因为七个色相已被 `domains` 占满，而 `#4C8DFF` 同时是 `derives` 的边色和 Science and Tech 的节点色，再拿它区分粒度会和域色/关系色双双撞车。端点标记色由它 `tintLight` 派生，不单独配 |
| 焦点模式无关连线压到多少 | `lod.focus_edge_dim`（0.07） | 选中节点后，与它（含其内部子元素）无关的连线压到此不透明度。**0 = 彻底不画**，1 = 不压暗。默认 7% 是有意留残影：保住「这片区域连得多密」的环境感知（Obsidian graph view 也是淡到约 10% 而非删掉） |
| 屏外端点名字 chip 最多挂几枚 | `lod.focus_offscreen_chips`（8） | 焦点边一端在屏外时，视口边止点旁挂写屏外端点名的 chip（§4.22）。**`raw` 下两端都出屏也挂一枚**，名字给非焦点的那一端（§4 坑 22）。超出截断、右下角折叠成一枚 `+k`；设 0 = 全部折叠成 `+k`（视口边箭头/圆点照旧） |
| hover 时连线压到多少 | `lod.hover_edge_dim`（0.75） | 只轻微提亮、不过滤。hover 每帧重算（`evalHover`），相机 tween 时会连续换节点，做强过滤会频闪 |
| **连线两端离圆边多远截断** | `lod.edge_trim_clearance`（2） | 屏幕像素。线不再画到圆心，两端各留这么宽的空隙，端点标记正好落在这里。0 = 线插进圆心（箭头会被圆盖掉，§4.20）。调大 → 线和标记离圆更远，短边更容易被 `edge_marker_min_len` 判死 |
| **多短的边不画端点标记** | `lod.edge_marker_min_len`（20） | 屏幕像素。截断后剩余长度低于此值的边**整条不画**（线也一起不画），免得密集层剩一堆盖不住圆边的碎箭头。调小 → 深层标记更多更碎；调大 → 只有长边才有方向信息 |
| **端点标记提亮多少** | `lod.edge_marker_tint`（0.55） | 标记色 = 边色向 `#d6dbe4` 混白的比例，取值 `[0,1]`。必须 >0：边色与节点 domain 色是同一个 `#4C8DFF`，不提亮的话箭头贴在圆边上隐形（§4.20 ①）。1 = 标记全变成浅灰 |
| 链接权重 | `weight.wiki_link` 1.0 / `heading_link_bonus` 0.5 / `embed_factor` 0.6 / `annotation_default` 3.0 | |
| 边的来源优先级 | `precedence: [annotation, frontmatter, wiki]` | 靠前的先决定 `weight` / `mastery` |
| 学科配色 / 边配色 | `theme.domains` / `theme.fallback` / `theme.edges` | 父子同色是刻意的（整条包含链继承学科色），别给子节点单独配色（§4.11）。`theme.domains` 现在有 7 个键：private 的 6 个学科 + `"Study log"`（public 的第三个根，`#F0883E`）——缺色的根会落 `fallback` 灰，所以新增公开根时记得补一行 |
| 候选边挖掘松紧 | `candidates.min_score` 0.45 / `min_term_len` 4 / `max_doc_freq_ratio` 0.25 / `min_shared_terms` 2 / `max_suggestions` 400 / `generic_headings` | |

### `web/render.js` 顶部常量

| 常量 | 值 | 作用 |
|---|---|---|
| `FOOTER_H` | 46 | canvas 的底部预留带：内容视口 = `H - FOOTER_H`，适配半径与 `farCornerDist`（判定「圆铺满视口」）都按它算。`#footer` 本身是右下角绝对定位块，改这个值等于改铺满判定，别随手调（§2） |
| `LABEL_CELL` | 24 | 标签碰撞网格边长（屏幕像素） |
| `LABEL_BUDGET` | 400 | 每帧最多考虑多少个标签候选 |
| `CULL_MARGIN` | 32 | 视口外扩余量。裁剪必须**按半径外扩**：大圆的中心常常在屏幕外，圆本身却铺满整屏 |
| `LABEL_INSIDE_PX` | 28 | 屏幕半径超过这个值的容器，标签压在圆内顶部而不是圆心；亦是「圆内装不下就改挂圆外」的条件之一（§4 坑 23） |
| `PAINT_MIN` | 0.02 | 「这一笔算不算画出来了」的最低不透明度。低于它的落笔在 8 位画布上合成后与背景完全同值（≈0.2/255，四舍五入成 0），肉眼与像素读回都看不见。`stats.painted` 与全空白兜底提示都按它判 —— 所以**不能**改成「有没有发起过绘制调用」那种计数（§4 坑 33） |
| `FONT` | 系统字体栈 | **字号不是常量**：由 `labelFontSize(sr)` + `fitFont` + `clipLabel` 三个函数按屏幕半径算出来（调参走 `lod.label_font_*`，见 §5）。行高 `hpx = fs + 4`；圆内摆放 `sy = cys - sr + fs*0.5 + 4`，任何字号下文字上边界都离圆描边 2px |

旧表里的 `HIT_CELL` **已不存在**：拾取不再用网格，`hitTest` 就是对 `lastDrawn` 的线性扫描
（同屏圆数被 `min_px` 钉成常数上界，最多一百多个，不需要空间索引）。

`TRIM` / `MARK_MIN` / `MARK_TINT` 也在文件顶部，但它们是 `lod.edge_*` 三个键的读取结果
（`== null` 兜默认，不是 `||` —— 0 是合法值），改数值请改 `config.yaml`，别改这里。
`MARK_LIGHT`（`#d6dbe4`）与 `MARK_RGB`（按 tint 预混好的标记色表）是硬编码的，
换主题配色时要一起看。

`CHIP_MAX` 同模式读 `lod.focus_offscreen_chips`（缺省 8）；折叠的 `+k` chip 右锚在
`(W-12, H-FOOTER_H-12)`，即右下角、避开 footer 预留带——改 `FOOTER_H` 会连带挪它。
`chipJobs` 一共四处入队（`web/render.js:893` raw 单端 / `:911` raw 两端都出屏 /
`:1209` `drawFocusEdges` / `:1219` `+k` 折叠），上限对四处**合起来**生效。

方向键平移**没有常量、也不读配置**：`panStep(fast)`（`web/render.js:1581-1585`）按视口现算 ——
一步 = `max(40, W/8)` × `max(40, (H-FOOTER_H)/8)`，`Shift` 时换成半个视口（≈4×）。
下限 40px 是给极小窗口兜底的，别删。理由见 §4 坑 32。

---

## 6. 待办清单（按建议顺序）

**P0 — 已完成**：看图验收；两个改进需求（同步方案、实心圆/细线/跨层级链接淡入淡出）；
**布局重构（同心环 → circle packing）+ 用户四条新要求**（同级内容多者圆更大 / 层级间大小
有区分 / 子在父内且同色 / 地图式淡入淡出）；**焦点模式**（选中即过滤连线 + 邻居蓝环）；
**连线端点标记**（两端截断 + 源点/箭头 + 标记提亮 + 祖先链改点线 + 图例说明）；
**屏外焦点边兜底**（视口边箭头/圆点 + 屏外端点名字 chip + 侧栏边行点击 fitPair 框住两端），
Python 侧、渲染侧、浏览器回归套件都已适配，并已分别提交（第10步、第11步、第12步）。

**P0 — 已完成并提交**：**标签字号绑屏幕半径 + 淡入淡出平滑**（§4 坑 23）
—— 新增 6 个 `lod.label_*` 键（字号三键 / bold_depth / max_width / smooth_dim）
并把 `label_alpha` 从 0.55 降到 0.12，观感不满意可以**全部在 `config.yaml` 里回退**，
不用碰代码；渲染侧与浏览器回归套件都已适配（`verify` 全绿、`browser_check` 84 [ok] / 0 FAIL
—— 那一批的基准；现在是 162 [ok] / 0 FAIL，见 §8；截图已人眼复核）。同批还修了回归套件的
fixture：改成按后缀解析，笔记改名不再让 7d 整段静默跳过（§4 坑 24）。已提交（第13步 `b528d2d`）。

**P0 — 已完成（本轮，未提交）**：**修掉「画布全黑却没有任何提示」这个真 bug** ——
兜底判据从「候选集是否为空」改成 `stats.painted`，新增 `PAINT_MIN` 与 `nearDist`（见 §4 坑 33）；
同时补上 3d 段「任何缩放 × 任何平移都不许留下无提示的空白」的 36 组整画布探针，
并订正两条被写错的断言（§8）。断言基线 103 → 108 → 156 → **162**（156 是加了「连线模式切换」1c 节、
并把焦点/标记/屏外兜底三段改成 raw / agg 两种模式各跑一遍之后的数；162 是再加 (a2)
「两端都在屏外」一段，3 条断言 × 2 种模式）。

**P1 — 让「掌握度/重要度」真正起作用**
`annotations.yaml` 是空的，111 篇笔记（private，示例快照 verify6 = 2026-10-17 00:15）`mastery` 全是 0，
暗色细边看不出来。
可选：提示用户填几条；或做 `build.py suggest-annotations`，按「标题数 / 链接数 / 行数」
给出初始 `weight` 建议草稿供人工审核。**绝对不要自动写进用户的笔记。**

**P2 — 候选边审核流程**
`candidates.yaml` 手工改 `status` 很累。可在页面里加「审核模式」：列出候选边，
点 accept/reject 后**导出 YAML 文本**给用户自己粘回文件（保持工具不写用户文件的边界）；
或写 `build.py review` 交互式命令行逐条确认。

**P3 — 规模压测**
当前 3558 节点（private，示例快照 verify6 = 2026-10-17 00:15）、idle rAF 63 fps（示例快照
bc6 = 2026-10-17 23:05）。没测过上限。可做：临时把范围放宽到全 vault
（在 `public-scope.yaml` 里给 `Logs`、`Excalidraw` 之类加一条 `scopes: [...]` 就行，
**不要去改 `config.yaml`**——`include` 这个键已经不存在了）；或造 1 万节点合成数据测深层渲染
与拾取。已知热点是标签竞争与聚合边重建；`raw` 模式落笔更多（home 视角 raw 96 条边 /
130 个端点标记，agg 只有 22 / 28；示例快照 bc6 = 2026-10-17 23:05），是两种画法里更重的
那一个；拾取现在是线性扫描 `lastDrawn`，规模上去后也要
回头看一眼。

**P4 — 语义质量**
- **14 处 `[[笔记#标题]]` 锚点未命中**：Obsidian 的锚点匹配更宽松。
  放宽逻辑在 `kg/graph.py` 的 `_normalize_heading()`。先打印出这 14 处看看是什么再决定。
- **中文不分词**，候选边只覆盖英文术语与 LaTeX 符号。引入 jieba 是新增依赖，需先问用户。
- **`derives` 方向语义模糊**：可在侧栏加「改这条边的类型」并导出 `annotations.yaml` 片段。

**P5 — 已完成（本轮）：统一公开范围定义**
站点侧（当年 `quartz-sync-task\sync.ps1` 的 `$dirs` 数组 —— 那个目录 2026-10-14 已删除，
脚本搬进 vault 的 `hush-ob-bucket\quartz-setup\sync.ps1`）与图谱侧（`config.yaml` 的 `include` 白名单）
过去是两份互相矛盾的手工清单：站点发的是 `Science and Tech` / `Projects` / `Logs/Study log` /
`Attachment`，图谱画的是另外 6 个学科目录。现在**只剩 vault 里的
`quartz-setup/public-scope.yaml` 一份**：

- 站点镜像清单 ← `build.py scope --scope public`（sync.ps1 解析它的 JSON，见 §4 坑 27/28）
- 公开图谱范围 ← 同一个 scope 的 `content` 条目（`assets` 只镜像、不进图）
- 私有图谱范围 ← 同一份文件里 `scopes` 含 `private` 的那些条目
- 站点发不发公开图谱 ← 同一份文件的 `publish_graph`（见 §4 坑 30）

⚠️ 这轮改动**仍在工作区未提交**（§0），提交前别当成已入库。

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
  （2026-10-10 那轮只换了标签不透明度的**读取路径**：`lod.label_smooth_dim`
  默认 true 时落笔浓度改读 `fillAlphaOf`，消除越 `_gate` 时 ~1.0 → parent_dim
  的瞬跳；候选排序仍读 `alpha.get()`。`alphaOf` 函数体一字未动。）
- **不要把「公开哪些目录」再写回任何脚本或 `config.yaml`**（P5 刚拆掉的就是这两份），
  也不要在 `public-scope.yaml` 里为「顺手」加与范围无关的配置——它是两份 scope + 站点
  三方共用的文件，改它等于改发布面。
- **不要动两个 `.ps1` 的编码**（必须是 UTF-8 **带 BOM**，见 §4 坑 26）；
  也不要往 `cmd_scope` 里加任何非 JSON 的 print（见 §4 坑 27）。

---

## 8. 回归基准（改坏了怎么发现）

下面的具体数字是**示例快照 build5 = 2026-10-16 23:02 / bc6 = 2026-10-17 23:05** 的读数（口径见
§3 快照章；只有 chip 与 (a2) 那几行换成了 **bc8 = 2026-10-18 22:46**，因为它们被改动②直接影响），
会随 vault 内容漂移；**要盯的是「全绿 / 0 FAIL / 162 ok」这些结构性结论，不是这些绝对数**。

```bash
python build.py build      # private：笔记 111 / 文件夹 35 / 标题 3412 / 节点 3558
                           # 深度轴 10 / 语义边 97 / 包含边 3552 / 标题级链接 68（未命中 14）
                           # layout_root_radius 1000.0 / nominal_fit_radius 427px / HTML 8957 KB
python build.py build --scope all   # 再出一份 public：节点 3518 / 最深层 3611 条边 / HTML 8871 KB
python build.py verify     # 必须 ✓ 全部自动校验通过（--scope private 与 --scope public 都要绿）
python build.py scope --scope public   # stdout 必须是一段能 ConvertFrom-Json 的 JSON（§4 坑 27）
python browser_check.py    # 必须 162 [ok] / 0 FAIL / ALL BROWSER CHECKS PASSED（两份都是 162）
                           # （warn 只允许条件跳过，不允许失败；[ok] 数掉下去
                           #   就说明有用例被跳过了 —— 见 §4 坑 24）
                           # 默认查 private 那份 HTML（dist/knowledge-graph.html）；
                           # 换 public：KG_HTML=knowledge-graph.public.html python browser_check.py
node --check web/app.js && node --check web/render.js   # 前端语法（一次只查一个文件）
```

`verify` 里最该盯的三条不变量——它们破了，「子在父内」和「放大 = 更深」就都不成立了：

1. **包含越界 0 个**（每个节点都完整落在父节点圆内）；
2. **兄弟相交 0 对**（private 当前 6841 对，示例快照 verify6 = 2026-10-17 00:15）；
3. **`r` 沿包含链严格递减**（违反 0 个）⇒ `minzoom` 严格递增 ⇒ 孩子绝不会比祖先先浮现。

另加本轮新入的那条（换 scope / 改 `as` 时最容易踩）：**重写过的路径前缀没有残留成节点 id**
（残留 0 个），以及 depth=1 的根 == 该 scope 声明的目录（private 6 个 / public 3 个）。

浏览器里再确认（下面的读数全部来自**示例快照 bc6 = 2026-10-17 23:05** 那一批 payload 上的
`browser_check.py` 实跑，1440×900；会随 vault 内容漂移，要刷新就重跑那个套件 ——
数据侧同一批参数见 §3。口径与 §3 快照章一致，**不要**把这里任何单个数字当不变量断言）：

```js
KG.state()                 // zoom 0.4610 / level 1 / shownNodes 55 / shownEdges 96（raw；agg 是 22）/ shownLabels 26
KG.zMin                    // 0.36784526 （最小学科根决定 × zoom_out_floor 1.05；与数据侧同值）
KG.zMax                    // 68.97530514（最挤节点 minzoom × zoom_in_ceiling 1.35）
KG.zHome                   // 0.4612   （home_fit 1.08；这一项读真实视口，会小幅浮动）
KG.renderer.setZoom(KG.zMin); KG.visible()
                           // 6 个学科根全部可见（shownNodes 47），**且它们的子圆也仍在画面里** ——
                           // 不再「只剩 6 个节点」，这正是 packing 与同心环的根本区别
                           // ⚠️ 现在必须**显式** setZoom(zMin)：滚轮已经不被 clamp 夹住，
                           //   「往下滚 20 格」会一路滚过地板进空白（2b 段钉的就是这件事）

# 缩放地标的两侧（2b / 3c / 3d 小节自动断言，见 §4 坑 32 / 坑 33）：
#   2b 往下滚：27 格后 zoom 0.017250 / shownNodes 0 —— `zMin` 被越过 20 倍以上才真的一屏全空；
#      中心带非背景像素 2476 → 兜底提示真的落笔了，不是死黑屏
#      （公开那份只需 18 格 → zoom 0.018530、像素 2474，它的 `zMin` 更低：0.14249589）
#   3c 往大放：home z=0.461 → **两份 HTML 现在都空于 z=472.2**（1024.0× home；
#      private ≈6.8× zMax、public ≈6.9× zMax）
#      → 提示照画（中心带非背景像素 private 18733 / public 2329）；
#        按 Home 后 zoom 0.461160 == zHome（容差 1e-6）
#      ⚠️ break 条件读的是 **`stats.painted == 0`**，**不是** `stats.nodes == 0`：公开那份在
#         极端缩放下永远剩 1 个「圆心远在屏外、半径极大」的候选圆，按候选集判就永远等不到
#         「空」，这一整段会静默失效（见 §4 坑 33）。
#   3d 任何缩放 × 任何平移都不许留下「空白且无提示」的画布：9 档缩放
#      （0.005 / 0.02 / 0.1 / 0.4612 / 3 / 30 / 1000 / 30000 / 1e5）× 4 种平移
#      （(0,0) / (600,400) / (-1200,-800) / (3000,-2500)）= **36 组**，每组读整画布探针
#      `CANVAS_LIT`（数遍全屏与背景色 `#0f1116` 不同的像素），要求没有一组出现
#      「非背景像素 < 500 且兜底提示没画」 → 实测 **0 组违规**（修那条 bug 之前扫得出）。
#      ⚠️ 收尾必须**瞬时**把相机设回 home（`setZoom(zHome)` + `panX/panY` 居中 + `draw()`），
#         **不能**调 `resetView()`：那是 364ms 的 tween，而极端 zoom 下每帧要栅格化半径上百
#         万像素的圆弧、rAF 被拖住，tween 迟迟走不完，下一段（4. LOD 契约）就会在「相机还在
#         飞」的中间态上取样（实测把节点的 `_sr` 读成 378442px 而实际该是 38px，于是挑错
#         目标节点、整段假红）。测试要的是确定的起始状态，不是动画。
#   不变量：越界不报错、空视口必画提示、Home 必能回到 zHome

# 方向键平移基线（5b 小节自动断言，读 KG.renderer.camera.panX/panY）：
#   ArrowRight panX 720.0 → 900.0（= panStep 180.0 = 1440/8）
#   ArrowDown 106.75（= (900-46)/8）；Shift+ArrowRight 位移 720.0（= 半个视口，≈4×）
#   全程 zoom 一点不动
#   选中 Medical and Health（focusEdges 1）后两次 ArrowLeft：sel 仍是它、focusEdges 仍 1；
#     再两次 ArrowRight 回原位：fx 1 → 1、panX 1620.0 → 1620.0
#     （被选中的那个节点会随 vault 内容变，别把 `Medical and Health` 钉进断言，读 `KG.state()` 里实际选中的那个）
#   搜索框有焦点时方向键不动相机；panBy 取消在飞的 tween（zoom 0.507476 → 0.507476）
#   不变量：平移只动相机 —— 选中 / 焦点状态逐位不变。`focusEdges` 是屏幕空间计数，
#           允许途中变化，只要求「挪出去再挪回来」完全复原（**别收紧成「途中不许变」**）

# 焦点模式基线（7b 小节自动断言；压暗不是删除，所以 home 的 shownEdges 不变）：
#   两种连线模式各跑一遍（断言名带 `[raw]` / `[agg]` 后缀），目标节点同为
#   Science and Tech/Electronic engineering/Electronic engineering basic（depth 3 / sr 81px）：
#   `raw`  home: shownNodes 55 / shownEdges 96 / marks 130（public 那份：52 / 95 / 130）
#          选中 → focusEdges 38 / focusNeighbors 8 / marks 66；Esc 后 shownEdges 仍 96
#   `agg`  home: shownNodes 55 / shownEdges 22 / marks 28（public 那份：52 / 22 / 28）
#          选中 → focusEdges 17 / focusNeighbors 10 / marks 22；Esc 后 shownEdges 仍 22
#   （早先记录里的顶栏「关系 17/22 · 相邻 10」是 `agg` 口径；这个读数跟着当前连线模式走，别写死）

# 端点标记基线（7c 小节自动断言，读 KG.renderer.markJobs）：
#   开扫前必须 `renderer.selected = null` —— `drawFocusEdges` 会另外补画「被主绘制趟那几道门挡下的
#   焦点边」的标记（门数随连线模式变：`raw` 一道、`agg` 三道，见 §4 坑 21），而比较用的 shownEdges 只算主绘制趟的代表边；带着上一节的选中开扫，
#   就会出现「2 条边 6 个标记」这种假红（本轮实测踩到过）。这一段验的是普通边标记的几何，
#   与选中无关，所以把选中清掉让输入集干净。
#   home（示例快照 bc6 = 2026-10-17 23:05；**marks 两份 HTML 相同、edges 不同**）：
#     `raw`  marks 130 = 箭头 65 + 源点 65（对应 96 条代表边；public 那份 95 条）
#     `agg`  marks 28 = 箭头 14 + 源点 14（对应 22 条代表边，两份同）
#   每个标记到所附圆边间隙恒为 2px；圆内 0 个
#   zoom 阶梯（enter[L-1]×1.05 那一档，L=10..1；读数 = 画出的代表边数 / 标记数；
#   连线模式切换落地后这条阶梯 raw / agg 各跑一遍，断言名带 `[raw]` / `[agg]` 后缀，
#   见 §8 的 1c 节说明；示例快照 bc6 = 2026-10-17 23:05）：
#     private `raw`  L=10 12/24 · L=9 14/28 · L=8 16/32 · **L=7 32/64** · L=6 38/72 ·
#                    L=5 42/80 · L=4 57/100 · L=3 92/150 · L=2 91/150 · L=1 96/120
#     private `agg`  L=10 0/0 · L=9 0/0 · L=8 0/0 · **L=7 1/2** · L=6 4/8 ·
#                    L=5 5/10 · L=4 19/26 · L=3 31/38 · L=2 30/38 · L=1 19/24
#     public  `raw`  L=10 19/38 · L=9 26/48 · L=8 29/54 · **L=7 34/68** · L=6 37/70 ·
#                    L=5 42/78 · L=4 58/102 · L=3 93/150 · L=2 91/92 · L=1 89/86
#     public  `agg`  L=10 5/4 · L=9 6/8 · L=8 6/8 · **L=7 3/6** · L=6 3/6 ·
#                    L=5 6/8 · L=4 17/24 · L=3 30/36 · L=2 9/4 · L=1 9/4
#   —— 以前只测 depth 6 一档，那是私有图的形状（公开图在 depth 6 当时只画得出
#      一条 4px 的截断边，两道门槛都合理地压掉标记，marks=0 —— 那是 `agg` 的旧口径）。
#      现在改成沿 payload
#      自己的 zoom 阶梯逐层扫 L=10..1；判据只要求「探针量到的**长边**」带标记
#      （`long_rungs`，见下面 ③），不再要求「有 ≥2 条代表边在屏的层就得有标记」。
#   不变量（⚠️ 四条都别「收紧」回去）：
#     ① **`marks <= 2*edges` 是硬不变式，`marks < 2*edges` 不是。** 每条画出的代表边可以
#        两端各挂一个标记（源端圆点 + 目标端箭头），所以「7 条边 14 个标记」完全合法 ——
#        实测 raw 模式 rung **L=7 就是 32/64**（agg 同档是 1/2；示例快照 bc6 = 2026-10-17 23:05）。
#        写成严格小于会在正常数据上假红。
#     ② `edge_marker_min_len` 守卫是否在生效，单独用「**阶梯上存在某档 marks < 2*edges**」
#        证明（确实有短边被压掉）。守卫一旦被删，整条阶梯会顶满 2×edges，这条就红。
#     ③ 阶梯那条判据**曾经**写成「有 ≥2 条代表边在屏就要求有标记」，那是假红，已改成
#        `long_rungs`：渲染器判门用的是未截断的 `glen`，探针量的是截断后的弦长，
#        **当时那批快照**里 private agg L=9 就出现过 2 边 / 0 标记 / 弦长 4.01px
#        （< `edge_marker_min_len` 20）—— 那是正确行为（bc6 里这一档已是 0 边 / 0 marks，
#        只当历史例子看）。同一轮还**删掉两条曾想加的等式断言**（`探针条数 == shownEdges`、
#        `marks == 2×long`）：`agg` 口径下弯边走 `quadraticCurveTo`、被 `edge_trim_clearance`
#        压到零长度、focus/ancestor 兜底都会让两边差一两条（**当时那批快照**：private raw L=1
#        探针 53 vs `shownEdges` 52；public agg L=8 出现 marks=2 / long=0），40 个组合里
#        37 个成立只是接近，绑上去就是间歇性假红。真正钉得住的只有 ①②。
#        ⚠️ 弯边/扇形那套已整体删除：`raw` 现在**恒直线**（`lineTo`），别再按「raw 也走
#        `quadraticCurveTo`」去推理它的形状；只有 `agg` 的代表边仍可能弯。
#     ④ minGap ≈ maxGap ≈ edge_trim_clearance。

# 屏外兜底基线（7d 小节自动断言，读 KG.renderer.chipJobs）：
#   ⚠️ 整节 raw / agg 两种模式各跑一遍，断言名带 `[raw]` / `[agg]` 后缀（见 §8 的 1c 节说明）。
#   深缩放选中 fixture（SEL = 理解傅利叶变换&频谱密度的几何意义，
#                       TGT = 5.1.2 定积分的定义(本质是求和的极限)）：
#     (a)  **一端**在屏外：focusEdges 1 / chips 1（这条 fixture 两种模式读数相同）；线止视口边挂
#       朝外箭头 + 选中圆边源点；chip 文以「5.1.2 定积分的定义」开头（chipLabel 截 18 字）
#     (a2) **两端都**在屏外（bc8 = 2026-10-18 22:46）：`raw` focusEdges 1 / chips **1** /
#       shownEdges 16 / anchored true / tgtChips ["5.1.2 定积分的定义(本质是求和…"] / selChips []；
#       `agg` chips **0** / shownEdges 0 / anchored false
#   侧栏出边行点击 → fitPair 一次 tween 框住两端（两个包围盒都在视口内），
#     且 selected 切到 TGT；示例快照 bc6 = 2026-10-17 23:05 下 agg 是 focusEdges 1 / marks 2，
#     raw 是 focusEdges 2 / marks 4
#   18 组缩放×选中组合：chips ≤ CHIP_MAX+1；折叠数**按模式分开写**：
#     `raw` 侧 **2 组触发折叠**（chip_max=8）—— `…/Electronic engineering basic/LTI analysis`
#     deg7 mult8→n9、末尾 chip 收成 `+7`；`…/Mathematics Basic/Calculus` deg5 mult8→n9、
#     收成 `+1`，两枚都 right-anchored；
#     `agg` 侧仍 **0 组**（最狠的 deg=7/mult=8 只出 1 枚 chip，+k 分支被 warn 条件跳过）
#   不变量（两种模式都成立，别只按 agg 的读数收紧）：
#     chip 数 ≤ 当帧屏外端焦点边数；两端屏外的边**按模式分开**：
#       `raw` 照画线（两端都出屏也横穿视口 stroke）**并且也挂一枚 chip** —— 名字给非焦点端、
#         且要求这一帧真落了笔（`laid`）；
#       `agg` 才是不产线也不产 chip
```

改完视觉**必须重新截图并人眼看**：`python browser_check.py` 后 ReadMediaFile `%TEMP%\kg_0*.png`。
