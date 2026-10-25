# 交接：阶段 4（Obsidian 插件）

> 你在接手一个**已经完成阶段 0~3**的项目。这份文件只写「接手这一刻的事实 + 下一步该做什么」。
> 完整背景、决策理由、量化阈值在 `PLAN_APPLICABILITY.md`（本文档所有章节号都指向它）。
> 项目红线见 §0（不改 vault 笔记 / 不读 `Utilities/API Key.md` / 不 push / 无运行时第三方依赖）。

## 1. 当前状态（2026-10-25 13:5x）

| 项 | 值 |
|---|---|
| git | 分支 `main`，HEAD = **`be259dd`**（阶段 3.4）；**19 个提交未 push**（用户自己 push，别推） |
| 工作区 | 干净（`git status` 空） |
| 阶段 0 / 0.5 / 1 / 2 / 3 | **全部完成**（0.1–0.3、0.5 探针、1.1–1.5、2.0–2.5、3.1–3.4） |
| 阶段 4 | **未开始**（本文件就是它的起点） |
| 阶段 5（可选） | 未开始（Louvain 虚拟学科层，见 §4 阶段 5） |

### 硬闸（改动前后必须对得上，不能降）

| 命令 | 期望 |
|---|---|
| `python build.py verify --scope all` | **138 ok / 0 FAIL（69+69）** |
| `python browser_check.py`（private） | **147 ok / 0 FAIL / 0 skip** |
| `KG_HTML=knowledge-graph.public.html python browser_check.py` | **146 ok / 0 FAIL / 1 skip** |
| `python fixtures/run_sweep.py --browser` | 11 个 fixture 四列全绿（verify 11×69=759，browser 全 0 FAIL） |
| 单文件 | private **4699 KB** / public **4751 KB**（阶段 3.4 列式化后） |

ok 数**变少**（而不是变多）就是回归，例外必须写进 `fixtures/manifest.yaml` 的 `known_gaps`。
`--update-manifest` 只回填读数、会**合并**旧值（不会抹掉 browser 列）。

## 2. 怎么跑（Windows / 本机）

```powershell
cd D:\obsidian_vault\knowledge-graph
python build.py build --scope all          # 重建 private + public（作者库）
python build.py verify --scope all         # 数据侧断言
python browser_check.py                    # 浏览器行为（Playwright + Chrome）
python fixtures/run_sweep.py               # 11 个形状 fixture：build + canary + verify
python fixtures/run_sweep.py --browser     # 再加浏览器列（约 30~40 分钟）
python fixtures/make_vaults.py --only <name>   # 重新生成某个 fixture
```

**沙箱坑（重要）**：本机文件沙箱对 `knowledge-graph/` 子目录是低完整性，`build/verify/browser_check/git`
都会 `PermissionError`。执行这些命令时给工具调用加 `sandbox_permissions: danger-full-access`（一次性提权）。
`write`/`edit` 工具本身不受限。另外 **PowerShell 不支持 `python - <<'PY'` heredoc** —— 一次性脚本写到
`D:\obsidian_vault\.recon\*.py` 再 `python <路径>`（该目录是临时区，不入库）。
截图落在 `%TEMP%\kg_*.png`（作者库）或 `fixtures/.shots/<name>/`（fixture）。

## 3. 代码地图

| 路径 | 作用 |
|---|---|
| `build.py` | CLI：`build` / `verify` / `candidates` / `check`；`build_payload()` 串联扫描→图→布局→payload |
| `kg/scan.py` `kg/parse.py` | 扫 vault、解析 frontmatter/标题/链接/图片 |
| `kg/graph.py` | 节点/边构建、`resolve()`（Obsidian 短路径规则，**阶段 3.3 加了后缀索引**）、`attach_previews()` |
| `kg/preview.py` | markdown → 预览 HTML（公式保 `$…$`，图片相对路径，标题锚点按源行号注入）；**阶段 3.1 预览预算** |
| `kg/layout.py` | circle packing + 深度分层 LOD（`enter[]`、`home_zoom`、`wheel_step`）；**阶段 3.2 半径钳位/坐标精度** |
| `kg/palette.py` | 学科色板（手写优先，其余黄金角） |
| `kg/config.py` | 配置默认值与校验；**所有相对路径相对 config.yaml** |
| `kg/codec.py` | **阶段 3.4** payload `idx1` 列式化编解码（整数引用） |
| `kg/emit.py` | 写 `graph.json` / 内联单文件 HTML（把 `web/*` 三件套塞进模板） |
| `web/render.js` | Canvas2D 渲染器（唯一真渲染实现，**插件必须复用/移植它**） |
| `web/app.js` | 浏览器侧 HUD / 侧栏 / 搜索 / 过滤 / 预览浮层 |
| `web/template.html` | 单文件外壳（CSS 全局作用域——**插件里要加命名空间**，见 C 约束） |
| `verify.py` | 数据侧断言（69 条/scope） |
| `browser_check.py` | 浏览器行为断言（147 条/scope） |
| `fixtures/` | 11 个形状 fixture + `manifest.yaml`（canary / expected_ok / known_gaps）+ `run_sweep.py` |

## 4. 阶段 4 的任务（PLAN §4 阶段 4 / §9 探针结论 C1–C12）

目标：**打包成 Obsidian 原生插件，演示效果与单文件一致**。

PLAN 的路线（阶段 0.5 探针的结论，务必先读 §9 全文再动手）：

1. **路线 B：JS 管线进插件**。插件里不能跑 Python；`isDesktopOnly=false` 时移动端没有 Node/Electron，
   所以插件侧要自带一套「扫描 → 图 → 布局 → payload」的 **JS 实现**（或至少把 Python 侧的逻辑移植成
   纯 JS 模块，两端共用同一份 `render.js`）。
2. **抽 `GraphCore`**：payload 形状 + canvas 渲染，无宿主依赖；上层两个适配层
   （浏览器单文件 / Obsidian `ItemView`）。「演示效果一致」靠**同一内核**保证，而不是靠两套实现对齐。
3. **Obsidian 侧 API**：`metadataCache`（`headings` / `links` / `embeds`）、`resolvedLinks`、
   `getFirstLinkpathDest`；视图用 `ItemView.contentEl` 放 canvas；图片走 `vault.getResourcePath(file)`
   （顺手解决「单文件其实不自包含图片」）。
4. **CSS 必须命名空间化**（`template.html` 现在是全局选择器，插件里会污染宿主）。
5. **防漂移**：同一个 vault 用「Python 构建」与「插件内 JS 构建」各出一份 payload，做 **golden payload 对比**
   （字段集合、每节点 `id/depth/r`、每边 `s/t/type`、`meta.zoom/lod` 数值），差异必须可解释。
6. **先做 30 分钟冒烟**（用户之前定的第一步）：写一个最小 `ItemView`，把**现有单文件 HTML 里的渲染器**
   （`web/render.js` + `web/app.js`）塞进 `contentEl` 的 canvas，确认能画出同一张图、能滚轮缩放。
   冒烟通过再谈架构抽取，别一上来就重构。

验收口径（PLAN §7 的插件列）：单文件 vs 插件在同一 vault 上**视觉一致**（同尺寸截图肉眼比对）、
`verify` 的等价断言在插件 payload 上全过、CSS 不污染宿主、移动端不依赖 Node。

## 5. 已知遗留 / 注意事项

- **preview 仍是 payload 的 60%**（作者库 1680 KB / 4196 KB）。它是「用户要的整篇预览」，只能靠
  预算（3.1 的 `preview.total_chars_budget`）压，不能靠编码压。做插件时注意 `JSON.parse` 体积。
- **阶段 2.4 明确否决过两件事**（理由见 PLAN §4）：树深压缩（破坏父浅于子几何契约）、虚拟簇节点
  （收益不抵风险）。不要再捡起来。
- `fixtures/manifest.yaml` 里 `deep-chain` 的 `known_gaps` 可能还留着一条 `[PILLS]`（阶段 2.4 已修
  「胶囊横向滚动」，若确认修好可以清掉并说明）。
- `.recon/` 里是本会话的一次性脚本（`payload_audit.py` 量化 payload 构成、`ab_*.py` 做 A/B、
  `bench_33.py` 量索引收益、`edge_perf.py`/`zoom_fps.py` 量渲染性能、`ghost_filter.py` 等）。
  **不属于仓库**，想复用量化手段可以照抄。
- 每次提交请沿用本仓库习惯：**详细中文提交信息**（为什么改 / 改了什么 / 实测数字 / 已知代价），
  并把结果同步进 `PLAN_APPLICABILITY.md` 的对应小节 + §10 changelog。

## 6. 建议的起手顺序

1. `git log --oneline -14` + 读 `PLAN_APPLICABILITY.md` §0 / §3 / §4（阶段 4）/ §9（C1–C12）。
2. 跑一遍硬闸（`verify --scope all`、`browser_check` private/public），确认起点与上表一致。
3. 30 分钟冒烟：最小 `ItemView` + 复用 `render.js`。
4. 冒烟过了再按 PLAN §4 阶段 4 拆 `GraphCore` 与两个适配层；每拆一步都跑硬闸 + golden payload 对比。
