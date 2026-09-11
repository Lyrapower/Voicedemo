"""h1_job_block — 桥 B:Grid 吐的 ```job 块 → 8630 可投 payload;收据 → 回链到发起块。

Grid 9-08 给的契约:中间表示 = [动作指令]+[边界条件]+[执行资源],缺一项即编译报错回退。
这里只做形状编译与相关性,不做门(门在 8630 gate)。

接线点(戌):
- H1 已有自己的块解析器 → 保留它,把它解出的 dict 交给 compile_job(payload, origin)。
- 本文件的 parse_job_block 只是最小解析器,给 synthetic 自证用;H1 格式若不同,以 H1 为准。
- 8630 收据落地时调用 attach_lineage(receipt, compiled) 把 seed_hash / origin / mission_ref 带上,
  再交 grid_inbound 写输入流;verify_roundtrip 用于终回执自证。
零依赖,3.9 语法。
"""
import hashlib
import re

JOB_FENCE = re.compile(r"```job[ \t]*\n(.*?)\n```", re.DOTALL)

# 三项必填;每项内必含的子键
SHAPE = {
    "action": ("goal",),
    "bounds": ("gate", "budget", "stop"),
    "resources": ("worker", "tools"),
}


class CompileError(ValueError):
    def __init__(self, missing):
        self.missing = list(missing)
        super().__init__("compile error: missing %s" % ",".join(self.missing))


def extract_job_blocks(text):
    return [m.group(1) for m in JOB_FENCE.finditer(text or "")]


def parse_job_block(block_text):
    """最小解析:每行 `a.b: value`;`tools` 逗号分列表。只给 synthetic 用。"""
    out = {}
    for raw in block_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        node = out
        path = k.split(".")
        for p in path[:-1]:
            node = node.setdefault(p, {})
        leaf = path[-1]
        if leaf == "tools":
            v = [t.strip() for t in v.split(",") if t.strip()]
        node[leaf] = v
    return out


def seed_hash_of(block_text):
    return hashlib.sha256(block_text.strip().encode("utf-8")).hexdigest()


def compile_job(payload, origin, block_text=None):
    """payload: dict(H1 解出的或 parse_job_block 解出的)。
    返回 8630 可投 payload;三项缺一抛 CompileError(编译报错回退)。"""
    missing = []
    for sect, keys in SHAPE.items():
        node = payload.get(sect)
        if not isinstance(node, dict):
            missing.append(sect)
            continue
        for k in keys:
            if node.get(k) in (None, "", []):
                missing.append("%s.%s" % (sect, k))
    if payload.get("type") != "MISSION":
        missing.append("type=MISSION")
    if missing:
        raise CompileError(missing)
    text = block_text if block_text is not None else repr(sorted(payload.items()))
    return {
        "type": "MISSION",
        "origin": origin,
        "seed_hash": seed_hash_of(text),
        "action": dict(payload["action"]),
        "bounds": dict(payload["bounds"]),
        "resources": dict(payload["resources"]),
        "status": "proposed",
    }


def attach_lineage(receipt, compiled, mission_ref):
    """收据带上发起块的相关字段。不改收据其他字段。"""
    r = dict(receipt)
    r["seed_hash"] = compiled["seed_hash"]
    r["origin"] = compiled["origin"]
    r["mission_ref"] = mission_ref
    return r


_FIELD = re.compile(r'(?:^|\s)([a-z_]+)=("(?:[^"]*)"|\S+)')


_NOTE = re.compile(r' note="[^"]*"')


def parse_row_fields(receipt_row):
    """note 是不可信数据:先把 note=\"...\" 整段挖掉再解析,里面写 seed_hash=xxx 也不算。"""
    clean = _NOTE.sub("", receipt_row)
    return dict((k, v) for k, v in _FIELD.findall(clean))


def verify_roundtrip(compiled, receipt_row):
    """终回执自证:输入流里那一行能不能对回发起块——按字段解析,不做子串匹配。"""
    f = parse_row_fields(receipt_row)
    return f.get("seed_hash") == compiled["seed_hash"] and f.get("origin") == compiled["origin"]
