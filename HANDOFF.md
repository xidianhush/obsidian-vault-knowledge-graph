# 交接文档 —— 知识笔记语义缩放可视化系统

> 写给接手「看图验证 + 改进优化」的编程智能体。先读完这份，再读 `README.md` 第 5 节
> （那里记着几个必须知道的技术坑）。

---

## 0. 一句话现状

数据管道与前端都已跑通，`python build.py verify` 全部通过；**但整个视觉呈现从未被任何
智能体看过一眼**（上一个 agent 的模型不支持图像输入）。第一优先级就是「看 + 调」。

```bash
cd D:/obsidian_vault/knowledge-graph
python build.py build        # 生成 dist/knowledge-graph.html（约 2MB 单文件）
python build.py verify       # 自动校验，应该全绿
python build.py watch        # 开发时挂上，改笔记/配置自动重建
```

唯一依赖 `PyYAML`（已装）。

---

## 1. 环境事实（别重复踩）

| 项 | 值 |
|---|---|
| 系统 | Windows 10/11，Bash 工具走 Git Bash（Unix 语法） |
| Python | 3.11.8，`PyYAML 6.0.3` 已安装 |
| Node | v24.18.0（只用来做 `node --check web/app.js` 这类语法检查） |
| 浏览器 | 用户机器上的 Chrome |
| vault | `D:/obsidian_vault/hush-ob-bucket`（**不要修改里面的笔记**） |
| 本项目 | `D:/obsidian_vault/knowledge-graph`（vault 同级，不在 vault 内） |

**自动化看页面的正路：** 上一轮用 Kimi WebBridge（`http://127.0.0.1:10086`）驱动用户浏览器
做程序化验证。两个注意点：

1. 扩展默认**不能导航到 `file://`**（会报 `Cannot navigate to a file URL without local file access`）。
   解决办法：在 `dist/` 下起一个临时服务器再访问，例如
   `cd dist && python -m http.server 8917 --bind 127.0.0.1`，然后导航到
   `http://127.0.0.1:8917/knowledge-graph.html`。**验证完记得停掉服务器。**
2. WebBridge 在 Windows 下**请求体必须写成文件再 POST**（`curl.exe --data-binary "@文件"`），
   内联 JSON 里的中文会被 shell 破坏。JSON 里的 JS 代码只用单引号，别出现裸双引号。

**页面内置了调试入口**，在浏览器控制台或 `evaluate` 里直接可用：

```js
KG.cy                              // Cytoscape 实例
KG.data                            // 内联的 graph.json
KG.setLevel(n)                     // 切到第 n 层（1..5）
KG.state()                         // {level, shownNodes, shownEdges, zoom, expanded, selected, search, labelMode, filterSet}
KG.select(id) / KG.centerOn(id)
KG.toggleHeadings(noteId) / KG.collapseHeadings()
KG.runSearch(q) / KG.applyFilters()
```

---

## 2. 文件职责

```
knowledge-graph/
├── config.yaml          ← 唯一维护入口：公开范围 / 缩放 / 权重 / 候选边 / 布局 / 配色
├── build.py             CLI：scan | suggest | build | watch | verify | all
├── verify.py            自动校验（断言式，无测试框架）
├── kg/config.py         配置加载与校验（非法配置给中文报错）
├── kg/scan.py           白名单 glob 扫描（include/exclude/exclude_notes）
├── kg/parse.py          frontmatter / 标题树（跳过代码块）/ wiki 链接 / 摘要
├── kg/graph.py          层级树、语义边、按层聚合边、标题级链接
├── kg/candidates.py     候选边挖掘（3 条启发式）
├── kg/layout.py         确定性层级径向布局 + 按层预计算的「省界」轮廓
├── kg/emit.py           输出 dist/graph.json 与自包含单文件 HTML
├── web/template.html    前端骨架 + CSS（构建时内联）
├── web/app.js           语义缩放、LOD、标题层、侧栏、搜索过滤（1165 行）
├── vendor/cytoscape.min.js   首次构建自动下载一次，之后离线
├── annotations.yaml     用户手工标注（权重/掌握度/别名/手工边）
├── candidates.yaml      321 条待审核候选边
└── dist/{graph.json, knowledge-graph.html}
```

数据流：vault → `kg/*` → `graph.json` → 内联进单文件 HTML → Cytoscape 渲染。

---

## 3. 已完成并实测验证的部分

当前数据（vault 已被用户整理过一轮，112 → 107 篇）：

```
纳入 107 篇（Science and Tech 86 + Projects 5 + 其他）· 文件夹 35 个 · 最大深度 5
语义边 28 条 · 层级包含边 136 条 · 标题 3347 个 · 标题级链接命中 70 处
附件链接 716 条已丢弃 · 链接解析失败 1 条（[[My tech log]]，目标笔记不存在）
各层可见：depth≤1 → 6 节点/1 边；≤2 → 28/28；≤3 → 94/91；≤4 → 152/160；≤5 → 144/164
```

在真实浏览器里实测过的指标：

| 项 | 实测 | 备注 |
|---|---|---|
| 悬停出详情 | **0.82ms** | 只更新两个节点的标签透明度 |
| 换层同步耗时 | 88ms | + 260ms 相机动画 |
| 单帧渲染（缩放） | 6~19ms | 相当于 50~60fps |
| 展开标题层 | 128ms 同步 | 折叠 14ms |
| 节点坐标漂移 | **0** | 切层前后逐节点比对，零漂移 |
| 画布实际绘制 | 导出 PNG 517KB | 清空所有元素后只有 6 字节 |
| 各层内容是否落在视口内 | 5 层全部 outside=0 | |
| 页面外部依赖 | **0** | 无 fetch/XHR/外链，`file://` 可用 |

`python build.py verify` 覆盖：最浅层只有顶层学科且无悬空边、最深层显示全部笔记、
边引用完整性、附件未被当成节点、省界轮廓包含关系正确、坐标两两不同且零漂移、
标题父子指针完整。**全绿。**

---

## 4. 必须知道的 5 个坑（不读会重犯）

1. **Cytoscape 的坐标变换是 `rendered = model × zoom + pan`**，不是 `(model − pan) × zoom`。
   要让模型点 `c` 落在视口中心：`pan = 视口宽/2 − c × zoom`。
   （上一轮因为写成 `w/(2z) − c·z`，导致每层内容都跑到画面外、画布一片空白。）
2. **节点 `data` 里绝对不能出现 `parent` 键** —— Cytoscape 会当成复合节点父子关系，
   把全部坐标重算。这里用的是 `parentId`。`web/app.js:88` 有注释。
3. **`cy.$('#id')` 是子串匹配，不是精确匹配。** 标题节点 id 里含所属笔记 id、
   轮廓 id 里含文件夹路径，所以代码里统一用 `getEl()`（`web/app.js` 内）做精确匹配。
4. **LOD 是离散层级状态机，不是「连续 zoom → 层级」映射。** 后者叠上「换层后自动适配视角」
   会正反馈震荡。别顺手改成连续映射。
5. **单文件必须全内联。** Chrome 在 `file://` 下禁止 `fetch`/XHR 读本地文件，
   所以 Cytoscape 与数据都内联进 HTML。不要为了「减小体积」改成外链 JSON。

---

## 5. ★ 第一件事：看图验证（上一个 agent 做不到的事）

建议流程：起本地服务器 → 用 WebBridge 打开 → 截图 → **自己看图** → 逐条判断下表。

### 5.1 必须确认的验收项

| # | 检查项 | 怎么看 |
|---|---|---|
| 1 | `file://` 双击打开正常 | 直接双击 `dist/knowledge-graph.html`（或问用户） |
| 2 | 切层动画是否流畅 >30fps | DevTools → Performance 录制，滚轮从 L5 到 L1 |
| 3 | 最外层（6 个学科）好不好看 | 切到 LOD 1，看节点是否过大/过小、是否居中 |
| 4 | 最深层（107 篇笔记）标签策略 | 切到 LOD 5：默认标签被隐藏（因为超阈值），是否可接受？ |
| 5 | 「省界」轮廓的视觉重量 | LOD 2~5 各有不同轮廓，看虚线框是否太抢眼/太弱 |
| 6 | 径向布局是否好看 | 圆心区域是空的（径向布局的固有特征），是否显得浪费 |
| 7 | 配色/对比度 | 深色底 + 6 学科色，检查是否可区分 |
| 8 | 侧栏信息是否够用 | 点一篇笔记：路径、掌握度、入边/出边、标题清单 |
| 9 | 知识点扇形展开 | 双击 `信号与系统`（223 个标题），看默认只展开 h1/h2 是否合理 |
| 10 | 搜索/过滤/标签下拉 | 搜「半导体」应高亮黄框；过滤「Science and Tech」应只剩该学科 |

### 5.2 我特别怀疑的几处（请优先看）

- **最深层标签默认不显示**：`web/app.js:386` 的阈值是「可见笔记 > 35 就隐藏笔记标签」。
  107 篇笔记在 2082×1046 视口下确实放不下，但「一片没名字的圆点」体验如何要你判断。
  备选方案：改成「只显示视口内 + 按权重取前 N 个」，或把 LOD 5 的 `radius_step` 调大。
- **`mastery` 边框目前完全看不到效果**：因为 `annotations.yaml` 是空的，107 篇笔记
  `mastery` 全是 0（= 暗色细边）。要看到「1 虚线 → 5 实线加粗」得先写几条标注。
  这不算 bug，但会让你误判「边框功能没实现」。
- **`level_span: 1.9`**（`config.yaml:40`）：每层只允许缩放到适配缩放的 1.9 倍。
  在最深层想放大看清一簇笔记时可能不够。调大它会让「换层所需的滚动次数」变多，需要权衡。
- **LOD 2 作为初始层级**（`web/app.js:52`）：只有 9 篇笔记是 depth 2，初始画面信息量偏少。
  也许初始给 LOD 3 更合适，需要看着定。

### 5.3 调参地图

| 想改什么 | 在哪 |
|---|---|
| 布局疏密（半径） | `config.yaml:72` `layout.radius_step`（260） |
| 每层可缩放幅度 / 滚轮步进 / 动画时长 | `config.yaml:40-42` |
| 学科配色、边颜色 | `config.yaml` `theme:` |
| 节点大小公式 | `web/app.js:342` `baseSize()` |
| 反缩放补偿曲线 | `web/app.js:436` `k = clamp(1.15/z)` |
| 上层节点额外放大 | `web/app.js:451` `boost = 1 + 0.10*gap` |
| 笔记标签显隐阈值 | `web/app.js:386` `notes > 35` |
| 标签换行宽度 | `web/app.js:160` `text-max-width: 130` |
| 标题层默认展开多少 | `web/app.js:788,794`（220 / 60 两个上限） |
| 初始层级 | `web/app.js:52` |
| 轮廓内边距 | `kg/layout.py` `_frames()` 里的 `pad = 44` |
| 相机/轮廓留白 | `web/app.js:282`（56）、`:906`（70） |

---

## 6. 待办清单（按建议顺序）

**P0 — 看图并调视觉**（见第 5 节）

**P1 — 让「掌握度/重要度」真正起作用**
现在全 vault 只有 3 篇笔记有 frontmatter，`annotations.yaml` 是空的。
两项可选工作：
- 提示用户填几条 `annotations.yaml`（权重、掌握度、别名），验证节点大小/边框/别名解析。
- 或者做一个 `build.py suggest-annotations`：按「标题数 / 链接数 / 笔记行数」给出
  初始 `weight` 建议草稿，让人工审核。**注意：不要自动写进用户的笔记。**

**P2 — 候选边审核流程**
`candidates.yaml` 有 321 条，手工改 `status` 很累。可考虑：
- 在页面里加一个「审核模式」：列出候选边，点击 `accept/reject` 并**导出 YAML 文本**，
  由用户自己粘回文件（保持「工具不写用户文件」的边界）。
- 或者写 `build.py review`：交互式命令行逐条确认。

**P3 — 性能与规模**
规模上限还没测过。可做的压力测试：
- 把 `include` 临时放宽到全 vault（含 Logs/Excalidraw）看会发生什么；
- 造 500~1000 节点的合成数据，测最深层渲染与交互。
已知瓶颈：换层 88ms、展开标题 128ms（都是 Cytoscape 的样式重算成本）。
`applySizing()` 里已有 `styleKeys` 缓存与 `crowded()` 的 O(n²) 修复，别退回去。

**P4 — 已知限制里的功能缺口**
- **中文不做分词**，所以「AI 自动发现前置知识」只覆盖英文术语。
  若要提升候选边召回，需要引入中文分词（jieba 之类），这是新增依赖，需先跟用户确认。
- **`[[链接]]` 的方向语义天然模糊**：目前统一记作 `derives`（引用方向）。
  要不要在侧栏加「改这条边的类型」并把结果导出成 `annotations.yaml` 片段，待定。
- **12 处 `[[笔记#标题]]` 锚点未命中**（`build` 会打印 `锚点未命中 12 处`）。
  原因是锚点文本与标题不完全一致（Obsidian 的锚点匹配更宽松）。可以看看这 12 处是什么，
  是否需要放宽匹配（`kg/graph.py` 的 `_normalize_heading()`）。

**P5 — 可选：统一公开范围定义**
`quartz-setup/quartz.config.ts` 与 `SETUP.md` 里定义的公开范围（junction `Study/`、`Tech/`）
**已经失效**——那两个目录在当前 vault 里不存在。本项目没有改它。
若用户想让 Quartz 发布与图谱共用一份 `include` 定义，需要单独确认后再动。

---

## 7. 明确不要做的事

- **不要修改 vault 里的任何笔记**（含批量注入 frontmatter）。标注走 `annotations.yaml`。
  （上一轮只 `touch` 过一次笔记的 mtime 来验证 watch，`git status` 始终是干净的。）
- 不要动 `.obsidian/`；不要读 `Utilities/API Key.md`（敏感凭证）。
- 不要在没有明确要求时执行 `git commit` / `git push`（vault 由 obsidian-git 自动备份）。
- 不要把 `dist/` 或 `vendor/` 当成需要精心维护的源码——它们是构建产物，可随时重建。
- 不要把「自动校验全绿」当作「视觉没问题」。这两件事无关。

---

## 8. 回归基准（改坏了怎么发现）

改完跑这三条，数字不该明显变差：

```bash
python build.py verify          # 必须全绿
python build.py build           # 应为：笔记 107 / 文件夹 35 / 最大深度 5 / 语义边 28 / 标题 3347
node --check web/app.js         # 前端语法
```

浏览器里再确认（`KG.setLevel(n)` 后读 `KG.state()`）：

```js
KG.setLevel(5); KG.state().shownNodes   // 应为 144
// 逐层节点总数（含轮廓）应为：6 / 34 / 94 / 152 / 144
// 切层前后 KG.cy.nodes() 的 position 必须完全不变（上一轮实测漂移为 0）
```
