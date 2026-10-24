# 交接文档 —— 知识笔记语义缩放可视化系统

> ⚠️ **先读 `HANDOFF_NEXT.md`（2026-10-24 已更新）**：它只有 170 多行，是近两轮的现状 +
> 给接手者的三步起手式 + 已过期章节清单。本文档的 §3 里那批「示例快照」数字**已经过期**
> （还写着聚合边、162 ok、home 停在第 1 层的旧口径），以 `HANDOFF_NEXT.md` §5 和
> `git log` 为准。

> 写给接手「看图验证 + 改进优化」的编程智能体。先读这份，再读 `README.md`
> （§4 语义缩放机制、§8 关键实现决定是同一批内容的用户视角版本）。

> **2026-10-24 更新：本轮是产品减法**（两个本地提交：`977e358` 砍「按尺度聚合」画边模式、
> `6af69fe` 砍「掌握度 / 重要度」节点标注）。**§0 / §3 / §8 里的历史快照数字已不能复现**
> —— 聚合边与掌握度都已不在，单文件从 ~11.3 MB 降到 ~6.1 MB。当前基线见 `HANDOFF_NEXT.md`
> §5；本轮的取舍与「别加回来」见 §4 新增**坑 42**；调参地图见 §5。

---

## 0. 一句话现状（2026-10-24）

**Canvas2D 自绘 + circle packing 嵌套圆 + 10 层深度轴 + 按深度层级带淡入淡出**；连线
**只有「逐条链接」一种画法**（按尺度聚合的模式已在 2026-10-24 删除，见坑 42），节点
**没有掌握度 / 重要度标注**；产出单文件 HTML（private **6.12 MB** / public **6.14 MB**，
2026-10-24 12:12 实测，会漂）。数据侧 `build.py verify --scope all` 两份全绿（合计 110 `[ok]`
/ 0 FAIL：private 55 / public 55）；浏览器侧 `browser_check` private 132 / public 133 `[ok]`、0 FAIL、1 warn（条件跳过）。
本地仓库**未 push，也不该 push**。

### 历史：之前几轮做了什么（都已提交，只当背景读）

**布局重构（同心环 → circle packing）与用户的四条新要求都已实现并提交**；其后的**焦点模式**
（选中即过滤连线 + 邻居蓝环，见 §4 坑 19）、**连线端点标记**（两端截断 + 源点/箭头，
见 §4 坑 20）、**屏外焦点边兜底**（视口边箭头/圆点 + 屏外端点名字 chip + 侧栏边行点击
fitPair 框住两端，见 §4 坑 21/22）都已落地并提交；**标签字号绑屏幕半径 + 淡入淡出平滑**
（见 §4 坑 23）第13步提交。数据侧（`build.py verify`）与浏览器侧（`browser_check.py`）
当时全绿，截图人眼复看过。剩下的有意待办见 §6。

**紧跟其后是「公开范围统一成一份真源」这一轮**（见 §1「范围真源」、§2、§4 坑 26–30、§5）：
`config.yaml` 里不再有 `include` / `exclude` / `exclude_notes` / `output`，范围全部来自 vault 里的
`quartz-setup/public-scope.yaml`；CLI 每条子命令都接受 `--scope private|public|all`（`-s`，
`all` 只对会遍历范围的子命令有意义 —— `watch --scope all` 会被直接拒绝）；
产出两份（private 沿用旧文件名 `graph.json` / `knowledge-graph.html`，public 加 `.public` 后缀）；
站点侧的同步脚本（当时还在 `quartz-sync-task\sync.ps1`，2026-10-14 已搬进 vault 的
`quartz-setup\sync.ps1`）也改成读同一份真源、读不到就整轮放弃（fail-closed）。
`python build.py verify --scope private` 与 `--scope public` 两份都全绿。
**这一轮早已提交**（`git log` 里能找到），旧文「还在工作区里没提交」的说法已过期。

下面这段是 packing 改造完成时的状态描述，只当历史读（per-node 淡入早已换成层级带，
2026-10-24 又删掉了聚合边与掌握度；**现状以本节开头为准**）：

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
（已提交，见 git log）公开范围统一成 public-scope.yaml 一份真源 + --scope + 站点侧 fail-closed 同步
```

```bash
cd D:/obsidian_vault/knowledge-graph
python build.py build        # 不出 --scope 时 = private：生成 dist/knowledge-graph.html
                             # （单文件，2026-10-24 12:12 实测 6265 KB ≈ 6.12 MB；
                             #   该值随 vault 内容漂移，不是固定不变量）
python build.py build --scope all    # 两份都建（public → dist/knowledge-graph.public.html，同快照 6291 KB）
python build.py verify       # 数据侧自动校验，应全绿（合计 110 [ok] / 0 FAIL：private 55 / public 55）
python browser_check.py      # 浏览器侧 ~132 项断言 + 截图，应全绿（public 那份 133；
                             #   默认查 private 那份 HTML；
                             #   想看 public 那份：KG_HTML=knowledge-graph.public.html …）
python build.py watch        # 开发时挂上，改笔记/配置/范围定义自动重建
```

**`python build.py` 不带子命令只跑 scan、不写 dist** —— 重建必须写 `build`。
不带 `--scope` 时所有子命令都作用于 `config.yaml` 的 `scopes` 里排第一的那份（= private）。
改了 `web/*.js` 或 `web/template.html` **必须重建 dist 再跑 `browser_check.py`**：这三个文件在
构建时被完整内联，不重建等于没改。这两条本轮真踩过。

改 `public-scope.yaml` 也算「改配置」：`watch` 的 snapshot 里已经包含 `cfg["scope_file_path"]`，
所以改范围定义会触发重建（见 `build.py:cmd_watch`）。

依赖：`PyYAML`（已装）、`markdown`（已装，构建期把笔记渲成预览 HTML）；`browser_check.py` 另需 `playwright`（已装，用 `channel="chrome"`
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
├── build.py             CLI：scan | suggest | build | verify | watch | scope（都吃 --scope/-s）（387 行）
├── verify.py            数据侧自动校验（断言式，无测试框架；含 scope 范围一致性断言）（582 行）
├── browser_check.py     浏览器侧自动回归：~132 项断言 + 截图（默认查 private；`KG_HTML` 可切 public）（1597 行）
├── sync-graph.ps1       计划任务包装：防重入 lock + python 检查 + UTF-8 + 日志裁剪 400 行；建本地的两份（`build --scope all`）（49 行）
├── kg/config.py         读 public-scope.yaml、解析各 scope、配置校验（中文报错；退役键直接报错）（382 行）
├── kg/scan.py           白名单 glob 扫描 + 落地名（remap）前缀重写               （118 行）
├── kg/parse.py          frontmatter / 标题树（跳过代码块）/ wiki 链接 / 摘要     （205 行）
├── kg/graph.py          层级树、语义边、标题级链接、每层读数、重映射路径的别名索引（428 行）
├── kg/candidates.py     候选边挖掘（3 条启发式）                                （302 行）
├── kg/layout.py         circle packing 布局 + 世界半径 r / minzoom              （478 行）
│                        ↑ 开头 docstring 是布局的权威叙述，改布局前先读它
├── kg/preview.py        Obsidian 式预览：markdown → HTML / 图片链接解析（2026-10-22）（315 行）
├── kg/ioutils.py        stdout UTF-8（`setup_stdout()`）                        （18 行）
├── kg/emit.py           输出 graph.json 与自包含单文件 HTML                      （96 行）
├── web/template.html    骨架 + CSS（顶栏：搜索框 / 学科下拉 / 标签下拉 / 重置视角；图例三块：
│                        学科 / 关系 `#legend-rel` / 节点；侧栏；画布；`#footer`）（301 行）
├── web/app.js           状态机、搜索过滤、侧栏、层级胶囊、事件绑定（含方向键/Home）、window.KG（821 行）
├── web/render.js        Canvas2D 渲染器：相机、趟次绘制、逐条链接（唯一画法，`drawEdges`）、
│                        端点标记、屏外 chip、fitPair、拾取、标签竞争、键盘平移 `panBy`/`panStep`
│                        （1438 行）
│                        ⚠️ 端点用 `rawAnchor`：**恒返回这条边真实的两个端点节点**，不沿 `parent`
│                        链上移。`resolveAnchor` 随聚合模式一起删了（2026-10-24），别去找。
├── annotations.yaml     用户手工标注（`notes.{aliases, domain}` + 手工边）—— **目前是空的**
├── candidates.yaml      候选边（待审核）
├── sync-graph.log/.lock 运行时产物，gitignore
└── dist/                构建产物，gitignore
    ├── graph.json / knowledge-graph.html              private（旧文件名；2026-10-24 12:12 快照 5771 KB / 6265 KB）
    └── graph.public.json / knowledge-graph.public.html public （同快照 5770 KB / 6291 KB）
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

> **⚠️ 历史快照（聚合边 / 掌握度时代）**：本节所有读数都产生于 **2026-10-18 及以前**，那时还有
> 「按尺度聚合（`agg`）」画边模式与「掌握度 / 重要度」节点标注。**2026-10-24 的产品减法把
> 这两样都删了**（见坑 42），所以本节里的 `agg` 读数、`162 ok`、2 条 warn、11.23MB 等数字
> **只当历史标本，不要拿来当基线**。当前基线见本文 §0 与 `HANDOFF_NEXT.md` §5；新的回归
> 基线见 §8。本节的布局结论（嵌套圆、`r` 沿包含链递减、`zMin`/`zMax` 是地标、`painted` 判据
> 等）仍然有效。

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

#### 1c 段（已随模式删除）：连线模式切换为什么曾这样断言

**2026-10-24 起没有 1c 段了** —— 顶栏「连线」下拉框、`#edgemode`、`kg.edgeMode`、
`#legend-rel-raw` / `#legend-rel-agg` 两套图例全删，只留一种画法。以下只当历史：
1c 当时测「下拉框真的驱动渲染器 + 两套图例互斥 + 选择持久化 + `raw` 边数 ≥ `agg`」，
并把焦点 / 端点标记 / 屏外兜底三段从单跑改成 raw/agg 各跑一遍（所以断言数从 108 涨到
156 → 162）。**现在这三段只跑一遍**，断言数是 132 / 133（见 §8）。

从那段挪过来的两条**别改回去**的判据（与模式无关，仍然成立）：

+ **绝不断言「`shownEdges` 任何一档都非 0 / 恒定」**。它是视口绑定的，实测 private 沿阶梯
  从 12 剧烈变到 96（当时快照）。写成「恒 > 0」会假红。
+ 用户要的「某一处链接不会因为缩小而消失」由 7d 的 `fitPair` 用例保证：框住同一对 fixture 后
  `focusEdges = 2 / marks = 4` —— 两条细线各有各的箭头，正是「细线条数 = 关联强度」的现场证据。

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
    ① **边色 == 节点色**，当年 `theme.edges.derives` 与 `theme.domains["Science and Tech"]`
      是同一个 `#4C8DFF`，箭头贴在圆边上等于隐形（`theme.edges` 已随聚合模式退役，现在所有
      链接统一用 `theme.raw_edge` 近白，与节点 domain 色拉开）；
    ② 线是**圆心到圆心**画的，两端都插进圆里，箭头正好落在被实心圆盖住的区段上；
    ③ 箭头只有约 **5.4px**，还要再乘 0.45 的 alpha；
    ④ 画在 `drawNodes` **之前**，packing 里圆是相切的，紧贴的邻圆能把它整个盖掉。
    现在的解法对应四条：两端各截断 `lod.edge_trim_clearance` 像素（线不再进圆心）、
    标记改用 `MARK_RGB`（线色向 `#d6dbe4` 混白 `lod.edge_marker_tint`，与节点色拉开）、
    箭头尺寸跟线宽走并夹在 `[7,14]`、落笔单独一趟排在 `drawNodes` 之后；而且**整趟连线
    就画在实心圆之上**（2026-10-21 起，见坑 40），所以 ②④ 那两条遮挡从根上没了。
    还有一处「虚线」误认：用户看到的虚线是 `drawChainHighlight` 的**祖先链**（包含关系），
    不是链接边。它现在改成 `setLineDash([1, 4])` 的圆头点线，跟链接边彻底区分开；
    `contrast` 走虚线 `[5, 4]`（当前零数据），节点级的掌握度虚线已随标注一起删除（坑 42）。
    **短边只跳标记、不跳线**：`drawSegment` 里只有 `glen < 0.5` 才不落笔，其余一律 stroke；
    `glen < RAW_MARK_MIN`（`lod.raw_marker_min_len`，默认 6 px）与冷边 `a < 0.1` 只挡标记。
    那个「短于 `lod.edge_marker_min_len`(20) 整条不画」的规则是聚合边时代的，已随模式退役
    （`kg/config.py` 见到会报错）。`drawSegment` 还返回**它到底有没有落笔** —— 两圆贴死时
    屏幕上没有可见长度，硬画只会得到一条方向反掉的短线段，比不画更乱（`stats.edges` 数的是
    真画出来的条数）。
    第 ③ 条的 alpha 成因也不存在了：alpha **恒为 1**（不乘端点淡入进度、也不乘「弱边打
    45 折」），线宽恒为 `lod.raw_edge_width`（1.0 px），标记尺寸 `clamp(5 + lw * 1.6, 7, 14)`
    就钉在下限 **7px**。这是有意的：用**条数**表达关联强度，不用粗细。

21. **「侧栏有这条边、画布却没有线」只有一道几何门 —— 别加「全部显示」开关。**
    侧栏入边/出边列表读的是**原始边表**（app.js `edgesOf`），没有尺度概念；画布上这条链接
    要在当前尺度画出来，只需过**一道几何门**：整条线段的屏幕 bbox 与内容视口（外扩
    `CULL_MARGIN`）不相交就不画；以及截断后线段短于 0.5px 时无笔可落（`glen < 0.5`，
    只在两个元素贴得极近时发生，**放大立刻恢复**）。
    端点由 `rawAnchor` 给出，恒为这条边自己真实的两个端点节点：不查预聚合索引、不沿
    `parent` 链上移（「两端塌到同一个代表圆」因此不可能发生，只剩「一个元素链到它自己」这种
    真自链接会被 `A.id === B.id` 跳过）、也不读 `alpha`（端点圆当帧没画出来也照样落笔）。
    这正是「链接不该因为缩小而消失」的落点。
    用户曾提议「选中后不管缩放比，把它自己和它全部子孙元素的出/入边箭头全显示」——驳回，
    理由三条：屏外目标端的箭头**本身不可见**（指向虚空）；粗缩放比下选中圆还没淡入、
    箭头**没有附着点**；子孙元素的全量边在粗尺度是几十上百条线 = 回到最初抱怨的「太乱了」。
    正确的后路是坑 22 的兜底，而不是放宽那道门。
    ⚠️ **别把端点改回上移。** 曾经也调过 `resolveAnchor`（聚合模式的做法），于是「看见一条
    从 A 出去的箭头、想知道它指向谁」这个最常见的动作会被缩放和平移**双双打断**。现在
    聚合模式已整条删除（2026-10-24），端点**永远在真实位置**：圆可以消失、线必须留在原地，
    端点落进父圆内部反而是想要的暗示（「这里面还有更深的知识点」）。**别再动这道门。**
    （历史：聚合模式当年还有另外两道门 —— 两端落在同一祖先圆不画、聚合索引该层无代表；
    用户实测的死区正是三门叠加。模式删掉后这整类坑消失。）

22. **屏外焦点边兜底：线一路画到屏外 + 名字 chip + 侧栏边行 fitPair。**
    现在只有逐条链接一种画法（坑 34/42），所以形态只有一种：**线的主绘制趟本来就会画到
    屏外**，缺的只是「这条线指向谁」这个名字。chip 由 `drawEdges` **自己挂**：
    + **恰好一端在屏外** → 条件 `hs && (aA.on !== aB.on)`，钉在线穿出视口的那一点上、
      沿线方向朝外，读作「顺着这条线出去就是它」，命名**屏外那一端**。
    + **两端都在屏外**（平移一下就会碰到：选中项整圆出屏，而它的链接对端本来就在远处）：
      线照画（横穿视口），并且**也挂一枚 chip**。三个要点：
      * **命名给「非焦点的那一端」**，不是字面的「远端/目标端」—— 选中 A 时答「这条线通向谁」，
        选中 B 时答「这条线来自谁」；两端同属焦点子树时无从区分，退回目标端 B。
      * **几何走 `entryToward`，不能复用单端那套公式**：单端分支的 `tBest = min(正 t)` 假定
        起点在矩形内、算出来的是**出口**；起点在屏外时它会返回远侧交点，把名字牌钉到线
        **离开**视口的那一头去。所以两端分支用 slab 裁剪（Liang–Barsky）求线段真正**进入**
        内容视口 `[0,W]×[0,Hc]` 的那一点（不外扩 `CULL_MARGIN`，与单端同口径）。
      * **额外要求 `laid`**（这一帧真落了笔）：两端都出屏时「线段 bbox 与视口相交」≠
        「真穿过视口」，斜角擦过的会被 `drawSegment` 自己判掉（`glen < 0.5`），没画出来的
        线不该有一枚指向虚空的名字牌。单端分支不加这道门 —— 那时必有一端在屏内，线一定落笔。
      挂**一枚不挂两枚**：线一进一出、方向本来就看得见，两枚只会把真正想看的焦点 chip 挤出
      `CHIP_MAX`。
    `droppedFocus` 只收两种线：真自链接（没有方向可画）与整段 bbox 出屏；它们只交给
    `drawFocusEdges` **计数**，不补画线（聚合时代那套「补一条止于视口边、挂朝外箭头」已随
    模式删除，见坑 42）。
    共同的实现要点：所有画边趟都只往 `chipJobs` 排队，真正落笔在 `drawChips` 的**屏幕空间**
    趟（`drawLabels` 之后、最顶层，不参与世界坐标的遮挡关系）；chip 同时最多 `CHIP_MAX` 枚
    （读 `lod.focus_offscreen_chips`，缺省 8），超出截断并在右下角补一枚右锚的 `+k` 折叠 chip
    （定位避开 `FOOTER_H`）。
    ⚠️ 旧文档里「raw 两端都出屏时按现设计不挂 chip」和「agg 两端都出屏不画线」两种说法都已
    过期：前者被用户否掉并改成**照挂**（`chips 1`），后者随 agg 模式删除。
    chip **不可点击**，`hitTest` 只认节点圆；导航走侧栏边行
    （`li` 带 `data-self` / `data-target`，点击 → `R.fitPair(idA, idB)` 一次 tween 框住两端，
    并把选中切到对端）。

23. **标签一律画在圆内、字号跟着圆长大**（2026-10-21 重写；上一版是「对数插值 + 圆外兜底」，
    那套的结论已被推翻，别再照着找 `label_font_ref` / `label_max_width` / `label_smooth_dim`
    —— 三个键已退役，`kg/config.py` 见到就直接报错）。
    **为什么改**：用户报「绝大部分实心圆的标签都在实心圆边上，有的还进入了其他元素内部」+
    「满屏大片实心圆、里面空荡荡」。实测两个成因：
    ① 圆外标签会压到兄弟圆上；② **字号封顶 22px** —— 直径 3135px 的圆里那行字只占 4%，
    所以大圆永远是一块纯色。
    + **位置**：全部压在圆心（水平垂直都居中）。半径 < `LABEL_INSIDE_PX`(28) 的圆不挂标签
      —— 它会在放大过程中自己长够。**没有圆外兜底了**，别加回来。
    + **字号**（方案「丙」，两个约束取小）：
      `fs = min(round(clamp(label_font_scale × _sr, 11, 64)), 塞得进圆的最大字号)`；
      塞不进的逐级下调到 11，仍塞不进就用 `clipToWidth` 二分前缀 + `…`。
      正比项让大圆的字跟着长大；「塞得下」保证长标题不溢出。落点：sr 40→12、100→30、
      200→60、≥213→上限 64。
    + **截到只剩 1 个字符**（圆太小 / 名字太长）直接不画 —— 那不是标签是噪声。
      原本就短的名字（「模电」「DSP」）不受影响：没被截断就不会带省略号。
    + **同进同出**：落笔浓度直接取 `alpha.get(id)`（圆这一帧的 alpha，已含层级带淡入与
      可读性地板），门槛 `label_alpha` 降到 0.02 只当「开始参与竞争」的开关。
      旧版的 `fillAlphaOf` / `label_smooth_dim` 那套不对称已经没了。
    + **必须取整**：`measure()` 的缓存 key 是 font 字符串；而且 `browser_check.py` 要求
      三模式切回 auto 后 `shownLabels` 精确复现，亚像素字号会让碰撞网格判定漂。
    + `clipCache` 的 key 是 `(节点 id, font, 可用宽取整)`，上界是「同屏标签数 × 字号档位」，
      有界不泄漏。
    + **仍然不按 `depth` 分档**：`depth` 是复合轴（`heading.depth = 笔记 depth + 标题级别`），
      且同为 depth-1 的六个学科根世界半径能差十几倍，按 depth 分档会让铺满全屏的根和
      20px 小圆点用同一个字号。
    + **已知观感**：祖先（压暗的容器）圆很大时，它居中的大字会横跨在子圆上 —— 这是
      「居中 + 字号跟圆走」的固有结果，用户 2026-10-21 已验收接受。如果以后要改，动
      `label_font_scale`（全局）或给容器单独乘一个系数，别退回圆外标签。

24. **回归套件的 fixture 不要写完整路径**（2026-10-10 踩到）：`browser_check.py` 的 7d/侧栏
    用例原先把 SEL/TGT 硬编码成 `…/信号与系统#分解信号/…` 这样的**全路径**，
    用户把笔记改名成 `LTI analysis.md` 之后路径失配，`have_pair` 为假 →
    整段 7d 被当成「条件跳过」warn 掉，套件依旧 `ALL BROWSER CHECKS PASSED`，
    **但屏外 chip / fitPair 那 12 条断言已经悄悄不再跑了**（`[ok]` 从 84 掉到 72，
    这是唯一的可见信号；现在的基准是 132 / 133，见 §8）。
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
    那份 HTML 现在约 **6.14 MB**（2026-10-24 12:12 实测；删聚合边之前是 8.7 MB —— 量级变了
    但结论不变）；
    站点仓库 `quartz-site` 近 60 天实测 **144 次提交 ≈ 2.4 次/天**（最后一次 2026-10-15 10:47:42 +0800）。
    （提交频率是示例快照，下面这笔账的量级不随快照变。）
    每次内容变动都往仓库里提交一整个 HTML 就是 6.14 MB × 2.4 × 365 ≈ **5.4 GB/年**
    （旧读数 8.7 MB 时是 7.6 GB/年），
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
      主绘制趟按视口裁剪圆（`web/render.js:545-546`），被那道几何门挡下的焦点边再由
      `drawFocusEdges()` 按「解析到的在屏锚点」分组（`web/render.js:1120-1143`；现在**只有
      一道门**，见坑 21。分组键带粒度后缀 `\0n`，让整篇级与标题级各自成组，`:1135-1136`），
      所以**平移本来就会改变这个数**（实测公开那份 2 → 1；这不是 bug，它数的就是屏幕上的东西）。
      正因如此 5b 段断言的是「挪出去再挪回来，`focusEdges` 与相机逐位相同」，
      **不是**「平移过程中计数不许变」—— 后者必然假红，改成它等于把这条覆盖废掉。
      （历史：聚合模式时代分组还按「门数随模式变」分两套；模式删掉后只剩一套，见坑 42。）
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

34. **画边只有一种模式：`raw`（逐条链接）—— 别再假设「边一定随缩放聚合」。**
    用户的原始要求是：标题→标题的链接在**任何**缩放尺度都在，颜色和浓淡不变，只变**形状**
    （线的长度和走向 —— 线宽也恒定）。2026-10-24 起这就是唯一画法；**另一条「按尺度聚合
    （`agg`）」的路径已整条删除**（当时它会让链接缩小后变淡、变少、最后消失 —— 那正是用户
    不要的效果；理由与收益见坑 42）。
    * **两个容器之间细线的条数才是关联强度，端点永不换代表。** 每帧遍历全部 `SEM`、每条
      原始边各画一条线，两端恒为真实节点自己的世界坐标（`rawAnchor`）。不查 `aggregates[L]`、
      不沿 `parent` 链上移端点（那套 `resolveAnchor` 已删）。于是缩到文件级时 heading 级的边
      仍然从两个标题的真实位置出发，看起来就是**一条线穿进父级圆的内部** —— 这正是用户要的
      效果（「这里面应该还有更深层次的知识点」），别把它当 bug 修掉。缩放/平移只改线的长度和
      形状，**不换端点、不减少条数**。线宽恒为 `lod.raw_edge_width`（1.0 px，不随缩放变）；
      标记门槛走 `lod.raw_marker_min_len`（6 px，读成 `RAW_MARK_MIN`），见坑 20。
    * **没有分组，每条边各画一条恒直的线。** 早先版本按无向键 `(小 id)\0(大 id)\0type` 把同一对
      元素之间的边并成一「束」、再按 `lod.raw_edge_spread` 沿法向偏离中线排成扇形（束越宽关系
      越强）。**扇形机制已整体删除**，`raw_edge_spread` 这个键在 `kg/config.py` / `config.yaml`
      里也不存在了：真实端点本来就散在父圆内部的不同位置，一束线天然散开。关联强度完全由
      条数表达。
    * **颜色统一（2026-10-20 起），不再按粒度 / 关系类型分色。** 所有语义链接线一律用
      `theme.raw_edge`（`#E6EDF3`，近白），端点标记由它 `tintLight` 派生；整篇级 `[[笔记]]`
      与标题级 `[[笔记#标题]]` **同色**。理由（用户原话意译）：文件夹 / 笔记 / 标题都是人为
      规定的**存储结构**，这张图关心的是知识内在的包含关系与连接关系，存储粒度不该参与视觉
      编码。**关系类型没有丢**：`contrast` 走虚线 `[5, 4]`、只有 `derives` / `prerequisite`
      画箭头（其余两端只画点）。**线型**才是类型信号，**颜色**不再是。
      ⚠️ 三条别再改回去 / 别误删：
      ① **`e._nl` 与分组键上的粒度后缀 `\0n` 必须保留**（`drawFocusEdges` 里 `nl = e._nl`）——
        它现在**不负责上色**，只负责让两种粒度各自成组；去掉会把 note 级边「LTI→Calculus」
        和 heading 级边「LTI#CTFT→Calculus#定积分」并成一条（它们在文件级解析到同一对锚点、
        同为 derives），`stats.focusEdges` 少算一条，7b/7d 的读数整体漂移。
      ② **关系类型别丢**（见上）；③ **别按关系类型改回颜色** —— `theme.edges` 已退役，见到会
        报错；统一色是与节点 domain 色拉开对比的前提（坑 20 ①）。`theme.note_edge` 也已改名
        `theme.raw_edge`，旧键会被拒。
    * **alpha 恒为 1，焦点/悬停压暗保留。** 不乘端点淡入进度、也不按条数打折；`FOCUS_DIM` /
      `HOVER_DIM` 的压暗照旧（那是「我选中的是什么」的语义，与缩放无关）。`drawFocusEdges`
      补画时线宽恒为 `RAW_LW + 0.8`、alpha 恒为 1。
    * **没有切换入口了。** 顶栏 `<select id="edgemode">`、`kg.edgeMode`、`applyEdgeLegend`、
      两套图例 `#legend-rel-raw` / `#legend-rel-agg` 全部删除（2026-10-24）；图例只剩一块
      `#legend-rel`，`KG.state()` 也不再导出 `edgeMode`。**别加回来。**
    * **断言纪律**（`browser_check.py` 的 7b/7c/7d，见 §8）：**绝不断言 `shownEdges` 在任一
      给定层非零或跨缩放恒定** —— 它是视口绑定的（private 实测从 L=10 的 12 条一路到 L=1 的
      96 条，示例快照 bc6 = 2026-10-17 23:05）。用户真正要的那句保证（「缩小后链接不消失」）
      由 `fitPair` 那条覆盖：框住同一对笔记后画出 `focusEdges = 2 / marks = 4`（两条细线各有
      各的箭头）。

35. **(a2)「两端都在屏外」这条 fixture 必须沿「远离另一端」的方向推 —— 推错方向时 `chips=0`
    是正确行为，断言红得毫无信息量。**（2026-10-18 踩到）
    第一版写法是 `R.panBy(-(3000 + n._r*zoom), 0)`，只往左推：SEL 落到 x≈-2321，
    可 TGT 本来就在 SEL 的**左上方**（屏空间单位向量 `u≈(-0.778, +0.628)`，与 zoom 无关），
    于是 TGT 被推到 x≈-23870 —— **两端同在视口左侧、连线压根不与视口相交**，被 `drawEdges`
    的 bbox 门挡掉、记进 `droppedFocus`；`drawFocusEdges` 对这类边
    **只计数不落笔** ⇒ `laid` 为假 ⇒ 两端 chip 分支不触发。
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

37. **图例的折叠开关只能切 `.collapsed` 类。**（2026-10-20 新增；2026-10-24 简化）
    折叠走 `#legend.collapsed #legend-body { display:none }`；状态存
    `localStorage` 键 `kg.legendCollapsed`，默认展开（不写 = 展开，截图基线与老行为都不变）；
    快捷键 `L` 走 `app.js` 的 keydown，和 `Esc`/`Home`/`[`/`]` 并列。
    旧文还有一句「**绝不动 `#legend-rel-raw` / `#legend-rel-agg` 的 `hidden`**」——
    那两个元素连同「两套图例按连线模式互斥显隐」一起在 2026-10-24 删掉了：图例只剩一块
    `#legend-rel`（原来的 `#legend-rel-raw` 改名），没有 `hidden` 状态可动。
    **别把模式切换 / 第二套图例加回来**（坑 42）。

38. **`browser_check.py` 的 `PICK_NODE` 必须扫整数屏幕像素。**（2026-10-20 修）
    它原先按 `x += 5` 从 `W*0.28` 累加，坐标带小数（如 `483.2`）。`page.mouse.click()` 会把坐标截成
    整数（`483`），而 `hitTest` 的判据是 `d <= max(_sr,4)+3` —— 扫描点若落在某个圆的边缘 1px 内，
    截断后正好出圈、命中它的父圆，于是「探针说 A、真实点击选中 B」。
    症状极具欺骗性：private 那份恰好不踩（483→523 换了位置），**只有 public 那份红 2 条**
    （`click selected a node` 与 `breadcrumb has clickable ancestors`），而且退回提交版照样复现
    —— 是测试自身的问题，不是渲染缺陷。现在从 `Math.ceil(...)` 起算、步长 5 全是整数。
    教训：**凡是「先探针取坐标、再真实 mouse.click」的用例，坐标必须整数**，否则会在圆边缘随机假红。
    2026-10-24 又补了同一类坑的另一半：**取样点必须排除图例 / 侧栏覆盖层**。几个「探针取坐标 →
    `page.mouse.click`」的用例（`PICK_NODE`、7b 靶子探测、7d `fitPair` 取点）现在都先要求
    `document.elementFromPoint(...) === canvas` 才认这个点，否则点会被图例或侧栏挡住、点击
    落空 —— 症状是「探针说 A、点击选中 None」的假红（本次布局重排一度把它暴露出来）。
    与「整数像素」是同一条教训：**先证明这个屏幕点真的属于画布，再点。**

39. **浮现时机从「per-node 门槛」改成「按深度的层级带」（2026-10-21，用户要求的第 4 轮改动）。**
    这一条**推翻了本文档里多处「per-node minzoom」的说法**（§3 的 enter 表、坑 5/6/23 的部分
    措辞、§5 调参表里 `min_px` 那两行），读旧段落时以本条为准。

    **为什么改**：用户报了两个症状 ——（a）home 视角下 6 个顶层学科深浅不一，有的已经变淡、
    里面的元素也浮出来了；（b）同一个父节点下、**同属一层的兄弟**只有半径最大的那个浮现了。
    根因是 per-node 门槛 `minzoom = min_px / r`：浮现时机取决于**节点自己的半径**，而层内
    半径差能到 9~40 倍（depth 2 = 39.7×），所以同层兄弟会错开五六个滚轮格。

    **新机制**（`kg/layout.py` 算、`web/render.js` 消费）：
    * `enter[L-1]` = 第 L 层**开始淡入**的 zoom；`M[L] = enter[L-1] × fade_span` = 该层**成熟**。
    * 同层共用一个 alpha ⇒ 同时出现、同时变深、成熟后颜色完全一致。
    * 父圆在**下一层成熟**时压暗到 `parent_dim`（`dimFactor`，与下一层的淡入带同一区间）。
    * 阶梯是**以 home 锚定的等比序列**：`M[home_level]` 由 `home_zoom` 与 `home_band` 反解，
      向上铺到 `zMax`。所以加一篇笔记不会让所有层级门槛一起跳（旧算法用每层 minzoom 中位数，
      会跟着内容漂）。**第 1 层另有一处特殊处理**：`M[1]` 被压到 `zMin` 以下，否则两个 scope
      里总有一个「缩到最外层连学科根都看不见」（public 的 zMin=0.142 比阶梯低得多）。
    * **可读性地板**：屏幕半径 < `0.5 × min_px` 不画，`[0.5, 1] × min_px` 线性淡入。
      同层最小那批因此比兄弟晚一点变实（这是「同层同色」唯一的例外，且是有意的）。
    * `r` 从此**只决定「同层里画多大」**，不再决定浮现时机；但它仍是布局契约
      （沿包含链严格递减 ⇒ 子在父内），verify 照旧断言。

    **两个新旋钮**（`config.yaml` 的 `zoom`）：
    `home_level`（默认 2，home 停在第几层）、`home_band`（默认 0.5，home 落在该层淡入带的
    哪个位置）。**`home_band` 别填 1**：层内半径差能到 40 倍，整层满不透明时最大的那几个圆
    会把父圆结构糊成一块色板（2026-10-21 实测）。

    **已知并接受的代价**：同一时刻基本只看得到 1~1.5 层，旧版「3~4 层以不同浓度叠着」的层次感
    消失；首屏是几块较大的同浓度圆叠在一起。用户 2026-10-21 人眼验收后选择接受（后续另有改动
    处理观感）。

    **⚠️ 五条别改回去 / 别误删**：
    ① **跳层落点、`focusOn`、`fitPair` 必须用 `M[L]`（`levelMature`）而不是 `n._mz`** ——
      `_mz` 已经与可见性脱钩，拿它当落点会跳到一个「目标还没浮现」的尺度（实测 alpha≈0.06）。
    ② **verify 的「落笔」复刻必须包含层入口 + 地板两条**（`verify.py` 的 `painted()`）；
      只用 `r×z ≥ min_px` 就又是旧模型了 —— 那会让 verify 在实现换了之后**依然全绿**（假安全）。
    ③ **涌入判据改成「落笔口径」、上限 35%**（原 20% / alpha 口径）。层级带**有意**让同层一起
      出现，所以旧口径必然超标；这是设计变更，不是放宽标准（实测 26%，同心环时代是 66%）。
    ④ **端点标记不要求端点圆落笔**。曾试过「端点没画就不挂标记」，结果浅缩放下箭头全灭
      （语义边的端点基本都还没浮现），9 条断言红 —— 箭头是用户当初要的功能，别拿它换观感。
      代价是粗尺度下会有「指向虚空的箭头」，这是 raw 契约（圆可消失、线要留下）的固有后果。
    ⑤ **`enter` 不再是「minzoom 中位数的前缀最大」**，`home_layer` 的含义也变成「home 处已
      *开始淡入* 的最深一层」。旧文档/旧断言里凡按「成熟点」判 home 的都会在 `home_band<1`
      时算成 1 层。

40. **连线一律画在「实心圆之上」（2026-10-21 用户点名要求；2026-10-24 起是唯一画法）。**
    **起因**：用户报「只有点层级胶囊那个缩放比时细线才完整，其它缩放会被实心圆盖住」。
    实测后修正了他的归因 —— 遮挡与「是否落在胶囊落点」无关（0.53 处 99% vs 0.66 处 98%、
    6.08 处 26% vs 7.60 处 26%），**只与缩到多深有关**：

    | zoom | level | 平均被不透明圆盖住 | 整条完全被盖 |
    |---|---|---|---|
    | 0.53 | 2 | 99% | **53 / 68 条** |
    | 1.80 | 4 | 57% | 32 / 81 |
    | 6.08 | 6 | 26% | 3 / 85 |
    | 11.20 | 7 | 13% | **0 / 85** |

    浅层有 53 条线整条躺在实心圆底下，屏幕上只剩「画在圆上」的箭头孤零零浮着 ——
    这违背契约（「每处链接各画一条细线，任何缩放尺度都在」）。
    **改法**：`draw()` 里的落笔顺序是 wash → 实心圆 → Ctrl 虚线圈 → **连线** →
    祖先点线 → 端点标记 → 强调环 → 标签 → 屏外 chip；连线排在实心圆**之后**，祖先点线
    （`drawChainHighlight`）跟着连线同一侧（它和连线一起读，留在圆下会只剩连线可见）。
    端点仍用 `rawAnchor` + `TRIM` 在各自圆的边界处截断，所以线不会插进自己的圆。
    **代价（已知并接受）**：浅层会看到 96 条白线横穿在大色块圆之上，偏「线网」感。
    用户 2026-10-21 人眼验收后选择 A 方案（照做）。
    **别再改回去**：
    ① 这不是「顺序写错了」—— 现在**只有一种画法**，不存在「按模式分位置」了（聚合模式已删，
      见坑 42）。
    ② 端点截断必须保留。没有 `TRIM` 的话，线会插进自己的圆、箭头被自己的圆盖住。
    ③ 如果以后嫌线网太吵，正确的降级路是「只把端点附近一小段 + 标记提到上层」（B 方案），
      **不是**把整趟塞回圆下 —— 那会退回「53 条线整条隐形」的原始问题。

41. **第 11 带：链接药丸 + Obsidian 式预览 —— 正文不要画在 canvas 上。**（2026-10-22，三轮）
    用户的实验想法：放大到最深一层（六级标题）之后继续放大，把笔记正文也呈现出来，「于是
    这张图把全部笔记知识完整呈现了」。**第一、二轮的教训**：直接在 canvas 上排正文，用户
    验收结论是「只是能用、能用」——canvas 排不出段落/表格/图片/公式，721 个公式只能显示成
    `$$U_{CEQ}$$` 这样的原字符。第三轮按用户自己的想法换成 **Obsidian 的做法**：
    深缩放 → 画该笔记的出站 `[[链接]]` **药丸**；按住 **Ctrl** 悬停药丸 → **HTML 浮层**预览
    （真排版 + KaTeX 公式 + 按路径引用的图片）。

    **机制**：链接带仍不是节点深度（`enter[]` 10 项不动），`lod.links = {enter, mature, hold,
    exit}` 接在 `M[10]=zMax` 之后，窗口 private **95.21 → 128.53 → 236.59 → 319.40**；
    **有退场**，越过后空视口 + 兜底提示 + 画布中央「已越过链接带」提示（第二轮教训：用户
    滚到 z≈845 时画面还有巨大标题圆、不算空视口，看着像功能坏了）。

    **数据侧（构建期）** `kg/preview.py` 把 markdown 渲成 HTML：
    ① **公式先「保护」成 `@@MATHn@@` 再过多 markdown**：`nl2br` 会把 `$$…$$` 里的换行变成
       `<br>`，定界符被拆进不同元素、运行时 auto-render 就匹配不到（第一版实测 0 个公式渲染）；
    ② `![[图.png]]` → `<img>` **相对路径**引用 vault（vault 里被引用的图共 519MB，绝不内联；
       `file://` 下实测可以加载）；
    ③ 坏引用（vault 里把说明文字写成图片 url、`![[x.pdf]` 少括号）→ 文字占位，不留破图标；
    ④ `[[笔记#标题|别名]]` → 可点 span + `links` 表（79 条能落到图上节点的出站链接）。
    KaTeX 用 vendored 的 0.16.11（`web/vendor/katex/`，js 269KB + css/woff2 base64 0.35MB），
    `emit.build_html` 内联；**woff/ttf 两档兜底必须去掉** —— 否则同一份字体 base64 在 css 里
    出现 3 次，实测 1.06MB vs 0.35MB。

    **运行时**：`render.js:drawLinks()` 只画「视口中心命中节点所属笔记」的出站链接药丸
    （屏幕空间常量大小，最多 10 枚 + 一枚 `+k`）；药丸锚点**必须夹到屏幕中心 +90px 以内** ——
    命中的常常是铺满屏幕的大圆（`_sr` 上千 px），钉它的圆底就跑到屏幕外（第一版实测
    `linkTarget` 有值、`links=0`）。`app.js`：按住 Ctrl 悬停药丸 → `#preview` 浮层
    （构建期 HTML + 运行时 KaTeX，按笔记缓存），跟着光标、clamp 在视口内、内部可滚动。

    **⚠️ 六条别改回去**：
    ① **公式必须整篇「保护」后过 markdown**（见上），否则 auto-render 一个都匹配不到；
    ② **图片只能按路径引用**（519MB），别内联；也**别加 `loading="lazy"`** —— 浮层顶部看不到的
       图片永远不会加载，回归里 `naturalWidth` 全是 0（实测踩过）；
    ③ **药丸锚点要 clamp**（见上），否则命中大圆时一枚药丸都不画；
    ④ **兜底判据是 `painted == 0 && links == 0`**（`render.js` draw() 与 `browser_check` 3c
       两处必须同步）；「已越过链接带」的提示不能删；
    ⑤ **不要断言「预览里没有 `[[`」** —— 代码块里的 `np.array([[1,2]])` 是内容，verify 要先把
       `<pre>/<code>` 剥掉再查（本轮因此假红过一次）；
    ⑥ **KaTeX 是唯一被允许内联的第三方**（用户 2026-10-22 明确选「方案 A」）：只在
       `preview.enabled` 时内联；关掉实验功能就不该为它背 0.6MB。

    **已知限制**：预览是整篇笔记（长笔记要滚动）；KaTeX 极少数宏可能不认
    （`throwOnError:false`，坏公式显示成红色原文）；vault 里写坏的图片引用只能显示占位。

    **第四轮（2026-10-23，用户验收第三轮后重做）**：用户指出药丸是「笔记级」的 —— 不管在
    哪个标题圆里，画的都是整篇笔记的出站链接；又因为命中的常是铺满屏幕的大圆、锚点被夹到
    屏幕中心，看起来是一串漂浮的无主标签。改成：
    **只有「下一级直接是正文」的元素**（没有子元素、自己直接含正文）才在**它自己的实心
    圆里**挂一枚药丸，文案「正文 · N 字」，出现由该圆自己的屏幕半径决定（44px 淡入 /
    64px 满），位置在标签下方（y = cy + 0.42·sr）、宽度 ≤ 1.6·sr；Ctrl 悬停 = 临时预览、
    单击 = 固定预览（Esc / 点浮层外面收），浮层**从这一节的锚点滚起**。
    全局「链接带」窗口、「已越过链接带」提示、视口中心选笔记那一套**全部删除**；
    空视口契约回到 `painted == 0`。

    数据侧给每个节点补 `leaf`（无子节点）/ `tlen`（本节非空白字符数）/ `anchor`
    （预览 HTML 里 `pv-hN`）；预览图片写 `width`/`height`（构建期 Pillow 读真实尺寸 ——
    异步加载不预留高度会让浮层从这一节滑走，公共版实测漂 3000+px）；0 字节图片按缺失处理。

    **⚠️ 第四轮别改回去**：
    ① 药丸必须**按叶子圆**画，别退回「按笔记 / 按视口中心」；
    ② 阈值用**该圆的屏幕半径**（44→64px），不是全局 zoom 带；
    ③ 锚点滚动靠构建期的 `pv-hN`，不是运行时猜标题；
    ④ 预览图片必须带 width/height（否则浮层滚到位后还会滑走）；
    ⑤ 单击药丸要能**固定**预览，否则长笔记根本滚不动；
    ⑥ 断言里不要要求「锚点精确停在顶部」—— 图片/字体加载会有几十像素的合法漂移，
       判据是「锚点落在浮层可视区顶部 ±160px」。

    **第四轮修订（2026-10-23 晚，用户验收后）**：
    ① **药丸判据放宽**：从「`leaf && tlen>0`」改成「`tlen>0`」—— 只要元素**自己直接含正文**
       就挂，有没有子元素都算（用户：「但凡元素内部包含了正文，都应该有药丸可以点」）。
       `leaf` 字段随之删除，避免下一位误以为它还在用。
    ② **图片显示不出来的两个 bug**（用户截图里 90% 的图片是 `Pasted image xxx.png ]` 字样）：
       - **坏嵌入容错规则抢在正常替换之前**：`BAD_EMBED_RE`（少一个右括号的容错）会先吃掉
         `![[x.jpg]]` 里的第一个 `]`，于是 651 个图片链接里 **631 个**退化成「附件」文字。
         修法：先 `WIKI_EMBED_RE` 全量替换，再让容错规则带负向前瞻 `(?!\])` 收尾。
       - **代码围栏里的内容也被替换**：替换出的 `<span class="pv-attach">` 在代码块里被
         markdown 转义，屏幕上直接显示标签字面量。修法：`_outside_fences()` 逐行处理、
         围栏内一律不替换（围栏里的 `![[…]]` 保持原文）。
         修完预览里 `<img>` 从 **36 → 640**。
       ③ **外链 http 图片不加载**（两张：imgur / csdn；离线时一直超时并让
          `browser_check` 的「no console error」假红）→ 退化成可点的链接文字。
       ④ 判据：3e 段「靶子圆 <44px 不挂药丸」只看**靶子自己**（一屏其它大圆仍可能有药丸，
          这是正常的）；verify 增加「有子元素但仍带导语的节点数 > 0」以覆盖非叶子情况。

    **已知限制**：药丸判据是「本节非空」，所以只有一句导语、随后全是子标题的元素也会挂
    （这是用户要的）；

    **第五轮（2026-10-24，用户提出「圆即药丸」）**：用户认为药丸是外挂物、界面不优雅，
    要求**所有元素的实心圆自己就是药丸**：按住 Ctrl + 悬停某个圆 → 若它是**标题**就从
    该标题那一节开始展示预览；若是**文件夹/笔记**则不预览、提示「该层级还没到标题」；
    预览里标题也要渲染出来（像 Obsidian 的悬停预览）。

    实现：删掉整个药丸层（`drawLeafPills` / `linkJobs` / `linkAt` / `stats.links` /
    `hasText` / `tlen` / `leaf` 全删）；复用已有 `hitTest` 在 `app.js` 的 mousemove 里
    取光标下的节点 → 标题圆就 `showPreviewFor(node)`（预览=该笔记 HTML，滚到 `node.anchor`），
    文件夹/笔记圆就 toast 提示。新增**Ctrl 模式虚线圈**（`setCtrlMode` + `drawCtrlRings`，
    按住 Ctrl 时给有锚点的标题圆描细虚线）—— 药丸没了，这是唯一的可发现性线索，**别删**。
    浮层顶部加 sticky 面包屑（`笔记 › 这一节`），滚动要给它让位。

    **⚠️ 第五轮别改回去**：
    ① 药丸层不要加回来（用户明确要「圆即药丸」）；
    ② Ctrl 虚线圈 + 顶栏文案是必须的（否则没人知道圆能悬停）；
    ③ 标题锚点必须是合法开标签 `<hN id="pv-hX">` —— 少一个 `>` 会让浏览器把后续内容
       吞进标题、标题文字消失（实测踩到，用户看到「预览没有标题」）；
    ④ 预览滚动要给 sticky 面包屑让位（`offsetTop - 面包屑高 - 10`）；
    ⑤ `<img>` 只保留一组 `width`/`height`（vault 自带尺寸时先删再加）。

    **第五轮修订（2026-10-24 晚，用户实测错位后）**：
    ① **锚点必须按源文件行号注入**（`<span class="pv-anchor" id="pv-hN"></span>` 放在标题行
       开头），**不要**再按「预览 HTML 里 `<hN>` 的出现顺序」编号 —— 两者对「HTML 块里的
       `#` 行」口径不同，会整体错位一格，表现为**悬停 A 标题却显示 B 标题的正文**
       （用户截图：悬停「例2…」看到「例3…」）。verify 有两条硬断言守它：
       「锚点都注入进 HTML」+「锚点后面紧跟的就是该标题自己的文字」。
    ② **Ctrl 模式下不弹 hover 气泡**（气泡和预览浮层会打架）。
    ③ **单击 = 固定预览**：只在**预览已打开**时接管（否则会吞掉画布单击选中、侧栏/边行
       点击，回归里整段假红）；固定后划过别的圆不打断，`Esc` 关闭；`keyup`/`blur` 里
       `if (!pvPinned)` 才 hide，否则松开 Ctrl 就把固定预览关掉了。
    ④ 滚动让位 = `offsetTop − (面板 padding + 面包屑高 + 8)`；面包屑用纯色 + 负 margin
       盖住面板顶部 padding 区，避免上一节内容从缝隙里漏出来。

    **第五轮已知限制**：文件夹/笔记圆只 toast 不预览；外链图片只显示链接文字；
    代码围栏里的 `![[…]]` 保持原文；没有锚点的标题悬停时预览退回顶部。
vault 里写坏的 markdown（表格里的
    `![[Pasted image…]]`）在浮层里会显示成文字；长笔记要滚动。

42. **产品减法（2026-10-24）—— 这两样别加回来。**
    用户的产品观：**功能越少越好、几分钟就能学会、更容易传播**。这一轮按这个原则砍了两样，
    并在同一个本地分支提交（**不要 push**）：
    + `977e358` 砍掉「按尺度聚合」画边模式（只留逐条链接）；
    + `6af69fe` 砍掉「掌握度 / 重要度」节点标注。

    **为什么砍 / 收益（都是实测过的）**：
    * **聚合边**：用户认为聚合边「效果更乱」，逐条链接已经把知识元素之间的联系说清楚，
      多一个模式只增加理解成本；同时 payload 里 `aggregates` 占 49%，删掉后单文件
      11.26 MB → 6.12 MB（−45%，2026-10-24 12:12 实测），双击打开 / 分享 / 每 30 分钟重建
      都受益。
      代码侧少一条并行画边路径（聚合版 `drawEdges` 152 行 + `resolveAnchor` +
      `drawFocusSegment` + 聚合索引/去重/分色），`render.js` 1804 → 1438 行；
      `kg/graph.py` 507 → 428、`browser_check.py` 1746 → 1597。
    * **掌握度 / 重要度**：这两个标注从建库起就一直是空的 —— `dist/graph.json` 里
      `mastery>0` 的节点 0 个、所有笔记 `weight` 恒为 1.0，界面上只剩「未标注」噪声，
      还和选中 / 搜索 / 邻居三种环抢同一条描边。删掉后顶栏少 2 个控件、图例少一行、
      侧栏少三枚 chip、hover 气泡少一行。
    两次减法都**没删任何回归判据里真正要验的东西**（掌握度本来 0 条断言；聚合边删的是
    4 条只服务它的断言，所以 `verify` 从 118 条 `[ok]` 变成 110）。

    **布局为什么改用「子树笔记数」排序**：原来兄弟排序按节点 `weight` 降序，而 `weight` 在
    未标注时对文件夹 = 子树笔记数、对笔记 = 1.0 —— 也就是说「重要度」唯一实际作用就是让
    文件夹按笔记数排。删掉 weight 后照旧用 `note_count` 表达同一件事（再按 label 稳定次序），
    所以**地图构图与删之前逐位一致**（用户截图人眼核对过）。**如果哪天发现地图整体重排了，
    那是 bug（比如漏了 `note_count` 或改了 tie-break），不是「删标注导致的」** —— 别把
    「构图变了」合理化。

    **测试教训（顺手修的）**：「探针取坐标 → `mouse.click`」的取样点必须排除图例 / 侧栏
    覆盖层 —— `PICK_NODE`、7b 靶子探测、7d `fitPair` 取点现在都要求
    `document.elementFromPoint(...) === canvas` 才认这个点。布局重排一度把这类假红暴露出来：
    点到的圆被覆盖层挡住 →「探针说 A、点击选中 None」。与坑 38 的「整数像素」同源：
    **先证明屏幕点属于画布，再点。**

    **⚠️ 别加回来**：不要恢复 `agg` / `theme.edges` / `weak_edge_min_count` /
    `edge_marker_min_len` / 两套图例 / `edgeMode`；不要恢复掌握度 / 重要度的顶栏下拉、图例行、
    侧栏 chip、hover 行与渲染器描边分支；不要恢复 `annotations.yaml` 的 `mastery` / `weight`
    节点字段或 `precedence`。用户要的是减法；要压「线网感 / 首屏观感」请走
    `lod.idle_edge_dim`、焦点模式、`zoom.home_*` 这些旋钮，不是把模式加回来。

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
| 下一层成熟时父圆压暗到多少 | `zoom.parent_dim`（0.22） | 父圆填充是子圆的底色，调到 0.5 会把同色子圆整体压暗（§4.8）。2026-10-21 起压暗时机从「孩子各自浮现」统一成「下一层成熟」（`dimFactor`，与下一层的淡入带同一区间） |
| 缩到最外层的余量 | `zoom.zoom_out_floor`（1.05） | **必须 ≥ 1**。它把 `zMin` 定成「最小的那个顶层学科刚好看得见」的**地标**（不是滚轮下界，见 §4 坑 32），取 0.9 会让最小那个根在最外层只剩 16.2px < `min_px`，「缩到最外层看见全部 6 个学科」当场破掉。1.05 留 5% 余量抵消落盘时 `r` 只保留 4 位小数的舍入。也决定 2 号判定：地板处每个顶层学科都在画面上 |
| 放大上界的余量 | `zoom.zoom_in_ceiling`（1.35） | 最挤节点完全浮现所需的 zoom × 此值 = `zMax`，即「最挤的节点舒服淡入」那个**地标**（不是滚轮上界，见 §4 坑 32）。调大 → 上界更松；调小 → 还没淡完就到头 |
| 初始视图松紧 | `zoom.home_fit`（1.08） | 刚好装下全图的 zoom × 此值。**上限是 `layout.padding` = 1.12**，再大就会把 Science and Tech 裁出屏幕。1.08 时六个学科全部完整落在视口内（最小根 20.4px，最大根包围盒 411.7px / 视口半高 427px） |
| **同级里的大小差** | `layout.size_exponent`（0.5） | 目标半径 ∝ 叶子数 ^ 此值。**0.5 是无标度不动点**（`√(ΣTᵢ²) = √(ΣLᵢ) = T_parent`），每层缩放退化成与分支数无关的常数 ≈0.85。调大 → 深层膨胀、根 spread 上升（0.6 时 16.2× → 28.3×，最小学科在 home 只剩 18.2px，贴着 `min_px` 没余量）；调小 → 深层急剧缩小、`zMax` 爆掉、缩放跨度拉长 |
| **层级间的大小差** | `layout.level_ratio`（1.5） | 父圆半径 ≥ 最大子圆 × 此值。独子链打包出的包围圆就等于子圆自己，光靠 `padding` 只有 1.12×，肉眼分不出父子；1.5 才看得出（实测 340 条独子链的比值精确落在 1.500） |
| 兄弟圆之间的留白 | `layout.padding`（1.12） | 父圆半径 ≥ 子圆包围圆 × 此值。它同时是 `zoom.home_fit` 的硬上限 |
| 世界坐标量级 | `layout.norm_root_radius`（1000.0） | 虚拟根归一化后的半径。钉住坐标量级，使 JSON 体积可控、`zMin/zMax` 不随 vault 增长而漂移。改它等于等比缩放整个世界（观感不变，但落盘精度与 JSON 体积会变） |
| 退化子树 / 孤点的兜底半径 | `layout.leaf_radius`（1.0） | 正常叶子的半径由缩放链决定，这个只兜底 |
| 整体旋转 | `layout.start_angle`（-90） | 打包完再整体旋转的角度。**同输入必得同输出**是同步任务的硬要求，别引入随机性 |
| **可读性地板（最小屏幕半径）** | `lod.min_px`（18） | 屏幕半径低于 `0.5 × min_px`（9px）的圆**不画**，`[0.5, 1] × min_px` 之间线性淡入。它同时决定 `zMin`（最小学科根在 `zMin` 处恰好是 `min_px × zoom_out_floor`）与同屏圆数上界 `(视口半径/min_px)²`。⚠️ 2026-10-21 起它**不再决定浮现时机**（时机归层级带，见坑 39），只决定「小到这个程度就别画了」 |
| **淡入带宽** | `lod.fade_span`（1.35） | 每一层从 `enter[L-1]` 升到 `M[L] = enter[L-1] × fade_span`，alpha 走 0→1。滚轮每格 1.12 ⇒ 约 2.6 格淡完。**相邻两层入口比 ≈1.84×（约 5.4 格/层）**，所以同一时刻最多一层在淡入（「同层同色」的前提，构建期断言 `M[L] < enter[L]`） |
| **home 停在第几层** | `zoom.home_level`（2） | 层级带阶梯的锚点：`M[home_level]` 由 home_zoom 反解，其余层按等比铺到 zMax。填 1 = home 回到第 1 层（旧观感）；填 3 = 首屏直接看第 3 层 |
| **home 落在该层的哪个位置** | `zoom.home_band`（0.5） | 0 = 该层刚开始浮现（看起来还是上一层），1 = 完全成熟。**别填 1**：层内半径差能到 40 倍，整层满不透明时最大的几个圆会把父圆结构糊成色板（2026-10-21 实测）。0.5 时父圆还透得出来 |
| 标签参与竞争的门槛 | `lod.label_alpha`（0.02） | 标签与圆**同进同出**（2026-10-21）：落笔浓度直接取圆这一帧的 alpha，这个门槛只当「开始参与竞争」的开关，不再是硬切。仍然必须读**未被压暗**的层级带进度，否则祖先层在被 `parent_dim` 压暗后永远够不到门槛、最粗视图一个标签都没有。标签另受 24px 碰撞网格与每帧 400 条预算限制 |
| 标签字号：比例 / 上下限 | `lod.label_font_scale`（0.3）/ `label_font_min`（11）/ `label_font_max`（64） | `fs = min(round(clamp(scale × 屏幕半径, min, max)), 塞得进圆的最大字号)`，塞不进就逐级降到 min、再不行截断加 `…`。落点：sr 40→12、100→30、200→60、≥213→上限 64。**别把上限改回 22**：直径 3135px 的圆里 22px 字只占 4%，整屏就是一块纯色（§4 坑 23）。仍**不要按 depth 分档** |
| 浅层标签半粗门槛 | `lod.label_bold_depth`（2） | depth ≤ 此值的标签用 600 半粗。粗细是「类别」信号、字号是「尺度」信号，两者不冲突 |
| **连线线宽** | `lod.raw_edge_width`（1.0） | 屏幕像素，**刻意不含任何 zoom 因子**：缩放只改线的长度，粗细、颜色、透明度全部恒定 —— 用户要的就是「同一批线在任何尺度上都在，且看起来是同一批线」。想让整束线更醒目就调大它，**别去改 alpha**。校验要求必须是正数 |
| **端点标记的最短线长** | `lod.raw_marker_min_len`（6） | 屏幕像素。**这是唯一一道标记门槛**（聚合边的 `edge_marker_min_len`(20) 已退役，见到会报错）：线恒为 1 px 细线、标记尺寸钉在下限 7px，用 20px 会把大量真实链接的箭头一起压掉，而契约恰恰是「每条链接都看得见」。短边**只跳标记、线照画**。填 **0 = 恒画标记**。校验要求非负 |
| **所有链接的颜色** | `theme.raw_edge`（`#E6EDF3`） | **全部**语义链接线（含整篇级 `[[笔记]]` 与标题级 `[[笔记#标题]]`）的统一颜色，端点标记色由它 `tintLight` 派生、不单独配。**2026-10-20 起不再按粒度分色**，2026-10-24 起也不再按关系类型分色（`theme.edges` 已退役；旧键名 `theme.note_edge` 已被 config 校验拒绝）。选近白是因为七个色相已被 `domains` 占满，而 `#4C8DFF` 同时是 Science and Tech 的节点色 —— 拿它当统一色，线会融进最大的那棵子树里。理由与三条「别改回去」见 §4 坑 34 |
| 焦点模式无关连线压到多少 | `lod.focus_edge_dim`（0.07） | 选中节点后，与它（含其内部子元素）无关的连线压到此不透明度。**0 = 彻底不画**，1 = 不压暗。默认 7% 是有意留残影：保住「这片区域连得多密」的环境感知（Obsidian graph view 也是淡到约 10% 而非删掉） |
| 屏外端点名字 chip 最多挂几枚 | `lod.focus_offscreen_chips`（8） | 焦点边一端在屏外时，视口边止点旁挂写屏外端点名的 chip（§4.22）。**`raw` 下两端都出屏也挂一枚**，名字给非焦点的那一端（§4 坑 22）。超出截断、右下角折叠成一枚 `+k`；设 0 = 全部折叠成 `+k`（视口边箭头/圆点照旧） |
| hover 时连线压到多少 | `lod.hover_edge_dim`（0.75） | 只轻微提亮、不过滤。hover 每帧重算（`evalHover`），相机 tween 时会连续换节点，做强过滤会频闪 |
| **静息态连线浓度** | `lod.idle_edge_dim`（0.45） | **既没选中、也没悬停**时所有连线的浓度。2026-10-21 新增：原先这个状态复用了 `hover_edge_dim`(0.75)，于是「刚打开界面」就满屏 0.75 的白线、首屏显得很吵（用户报的「网线感」）。现在只有**选中**浅层大元素时才靠 `1.0` vs `focus_edge_dim`(0.07) 的对比呈现网线感。调大 → 回到旧观感；调到 0.3 以下开始看不清连接关系 |
| **连线两端离圆边多远截断** | `lod.edge_trim_clearance`（2） | 屏幕像素。线不再画到圆心，两端各留这么宽的空隙，端点标记正好落在这里。0 = 线插进圆心（箭头会被圆盖掉，§4.20）。调大 → 线和标记离圆更远，短边更容易触发 `raw_marker_min_len` 而不挂标记（线照画） |
| **端点标记提亮多少** | `lod.edge_marker_tint`（0.55） | 标记色 = 线色向 `#d6dbe4` 混白的比例，取值 `[0,1]`。提亮让标记比线本身更亮，压在底图 wash 上也认得出；1 = 标记全变成浅灰 |
| 链接权重 | `weight.wiki_link` 1.0 / `heading_link_bonus` 0.5 / `embed_factor` 0.6 / `annotation_default` 3.0 | 只服务**边**（链接强度 / 侧栏排序），不再影响节点大小 |
| 学科配色 | `theme.domains` / `theme.fallback` | 父子同色是刻意的（整条包含链继承学科色），别给子节点单独配色（§4.11）。`theme.domains` 现在有 7 个键：private 的 6 个学科 + `"Study log"`（public 的第三个根，`#F0883E`）——缺色的根会落 `fallback` 灰，所以新增公开根时记得补一行。**边色不在这里**：所有链接统一 `theme.raw_edge`，关系类型由线型/箭头表达（`theme.edges` 已退役） |
| 候选边挖掘松紧 | `candidates.min_score` 0.45 / `min_term_len` 4 / `max_doc_freq_ratio` 0.25 / `min_shared_terms` 2 / `max_suggestions` 400 / `generic_headings` | |

### `web/render.js` 顶部常量

| 常量 | 值 | 作用 |
|---|---|---|
| `FOOTER_H` | 46 | canvas 的底部预留带：内容视口 = `H - FOOTER_H`，适配半径与 `farCornerDist`（判定「圆铺满视口」）都按它算。`#footer` 本身是右下角绝对定位块，改这个值等于改铺满判定，别随手调（§2） |
| `LABEL_CELL` | 24 | 标签碰撞网格边长（屏幕像素） |
| `LABEL_BUDGET` | 400 | 每帧最多考虑多少个标签候选 |
| `CULL_MARGIN` | 32 | 视口外扩余量。裁剪必须**按半径外扩**：大圆的中心常常在屏幕外，圆本身却铺满整屏 |
| `LABEL_INSIDE_PX` | 28 | 屏幕半径超过这个值的容器，标签压在圆内顶部而不是圆心（§4 坑 23；没有「改挂圆外」了） |
| `PAINT_MIN` | 0.02 | 「这一笔算不算画出来了」的最低不透明度。低于它的落笔在 8 位画布上合成后与背景完全同值（≈0.2/255，四舍五入成 0），肉眼与像素读回都看不见。`stats.painted` 与全空白兜底提示都按它判 —— 所以**不能**改成「有没有发起过绘制调用」那种计数（§4 坑 33） |
| `FONT` | 系统字体栈 | **字号不是常量**：由 `labelFontSize(sr)` + `fitFont` + `clipLabel` 三个函数按屏幕半径算出来（调参走 `lod.label_font_*`，见 §5）。行高 `hpx = fs + 4`；圆内摆放 `sy = cys - sr + fs*0.5 + 4`，任何字号下文字上边界都离圆描边 2px |

旧表里的 `HIT_CELL` **已不存在**：拾取不再用网格，`hitTest` 就是对 `lastDrawn` 的线性扫描
（同屏圆数被 `min_px` 钉成常数上界，最多一百多个，不需要空间索引）。

`TRIM` / `RAW_MARK_MIN` / `MARK_TINT` 也在文件顶部，但它们是 `lod.edge_trim_clearance` /
`lod.raw_marker_min_len` / `lod.edge_marker_tint` 的读取结果（`== null` 兜默认，不是 `||`
—— 0 是合法值），改数值请改 `config.yaml`，别改这里。
`MARK_LIGHT`（`#d6dbe4`）与 `MARK_RGB`（按 tint 预混好的标记色表）是硬编码的，
换主题配色时要一起看。

`CHIP_MAX` 读 `lod.focus_offscreen_chips`（缺省 8）；折叠的 `+k` chip 右锚在
`(W-12, H-FOOTER_H-12)`，即右下角、避开 footer 预留带——改 `FOOTER_H` 会连带挪它。
`chipJobs` 一共三处入队（单端在屏外 / 两端都在屏外 / `+k` 折叠），上限对三处**合起来**生效。

图例 DOM：只有一块 `#legend-rel`（2026-10-24 由 `#legend-rel-raw` 改名；
`#legend-rel-agg` 与 `applyEdgeLegend()` 已删）。折叠/展开见 §4 坑 37。

方向键平移**没有常量、也不读配置**：`panStep(fast)` 按视口现算 ——
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
不用碰代码；渲染侧与浏览器回归套件都已适配（那一批的 `browser_check` 是 84 [ok] / 0 FAIL；
现在是 132 / 133，见 §8）。同批还修了回归套件的
fixture：改成按后缀解析，笔记改名不再让 7d 整段静默跳过（§4 坑 24）。已提交（第13步 `b528d2d`）。

**P0 — 已完成并提交**：**修掉「画布全黑却没有任何提示」这个真 bug** ——
兜底判据从「候选集是否为空」改成 `stats.painted`，新增 `PAINT_MIN` 与 `nearDist`（见 §4 坑 33）；
同时补上 3d 段「任何缩放 × 任何平移都不许留下无提示的空白」的 36 组整画布探针，
并订正两条被写错的断言（§8）。断言基线当时从 103 → 108 → 156 → 162（中途膨胀是因为
给 1c 段和 raw/agg 双轮加断言）；**2026-10-24 删掉模式切换后回落到 110 `verify` 断言 /
132（private）· 133（public）`browser_check`**，见 §8。

**P1 — 首屏观感（用户明确说过后续还有一版改动解决）**
先问清楚他要什么，别自己猜。可动的旋钮都在 §5：`zoom.home_level` / `zoom.home_band`、
`lod.idle_edge_dim`、`lod.min_px`、`layout.*`。**原 P1「让掌握度 / 重要度真正起作用」已取消**
—— 2026-10-24 的产品减法把这两套节点标注整体删了（见 §4 坑 42），别再把它当待办加回来。

**P2 — 候选边审核流程**
`candidates.yaml` 手工改 `status` 很累。可在页面里加「审核模式」：列出候选边，
点 accept/reject 后**导出 YAML 文本**给用户自己粘回文件（保持工具不写用户文件的边界）；
或写 `build.py review` 交互式命令行逐条确认。

**P3 — 规模压测**
当前 3558 节点（private，示例快照 verify6 = 2026-10-17 00:15）、idle rAF 63 fps（示例快照
bc6 = 2026-10-17 23:05）。没测过上限。可做：临时把范围放宽到全 vault
（在 `public-scope.yaml` 里给 `Logs`、`Excalidraw` 之类加一条 `scopes: [...]` 就行，
**不要去改 `config.yaml`**——`include` 这个键已经不存在了）；或造 1 万节点合成数据测深层渲染
与拾取。已知热点是标签竞争与逐条链接的落笔（home 视角约 96 条边 / 130 个端点标记；
聚合边那条「重建」热点随模式删除，见 §4 坑 42）；拾取现在是线性扫描 `lastDrawn`，
规模上去后也要回头看一眼。

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

✅ 这轮改动**早已提交**（见 `git log`），别再当成「工作区未提交」。

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
- 不要在没跟用户确认的情况下新增第三方依赖（前端尤其）。**唯一例外**：KaTeX（2026-10-22，
  用户为「Obsidian 式预览」明确选的内联方案），见 §4 坑 41；除此之外运行时仍零依赖。
- **不要在没跟用户确认的情况下改 `alphaOf` 的函数体**——那条淡入淡出曲线
  （`levelFade × dimFactor`，层级带之后由它们合成）用户已经人眼验收过。
  要调观感先动 `zoom.home_level` / `zoom.home_band` / `lod.fade_span` / `zoom.parent_dim`。
  （2026-10-21 那轮把「per-node smoothstep」整体换成了层级带，`alphaOf` 的函数体确实改了
  —— 那是用户点名要的改动，不是顺手改；除此之外它的语义没被动过。）
- **不要把「公开哪些目录」再写回任何脚本或 `config.yaml`**（P5 刚拆掉的就是这两份），
  也不要在 `public-scope.yaml` 里为「顺手」加与范围无关的配置——它是两份 scope + 站点
  三方共用的文件，改它等于改发布面。
- **不要动两个 `.ps1` 的编码**（必须是 UTF-8 **带 BOM**，见 §4 坑 26）；
  也不要往 `cmd_scope` 里加任何非 JSON 的 print（见 §4 坑 27）。

---

## 8. 回归基准（改坏了怎么发现）

下面的数字分两批读：**2026-10-24 12:12 的新基线**（`verify --scope all` 合计 **110 `[ok]` /
0 FAIL**（private 55 / public 55）；`browser_check` private **132** / public **133 `[ok]`**、0 FAIL、1 warn），以及后面 JS
块里那些 **2026-10-17 / 18 的示例快照**（当时还有聚合边，块里的 `agg` 行只当历史，别拿它比）。
**要盯的是「全绿 / 0 FAIL / ok 数没掉」这些结构性结论，不是绝对数**；要刷新就重跑。
（2026-10-21 层级带改造后曾是 private 166 / public 167 `[ok]`；2026-10-24 删掉模式切换后回落
到 132 / 133 —— **数字下降是删用例不是静默跳过**：1c 整节 14 条 + 7b/7c/7d 不再各跑两遍的
43 条 = 53 条，与 185−132 逐条对得上。）

```bash
python build.py build      # private：笔记 114 / 文件夹 37 / 标题 3359 / 节点 3510（2026-10-24 12:12）
                           # 深度轴 10 / 语义边 97 / 包含边 3504 / 标题级链接 68（未命中 14）
                           # layout_root_radius 1000.0 / nominal_fit_radius 427px / HTML 6265 KB
python build.py build --scope all   # 再出一份 public：节点 3466 / 最深层 3559 条边 / HTML 6291 KB
python build.py verify     # 必须 ✓ 全部自动校验通过（合计 110 [ok] / 0 FAIL：private 55 / public 55）
python build.py scope --scope public   # stdout 必须是一段能 ConvertFrom-Json 的 JSON（§4 坑 27）
python browser_check.py    # 必须 ALL BROWSER CHECKS PASSED；ok 数 private 132 / public 133
                           # （两份不再相等：条件跳过不同。ok 数掉下去就是有用例被跳过）
                           # （warn 只允许条件跳过，不允许失败；[ok] 数掉下去
                           #   就说明有用例被跳过了 —— 见 §4 坑 24）
                           # 默认查 private 那份 HTML（dist/knowledge-graph.html）；
                           # 换 public：KG_HTML=knowledge-graph.public.html python browser_check.py
node --check web/app.js && node --check web/render.js   # 前端语法（一次只查一个文件）
```

`verify` 里最该盯的三条不变量——它们破了，「子在父内」和「放大 = 更深」就都不成立了：

1. **包含越界 0 个**（每个节点都完整落在父节点圆内）；
2. **兄弟相交 0 对**（private 当前 **6766** 对，2026-10-24 12:12 快照；会随 vault 漂）；
3. **`r` 沿包含链严格递减**（违反 0 个）⇒ `minzoom` 严格递增 ⇒ 孩子绝不会比祖先先浮现。

另加本轮新入的那条（换 scope / 改 `as` 时最容易踩）：**重写过的路径前缀没有残留成节点 id**
（残留 0 个），以及 depth=1 的根 == 该 scope 声明的目录（private 6 个 / public 3 个）。

浏览器里再确认（下面的读数全部来自**示例快照 bc6 = 2026-10-17 23:05** 那一批 payload 上的
`browser_check.py` 实跑，1440×900；会随 vault 内容漂移，要刷新就重跑那个套件 ——
数据侧同一批参数见 §3。口径与 §3 快照章一致，**不要**把这里任何单个数字当不变量断言）：

```js
KG.state()                 // 示例快照 bc6：zoom 0.4610 / level 1 / shownNodes 55 / shownEdges 96 / shownLabels 26
                           // （2026-10-24 起没有 edgeMode 字段了；shownEdges 就是唯一画法的读数）
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
#   只有逐条链接一种画法（2026-10-24 起 7b 只跑一遍，不再标 `[raw]` / `[agg]` 后缀），
#   目标节点 = Science and Tech/Electronic engineering/Electronic engineering basic
#   （depth 3 / sr 81px；示例快照 bc6 = 2026-10-17 23:05）：
#     home: shownNodes 55 / shownEdges 96 / marks 130（public 那份：52 / 95 / 130）
#     选中 → focusEdges 38 / focusNeighbors 8 / marks 66；Esc 后 shownEdges 仍 96
#   （顶栏「关系 17/22 · 相邻 10」那种读数是旧聚合模式口径；现在页脚只有「关系 N / 总数」，
#     别写死具体数）

# 端点标记基线（7c 小节自动断言，读 KG.renderer.markJobs）：
#   开扫前必须 `renderer.selected = null` —— `drawFocusEdges` 会另外补画「被主绘制趟那道
#   几何门挡下的焦点边」的标记（现在只有一道门，见 §4 坑 21），而比较用的 shownEdges 只算
#   主绘制趟的边；带着上一节的选中开扫，就会出现「2 条边 6 个标记」这种假红（本轮实测踩到过）。
#   这一段验的是普通边标记的几何，与选中无关，所以把选中清掉让输入集干净。
#   home（示例快照 bc6 = 2026-10-17 23:05；**marks 两份 HTML 相同、edges 不同**）：
#     marks 130 = 箭头 65 + 源点 65（对应 96 条边；public 那份 95 条）
#   每个标记到所附圆边间隙恒为 2px；圆内 0 个
#   zoom 阶梯（enter[L-1]×1.05 那一档，L=10..1；读数 = 画出的边数 / 标记数；
#   示例快照 bc6 = 2026-10-17 23:05）：
#     private  L=10 12/24 · L=9 14/28 · L=8 16/32 · **L=7 32/64** · L=6 38/72 ·
#              L=5 42/80 · L=4 57/100 · L=3 92/150 · L=2 91/150 · L=1 96/120
#     public   L=10 19/38 · L=9 26/48 · L=8 29/54 · **L=7 34/68** · L=6 37/70 ·
#              L=5 42/78 · L=4 58/102 · L=3 93/150 · L=2 91/92 · L=1 89/86
#   —— 以前只测 depth 6 一档，那是私有图的形状（公开图在 depth 6 当时只画得出
#      一条 4px 的截断边，门槛合理地压掉标记，marks=0）。现在改成沿 payload
#      自己的 zoom 阶梯逐层扫 L=10..1；判据只要求「探针量到的**长边**」带标记
#      （`long_rungs`，见下面 ③），不再要求「有 ≥2 条边在屏的层就得有标记」。
#   不变量（⚠️ 四条都别「收紧」回去）：
#     ① **`marks <= 2*edges` 是硬不变式，`marks < 2*edges` 不是。** 每条画出的边可以
#        两端各挂一个标记（源端圆点 + 目标端箭头），所以「7 条边 14 个标记」完全合法 ——
#        实测 rung **L=7 就是 32/64**（示例快照 bc6 = 2026-10-17 23:05）。
#        写成严格小于会在正常数据上假红。
#     ② **`lod.raw_marker_min_len` 守卫**是否在生效，单独用「**阶梯上存在某档 marks < 2*edges**」
#        证明（确实有短边被压掉）。守卫一旦被删，整条阶梯会顶满 2×edges，这条就红。
#     ③ 阶梯那条判据**曾经**写成「有 ≥2 条边在屏就要求有标记」，那是假红，已改成
#        `long_rungs`：渲染器判门用的是未截断的 `glen`，探针量的是截断后的弦长，
#        截断一压就可能出现「2 边 / 0 标记」（**当时那批快照**里 private L=9 出现过
#        弦长 4.01px < 门槛 20）—— 那是正确行为。同一轮还**删掉两条曾想加的等式断言**
#        （`探针条数 == shownEdges`、`marks == 2×long`）：被 `edge_trim_clearance` 压到
#        零长度、focus 兜底都会让两边差一两条，绑上去就是间歇性假红。真正钉得住的只有 ①②。
#        ⚠️ 弯边/扇形那套已整体删除：现在**恒直线**（`lineTo`），别再按弯边推理形状。
#     ④ minGap ≈ maxGap ≈ edge_trim_clearance。

# 屏外兜底基线（7d 小节自动断言，读 KG.renderer.chipJobs）：
#   2026-10-24 起这一节只跑一遍（不再分 raw / agg）。
#   深缩放选中 fixture（SEL = 理解傅利叶变换&频谱密度的几何意义，
#                       TGT = 5.1.2 定积分的定义(本质是求和的极限)）：
#     (a)  **一端**在屏外：focusEdges 1 / chips 1；线照画到屏外，chip 挂在它穿出视口
#        的那一点；chip 文以「5.1.2 定积分的定义」开头（chipLabel 截 18 字）
#     (a2) **两端都**在屏外（bc8 = 2026-10-18 22:46）：focusEdges 1 / chips **1** /
#       shownEdges 16 / anchored true / tgtChips ["5.1.2 定积分的定义(本质是求和…"] / selChips []
#   侧栏出边行点击 → fitPair 一次 tween 框住两端（两个包围盒都在视口内），
#     且 selected 切到 TGT；示例快照 bc6 = 2026-10-17 23:05 下是 focusEdges 2 / marks 4
#   18 组缩放×选中组合：chips ≤ CHIP_MAX+1；**2 组触发折叠**（chip_max=8）——
#     `…/Electronic engineering basic/LTI analysis` deg7 mult8→n9、末尾 chip 收成 `+7`；
#     `…/Mathematics Basic/Calculus` deg5 mult8→n9、收成 `+1`，两枚都 right-anchored
#   不变量（别按旧 agg 的读数收紧）：
#     chip 数 ≤ 当帧屏外端焦点边数；两端屏外的边**照画线**（横穿视口也 stroke）
#     **并且也挂一枚 chip** —— 名字给非焦点端、且要求这一帧真落了笔（`laid`）
```

改完视觉**必须重新截图并人眼看**：`python browser_check.py` 后 ReadMediaFile `%TEMP%\kg_0*.png`。
