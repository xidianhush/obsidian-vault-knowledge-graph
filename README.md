# 知识笔记语义缩放可视化系统

把 Obsidian vault 里指定范围的笔记，做成一张**带权有向图**，并像地图一样**按缩放级别切换显示粒度**：
学科 → 子学科 → 课程 → 笔记 → 笔记内的标题（知识点）。

产出是一个**单文件 HTML**（`dist/knowledge-graph.html`），双击就能在 Chrome 里打开，不需要服务器、不需要联网。

```
python build.py scan      # 扫描 vault，打印纳入/排除与链接统计
python build.py suggest   # 挖掘候选边 → candidates.yaml（待你审核）
python build.py build     # 生成 dist/graph.json 与单文件 HTML
python build.py watch     # 笔记改动后自动重建（挂在旁边即可）
python build.py verify    # 跑自动校验
python build.py all       # scan + suggest + build
```

只用到一个第三方依赖：`PyYAML`（`pip install pyyaml`）。Python ≥ 3.9。

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
  - "**/draft*"                 # 文件名含 draft 的一律排除（Draft.md 目前就是靠这条排除的）
  - "**/*.excalidraw.md"

exclude_notes: []               # 逐篇排除：写笔记名（不带 .md）或相对路径
#  - "半导体物理(大二下)"
```

改完跑 `python build.py build`。想先确认范围对了，跑 `python build.py scan`，它会打印：

```
[公开范围]  vault 内 .md 共 132 篇，纳入 107 篇，排除 25 篇
[层级]      文件夹 35 个，最大深度 5
[深度分布]  笔记所在层：{2: 9, 3: 39, 4: 55, 5: 4}
[链接]      [[链接]] 总数 803
  附件链接         █████████████████████··· 716
  笔记→笔记        █······················· 40
```

---

## 2. 语义缩放怎么用

### 层级（LOD）

LOD 的判定用的是**节点在目录树里的深度**，不是固定四层。`depth 1` = 顶层目录，笔记的 depth = 所在目录 depth + 1（当前最大 5）。

| 层级 | 显示内容 |
|---|---|
| 1 | 6 个顶层学科（Economy and Finance / Interest / …） |
| 2 | 浅层目录 + 直接放在顶层的笔记 |
| 3 | 子学科、课程目录 + 对应笔记 |
| 4 / 5 | 全部笔记（107 篇） |

**滚轮**或顶栏 **+ / −**（快捷键 `]` `[`）在层级之间切换；每层有自己的预设视角，层内可以自由平移缩放。切换时相机动画 260ms。

> 为什么不做成「连续 zoom → 层级」的映射？因为那样会形成正反馈：收窄视角使 zoom 变大 → 跳到更深层 → 视角再放大 → 来回震荡。所以层级是离散状态，各自带一个预设相机。

### 节点与边

- **圆角方框** = 文件夹（也就是「省界」轮廓，标签是名字 + 旗下笔记数）
- **圆** = 笔记，颜色按顶层学科区分，大小随重要度
- **边框** = 掌握度（1 虚线 → 5 实线加粗；0 = 未标注，暗色细边）
- **小圆** = 笔记内的标题（知识点），点开某篇笔记才渲染
- **边**：前置（灰，带箭头）／引用（蓝，带箭头，来自正文 `[[链接]]`）／并列对比（橙虚线，无箭头）／层级包含（暗灰虚线）

### 交互

| 操作 | 效果 |
|---|---|
| 滚轮 / `+` `−` / `[` `]` | 换层 |
| 单击节点 | 右侧详情栏：路径、掌握度、入边、出边、标题清单 |
| 双击笔记 | 展开该笔记的知识点头层 |
| 双击文件夹 | 进入下一层 |
| 悬停 | 气泡显示标题、所属课程、掌握度、摘要 |
| 侧栏「展开知识点」 | 把笔记内的标题按径向扇形铺开，并画出指向具体标题的跨笔记链接 |
| 侧栏「在 Obsidian 打开」 | `obsidian://open?…` 直接跳回 Obsidian |
| 搜索框 | 高亮匹配的笔记与标题（黄色边框），点结果可直达 |
| 学科 / 掌握度下拉 | 过滤 |
| 标签下拉 | 笔记标签策略：自动（默认，密集时只留悬停/选中/命中）／全部显示／只显示选中 |
| `Esc` | 收起知识点 / 取消选中 |

**「加了标题会自动出现在图里吗？」会。** 标题层是每次构建时从笔记正文实时解析的，
你在任何笔记里加标题、加内容、加 `[[链接]]`，只要重新构建就会反映出来：

- 手动：`python build.py build`
- 自动：`python build.py watch`（挂在旁边，笔记一存盘就重建，2 秒轮询）

---

## 3. 给图谱加语义：三种方式

### 3.1 `annotations.yaml`（推荐，手工但集中）

不用往 107 篇笔记里塞 frontmatter，全部标注集中在一个文件里：

```yaml
notes:
  "模拟集成电路":
    weight: 5          # 重要度，影响节点大小
    mastery: 3         # 掌握度 1-5，影响边框
    aliases: ["模电"]  # 让 [[模电]] 也能解析到这篇
edges:
  - source: "MOSFET"
    target: "模拟集成电路"
    type: prerequisite  # 或 derives / contrast
    weight: 3
    reason: "模电第一节课就是 MOSFET 的小信号模型"
```

优先级：`annotations.yaml` > 笔记 frontmatter > 自动推断的 wiki 链接（可在 `config.yaml` 的 `precedence` 里翻转）。

### 3.2 笔记 frontmatter（可选）

也支持文档里那套字段：`prerequisites` / `derives` / `contrasts` / `mastery` / `weight`。
写了就生效，不写不影响。`parent` / `subject` / `domain` 只作为显示信息，**不会**改变层级归属。

### 3.3 `candidates.yaml`（自动挖掘 + 人工审核）

`python build.py suggest` 会离线挖掘候选边，每条都带得分、类型、理由：

```yaml
candidates:
  - source: "半导体物理(大三上)"
    target: "半导体物理(大二下)"
    type: contrast
    score: 0.99
    reason: "共享术语：junction、impurity…；两篇笔记都含有同名标题（共 3 篇重复），疑似同一门课的不同版本"
    status: pending
```

把想保留的 `status` 改成 `accepted`，再 `python build.py build`。`pending` / `rejected` 都不进图。
**重跑 `suggest` 会保留你已有的审核结果**，不会把 accepted 打回 pending。

三条启发式：标题与笔记同名（→ 前置）／英文术语与 LaTeX 符号的逆文档频率共现（→ 并列）／同名标题跨 3 篇以上笔记（→ 疑似重复笔记）。
中文不分词——不引入 jieba 之类的重依赖，中文侧只做标题精确匹配，宁缺勿滥。

---

## 4. 产物与目录

```
knowledge-graph/
├── config.yaml            唯一维护入口
├── build.py               CLI
├── verify.py              自动校验
├── kg/                    数据管道
│   ├── config.py          配置加载与校验
│   ├── scan.py            白名单扫描
│   ├── parse.py           frontmatter / 标题树 / wiki 链接
│   ├── graph.py           层级树、语义边、聚合边
│   ├── candidates.py      候选边挖掘
│   ├── layout.py          确定性层级径向布局 + 省界轮廓
│   └── emit.py            输出 JSON 与自包含 HTML
├── web/                   前端源码（构建时内联进单文件）
│   ├── template.html
│   └── app.js
├── vendor/cytoscape.min.js  首次构建自动下载一次，之后完全离线
├── annotations.yaml       你的手工标注
├── candidates.yaml        候选边（待审核）
├── HANDOFF.md             交接文档：现状、实测数据、待办、调参地图
└── dist/
    ├── graph.json         中间产物，调试用
    └── knowledge-graph.html  ★ 双击打开
```

---

## 5. 实现上的几个关键决定（维护时先看这里）

1. **单文件必须全内联。** Chrome 在 `file://` 下禁止 `fetch`/XHR 读本地文件，
   如果 HTML 去 fetch `graph.json`，双击打开必然失败。所以 Cytoscape 和数据都内联进 HTML。

2. **坐标一次算定，缩放只切可见性。** `layout.py` 按「半径 = 深度 × radius_step，
   角度按子树笔记数加权」算出所有节点坐标，父节点不做质心回退。层级切换只改
   `display`，所以节点在任何层级下的绝对坐标都不变——位置稳定是构造出来的，不是动画掩盖的。
   `verify.py` 会断言「切层前后坐标零漂移」。

3. **两条 Cytoscape 的坑（踩过了，别再踩）：**
   - 坐标变换是 `rendered = model × zoom + pan`，**不是** `(model − pan) × zoom`。
     要让模型点 `c` 落在视口中心：`pan = 视口宽/2 − c×zoom`。
   - 节点 `data` 里**不能出现 `parent` 键**——Cytoscape 会把它当成复合节点（compound node）
     的父子关系，进而重算全部坐标，整张图会错位。这里用的是 `parentId`。
   - 另外 `cy.$('#id')` 是**子串**匹配，不是精确匹配（标题节点 id 里含有笔记 id、
     轮廓 id 里含有文件夹路径），所以代码里统一用 `getEl()` 做精确匹配。

4. **性能**：悬停只改两个节点的标签透明度（0.8ms，而不是全量重算的 55ms）；
   尺寸按「该层的适配缩放」预补偿，缩放期间不重算样式；样式写入带缓存，只写变化的元素。

---

## 6. 校验

### 自动校验（`python build.py verify`）

覆盖这些可脚本判定的验收标准：

- 最浅层只有顶层学科，且该层没有悬空边
- 最深层显示全部笔记，边两端都可见
- 所有边两端都存在；没有把附件（png/pdf/…）当成节点；链接解析统计完整
- 文件夹「省界」轮廓包住了各自截至该层已可见的全部笔记
- 节点坐标两两不同；**切层前后坐标零漂移**
- 标题父子指针完整；每篇笔记都有对应的标题列表

### 需要在浏览器里人工确认

这部分无法由脚本客观判定，请不要只看自动校验就认为没问题：

- [ ] 双击 `dist/knowledge-graph.html`，`file://` 下能正常打开（无需服务器、无需联网）
- [ ] 层次切换的动画是否流畅（DevTools Performance 录制，看是否稳定 >30fps）
- [ ] 效果层面：节点/标签是否重叠、配色是否好看、密集层的标签是否需要调
      （顶栏「标签」下拉，或改 `app.js` 里 `recomputeLabelBudget()` 的阈值 35）
- [ ] 界面在 100% 缩放的 1920×1080 及以上是否舒适（默认布局按较大视口设计）

---

## 7. 已知限制

- **最深层（107 篇笔记）默认不显示笔记标签**，因为屏幕放不下会糊成一片。
  悬停、选中、搜索命中时仍会显示；顶栏可切「全部显示」。密集层想看名字，建议配合搜索或过滤器。
- 中文不做分词，所以「AI 自动发现前置知识」只覆盖英文术语与 LaTeX 符号，
  中文关系靠标题精确匹配 + 你手工标注。
- 正文 `[[链接]]` 的方向语义天然模糊（`A 链接到 B` 可能是 A 依赖 B，也可能只是"另见"）。
  这里统一记作 `derives`（引用方向），要精确语义请写进 `annotations.yaml`。
- `quartz-setup/` 里那份公开范围定义（junction `Study/`、`Tech/`）已经失效，
  本项目没有改它。若想让两者共用一份定义，属于另一个任务。

---

## 8. 如果以后想扩展

- 时间轴（按笔记创建时间播放知识增长）：`scan.py` 加文件 mtime，前端加一条时间滑杆
- 学习路径推荐：对 `prerequisite` 边做拓扑排序
- 掌握度热力图：给 `theme` 加一套按 mastery 的配色，`app.js` 换一个 color 映射
- 跨 vault：`config.yaml` 的 `vault` 改成列表，`scan.py` 遍历多个根
