# 知识笔记语义缩放可视化系统

把 Obsidian vault 里指定范围的笔记，做成一张**像地图一样按缩放级别切换显示粒度**的图：
滚轮放大 → 看到更细的知识结构，滚轮缩小 → 收拢回学科总览。

深度轴一共 **10 层**，从最粗到最细：

```
顶层文件夹 → 中间文件夹 → 子文件夹 → 笔记(.md) → 一级标题 → 二级 → 三级 → 四级 → 五级标题
```

文件夹、笔记、标题都是人为规定的**存储结构**；这张图关心的是知识内在的**包含关系**与**连接关系**，
所以包含关系画成同心圆布局（不画成一堆线），连接关系画成细线。

产出是一个**单文件 HTML**（`dist/knowledge-graph.html`），双击就能在 Chrome 里打开，
不需要服务器、不需要联网。**渲染是自绘的 Canvas2D，没有用任何第三方图形库**（早期版本用
Cytoscape，已整体替换，原因见 `HANDOFF.md`）。

```
python build.py scan      # 扫描 vault，打印纳入/排除与链接统计
python build.py suggest   # 挖掘候选边 → candidates.yaml（待你审核）
python build.py build     # 生成 dist/graph.json 与单文件 HTML
python build.py verify    # 跑自动校验（每次改动后都要跑）
python build.py watch     # 笔记改动后自动重建（2 秒轮询，挂在旁边即可）
python build.py all       # scan + suggest + build
```

只用到一个第三方依赖：`PyYAML`（`pip install pyyaml`）。Python ≥ 3.9。

回归验证：

```
python build.py verify      # 数据侧断言
python browser_check.py     # 浏览器侧 52 项断言（Playwright + 本机 Chrome，自动截图）
```

---

## 1. 改「公开哪些文件夹和笔记」

**唯一入口是 `config.yaml`**，不需要碰 Python 代码：

```yaml
include:                        # 白名单：想公开哪个目录就加一行
  - "Science and Tech/**"
  - "Economy and Finance/**"
  - "Medical and Health/**"
  - "Literature History Philosophy/**"
  - "Interest/**"
  - "Projects/**"

exclude:                        # 黑名单，优先级高于 include
  - "**/private/**"
  - "**/draft*"                 # 文件名含 draft 的一律排除
  - "**/*.excalidraw.md"

exclude_notes: []               # 逐篇排除：写笔记名（不带 .md）或相对路径
```

改完跑 `python build.py build`。想先确认范围对不对，跑 `python build.py scan`：

```
[公开范围]  vault 内 .md 共 133 篇，纳入 107 篇，排除 26 篇
[层级]      文件夹 35 个，最大深度 5
[深度分布]  笔记所在层：{2: 9, 3: 40, 4: 54, 5: 4}
[链接]      [[链接]] 总数 735
  附件链接         ██████████████████████·· 652
  笔记→笔记        █······················· 40
  自链接           █······················· 42
  解析失败         ························ 1   ← [[My tech log]]，目标笔记不存在
```

附件链接（指向 png/pdf 等）会被丢弃，不进图。

---

## 2. 与笔记保持同步

笔记会一直改，所以图必须能自动跟上。三种方式，按需选：

| 方式 | 命令 | 适用 |
|---|---|---|
| 手动 | `python build.py build` | 改完立刻看效果 |
| 实时监听 | `python build.py watch` | 开发/整理笔记时挂在旁边，存盘即重建（2 秒轮询） |
| 定时任务 | `sync-graph.ps1` | 平时后台每 30 分钟重建一次，无需开着终端 |

`sync-graph.ps1` 是给 Windows 计划任务用的包装脚本，它做四件事：

1. **防重入**：`sync-graph.lock` 存在且 2 小时内没结束就 skip（上一次还在遍历 vault）。
2. **强制 UTF-8 输出编码**：`build.py` 输出含中文，不改会在日志里变乱码。
3. **跑 `python build.py build`**，把输出最后 4 行 + exit code 追加进 `sync-graph.log`。
4. **裁剪日志**：只保留最近 400 行。

它**只重建 `dist/`，不碰 vault 里的任何笔记，也不做任何 git 操作**（vault 由 obsidian-git 自己备份）。
`.log` / `.lock` 都在 `.gitignore` 里。

注册计划任务（**请自己确认后执行**，每 30 分钟一次，在 :07 和 :37 触发）：

```
schtasks /Create /TN "Knowledge Graph Auto Sync" /SC MINUTE /MO 30 /ST 00:07 /RL LIMITED /F /TR "'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'D:\obsidian_vault\knowledge-graph\sync-graph.ps1'"
```

> 为什么是 :07/:37：机器上已有的 `Quartz Site Auto Sync` 是每 30 分钟从 :24 起算（:24/:54），
> 两个任务都遍历同一个 vault，错开 17 分钟避免撞车。

取消：`schtasks /Delete /TN "Knowledge Graph Auto Sync" /F`

浏览器里已经打开着旧页面时，重建不会自动刷新——**重新双击一次 HTML 即可**（单文件，没有缓存问题）。

---

## 3. 图里画什么

### 节点：一律实心圆

所有层级（文件夹 / 笔记 / 标题）都画成**实心圆**，靠三个视觉变量区分：

| 变量 | 含义 |
|---|---|
| **颜色** | 所属顶层学科（`theme.domains`，6 色 + 灰色 fallback） |
| **大小** | 规模：文件夹=旗下笔记数，笔记=标题数 + 链接权重，标题=子标题数 |
| **白色描边** | 掌握度 1–5（越粗越实=越熟）；`0` = 未标注，只有暗色细边 |
| **黄色光晕** | 搜索命中 |

之所以全用实心圆：用户是靠 ctrl+滚轮缩放在层级之间穿行的，不同层级的内容本来就靠淡入淡出
区分，再叠加「方框=文件夹、圆=笔记」的形状编码是冗余信息，只会让密集层更难读。

### 边：只画「连接」，不画「包含」

- **语义边（细线）**：前置 prerequisite（灰，带箭头）／引用 derives（蓝，带箭头）／
  并列对比 contrast（橙虚线，无箭头）。
- **heading → heading 的链接是真边**：`[[Calculus#二阶常系数非齐次微分方程的通解求解步骤]]`
  会精确连到 Calculus 笔记里那个标题节点上（当前 66 处命中，12 处锚点未命中，见 §7）。
- **聚合边**：当两篇笔记之间有很多条标题级链接时，在较粗的层级上它们被合并成
  「各自祖先之间的一条边」，**线宽 = 被合并的原始链接数**。这就是跨层级链接的处理方式（§4）。
- **包含关系不画成网状线**：同心圆布局本身就在表达包含。hover 或选中某节点时，
  才用**虚线**画出它的祖先链，并在侧栏顶部给出面包屑。

---

## 4. 语义缩放与淡入淡出（核心机制）

**方向：滚轮向上 = 放大 = 看到更深的层级**，和地图软件一致。

这个方向不是自动成立的，是靠 `kg/layout.py` 的 `_apply_depth_floor` 按深度封顶封出来的：
每一层的 `minzoom` 由「该层最挤的节点需要多大 zoom 才能满足最小屏幕间距」决定，
再对深度做单调封顶，保证「越深 → minzoom 越大 → 必须放得更大才看得见」。

### 每个节点自己决定何时浮现

构建期给每个节点算一个 `reveal`（= 它与同层最近邻的世界距离），渲染期：

```
minzoom = lod.min_px / reveal          # 屏幕间距达到 min_px 像素时开始浮现
alpha   = smoothstep(minzoom/fade_span, minzoom, zoom)   # 在 fade_span 倍率带宽内淡入
```

所以**淡入淡出是 per-node 的连续过程，不是 per-layer 的开关**。放大时深层节点从各自的
位置逐个「长出来」，父层节点则被 `zoom.parent_dim`（0.5）压暗但保留，作为上下文。

### 跨层级链接怎么办（这是你问的那个疑惑）

地图软件处理「北京到上海的高铁」时，在省级图上是两个省会之间一条线，在市区图上是两个
车站之间一条线。它用的是**两层机制叠加**，本项目照搬：

1. **层级预聚合（generalization）** —— 构建期已算好 `aggregates[L]`：任意两个元素之间的
   关系，在第 L 层表现为「各自在第 L 层的祖先」之间的一条聚合边。所以一条 heading→heading
   的链接**在每个尺度上都有一个唯一确定的代表**，不需要在渲染期临时决定端点。
2. **per-node minzoom** —— 就是 Mapbox vector tile 里那个 `minzoom` 字段。端点自己决定
   什么时候浮现，**边的 alpha 直接取两端点 alpha 的最小值**。

于是：「这条边现在画在哪两个点之间」由 (1) 决定，「它现在该不该出现、多透明」由 (2) 决定。
**边本身不做独立的淡入淡出——那是它两端点的事。** 两端都在淡入带里时，边跟着一起淡。

### 换层与跳层

- **层级胶囊**（顶栏 1..10）点一下就跳到那层；**`[` `]`** 逐层换；
  **`zoomToDepth(d)`** 是控制台入口。
- 每个层级有一个 `enter[L]` 缩放值（= 该层所有节点 minzoom 的前缀最大值的中位数），
  保证跳层后该层内容确实看得见。**方向锁**：只允许向更细的方向用 `enter[]`，
  向粗方向走时不强行改相机，避免来回跳。
- **双击空白处**回到 home 视角（`lod.home_layer = 4`，即全部笔记那一层）。
- 缩到最深却落在没有内容的地方时，画布上有兜底提示文字。

---

## 5. 交互

| 操作 | 效果 |
|---|---|
| ctrl + 滚轮 / 滚轮 | 连续缩放（光标处锚定，`zoom.wheel_step = 1.12`） |
| `[` `]` | 换到更粗 / 更细一层 |
| 顶栏层级胶囊 1..10 | 跳到指定层 |
| 拖拽 | 平移 |
| 双击空白处 | 回到 home 视角（depth 4） |
| 单击节点 | 右侧详情栏：面包屑、掌握度、入边、出边、标题清单 |
| 悬停 | 气泡（标题、所属、掌握度、摘要）+ 画祖先链虚线 |
| 搜索框 | 命中节点加黄色光晕，点结果直达并换层 |
| 学科 / 掌握度下拉 | 过滤 |
| 标签下拉 | 自动（默认，按屏幕密度竞争）／全部显示／只显示选中 |
| 侧栏「在 Obsidian 打开」 | `obsidian://open?…` 跳回 Obsidian |
| `Esc` | 取消选中 |

**「我在笔记里加了个标题，会自动出现在图里吗？」会。** 标题层是每次构建时从正文实时解析的。
重建方式见 §2。

---

## 6. 给图谱加语义：三种方式

### 6.1 `annotations.yaml`（推荐，手工但集中）

不用往 107 篇笔记里塞 frontmatter，全部标注集中在一个文件里：

```yaml
notes:
  "模拟集成电路":
    weight: 5          # 重要度，影响节点大小
    mastery: 3         # 掌握度 1-5，影响白色描边
    aliases: ["模电"]  # 让 [[模电]] 也能解析到这篇
edges:
  - source: "MOSFET"
    target: "模拟集成电路"
    type: prerequisite  # 或 derives / contrast
    weight: 3
    reason: "模电第一节课就是 MOSFET 的小信号模型"
```

优先级：`annotations.yaml` > 笔记 frontmatter > 自动推断的 wiki 链接
（`config.yaml` 的 `precedence` 可以翻转）。

### 6.2 笔记 frontmatter（可选）

支持 `prerequisites` / `derives` / `contrasts` / `mastery` / `weight`。写了就生效，不写不影响。
`parent` / `subject` / `domain` 只作为显示信息，**不会**改变层级归属。

### 6.3 `candidates.yaml`（自动挖掘 + 人工审核）

`python build.py suggest` 离线挖掘候选边，每条带得分、类型、理由：

```yaml
candidates:
  - source: "半导体物理(大三上)"
    target: "半导体物理(大二下)"
    type: contrast
    score: 0.99
    reason: "共享术语：junction、impurity…；两篇笔记都含有同名标题，疑似同一门课的不同版本"
    status: pending
```

把想保留的 `status` 改成 `accepted`，再 `python build.py build`。`pending` / `rejected` 都不进图。
**重跑 `suggest` 会保留你已有的审核结果**，不会把 accepted 打回 pending。

三条启发式：标题与笔记同名（→ 前置）／英文术语与 LaTeX 符号的逆文档频率共现（→ 并列）／
同名标题跨 3 篇以上笔记（→ 疑似重复笔记）。中文不分词——不引入 jieba 这类重依赖，
中文侧只做标题精确匹配，宁缺勿滥。

---

## 7. 目录

```
knowledge-graph/
├── config.yaml            唯一维护入口：公开范围/缩放/权重/布局/LOD/配色
├── build.py               CLI：scan | suggest | build | verify | watch | all
├── verify.py              数据侧自动校验（断言式，无测试框架）
├── browser_check.py       浏览器侧自动回归（Playwright + 本机 Chrome，52 项断言 + 截图）
├── sync-graph.ps1         计划任务包装脚本（防重入 + UTF-8 + 日志裁剪）
├── kg/                    数据管道
│   ├── config.py          配置加载与校验（非法配置给中文报错）
│   ├── scan.py            白名单 glob 扫描
│   ├── parse.py           frontmatter / 标题树（跳过代码块）/ wiki 链接 / 摘要
│   ├── graph.py           层级树、语义边、按层聚合边、标题级链接、reveal
│   ├── candidates.py      候选边挖掘（3 条启发式）
│   ├── layout.py          同心圆布局 + reveal/minzoom + 深度封顶
│   ├── ioutils.py         stdout UTF-8
│   └── emit.py            输出 graph.json 与自包含单文件 HTML
├── web/                   前端源码（构建时全部内联进单文件）
│   ├── template.html      骨架 + CSS（顶栏 / 侧栏 / 画布 / footer）
│   ├── app.js             状态机、搜索过滤、侧栏、层级胶囊、事件绑定（550 行）
│   └── render.js          Canvas2D 渲染器：相机、淡入淡出、聚合边、拾取（739 行）
├── annotations.yaml       你的手工标注
├── candidates.yaml        候选边（待审核）
├── HANDOFF.md             交接文档：现状、实测数据、坑、待办、调参地图
└── dist/                  构建产物（gitignore）
    ├── graph.json         中间产物，调试用
    └── knowledge-graph.html  ★ 双击打开（约 8.7 MB）
```

数据流：vault → `kg/*` → `graph.json` → 内联进单文件 HTML → Canvas2D 自绘。

---

## 8. 关键实现决定（维护时先看这里）

1. **单文件必须全内联。** Chrome 在 `file://` 下禁止 `fetch`/XHR 读本地文件，
   HTML 一旦去 fetch `graph.json`，双击打开必然失败。数据与全部 JS/CSS 都内联。
   代价是 8.7 MB，但换来「双击即用」。

2. **坐标一次算定，缩放只改可见性。** `layout.py` 用同心圆布局：
   半径 `base_radius × ring_ratio^(depth-1)`（300 → 510 → 867 → … → 35576），
   角度按子树规模加权（`angle_power = 0.5` 次线性，避免大子树吃掉整圈）。
   渲染期**不做任何布局计算**，所以缩放时节点永不跳动。`verify.py` 断言「切层前后坐标零漂移」。

3. **`reveal` 必须沿包含链取前缀最小值。** 一个标题的可用间距不能大于它所属笔记的间距，
   否则会出现「子节点已经浮现、父节点还没浮现」的空心结构。

4. **同心圆 ≠ 地图，不能直接照搬 zoom→细节的映射。** 地图把细节编码成**尺度**
   （放大后同一块地物变大、露出更多细节），同心圆把深度编码成**半径**。
   两者不同构，所以必须额外叠一层 per-depth 封顶（`_apply_depth_floor`）才能让
   「放大 = 更深」成立。

5. **同一圈的疏密与半径无关。** 屏幕上相邻节点的间距 ≈ 视口半径 × Δθ，只跟角度分配有关。
   所以「太挤」要用 `angle_power` 调角度分配，「圈与圈分不开」才用 `ring_ratio` 调半径。
   从 `min_gap` 反解半径是范畴错误（早期版本犯过）。

6. **`<canvas>` 是替换元素**，CSS 必须写 `width:100%; height:100%`，
   同时 JS 里设 `canvas.width/height` 为设备像素，两者缺一就会模糊或尺寸错位。

7. **相机 tween 每一帧都必须回调 `onCamera`**，否则动画期间画布不重绘，看起来像卡死。
   `browser_check.py` 用「连续两帧快照比对」来收口这类问题。

8. **标签门槛读的是「未压暗的淡入进度」，不是最终 alpha**（`lod.label_alpha`）。
   祖先层被 `parent_dim` 压到 0.5 之后就永远够不到 0.55 的门槛，
   结果最粗的视图（最该有标签的视图）会一个标签都没有。这是个踩过的 bug。

9. **`parse.py` 有意不排除行内代码里的 `[[Foo]]`。** 笔记里用 `` `[[Foo]]` `` 举例时
   确实会产生一条假链接，但排除行内代码会连带干掉大量正文里合法的链接写法，
   权衡后保留，宁可多一条弱边。

---

## 9. 校验

### `python build.py verify`（数据侧）

- 深度轴 10 层，每层节点/边数与 `levels` 一致
- 所有边两端都存在；附件没有被当成节点；链接解析统计完整
- 节点坐标两两不同；**切层前后坐标零漂移**
- **每个节点的「首现层级」沿深度轴单调**（由 `enter[]` 构造保证）
- 标题父子指针完整；每篇笔记都有对应标题列表
- 聚合边在各层的端点都是该层可见节点

### `python browser_check.py`（浏览器侧，52 项断言）

Playwright 驱动本机 Chrome（`channel="chrome"`）直接 `goto file:///…`，无需起服务器。
覆盖：初始视角、逐层缩放扫描（节点/边/标签数）、标签三种模式、搜索命中、学科过滤、
双击空白回 home、帧率（实测 62fps）、20 格滚轮耗时（实测 1090ms）、空白区兜底提示、
侧栏详情、hover 气泡与图例、无 console error / pageerror。
截图落在 `%TEMP%\kg_*.png`（可用 `KG_SHOT_DIR` 改），**改完视觉要自己看图**。

### 仍需在浏览器里人工确认

- [ ] 配色、疏密、标签密度是否好看（`lod.min_px` / `layout.angle_power`）
- [ ] 深层（标题 3339 个）拥挤时的可读性
- [ ] 1920×1080 100% 缩放下界面是否舒适

---

## 10. 已知限制

- **同心圆的圆心是空的**，这是布局的固有特征。在空白处一路放大到最深层会看到 0 个节点，
  画布上给了兜底提示文字（「向下滚回到更粗的层级，或双击空白处回到默认视角」），
  但这不是 bug，改不掉，除非换成非同心布局。
- **缩到 `zMin` 时只剩 6 个节点**（顶层学科），是结构结果不是 bug：
  要让第 1 圈铺满屏幕需要 zoom ≈ 1.42，比 home 视角的 0.29 还大，与「zMin = 看得最粗」
  的语义冲突，所以取的是能看见顶层学科的下界。
- **12 处 `[[笔记#标题]]` 锚点未命中**：锚点文本与标题不完全一致
  （Obsidian 的锚点匹配更宽松）。放宽逻辑在 `kg/graph.py` 的 `_normalize_heading()`。
- **中文不分词**，所以「自动发现前置知识」只覆盖英文术语与 LaTeX 符号。
- **正文 `[[链接]]` 的方向语义天然模糊**（A 链接到 B 可能是依赖，也可能只是"另见"），
  统一记作 `derives`。要精确语义请写进 `annotations.yaml`。
- **掌握度描边目前看不到效果**：`annotations.yaml` 里还没标 mastery，
  107 篇笔记全是 0（暗色细边）。这不是功能缺失。
- `quartz-setup/` 里那份公开范围定义（junction `Study/`、`Tech/`）已经失效，本项目没有改它。

---

## 11. 如果以后想扩展

- 时间轴（按笔记创建时间播放知识增长）：`scan.py` 加 mtime，前端加时间滑杆
- 学习路径推荐：对 `prerequisite` 边做拓扑排序
- 掌握度热力图：给 `theme` 加一套按 mastery 的配色，`render.js` 换 color 映射
- 跨 vault：`config.yaml` 的 `vault` 改成列表，`scan.py` 遍历多个根
- 候选边审核 UI：在页面里列出候选、点 accept/reject 后**导出 YAML 文本**给用户粘回文件
  （保持「工具不写用户文件」的边界）
