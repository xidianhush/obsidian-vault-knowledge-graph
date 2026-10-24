"""候选边挖掘：离线跑，产出 candidates.yaml 供人工审核。

三条高精度启发式（都能解释「为什么是它」）：

1. 标题 ↔ 笔记同名 —— 笔记 A 里出现与笔记 B 同名的标题，说明 B 是 A 的下位概念 → prerequisite。
2. 术语共现 —— 英文技术词 / LaTeX 命令的逆文档频率加权共现。方向未知，所以记 contrast（无箭头），
   不假装知道推导方向。
3. 重复笔记探测 —— 同一非通用标题跨越 3 篇以上笔记，多半是同一门课的多个版本 → contrast。

中文不做分词：不引入 jieba 之类的重依赖，中文侧只做标题精确匹配，宁缺勿滥。
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict

import yaml

# 只取 ASCII 技术词；LaTeX 反斜杠命令（\displaystyle、\varepsilon 之类）在这个 vault 里
# 是纯排版噪声，共享它们不能说明两篇笔记相关，所以整类排除。
TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#]{2,}")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
NON_WORD_RE = re.compile(r"[\s\u3000_\-—–·、，,。.：:；;！!？?（）()\[\]【】《》<>\"'“”‘’/\\|*#>+~^=@$%&]")
DATA_URI_RE = re.compile(r"data:[^\s)\"']{16,}")
BLOB_RE = re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")
MATHY_RE = re.compile(r"^[A-Za-z]_?[A-Za-z0-9]{0,2}$")
LATEX_CMD_RE = re.compile(r"\\[A-Za-z]+")

# 通用英文词 / 数学排版命令 —— 出现频率高但不能说明两篇笔记相关
GENERIC = {
    "the", "and", "for", "with", "that", "this", "from", "are", "not", "but", "you", "can",
    "use", "uses", "using", "used", "will", "have", "has", "had", "was", "were", "its", "all",
    "any", "one", "two", "three", "four", "five", "when", "then", "than", "into", "out", "over",
    "such", "also", "more", "most", "other", "others", "some", "only", "same", "each", "both",
    "very", "well", "make", "makes", "made", "does", "did", "how", "why", "what", "which",
    "where", "their", "them", "they", "these", "those", "here", "there", "about", "after",
    "before", "because", "between", "during", "under", "above", "below", "again", "once",
    "need", "needs", "want", "like", "just", "know", "see", "let", "get", "got", "new", "old",
    "first", "second", "third", "list", "note", "notes", "example", "examples", "summary",
    "define", "definition", "etc", "print", "def", "class", "import", "return", "self", "true",
    "false", "none", "int", "str", "float", "bool", "var", "const", "function", "functions",
    "void", "include", "stdio", "printf", "cout", "endl", "main", "html", "css", "json",
    "http", "https", "www", "com", "png", "jpg", "pdf", "image", "images", "pasted", "nbsp",
    "code", "text", "file", "files", "line", "lines", "page", "table", "type", "types",
    "value", "values", "name", "names", "data", "case", "cases", "point", "points", "part",
    "parts", "side", "sides", "left", "right", "top", "bottom", "start", "starts", "end",
    "ends", "time", "times", "change", "changes", "different", "given", "require", "required",
    "requires", "assume", "suppose", "consider", "depends", "dependent", "independent",
    "increase", "decrease", "larger", "smaller", "equal", "equals", "positive", "negative",
    "zero", "unit", "units", "order", "orders", "degree", "degrees", "problem", "problems",
    "solution", "solutions", "answer", "answers", "method", "methods", "result", "results",
    "figure", "figures", "chapter", "section", "sections", "table", "tables", "theorem",
    "theorems", "proof", "property", "properties", "system", "systems", "general", "special",
    "simple", "complex", "real", "imaginary", "small", "large", "high", "higher", "low",
    "lower", "middle", "average", "total", "sum", "product", "ratio", "rate", "level",
    "levels", "based", "given", "known", "unknown", "common", "normal", "standard",
    "example", "principle", "principles", "application", "applications", "key", "related",
    "outside", "inside", "input", "output", "inputs", "outputs", "state", "states",
    "transform", "transforms", "frequency", "frequencies", "frequency", "theory", "analysis",
    "practice", "exercise", "exercises", "review", "overview", "introduction", "summary",
    "important", "useful", "necessary", "possible", "impossible", "correct", "wrong",
    "width", "height", "length", "size", "area", "volume", "mass", "speed", "motion",
    "cent", "alpha", "beta", "gamma", "delta", "theta", "omega", "lambda", "sigma", "mu",
    "frac", "sqrt", "cdot", "times", "left", "right", "begin", "end", "text", "mathrm",
    "boldsymbol", "displaystyle", "displaystyle", "qquad", "quad", "circ", "approx",
    "varepsilon", "infty", "partial", "nabla", "overline", "underline", "hat", "bar",
    "vec", "dot", "ddot", "prime", "limits", "subset", "supset", "forall", "exists",
    "implies", "iff", "triangleq", "equiv", "leq", "geq", "neq", "ll", "gg", "propto",
    "author", "date", "title", "tags", "created", "modified", "folder", "path", "root",
    "null", "undefined", "error", "warning", "debug", "test", "tests", "run", "runs",
    "install", "setup", "config", "option", "options", "default", "user", "users", "server",
    "client", "request", "response", "remote", "local", "mode", "sample", "samples",
    "console", "continue", "edit", "edits", "draft", "logpoint", "breakpoint", "terminal",
    "plugin", "plugins", "extension", "extensions", "setting", "settings", "shortcut",
    "command", "commands", "palette", "window", "panel", "view", "menu", "click", "open",
    "close", "save", "saved", "load", "line", "column", "print", "echo", "output", "input",
}


def _strip_noise(text: str) -> str:
    """去掉代码块、行内代码、data URI、base64 块 —— 它们只贡献噪声术语。"""
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None:
            out.append(line)
    text = "\n".join(out)
    text = CODE_SPAN_RE.sub(" ", text)
    text = DATA_URI_RE.sub(" ", text)
    text = LATEX_CMD_RE.sub(" ", text)      # 先整体删掉 \operatorname 这类命令，否则词干会残留
    return BLOB_RE.sub(" ", text)


def _plausible(token: str, min_len: int) -> bool:
    if len(token) < min_len or len(token) > 28:
        return False
    low = token.lower()
    if low in GENERIC or low.isdigit():
        return False
    if len(set(low)) == 1:
        return False
    if MATHY_RE.match(token):          # p_1、R_n、E_x 这类单字母+下标
        return False
    digits = sum(c.isdigit() for c in token)
    vowels = sum(c in "aeiouAEIOU" for c in token)
    if len(token) >= 10 and (digits >= 4 or vowels <= 1):
        return False                    # 随机串 / 哈希 / 编码残留
    if digits > len(token) / 2:
        return False
    return True


def extract_terms(text: str, min_len: int):
    counts = Counter()
    for token in TERM_RE.findall(_strip_noise(text)):
        if _plausible(token, min_len):
            counts[token] += 1
    return counts


def normalize_title(title: str) -> str:
    return NON_WORD_RE.sub("", title).lower()


def collect(cfg, notes, existing_pairs):
    cand = cfg["candidates"]
    min_score = float(cfg["candidates"]["min_score"])
    generic = {normalize_title(t) for t in cand.get("generic_headings", [])}
    by_id = {n.file.id: n for n in notes}

    title_index = defaultdict(list)          # 归一化笔记名 → 笔记 id
    for note in notes:
        title_index[normalize_title(note.file.stem)].append(note.file.id)

    found: dict[tuple, dict] = {}

    def offer(source, target, etype, score, reason):
        if source == target or score < min_score:
            return
        if (source, target) in existing_pairs:
            return
        key = (source, target, etype)
        cur = found.get(key)
        if cur and cur["score"] >= score:
            if reason not in cur["reason"]:
                cur["reason"] = f"{cur['reason']}；{reason}"
            return
        found[key] = {
            "source": source,
            "target": target,
            "type": etype,
            "weight": float(cfg["weight"]["annotation_default"]),
            "score": round(score, 3),
            "reason": reason,
            "status": "pending",
        }

    # 启发式 1：标题 ↔ 笔记同名
    for note in notes:
        for head in note.headings:
            norm = normalize_title(head.title)
            if len(norm) < 2 or norm in generic:
                continue
            for other in title_index.get(norm, []):
                if other == note.file.id:
                    continue
                offer(
                    other, note.file.id, "prerequisite", 0.9,
                    f"《{by_id[note.file.id].file.stem}》中有标题「{head.title}」，"
                    f"与笔记《{by_id[other].file.stem}》同名",
                )

    # 启发式 2：术语共现
    n_notes = len(notes)
    df_cap = max(2, int(n_notes * float(cand["max_doc_freq_ratio"])))
    doc_terms: dict[str, set] = {}
    display: dict[str, Counter] = defaultdict(Counter)
    for note in notes:
        counts = extract_terms(note.text, int(cand["min_term_len"]))
        doc_terms[note.file.id] = set(counts)
        for token, cnt in counts.items():
            display[token.lower()][token] += cnt

    df = Counter()
    for terms in doc_terms.values():
        df.update(terms)
    informative = {t for t in df if 2 <= df[t] <= df_cap}
    postings = defaultdict(list)
    for note_id, terms in doc_terms.items():
        for term in terms & informative:
            postings[term].append(note_id)

    shared = defaultdict(list)
    for term, ids in postings.items():
        weight = math.log(n_notes / df[term])
        ids.sort()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                shared[(ids[i], ids[j])].append((term, weight))

    min_shared = int(cand["min_shared_terms"])
    for (a, b), terms in shared.items():
        if len(terms) < min_shared:
            continue
        total = sum(w for _, w in terms)
        score = round(total / (total + 3.0), 3)
        if score < min_score:
            continue
        top = sorted(terms, key=lambda t: -t[1])[:5]
        seen_names = []
        for term, _ in top:
            name = _best_display(display, term)
            if name.lower() not in {s.lower() for s in seen_names}:
                seen_names.append(name)
        offer(a, b, "contrast", score, f"共享术语：{'、'.join(seen_names)}")

    # 启发式 3：重复笔记探测
    title_notes = defaultdict(set)
    for note in notes:
        for head in note.headings:
            norm = normalize_title(head.title)
            if len(norm) < 5 or norm in generic:
                continue
            title_notes[norm].add(note.file.id)
    for norm, ids in title_notes.items():
        if len(ids) < 3:
            continue
        ids = sorted(ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                offer(
                    ids[i], ids[j], "contrast", min(0.95, 0.5 + 0.08 * len(ids)),
                    f"两篇笔记都含有同名标题（共 {len(ids)} 篇重复），疑似同一门课的不同版本",
                )

    results = sorted(found.values(), key=lambda c: (-c["score"], c["source"], c["target"]))
    return results[: int(cand["max_suggestions"])]


def _best_display(display, key):
    counter = display[key]
    return counter.most_common(1)[0][0] if counter else key


HEADER = """# 候选边 —— 由 `python build.py suggest` 生成，请人工审核
#
#   status: pending    → 不进图（默认）
#   status: accepted   → 进图
#   status: rejected   → 永久忽略（下次 suggest 会保留这个状态，不会重新变成 pending）
#
# 方向说明：
#   prerequisite  source 是 target 的前置（有箭头）
#   derives       source 推导出 target（有箭头）
#   contrast      并列/对比，方向未知（无箭头，虚线）
#
# 改完跑 `python build.py build` 生效。手工新增的边建议写进 annotations.yaml。
"""


def write(cfg, candidates, path=None):
    path = path or os.path.join(cfg["config_dir"], cfg["candidates_file"])
    body = yaml.safe_dump(
        {"candidates": candidates},
        allow_unicode=True,
        sort_keys=False,
        width=200,
        default_flow_style=False,
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(HEADER)
        fh.write(body)
    return path


def load(cfg, path=None):
    path = path or os.path.join(cfg["config_dir"], cfg["candidates_file"])
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        return yaml.safe_load(fh) or {}


def preserved_statuses(cfg):
    """把上一次审核结果保留下来，避免重跑 suggest 把 accepted 打回 pending。"""
    old = load(cfg)
    out = {}
    for item in (old.get("candidates") or []):
        if isinstance(item, dict):
            out[(str(item.get("source")), str(item.get("target")), str(item.get("type")))] = \
                str(item.get("status", "pending"))
    return out
