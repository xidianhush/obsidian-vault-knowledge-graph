"""生成 8 个「形状」fixture vaults（PLAN_APPLICABILITY.md 阶段 0.2）。

**为什么要有它**：PLAN 的目标是「换一个别人的库还能不能用」，而只有一个库的时候
「换库会不会坏」无法验收。这里用**确定性**生成器造出 8 种形状各异的库，每个专考一种
失效模式（见 `fixtures/manifest.yaml` 的 `tests` 字段）。

**入库的只有本脚本 + manifest.yaml**；生成出来的 `fixtures/vaults/` 已 gitignore。

用法：
    python fixtures/make_vaults.py              # 生成全部（已存在则覆盖）
    python fixtures/make_vaults.py --list       # 只列出 fixture 清单
    python fixtures/make_vaults.py --only tiny  # 只生成指定的（逗号分隔）
    python fixtures/make_vaults.py --clean      # 删掉 vaults/

布局：
    fixtures/vaults/<name>/config.yaml   自包含配置（config 里的相对路径都相对它）
    fixtures/vaults/<name>/vault/...     vault 本体
    fixtures/vaults/<name>/dist/         构建产物（gitignored）

**确定性**：没有随机数、没有时间戳、没有依赖系统 locale 的排序。同样的脚本必然产出
同样的内容；每次生成后打印内容指纹，`--clean` 后重跑指纹不变即证明可复现。
"""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "vaults")

# 1×1 透明 PNG —— preview 的 <img> 要指向一个真实存在的文件，verify 会查它
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ── 小工具 ──────────────────────────────────────────────────────────────
def w(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def wpng(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(PNG_1PX)


def inline_config(include: str = '"**"') -> str:
    """内联 scope 的 config（没有 scope_file —— 别人的库长这样）。"""
    return (
        "# 内联 scope：这个 fixture 没有 quartz-setup/public-scope.yaml（阶段 0.1 起支持）\n"
        "vault: vault\n"
        "page_title: fixture\n"
        "scopes:\n"
        "  main:\n"
        f"    include: [{include}]\n"
        "    output:\n"
        "      json: dist/graph.json\n"
        "      html: dist/graph.html\n"
    )


def scope_file_config() -> str:
    """scope_file 工作流（作者的路径）：用来测 `as` 重映射与同名 stem。"""
    return (
        "# scope_file 工作流：测 `as` 重映射（inline scope 没有 mirror/remap 语义）\n"
        "vault: vault\n"
        "page_title: fixture-remap\n"
        "scope_file: scope.yaml\n"
        "scopes:\n"
        "  main:\n"
        "    output:\n"
        "      json: dist/graph.json\n"
        "      html: dist/graph.html\n"
    )


# ── 8 个 fixture ────────────────────────────────────────────────────────
def fx_shallow(base: str) -> None:
    """1 个文件夹 + 15 篇笔记，正文完全不用 #（max_depth=2）。"""
    notes = os.path.join(base, "vault", "Notes")
    for i in range(1, 16):
        w(os.path.join(notes, f"Note {i:02d}.md"),
          f"第 {i:02d} 篇：一句话正文，没有标题。\n\n再来一行正文，仍然没有 # 标题。\n")
    w(os.path.join(base, "config.yaml"), inline_config())


def fx_deep_chain(base: str) -> None:
    """单链 10 层目录、每层 1 篇（文件系统深度 10 + 标题 1 → max_depth=11）。"""
    path = os.path.join(base, "vault")
    for level in range(1, 11):
        path = os.path.join(path, f"L{level:02d}")
        w(os.path.join(path, f"Note L{level:02d}.md"),
          f"# 第 {level:02d} 层\n\n这一层只有一篇笔记，用来把深度轴拉长。\n")
    w(os.path.join(base, "config.yaml"), inline_config())


def fx_wide_roots(base: str) -> None:
    """30 个顶层目录、共 150 篇；最大那个占 60%（90/150）。"""
    vault = os.path.join(base, "vault")
    counts = {1: 90}
    remaining = 60
    for i in range(2, 31):
        take = 2
        counts[i] = take
        remaining -= take
    counts[2] += remaining                      # 余数都塞进第二个目录
    for i in range(1, 31):
        folder = os.path.join(vault, f"Domain {i:02d}")
        for j in range(1, counts[i] + 1):
            w(os.path.join(folder, f"Topic {i:02d}.{j:03d}.md"),
              f"# Domain {i:02d} 的第 {j} 篇\n\n"
              f"这是第 {i:02d} 个顶层学科的正文，用来把顶层扇出撑到 30 个。\n")
    w(os.path.join(base, "config.yaml"), inline_config())


def fx_hub_dense(base: str) -> None:
    """80 篇 / 320 条 [[链接]] / 一个度数 >8 的 hub / 5 条标题级链接。"""
    hub = os.path.join(base, "vault", "Hub")
    n = 80
    for i in range(1, n + 1):
        links = []
        for off in (1, 7, 13, 31):
            tgt = (i - 1 + off) % n + 1
            links.append(f"- 参见 [[Topic {tgt:02d}]]")
        if 1 <= i <= 12:
            links.append("- 重要的总览 [[Topic 20]]")
        if i == 5:
            links.append("- 带锚点 [[Topic 07#小节 1]]")
            links.append("- 带锚点 [[Topic 09#小节 2|别名]]")
        w(os.path.join(hub, f"Topic {i:02d}.md"),
          f"# Topic {i:02d}\n\n## 小节 1\n\n正文。\n\n## 小节 2\n\n正文。\n\n"
          f"## 小节 3\n\n" + "\n".join(links) + "\n")
    w(os.path.join(base, "config.yaml"), inline_config())


def fx_heading_zoo(base: str) -> None:
    """h1..h6 链 + **只用 h5/h6 的笔记** + 笔记内重复标题 + 公式 + 图片。

    Offset.md 是阶段 1.1 的靶子：它的标题从 `#####` 起。旧口径（标题级别字面值当层数）下
    这篇笔记会把深度轴凭空拉长 4 层；稠密化之后它只占「笔记深度 +1 / +2」。
    """
    zoo = os.path.join(base, "vault", "Zoo")
    chain = ["# 一级", "## 二级", "### 三级", "#### 四级", "##### 五级", "###### 六级"]
    w(os.path.join(zoo, "Chain.md"),
      "\n\n".join(f"{h}\n\n第 {k} 层正文，公式 $x^{k}+y_{k}=z$。" for k, h in enumerate(chain, 1)) + "\n")
    w(os.path.join(zoo, "Offset.md"),
      "##### 从五级开始\n\n这篇笔记不用 h1~h4（粘贴来的片段常见）。\n\n"
      "###### 六级小节\n\n**稠密化之后它的层数只占 +1 / +2，不是 +5 / +6。**\n")
    for i in (1, 2, 3):
        w(os.path.join(zoo, f"Dup {i:02d}.md"),
          f"# Dup {i:02d}\n\n## 总结\n\n第一段。\n\n## 过程\n\n正文。\n\n## 总结\n\n重复的标题名。\n")
    w(os.path.join(zoo, "Pictures.md"),
      "# 图片\n\n![[img1.png]]\n\n$$\\int_0^1 x^2\\,dx = \\frac13$$\n\n![[img2.png]]\n")
    w(os.path.join(zoo, "NoPictures.md"),
      "# 无图\n\n只有一个行内公式 $E=mc^2$。\n")
    wpng(os.path.join(base, "vault", "Attachment", "img1.png"))
    wpng(os.path.join(base, "vault", "Attachment", "img2.png"))
    w(os.path.join(base, "config.yaml"), inline_config())


def fx_plain(base: str) -> None:
    """0 标题 / 0 公式 / 0 图片 / 0 链接 —— 专考「内容特征被当成契约」。"""
    notes = os.path.join(base, "vault", "Notes")
    for i in range(1, 11):
        w(os.path.join(notes, f"Plain {i:02d}.md"),
          f"第 {i:02d} 篇纯文本。没有标题、没有公式、没有图片、没有任何 wiki 链接。\n")
    w(os.path.join(base, "config.yaml"), inline_config())


def fx_remap_dup(base: str) -> None:
    """同名 stem 两处 + scope `as` 重映射 + 一个空目录（scope_file 工作流）。"""
    vault = os.path.join(base, "vault")
    w(os.path.join(vault, "AA", "Notes.md"), "# AA 的 Notes\n\n同名 stem 的第一份。\n")
    w(os.path.join(vault, "AA", "Extra.md"), "# AA 的 Extra\n\n正文。\n")
    w(os.path.join(vault, "BB", "Notes.md"), "# BB 的 Notes\n\n同名 stem 的第二份。\n")
    w(os.path.join(vault, "BB", "Other.md"), "# BB 的 Other\n\n正文。\n")
    os.makedirs(os.path.join(vault, "Empty"), exist_ok=True)
    w(os.path.join(base, "scope.yaml"),
      "# 只列 AA / BB，Empty 故意不列（它必须不出现在图里）\n"
      "content:\n"
      "  - from: \"AA\"\n"
      "    as: \"Alpha\"\n"
      "    scopes: [main]\n"
      "  - from: \"BB\"\n"
      "    as: \"Beta\"\n"
      "    scopes: [main]\n"
      "exclude:\n"
      "  - \"**/.trash/**\"\n")
    w(os.path.join(base, "config.yaml"), scope_file_config())


def fx_edge_storm(base: str) -> None:
    """重量级链接库：500 篇、每篇 12 条出站链接 → **6000 条**语义边（阶段 2.2 的性能靶子）。

    作者的库只有 97 条边；别人的库常见 1~3 万条。上一版每帧逐条边 2 次 stroke（跨域
    还各建一个渐变对象），6000 条就是每帧 1.2 万次 stroke —— 拖拽/滚轮会掉到个位数 fps。
    每篇 1 个 h1 + 2 个 h2，节点量约 2000，避免标题数掩盖「边」本身的成本。
    """
    storm = os.path.join(base, "vault", "Notes")
    offs = (1, 7, 13, 29, 59, 97, 157, 251, 331, 421, 479, 499)
    for i in range(1, 501):
        targets = [(i - 1 + off) % 500 + 1 for off in offs]
        lines = ["- 参见 [[Note %03d]]" % t for t in targets]
        w(os.path.join(storm, "Note %03d.md" % i),
          "# Note %03d\n\n## 内容\n\n这一篇用来压低「每帧逐条画边」的成本。\n\n"
          "## 关联\n\n%s\n" % (i, "\n".join(lines)))
    w(os.path.join(base, "config.yaml"), inline_config())


def fx_long_notes(base: str) -> None:
    """超长笔记 + 很小的预览预算 → 验阶段 3.1 的截断路径。

    预览是 payload 里最大的一块（作者库占节点字段 48%），大库不设预算会撑爆 20 MB
    单文件上限。这个 fixture 把 `preview.total_chars_budget` 压到 12000：
    8 篇 × 约 3000 字符 → 每篇上限 1500，全部触发截断；
    其中一篇的截断点落在**围栏代码块里**，验「补一个闭合围栏」不破结构。
    """
    notes = os.path.join(base, "vault", "Long")
    for i in range(1, 9):
        para = ("这是第 %d 段正文，用来把一篇笔记撑到三千字符以上。" % i) * 40
        if i == 3:
            # 故意让代码块盖住截断点：预算 1500 字符左右会切在围栏内部
            body = "# 长笔记 %d\n\n## 开头\n\n%s\n\n```python\n%s\n```\n\n## 结尾\n\n%s\n" % (
                i, para[:800], "\n".join("x = %d  # 代码行 %d" % (j, j) for j in range(120)),
                para[:600])
        else:
            body = "# 长笔记 %d\n\n## 开头\n\n%s\n\n## 结尾\n\n%s\n" % (i, para[:1200], para[:600])
        w(os.path.join(notes, "Long %02d.md" % i), body)
    cfg = (
        "# 内联 scope + 很小的预览预算（阶段 3.1 截断路径）\n"
        "vault: vault\n"
        "page_title: fixture\n"
        "preview:\n"
        "  total_chars_budget: 12000\n"
        "scopes:\n"
        "  main:\n"
        "    include: [\"**\"]\n"
        "    output:\n"
        "      json: dist/graph.json\n"
        "      html: dist/graph.html\n"
    )
    w(os.path.join(base, "config.yaml"), cfg)


def fx_tiny(base: str) -> None:
    """1 篇笔记，直接放在 vault 根（没有文件夹）—— 退化规模 + 根笔记。"""
    w(os.path.join(base, "vault", "Only.md"), "# 唯一标题\n\n只有这一篇。\n")
    w(os.path.join(base, "config.yaml"), inline_config())


FIXTURES = [
    ("tiny", fx_tiny),
    ("shallow", fx_shallow),
    ("deep-chain", fx_deep_chain),
    ("wide-roots", fx_wide_roots),
    ("hub-dense", fx_hub_dense),
    ("edge-storm", fx_edge_storm),
    ("long-notes", fx_long_notes),
    ("heading-zoo", fx_heading_zoo),
    ("plain", fx_plain),
    ("remap-dup", fx_remap_dup),
]


# ── 生成 / 指纹 ─────────────────────────────────────────────────────────
def clean() -> None:
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
        print(f"已删除 {OUT}")


def generate(names) -> int:
    os.makedirs(OUT, exist_ok=True)
    for name, builder in FIXTURES:
        if names and name not in names:
            continue
        base = os.path.join(OUT, name)
        vault = os.path.join(base, "vault")
        if os.path.isdir(vault):
            shutil.rmtree(vault)
        builder(base)
        print(f"  [built] {name:<12} {_count_md(vault):>4} 篇笔记")
    return fingerprint()


def _count_md(root: str) -> int:
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        n += sum(1 for f in files if f.lower().endswith(".md"))
    return n


def fingerprint() -> str:
    """对生成出来的所有文件内容取指纹（排除 dist/）—— 可复现性的证据。"""
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(OUT):
        dirs[:] = sorted(d for d in dirs if d != "dist")
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, OUT).replace("\\", "/")
            h.update(rel.encode("utf-8"))
            with open(path, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def main(argv) -> int:
    names = set()
    do_clean = False
    for a in argv[1:]:
        if a == "--clean":
            do_clean = True
        elif a == "--list":
            for name, builder in FIXTURES:
                print(f"{name:<12} {(builder.__doc__ or '').strip().splitlines()[0]}")
            return 0
        elif a.startswith("--only=") or a == "--only":
            if a == "--only":
                continue
            names = {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
        elif not a.startswith("-"):
            names |= {x.strip() for x in a.split(",") if x.strip()}
    if do_clean:
        clean()
        return 0
    fp = generate(names)
    print(f"\n指纹 sha256={fp[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
