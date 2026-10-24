# PLAN_APPLICABILITY —— 从「只适用于我的库」到「适用于任意笔记库」

> 写于 **2026-10-24**，由 DeepSeek Harness 会话产出。本文是**路线图 + 验收契约**，不是已完成的工作记录：
> 每完成一个阶段，把「状态」改成「已完成（提交 `<sha>`）」并把实测数字补进 §7。
> 与代码冲突时**以代码和 `git log` 为准**；本文里的行号是 2026-10-24 的快照，会漂。
>
> **背景**：项目现在是「作者本人 114 篇 / 37 夹 / 3359 标题 / 10 层」这一份库上长出来的。
> 这一轮要回答的问题是：换一个别人的库（层级更深/更浅、顶层学科 30 个、某层扇出 500、
> 全库没文件夹只有散笔记、几千篇笔记），它还能不能用、好不好看。最终目标是**分发**
> （Obsidian 原生插件），但分发形态不是解法，通用化才是。

---

## 0. 决策记录（2026-10-24 用户拍板）

| # | 决定 | 结论 |
|---|---|---|
| 1 | 顺序 | **先做阶段 0**（不先看视觉）。视觉相关的 1.x/2.x 一律排在「能换库 + 有度量」之后 |
| 2 | 规模边界 | **接受**：≤ 2 万节点 / ≤ 3 万边 / 单文件 ≤ 20 MB / 层数 ≤ 14 = 「好用」；超出**降级**而不是崩。见 §3（可调，不是硬编码） |
| 3 | 插件顺序 | **0 → 0.5（半天探针，不写码）→ 1 → 2 → 3 → 4**。0.5 的产出是一页平台约束清单，不是插件 |
| 4 | 本文档 | `knowledge-graph/PLAN_APPLICABILITY.md`，含 fixture 矩阵、每阶段断言影响、验收表 |

**红线不变**：绝不修改 vault 里的任何笔记；不读 `Utilities/API Key.md`；不加第三方运行时依赖；
改 `web/*.js` / `web/template.html` 必须重建 `dist/` 再跑浏览器回归；视觉改动必须截图人眼验收。
**新增红线（本轮起）**：`verify` 的 110 ok 与 `browser_check` 的 132/133 ok **不得减少**
（少掉 = 有用例被静默吞掉，见 §6）；作者的库是**回归基准**，任何通用化都不许让它变差。

---

## 1. 诊断：到底什么在绑死这个库

结论先说：**不是「参数写死了」，circle packing 本身对扇出/根数/深度相当健壮。**
真正的四处耦合是：**①配置入口 ②深度轴语义 ③preview 无上限 ④缩放行程取决于半径比**。
另有五处「不崩但会难看」的渲染侧耦合。

### 1.1 四处真耦合（换库就会坏）

| # | 耦合 | 证据 | 失效反例 |
|---|---|---|---|
| 1 | **入口绑死作者环境** | `config.yaml:13,20` 绝对路径；`kg/config.py:368-371` 强制 `scope_file`；`build.py:339,362` 调 `load()` 不带路径；CLI 只有 `--scope`（`build.py:313-329`），未知参数**静默吞**（`:326-327`） | 任何没有 `quartz-setup/public-scope.yaml` 的 vault：**跑不起来**（ConfigError），必须先手写一份 Quartz 格式 YAML |
| 2 | **深度轴 = 文件深度 + 标题级别字面值** | `kg/graph.py:155` `depth = note.depth + h.level` | ①正文不用 `#` 的库 → `max_depth==2==home_level`，阶梯塌（`kg/layout.py:445-448`），上半段缩放空转、verify 必红；②一篇用了 `######` 就把轴抬 5 层、空层占整条带（`kg/layout.py:406-417`） |
| 3 | **preview 全量内联 + 限流开关空转** | `kg/graph.py:186-189`；`preview.max_note_chars` **全仓无一处读取**（`kg/config.py:80,148-150` 只声明与校验）；`kg/emit.py:39-58` 三重复制 | 3000 篇 → 单文件 150MB+、构建峰值 1GB、`JSON.parse` 卡死。实用上限约 1~2k 篇 |
| 4 | **缩放行程 = 1.286 × 半径比** | `render.js:250-257`；`kg/layout.py:439-448`（`z_hi = min_px/min(r) × ceiling`） | 平铺库（半径比≈1）只剩 **2.4 格滚轮**；叶子 ≤150 时 `zMax < home_zoom` → home 被夹到 zMax，**语义缩放消失** |

### 1.2 五处「不崩但难看」（渲染侧）

| # | 现象 | 证据 | 反例 | 状态 |
|---|---|---|---|---|
| 5 | 第 8 个学科起全灰 | `config.yaml:232-240` 只 7 色 + `kg/config.py:82` 单一 fallback；无自动色板 | 30 个顶层目录 → 23 个同灰，图例 30 行配同色点 | ✅ 1.3 已修（构建期 golden-angle 补齐，30 个 domain 30 色） |
| 6 | 无文件夹库 → 满图全灰、图例空白、学科下拉空 | `app.js:195-214` 图例 = 「depth===1 的 folder」；`kg/graph.py:104` 根笔记 domain="" | 全散笔记的库，面板说「颜色=学科」但一张全灰图 | ✅ 1.3 已修（图例读 `meta.domains`，无学科时显示「未分学科」） |
| 7 | 宽扇出层整层 0 标签 | `render.js:46` `LABEL_BUDGET=400`；`:1267` 截断**早于** `:1281`（sr<28 跳过）/`:1303`（出屏跳过） | 一个文件夹 500~2000 篇笔记 → 前 400 候选全被 continue，祖标也被挤出预算 |
| 8 | 边全量每帧画 | `render.js:711-890`：每条 2 次 stroke + 跨域渐变 + 2 个 marker，无索引无预算 | 2 万节点 / 3 万条 `[[链接]]` → 拖拽 1~5 fps，整屏白线 |
| 9 | 预览整篇 `innerHTML` + 同步 KaTeX；图片是相对路径 | `app.js:523-565`；`kg/preview.py:135` | HTML 换个目录/发给别人 → 图片全碎（单文件其实不自包含图片）；30 万字笔记悬停卡 ~1s |

### 1.4 阶段 0.1 实测到的两个新证据（2026-10-24）

1. **DEFAULTS 不完整 = 「别人的库跑不起来」的第二道锁。** `kg/config.py` 的 `DEFAULTS.lod`
   缺 `label_font_min/max/scale` 与 `label_bold_depth`——这四个键一直只写在作者的 config.yaml 里，
   于是「一份最小配置」（别人照着改的、或 fixture 的）在校验阶段直接报
   `lod.label_font_scale 必须是正数，收到 None`。**默认值必须自洽到能跑**，已补齐。
   > ⚠️ 补键必须**追加在 `DEFAULTS.lod` 末尾**：`_deep_merge` 先放 DEFAULTS 的键、再追加
   > config 独有的键，插在中间会改变 payload 里 `lod` 的键序 —— JSON 语义不变，但产物 diff 会变脏
   > （阶段 0.1 第一版就踩到，靠「归一化逐位比较」才发现）。
2. **3 篇笔记的库就把 §1.1 #4 复现了。** 内联 scope 建出来的最小库（1 个文件夹 / 3 篇 / h1-h3）
   跑 verify，三条红全是同一个根因：`max_depth=5`、home 在 2 层，但 `zMax = 0.1478 < home_zoom = 0.4612`，
   于是阶梯再也铺不到 zMax，`M[5]=1.3834 != zMax=0.1478`；镜头被夹在 home，滚一格就涌入 **90%** 节点。
   → **阶段 1.2（缩放行程标定）不是「优化」，是「小库基本可用」的前提。**

### 1.3 已经自适应、**不要动**的好设计

- `max_depth` 从数据算（`build.py:79`），不截断不压平；深度轴本身没有 10/6 的常量。
- 半径 = 叶子数^0.5 + 自顶向下等比缩放 + 虚拟根归一化到 1000（`kg/layout.py:328-376`）：
  扇出 500 与扇出 3 一样装得下，世界坐标量级与库规模无关。
- LOD = 层级带（`kg/layout.py:419-463`）：同层同时浮现，`fade_span`/`home_band` 是无量纲常数。
- 三条包含几何（子在父内 / 父≥1.5×子 / 兄弟不相交）是构造性断言。
- zMin/zMax/homeZoom 在渲染侧现算（`render.js:250-257,298-300`），换库不会「缩放范围错」。
- 有界列表（边 60 / 标题 60 / 搜索 30 / chip 8+折叠）、DPR 处理、空视口兜底按「真的落笔」判。

---

## 2. 明确否决的方向（别再提）

1. **LLM 进入核心循环做「参数动态调整」——否决。** 参数必须由**可测的库统计量**派生
   （扇出 / 层数 / 边数 / 预览字节 / 半径分布）。LLM 不确定、不可复现、要联网要花钱，
   直接破坏「单文件、离线、零运行时依赖」契约，而且它解决不了可视化效果。
   **唯一合理位置**：阶段 5 的构建期语义层（分组推断 / 簇命名 / 候选边排序），
   默认关闭、结果落盘进 payload、运行时不联网。
2. **「适用于所有人」= 无限通用 —— 否决。** 先划边界（§3），超出走降级。没有边界的通用化
   会变成无底洞，而且永远无法验收。
3. **先做插件 —— 否决。** 插件是分发形态，不是解法；核心还绑在作者库上时包插件只是把问题
   搬进 Obsidian，还失去 Playwright 回归手段。顺序见 §4。
4. **换掉 circle packing（改用 treemap / 力导向）—— 暂不。** 它是这套设计的地基
   （「容器即内容」），换掉等于重做视觉语言。极端扇出用**泛化**（分桶/抽稀）解决，不换算法。

---

## 3. 规模边界与降级策略（决定 2；可调）

| 维度 | 「好用」上限 | 超出后的降级（不许崩） |
|---|---|---|
| 节点 | 20,000 | 布局照算；渲染走分桶 + 视口裁剪；标签预算再收紧；提示「已进入降级模式」 |
| 语义边（要画的线） | 30,000 | 边分桶 + 同色合并 `Path2D` + 远端边抽稀（近端保留，保住「任何尺度都在」的可读部分） |
| 单文件 HTML | 20 MB | preview 按总预算分摊截断（见下）→ 仍超则拆 `graph.json` 旁挂（放弃严格单文件，明确告知） |
| 层数 | 14 | 标题层稠密化 + h4/h5/h6 合并为一层「更多标题」；单子链折叠 |

**依据（不是拍的）**：
- 节点 2 万：每帧三趟 O(N) 遍历（`render.js:532-559`、`:722`、`:1144`）+ `JSON.parse` 单文件，
  在 6 MB / 3510 节点上实测空闲 63 fps；线性外推到 2 万节点 ≈ 34 MB，已顶到 20 MB 预算边缘。
- 边 3 万：每帧 6 万次 `stroke` + 3 万个 marker 对象 —— 这是**先崩的那一项**，所以单独列上限。
- 20 MB：`file://` 双击打开 + 分享的实用上限，也是「首屏解析 ≤2 s」的量级（当前 6.3 MB ≈ 1.7 s）。
- 层数 14：`max_depth` 每层至少跨一条淡入带（`kg/layout.py:447-448`），滚轮 1.12/格；14 层 ≈ 45~60 格，
  再多就要靠「每层不足一格」才排得下，HUD 胶囊也会撑爆顶栏（`template.html:86-91` 已承认 10 个就超额）。
- **这些数字是 config 键，不是代码常量**：落地时写成 `limits: {nodes, edges, bytes, depth}`，
  超出只影响渲染策略与提示，不影响构建正确性。

---

## 4. 路线图

### 阶段 0：任意 vault 能跑 + 一张「形状体检表」 ✅ 已完成（0.1 / 0.2 / 0.3）
> 用户 2026-10-24 决定：**先做这个，先不看视觉。**

| 步 | 内容 | 涉及文件 | 断言影响 |
|---|---|---|---|
| 0.1 ✅ | `--config/-c` + 未知参数报错；`scope_file` 可选（无真源时用 config 内联 scope 定义）；路径统一相对 config.yaml；补齐 DEFAULTS | `build.py`, `kg/config.py`, `kg/emit.py`, `kg/candidates.py`, `verify.py` | 无新增断言；**已实测：两份产物归一化后逐位不变**，`verify --scope all` 仍 110 ok |
| 0.2 ✅ | fixture 生成器（确定性）+ 8 个形状库 + `manifest.yaml`（canary / expected_ok / known_gaps） | 新增 `fixtures/make_vaults.py`、`fixtures/manifest.yaml`；`.gitignore` 加 `fixtures/vaults/` | 不碰 vault；**8 个库全部 build 通过**（见 §5 实测列） |
| 0.3 ✅ | sweep runner + 两个检查器补 **ok 计数 / vault 身份 / 机器可读结果行**；`KG_HTML` 接受绝对路径；`browser_check` 的作者 fixture 常量（`微分方程`、作者笔记名、`setLevel(4)`）参数化；verify 的两处**崩溃**与两处**内容特征当契约**修掉 | `fixtures/run_sweep.py`, `verify.py`, `browser_check.py`, `kg/graph.py`, `kg/config.py` | 作者库 verify 110 → **112**（新增每 scope 1 条身份断言），browser 仍 132/133；8 个 fixture 的 ok 数已标定进 manifest |

**验收（2026-10-24 实测）**：
- `python fixtures/run_sweep.py` → `## SWEEP_RESULT {"fixtures": 8, "errors": [], "pending": []}`
  —— canary 全对、8 个库的 verify ok 数 == manifest.expected_ok（硬闸生效）。
- 8 个库合计 **426 ok / 22 FAIL**（0.3 动手前是 406 / 32）。剩下的 22 条分成三簇：
  `[LADDER] M[last]!=zMax`、`[INFLOW] 单格涌入>35%`（两者同根：PLAN §1.1 #4）、
  `[ROOT-NOTE]` tiny 的根笔记模型 —— **全部指向阶段 1.2 / 1.4，不是回归**。
- 修掉的两处崩溃：`verify.py` 在 0 标题库上 `min()` 空序列 `ValueError`；`browser_check` 3e 在
  无锚点标题时 `tgt=null` 的 `TypeError`。
- 修掉的两处「内容特征当契约」：`verify` 的「预览里必须有 `$` 公式」（改成按
  `meta.link_stats.preview_math_notes` 条件化）、「标题锚点覆盖率」在 0 标题时的分母为 0。
- 顺手修掉的内联 scope 缺陷：`roots` 原来把 `Attachment/` 这类无 .md 的目录也算成学科根
  （heading-zoo 假红），改成「只算含 .md 的目录 + vault 根下的 .md」。

**体检表（verify，2026-10-24 标定）**：

| fixture | ok | FAIL | 红项簇 |
|---|---|---|---|
| tiny | 50 | 6 | ROOT-NOTE×3 + LADDER + 放到最内 + INFLOW |
| shallow | 53 | 3 | LADDER + 放到最内 + INFLOW(94%) |
| deep-chain | 54 | 2 | LADDER + 放到最内 |
| wide-roots | 55 | 1 | INFLOW(45%) |
| hub-dense | 55 | 1 | INFLOW(60%) |
| heading-zoo | 53 | 3 | LADDER + 放到最内 + INFLOW(37%) |
| plain | 53 | 3 | LADDER + 放到最内 + INFLOW(91%) |
| remap-dup | 53 | 3 | LADDER + 放到最内 + INFLOW(80%) |

> 浏览器列（`--browser`）尚未标定：8 个库 × ~3 分钟，需要 Chrome；等阶段 1.2 修完缩放行程
> 再一次性标定，否则现在标出来的数下一轮就全变。

### 阶段 0.5：插件形态探针（半天，不写码） ✅ 2026-10-24（结论见 §9）
读 Obsidian 插件 API，确认：① 插件能否直接读 vault 现算（决定路线 A/B：A=读 Python 产物、
B=内置 JS 管线）；② canvas 在 Obsidian 容器里的尺寸/DPR/主题隔离；③ 预览图片走哪条路径。
**产出**：一页约束清单 → 写进阶段 0 的架构约束。**为什么必须在这里**：若走 B，`kg/layout.py`
那套要移植成 JS，而移植必须在阶段 1 的算法定稿之后，否则移植两遍。

**结论摘要**：走 **B**（移动端无 Node/Electron，A 路线根本上不了移动端）；解析层由平台代劳
（`metadataCache` + `resolvedLinks`）；图片走 `vault.getResourcePath`；**模型层必须与 Python 同构**，
用 8 个 fixture 的 payload 当 golden 文件防两个实现漂移。12 条硬约束见 §9.2。

### 阶段 1：参数从「写死」变「派生」 🟡 进行中（1.2 ✅ / 1.1、1.3、1.4、1.5 ⬜）
1.1 深度轴稠密化（标题级别 → 该笔记内出现过的 level 的**稠密 rank**）+ 清空层 + 单子链折叠
1.2 ✅ **缩放行程标定（2026-10-24）**：① 统一 `z_lo` 为 `min_px/min(r_根)`（原来 layout 用
   `max(r_根)`，与 render/verify 差 13.9×）；② anchor 加**上界** `z_hi/(fade×1.02)^steps`
   （旧版没有 → 小库上 M[D] 超调到 zMax 的几倍）；③ `steps==0`（浅库）时 anchor 直接等于 zMax；
   ④ home 落点改成「第 home_level 层带上的 home_band 位置」，并落盘 `meta.zoom.home_zoom`；
   ⑤ `wheel_step` 按「目标格数 = clamp(6×(D-1)+8, 20, 48)」反解，不再全库写死 1.12。
   ⑥ verify 的单格涌入上限改成 `max(35%, 最大层占比 + 2%)` —— 层级带**有意**让同层同现，
   写死 35% 等于把「一个文件夹装全部笔记」的库形状当 bug。
1.3 ✅ **自动色板 + 图例同源（2026-10-24）**：新增 `kg/palette.py`，构建期按「手写覆盖
   优先 → 其余按 golden-angle 低饱和生成」补齐**这份库实际出现的全部 domain**，落盘
   `meta.theme.domains`（完整映射）与 `meta.domains`（按笔记数降序的 `{name, color, count}`）；
   图例与学科下拉改成读 `meta.domains`，不再「扫 depth-1 的 folder 节点」猜学科；没有学科目录的
   库图例显示「未分学科」。实测：wide-roots（30 个顶层目录）**30 个 domain 30 种颜色、0 个灰**。
   验证：`verify` 新增 6 条（覆盖完整 / 无 fallback 灰 / 配色互不相同 / 名单与计数一致）。
1.4 ✅ **根笔记模型（2026-10-24）**：直接把笔记放在 vault 根的库（"懒人库"）原来满图走 fallback
   灰、图例空白、校验报「depth1 不是学科」。现在 ① `graph.py` 给根笔记的 `domain` = 笔记自己的 id；
   ② `verify` 允许 depth1 是 note（只禁「顶层出现标题」）；③ 越界判据改走**父链取顶层祖先**
   （原来按 id 第一个 "/" 切，根笔记的标题节点会被误判越界）。tiny 从 3 红变 **0 红**。
1.5 `NOMINAL_FIT_RADIUS=(900-46)/2=427` 把 1440×900 写进世界归一化 → 改成运行时视口（扣顶栏 + 侧栏）
> **阶段 0.5 带来的新约束**：1.x 改出来的算法要写成**可移植的纯函数**（输入=节点树+配置，
> 输出=坐标/半径/enter[]），浮点舍入点与现状对齐（x/y 3 位、r 4 位、enter 6 位），
> 不要用 dict 顺序、生成器、Python 独有特性 —— 这样 JS 移植版能拿 8 个 fixture 的 payload
> 当 golden 文件做逐位对比，否则「插件与演示效果一致」无法验收。
> 验收：fixture 表红项清一轮；作者库 112/132/133 不倒退；截图人眼。

### 阶段 2：渲染侧泛化 ⬜
2.1 标签预算派生 + 门（sr/出屏/碰撞）**移到预算之前** + 字号上限派生 + 修「只显示选中」（现在是 `off`）
2.2 边分桶（父圆/网格）+ 视口裁剪 + 同色合并，保住「逐条链接、任何尺度都在」契约
2.3 ghost 只扫目标层、ghost 与边吃 `filterSet`（现在过滤后「圆没了线还在」）
2.4 扇出分桶（虚拟簇节点：只参与布局/绘制，不进语义边/搜索/预览）+ >14 层压缩
2.5 搜索 debounce + 命中上限；侧栏/面板宽度随 `vw`

### 阶段 3：规模上限落地 ⬜
preview 真接 `max_note_chars` + 笔记间预算分摊 + 分块懒解析；payload 列式化（现在节点字段
0.9~1.3 KB，中文 id/path/title 三重冗余）；`r` 落盘钳到 ≥1e-4（`kg/layout.py:395` 现在 round 4 位，
30 层深链会落成 0.0 → `verify.py:229` ZeroDivisionError）；`_heading_id`/`resolve` 的全表扫改成按 note 分组索引。

### 阶段 4：Obsidian 插件 ⬜
抽 `GraphCore`（payload + canvas，无宿主依赖）+ 浏览器适配层 + Obsidian `ItemView` 适配层，
两端共用同一内核 → 「演示效果一致」是构造保证。插件里图片走 vault 资源 URL（顺手解决
「单文件不自包含图片」）。前提：阶段 1~3 完成。

### 阶段 5（可选）：构建期语义增强 ⬜
无文件夹/目录名无意义的库 → 链接图上跑 **Louvain 聚类**生成「虚拟学科层」（纯 Python、可离线、
可断言）；LLM 仅用于簇命名 / 候选边排序，默认关闭、结果内联。**不进入核心几何。**

---

## 5. fixture 矩阵（阶段 0.2）

生成器 `fixtures/make_vaults.py` 必须**确定性**（同 seed 同输出），仓库只提交生成器 + manifest，
vault 本体生成到 `fixtures/vaults/` 且 gitignore。

| # | fixture | 形状（实测人口） | 专考什么 | 预期会红的项 |
|---|---|---|---|---|
| 1 | `shallow` | 1 文件夹 + 15 篇、正文不用 `#`（depth 2｜夹1 笔15 标0 边0） | 阶梯 `steps==0` 塌陷 | `verify.py:257`、home_layer 分叉 |
| 2 | `deep-chain` | 单链 10 层目录、每层 1 篇 h1（depth **12**｜夹10 笔10 标10 边0） | 独子链 / 深度轴 / 胶囊溢出 | 顶栏 12 个 pill、`zoomToDepth` |
| 3 | `wide-roots` | 30 个顶层目录共 **150** 篇，最大占 60%、最小 1.3%（depth 3｜夹30 笔150 标150 边0） | 根数 ≠ 6、最小份额 | 第 8 个起同灰、图例 30 行 |
| 4 | `hub-dense` | 80 篇 / **335** 条语义边 / 入度 ≥12 的 hub / 5 条标题级链接（depth 4｜夹1 笔80 标320） | 边绘制、焦点、chip | 7b/7c/7d、帧率 |
| 5 | `heading-zoo` | h1..h6 链 + 笔记内重复「总结」+ 公式 + 2 张图（depth **8**｜夹1 笔6 标20 边0） | 标题锚点唯一性 / KaTeX / 图片 | verify 锚点、预览滚动 |
| 6 | `plain` | 0 标题 / 0 公式 / 0 图片 / 0 链接（depth 2｜夹1 笔10 标0 边0） | 「内容特征被当契约」 | `verify.py:317/:381` 红、`browser_check` 3e 靶子 `null` 崩 |
| 7 | `remap-dup` | 同名 stem 两处 + `as` 重映射 + 一个未列出的空目录（depth 3｜夹**2** 笔4 标4 边0） | `resolve` 歧义 / roots 残留 | `verify.py:84-97` |
| 8 | `tiny` | 1 篇笔记**直接放在 vault 根**（depth 2｜夹0 笔1 标1 边0） | 退化规模 + 根笔记 | `roots=[]` → 范围断言红；`depth1 只有文件夹` 红 |

**canary（每个 fixture 必须自带人口）**：`semantic_edges>0`、`headings>0`（除 `plain`）、`hlinks>0`
（除 `plain`）——否则「没有东西可坏」= 假绿。

**实测（2026-10-24，阶段 0.2）**：`python fixtures/make_vaults.py` 生成 8 个库，逐个
`build --config` **全部通过**，单文件 776~1063 KB（下限 776 KB 是内联 KaTeX 的固定成本）。
`--clean` 后重跑指纹不变（`sha256=8360014295776682…`）→ 生成器确定性成立。
`fixtures/vaults/` 已 gitignore，入库的只有生成器 + manifest。

---

## 6. 回归口径的三条硬闸 ✅ 已落地（阶段 0.3）

> 落地前的状态：两个检查器只记 FAIL、不记 ok —— 少跑几条仍然打「✓ 全部自动校验通过 /
> ALL BROWSER CHECKS PASSED」。现在两边都输出机器可读结果行，由 `fixtures/run_sweep.py` 做硬闸：
> `## VERIFY_RESULT {"ok":…,"fail":…}`、`## BROWSER_RESULT {"ok":…,"fail":…,"skipped":…}`。

1. **ok 计数 + expected 硬闸**：`ok + skipped + fail == 静态用例数`，每个 fixture 在 manifest 里写
   `expected_ok`；`skipped` 必须显式。
2. **warn 默认算失败**：只允许 manifest 里显式白名单（附原因）。
3. **身份断言**：`verify` 校验 `meta.vault == cfg.vault`；`browser_check` 校验
   `window.KG.data.meta.vault` 与 `KG_EXPECT_VAULT` 一致。**否则忘设 `KG_HTML` / 跑旧 dist 都会全绿。**
4. **假绿 canary**：「not bad」型断言在空集合上恒真（`verify.py:112/:119/:124/:132/:329/:341/:374`；
   `browser_check:993/:1000/:1235/:1412`）——必须靠 §5 的 canary 兜住。
5. **共享文件污染**：`annotations`/`candidates_file` 固定在项目根（`kg/config.py:85-86`），
   fixture 不覆盖会掺入作者的手工边。manifest 要断「语义边数在区间内」。
6. **不跑 `build.py all`**：`build.py:372-379` 会在第一个 scope 写共享 `candidates.yaml`。sweep 只跑
   `build --scope <one>`。

**原来写死的作者 fixture —— 阶段 0.3 已参数化**：
`browser_check` 的搜索词「微分方程」→ 从 payload 取笔记名前两字；`:1260-1261` 作者两篇笔记名 →
先按后缀找、找不到就用「两端世界距离最大的语义边」兜底；chip 文本 → 取目标节点自己的 label；
`setLevel(4)` → `LV_START = max(1, min(4, max_depth-1))`；无锚点标题的库 → 3e 显式跳过并计数；
单学科库 → domain 过滤断言显式跳过并计数。`verify` 侧的公式断言与标题锚点覆盖率也改成条件化，
0 标题库不再崩。
**仍留在 manifest.known_gaps 里的**（阶段 2 处理）：`:1144` 要求有向边 → `arrows>0`（只有 contrast
边的库会红）、`max_depth` 大时的顶栏胶囊溢出。

---

## 7. 验收表（每阶段填一次）

### 7.1 作者库（回归基准，**任何阶段都不许倒退**）

| 项 | 基线（2026-10-24 15:12） | 阶段 0 后（0.3 实测） | 阶段 1 后（1.2 实测） | 阶段 2 后 |
|---|---|---|---|---|
| `verify --scope all` | 110 ok / 0 FAIL（55+55） | 112 ok（56+56） | **124 ok / 0 FAIL（62+62）**（1.3 的 6 条色板断言） | |
| `browser_check` private | 132 ok / 0 FAIL / 1 warn | 132 ok / 0 FAIL / 1 skip | **133 ok / 0 FAIL / 0 skip** | |
| `browser_check` public | 133 ok / 0 FAIL / 0 warn | 133 ok / 0 FAIL / 0 skip | **132 ok / 0 FAIL / 1 skip** | |
| 两份浏览器 ok 合计 | 265 | 265 | **265**（条件跳过互换了位置，用例没少） | |
| 单文件 | 6277 KB / 6303 KB | 6277 / 6303 KB | **6277 / 6303 KB** | |
| 空闲 fps | 63 | 未复测 | 未复测（1.2 没动渲染） | |
| 20 格滚轮 | private 1654 ms / public 1644 ms | 未复测 | 未复测（1.2 没动渲染） | |
| 产物 hash | 见 §7.3 | +`preview_math_notes` | payload 变：`zoom.wheel_step` / `zoom.home_zoom` / `lod.enter[]` | |

### 7.2 形状体检表（8 个 fixture，2026-10-24 阶段 0.3 实测）

| fixture | 构建 | verify ok / FAIL | browser | HTML KB | depth | 灰节点占比 | 20 格滚轮 |
|---|---|---|---|---|---|---|---|
| tiny | ok | **62 / 0** | **86 / 10 / 10**（退化规模的用例前提，见 known_gaps） | 776 | 2 | — | — |
| shallow | ok | **62 / 0** | 待标定 | 784 | 2 | — | — |
| deep-chain | ok | **62 / 0** | 待标定 | 791 | 12 | — | — |
| wide-roots | ok | **62 / 0** | **93 / 9 / 7**（无语义边 → 边相关用例不适用） | 958 | 3 | **0 / 30** | — |
| hub-dense | ok | **62 / 0** | 待标定 | 1063 | 4 | — | — |
| heading-zoo | ok | **62 / 0** | 待标定 | 789 | 8 | — | — |
| plain | ok | **62 / 0** | 待标定 | 781 | 2 | — | — |
| remap-dup | ok | **62 / 0** | 待标定 | 779 | 3 | — | — |

> 阶段 1.4（2026-10-24）之后：8 个库合计 **496 ok / 0 FAIL**（1.3 后是 496 / 3）——
> **verify 侧全绿**。两条 `[ROOT-NOTE]` 是按「库形状」修掉的，不是调阈值：
> 根笔记的 `domain` 改成笔记自己的 id、`depth1` 允许是 note、越界判据改走父链取顶层祖先。
> 浏览器列只有 tiny 与 wide-roots 跑过（两个极端），红项全是**用例前提不成立**
> （0 条语义边 / 退化规模 / 最小根在 zMin 处本来就不挂标签 / 3e 锚点差 17px），
> 已逐条写进 manifest.known_gaps，修法是阶段 2 给浏览器侧加显式跳过与形状感知的阈值。

### 7.3 阶段 0.1 的「零改动」证明（已有）

改动前（2026-10-24 15:12 构建）：

```
graph.json                 5EFCBB9B4F3429D4ED58789C4A7A096F24F45E36B7DFCCBD831EDC29102A2EE2
graph.public.json          46C94716779A0F726814F64AD41244BE6A66326051A8E07B6767F12B28EB3A3A
knowledge-graph.html       2F5690D859A8BF9ACB13C3DD89A8A0D87F49DC6EF5CE73BE529E0426FF515647
knowledge-graph.public.html 20E14BF9E3B880BCAD7B49FC4E90B009977A8EC2E0B9BDE314FEE8093C22224D
```

阶段 0.1 改完必须重建后**逐位一致**（否则说明「加参数」顺手改了行为）。

**实测结果（2026-10-24，阶段 0.1 完成后）**：四份产物归一化时间戳后**全部 [SAME]**。
中间踩过一次：把补齐的四个 `lod` 默认键插在 `DEFAULTS.lod` 中间 → payload 里 `lod` 的键序变了
（JSON 语义相同），HTML 因此 [DIFF]；改成追加到末尾后恢复 [SAME]。这就是「产物级逐位比较」
比「眼睛看一遍」值钱的地方。

---

## 8. 量化门限（可直接写成 fixture 断言）

1. **最小学科叶子份额 < 0.32%** ⇒ 最外层会冒出第 2 层节点：`kg/layout.py:456-463` 用 `max(r)` 把
   `M[1]` 压到 `z_lo`，而真实 zMin 由 `min(r)` 决定。作者库 8/2167 = **0.37%，余量仅 7%**。
2. **< 0.23%** ⇒ `home_zoom < zMin`，home 被夹到 zMin、最大根可能被裁出屏（`render.js:298-300`）。
3. ~~**两套 zMin 定义**~~（2026-10-24 阶段 1.2 已统一）：原 `kg/layout.py` 用 `max(r_根)`、
   `verify.py`/`render.js` 用 `min(r_根)`，作者库上差 13.9× —— 现在三处同源用 `min(r_根)`。
4. ~~**缩放行程 = 1.286 × 半径比**~~（阶段 1.2 已改）：现在 `wheel_step` 按「目标格数
   = clamp(6×(D-1)+8, 20, 48)」反解、`home_zoom` 由本库区间反解、anchor 有上界夹住 ——
   平铺库/浅库不再出现「2 格滚轮走完全图 / M[D] 超调」。
   **新口径**：`行程格数 ≈ clamp(6×(D-1)+8, 20, 48)`；`author` 10 层 → 48 格，`tiny` 2 层 → 20 格。

---

## 9. 阶段 0.5：插件形态探针（结论）✅ 2026-10-24

> 只读探针，没有改任何渲染 / 布局 / 构建代码；依据是 Obsidian 官方开发者文档（链接见 §9.5）。
> 这一节的结论会**反过来约束阶段 1.2 怎么写**，所以先看 §9.1 的三条。

### 9.1 三个问题的答案

| # | 问题 | 答案 | 依据 |
|---|---|---|---|
| ① | 插件能否直接读 vault 并在 JS 里现算布局？ | **能，而且比预想的省事得多**：`app.vault.getMarkdownFiles()` 拿文件、`app.metadataCache.getFileCache()` 拿**标题/链接/嵌入/frontmatter**、`app.metadataCache.resolvedLinks` 拿**已解析好的链接图**、`app.metadataCache.getFirstLinkpathDest()` 按 Obsidian 自己的规则解析链接。`kg/scan.py`、`kg/parse.py`、`kg/preview.py` 的解析职责基本由平台代劳 | `Vault`、`CachedMetadata`、`MetadataCache` |
| ② | canvas 在 Obsidian 容器里的约束？ | `ItemView.contentEl` 里放 canvas 即可（Electron/Chromium，Canvas2D 与 rAF 全可用）；尺寸随标签页/侧栏拖拽变化 → 需要 `ResizeObserver`；DPR 走 `devicePixelRatio`；**插件 `styles.css` 是全局注入**，现有 `#topbar/#legend/#sidebar` 这类 id 选择器必须加命名空间，否则会跟主题/别的插件打架 | `ItemView` 示例（`contentEl`）、官方 CSS 变量惯例 |
| ③ | 预览图片怎么走？ | **`app.vault.getResourcePath(file)`**（返回 `app://` URI，桌面与移动端都可用）—— 这直接解决现在「单文件其实不含图、换个目录图全碎」的问题；但**单文件 HTML 用不了它**，所以两种产物形态在图片上必然不同 | `Vault.getResourcePath(file: TFile): string` |

**三条由此产生的结论：**

1. **路线选 B（插件内置 JS 管线）**，不是 A（读 Python 产物）。理由不只是「用户装 Python 不现实」：
   移动端**没有 Node/Electron**（官方原文：Node.js 与 Electron API 在移动端不可用），所以任何依赖
   Python 子进程的方案都无法上移动端；而路线 B 在移动端只是算力问题，不是能力问题。
2. **服务器时代的 30 分钟全量重建在插件里应该消失**：`Vault.on('create'/'modify'/'delete'/'rename')`
   + `MetadataCache.on('resolved')` 足够做**增量重建**。单文件产物仍然需要定时全建。
3. **模型层必须与 Python 端同构**（同一份 `{nodes, edges, layers, levels, meta}`）。这样插件产出的
   payload 能直接喂给现有的 `verify.py --config` / `browser_check.py --config`（0.1~0.3 刚建好的
   那套），「插件效果与演示一致」就从「人工承诺」变成**可断言**的事。

### 9.2 平台约束清单（对架构的硬要求）

| # | 约束 | 影响 | 处理阶段 |
|---|---|---|---|
| C1 | 移动端无 Node/Electron；`isDesktopOnly` 在 manifest 里声明 | 不能调 Python / `fs` / `child_process`；想上移动端就必须全 JS | 4 |
| C2 | 插件要打包成 `main.js`（esbuild/rollup） | 与现在「零构建、手写 JS 直接内联」冲突 → 新增一条工具链；审查也关注 bundle 体积 | 4 |
| C3 | Obsidian 自带 Markdown 与公式渲染 | **插件里不要内联 KaTeX**（0.6 MB），预览浮层用平台的 markdown 渲染 + 组件生命周期 | 4 |
| C4 | 视图生命周期由平台管理：`onOpen/onClose`、`registerEvent`、不要长期持有 view 引用（官方明确警告） | rAF 循环必须在 `onClose` 停掉、视图不可见时暂停；否则切标签页后台还在烧 CPU | 4 |
| C5 | `contentEl` 尺寸会变（拖侧栏、切分屏） | 画布 resize 必须挂 `ResizeObserver`，不能只在 `window.resize` 上做 | 4 |
| C6 | 插件 CSS 全局注入 | 现有面板 id（`#topbar`/`#legend`/`#sidebar`/`#preview`）要改成插件命名空间前缀；否则在用户装了别的插件时可能出现样式互踩 | 4 |
| C7 | **主题**：Obsidian 有浅色主题，而我们的视觉语言是深青玻璃 | 画布配色要么强制深色、要么出两套调色板（按 `theme-light` 切换）；面板用 Obsidian CSS 变量更稳 | 2 / 4 |
| C8 | 图片必须走 `getResourcePath` | 预览里的 `<img>` 在生产端有两种来源（单文件=相对路径、插件=app://），构建期要能**按目标形态**产出 | 3 / 4 |
| C9 | 插件不能依赖「构建期生成 payload」 | 布局/LOD 算法要能在浏览器里跑完一个几万节点的库（含打包），所以**纯函数 + 无 Python 特性**是硬要求 | 1.2 / 4 |
| C10 | 移动端性能弱于桌面（无独立 GPU 保证） | ghost / 圆材质 / 月牙投影要能按 `Platform.isMobile` 降级 | 2 / 4 |
| C11 | iOS 16.4 以下不支持正则 lookbehind | 预览/链接解析里如果用到 lookbehind 要换写法；JS 侧要自查一遍 | 4 |
| C12 | 社区插件审核：无遥测 / 无远程代码 / 无广告 / manifest 规范 / 说明用途 | 插件版不能「联网调 LLM」（与 §2 的否决一致）；阶段 5 若做语义增强必须默认关闭且离线 | 4 / 5 |

### 9.3 路线 B 的分工（哪些代码去哪）

| 层 | 单文件 HTML（现在） | 插件（将来） | 共享方式 |
|---|---|---|---|
| 扫描 | `kg/scan.py` | `app.vault.getMarkdownFiles()` + `getAllFolders()` | 不共享（平台代劳） |
| 解析 | `kg/parse.py` | `metadataCache.getFileCache()`（headings/links/embeds/frontmatter） | 不共享 |
| 链接解析 | `graph.resolve` + `_normalize_heading` | `resolvedLinks` + `getFirstLinkpathDest` | 不共享；**顺手解决 P4 的 14 处锚点未命中**（Obsidian 的匹配规则更宽松） |
| 建树/建边 | `kg/graph.py` | 移植成 JS（纯函数，输入=文件列表+缓存） | **golden payload 对比** |
| 布局 + LOD 阶梯 | `kg/layout.py`（478 行） | 移植成 JS | **golden payload 对比**（x/y 3 位、r 4 位、enter 6 位） |
| 渲染 | `web/render.js` | **原样复用**（只把宿主依赖抽走） | 同一个文件 |
| 宿主胶水 | `web/app.js`（DOM/面板/预览） | `ItemView` 适配层 + 平台 markdown 渲染 | 拆成 adapter 接口 |
| 预览 HTML | 构建期 `kg/preview.py` → 内联 | 运行时 `MarkdownRenderer` | 不共享（插件不需要预渲染，按需渲染即可） |

**关键防漂移手段（建议阶段 1.2 就开始遵守）**：把 8 个 fixture 的 payload 当 **golden 文件**，
JS 移植版对同一输入必须产出**逐位相同**的 `x/y/r/enter[]`。这比「两个实现看起来一样」强得多，
也让「插件演示效果与单文件一致」有可执行的判据。

### 9.4 风险与未决问题

1. **双实现漂移**（Python 布局 vs JS 布局）是最大风险。缓解：golden payload + 同一套 fixtures；
   如果不能保证逐位一致，就退一步「几何等价」（三条包含关系 + enter[] 单调 + 同层同色）。
2. **浅色主题**是设计层问题，不是工程问题：深青玻璃在白色背景上会很突兀。要么插件只支持深色
   （体验打折），要么做两套画布配色（工作量翻倍在**调色**上，不在代码上）。
3. **Obsidian 内部 API**（`MarkdownRenderer`、popover 之类）不是稳定公开 API，跨大版本可能变；
   插件要包一层薄封装，坏了自己兜底（退化成纯文本预览）。
4. **插件审核**的时间不可控；先以「本地安装 / BRAT」为目标形态，别把节奏押在审核上。
5. 本探针**没有**在真实 Obsidian 里跑过代码（纯文档 + API 调研）。真正开工前建议做一次
   「hello-world ItemView + 一块 canvas 渲染 100 个圆」的 30 分钟冒烟，确认 DPR/主题/尺寸三条。

### 9.5 依据

- 自定义视图（`ItemView` / `registerView` / `contentEl` / 不要持有 view 引用）：
  https://docs.obsidian.md/Plugins/User+interface/Views
- 移动端（Node/Electron 不可用、`isDesktopOnly`、`Platform`、iOS lookbehind）：
  https://docs.obsidian.md/Plugins/Getting+started/Mobile+development
- `Vault`（`getMarkdownFiles` / `cachedRead` / `getResourcePath` / 文件事件）：
  https://docs.obsidian.md/Reference/TypeScript+API/Vault
- `MetadataCache`（`resolvedLinks` / `unresolvedLinks` / `getFirstLinkpathDest` / 索引事件）：
  https://docs.obsidian.md/Reference/TypeScript+API/MetadataCache
- `CachedMetadata`（`headings` / `links` / `embeds` / `frontmatter` / `sections`）：
  https://docs.obsidian.md/Reference/TypeScript+API/CachedMetadata

> 注：本轮网络对部分文档页抓取不稳定，`MarkdownRenderer` 与插件提交规范没抓到原文，
> 相关内容按官方文档的公开口径写，**阶段 4 开工前要逐条复核一遍**。

---

## 10. 变更日志

| 日期 | 阶段 | 内容 | 提交 |
|---|---|---|---|
| 2026-10-24 | — | 本文档建立（诊断 + 路线图 + 验收契约） | 与 0.1 同一提交 |
| 2026-10-24 | 0.1 | `--config` + 未知参数报错 + 内联 scope（无 scope_file）+ 路径统一相对 config + 补齐 DEFAULTS；产物归一化后逐位不变 | `feat(app): 阶段 0.1`（见 `git log`） |
| 2026-10-24 | 0.2 | 8 个形状 fixture + 确定性生成器 + manifest（canary / expected_ok / known_gaps）；8 库全部 build 通过 | `feat(fixtures): 阶段 0.2`（见 `git log`） |
| 2026-10-24 | 0.3 | sweep runner + ok 计数/vault 身份/机器可读结果行；修 2 处崩溃 + 2 处「内容特征当契约」+ 内联 roots 多算附件目录；8 库标定为 426 ok / 22 FAIL | `feat(fixtures): 阶段 0.3`（见 `git log`） |
| 2026-10-24 | 0.5 | 插件形态探针（只读）：路线 B + 平台代劳解析层 + `getResourcePath` 图片 + golden payload 防漂移；12 条平台硬约束 | `docs(plan): 阶段 0.5`（见 `git log`） |
| 2026-10-24 | 1.2 | 缩放行程标定：z_lo 三处同源、anchor 加上界、steps==0 特判、home 由区间反解并落盘、wheel_step 按目标格数反解、涌入上限按层占比；8 库 456 ok / 3 FAIL（原 426/22） | `feat(lod): 阶段 1.2`（见 `git log`） |
| 2026-10-24 | 1.3 | 自动色板（golden-angle + 手写优先）+ `meta.domains` 成为图例/下拉唯一真源 + 无学科库降级显示；wide-roots 30 学科 30 色 0 灰；8 库 496 ok / 3 FAIL | `feat(theme): 阶段 1.3`（见 `git log`） |
| 2026-10-24 | 1.4 | 根笔记模型：domain = 笔记自己的 id、depth1 允许 note、越界判据走父链；8 库 **496 ok / 0 FAIL**（形状体检表 verify 侧全绿） | `fix(graph): 阶段 1.4`（见 `git log`） |
