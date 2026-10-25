"""payload 列式化编解码（阶段 3.4）。

**目标：不改任何语义，只改传输形状。** payload 里最大的一块是重复的中文 id：
`node.parent` / `node.note`、`edge.s` / `edge.t`、`heading_links.*`、`links[].t` 全都是完整
id 字符串，而 id 本身已经是节点主键 —— 一条边要存两个 id，等于同一串路径重复 2~3 次。
作者库实测：`parent` 398 KB + `note` 238 KB + 边 1322 KB 中的 s/t 大头 + `path`/`domain`
重复值，合计约 1.7 MB / 5.8 MB。

编码后：
    node.parent / node.note / edge.s / edge.t / heading_links.* / links[].t
        → nodes 数组下标（-1 = 空）
    node.domain  → meta.domains 里的下标（名称从 meta.domains[i]["name"] 取）
    edge.type    → meta.edge_types 里的下标
    meta.codec   = "idx1"

解码方（verify.py / web/app.js）在启动时**原地展开回旧形状**，
此后所有既有代码一行不改 —— 列式化只影响体积，不影响任何读 payload 的逻辑。
没有 `meta.codec`（或值不认识）的旧 payload 原样通过，向后兼容。
"""

CODEC = "idx1"

_REF_KEYS = ("s", "t", "source", "from_heading", "heading", "note")


def encode(payload: dict) -> dict:
    """把 payload 原地编码成 idx1 形状，返回同一个 dict。"""
    nodes = payload.get("nodes") or []
    if not nodes:
        return payload
    meta = payload.setdefault("meta", {})
    idx = {n["id"]: i for i, n in enumerate(nodes)}
    domains = [d.get("name") for d in (meta.get("domains") or [])]
    dpos = {name: i for i, name in enumerate(domains) if name is not None}
    types: list[str] = []
    tpos: dict[str, int] = {}

    def ref(value):
        if not isinstance(value, str):
            return value
        i = idx.get(value)
        return i if i is not None else value   # 解析不到就原样保留（防御，不应发生）

    def type_ref(value):
        if not isinstance(value, str):
            return value
        if value not in tpos:
            tpos[value] = len(types)
            types.append(value)
        return tpos[value]

    for n in nodes:
        for key in ("parent", "note"):
            if key in n:
                n[key] = ref(n[key])
        d = n.get("domain")
        if isinstance(d, str) and d in dpos:
            n["domain"] = dpos[d]
        for link in (n.get("links") or []):
            if "t" in link:
                link["t"] = ref(link["t"])

    for e in payload.get("edges") or []:
        for key in ("s", "t"):
            if key in e:
                e[key] = ref(e[key])
        if "type" in e:
            e["type"] = type_ref(e["type"])

    for h in payload.get("heading_links") or []:
        for key in _REF_KEYS:
            if key in h:
                h[key] = ref(h[key])

    meta["edge_types"] = types
    meta["codec"] = CODEC
    return payload


def decode(payload: dict) -> dict:
    """把 idx1 形状原地展开回旧形状；没有 codec 标记时原样返回。"""
    meta = payload.get("meta") or {}
    if meta.get("codec") != CODEC:
        return payload
    nodes = payload.get("nodes") or []
    ids = [n["id"] for n in nodes]
    domains = [d.get("name") for d in (meta.get("domains") or [])]
    types = meta.get("edge_types") or []

    def unref(value):
        if not isinstance(value, int) or isinstance(value, bool):
            return value
        return ids[value] if 0 <= value < len(ids) else None

    def untype(value):
        if not isinstance(value, int) or isinstance(value, bool):
            return value
        return types[value] if 0 <= value < len(types) else None

    for n in nodes:
        for key in ("parent", "note"):
            if key in n:
                n[key] = unref(n[key])
        if isinstance(n.get("domain"), int) and not isinstance(n.get("domain"), bool):
            d = n["domain"]
            n["domain"] = domains[d] if 0 <= d < len(domains) else ""
        for link in (n.get("links") or []):
            if "t" in link:
                link["t"] = unref(link["t"])

    for e in payload.get("edges") or []:
        for key in ("s", "t"):
            if key in e:
                e[key] = unref(e[key])
        if "type" in e:
            e["type"] = untype(e["type"])

    for h in payload.get("heading_links") or []:
        for key in _REF_KEYS:
            if key in h:
                h[key] = unref(h[key])
    return payload
