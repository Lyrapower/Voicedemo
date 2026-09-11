"""grid_inbound — 8630 收据原行 → Grid 输入流(桥 A 的生产侧)。

规矩(不变):
- 只写收据原行。不写 persona、不写"你是"、不写工具表、不写解释。
- 幂等:键 = receipt_id(有则用),否则 jid;键写在行里(key=),重启时从流本身重建已见集——只有一个文件,
  没有"流写了账本没写"的半状态(Astra v4.1 R06)。同键重写 = duplicate,文件不变。
- 时间:at= 收据自带的事件时间(ts/finished_at/completed_at/created_at/time,任一),没有就 at=unknown;
  ingested= 本次写入时刻。两者都按 America/Los_Angeles(PDT/PST 自动),没有 zoneinfo 就报错,不静默退回 UTC(R04)。
- 追加写在 fcntl 排他锁内 + flush + fsync;一行一条,行内无换行。多进程并发追加不交错。
- note 是不可信数据:压平、截断、剥引号;以"你是/You are/system:"开头的整条拒。这是清洗不是注入防护,
  Grid 侧仍把整行当收据数据不当指令(R05)。
- 零依赖,3.9 语法。

接线点(戌):receipts.jsonl 落地那一处 hook,同一处已写 harness-shared;
调用 InboundWriter(stream_path).write(receipt_dict)。
receipt_dict 至少含 jid / tool / status;可选 mid / grade / chars / ts(epoch 秒)/ note / receipt_id / mission_ref / seed_hash。
"""
import fcntl
import json
import os
import re
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # 3.8 及以下
    ZoneInfo = None

TZ_NAME = "America/Los_Angeles"
_PERSONA_PREFIX = re.compile(r"^\s*(you are|你是|system:)", re.IGNORECASE)
_WS = re.compile(r"[\r\n\t]+")
_KEY_IN_ROW = re.compile(r"(?:^|\s)key=(\S+)")
_COMPLETE = re.compile(r"\singested=\S+")  # ingested= 是每行最后一个必带字段:没有它的行是半行/杂行
REQUIRED = ("jid", "tool", "status")


class InboundError(ValueError):
    pass


def _tz():
    if ZoneInfo is None:
        raise InboundError("zoneinfo unavailable: refuse to write time without %s" % TZ_NAME)
    return ZoneInfo(TZ_NAME)


def local_iso(ts=None):
    """epoch 秒 → America/Los_Angeles ISO 字符串(带 -07:00 / -08:00)。"""
    tz = _tz()
    if ts is None:
        dt = datetime.now(tz)
    else:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(tz)
    return dt.replace(microsecond=0).isoformat()


def receipt_key(receipt):
    rid = receipt.get("receipt_id")
    if rid:
        return "r:%s" % rid
    return "j:%s" % receipt["jid"]


def format_receipt_row(receipt):
    """一条收据 → 一行原文。缺必填即报错。"""
    for k in REQUIRED:
        if not receipt.get(k):
            raise InboundError("receipt missing %s" % k)
    parts = ["[harness]"]
    parts.append("key=%s" % receipt_key(receipt))
    parts.append("jid=%s" % receipt["jid"])
    parts.append("mid=%s" % (receipt.get("mid") or receipt.get("mission_ref") or "-"))
    parts.append("tool=%s" % receipt["tool"])
    parts.append("status=%s" % receipt["status"])
    for k in ("grade", "chars", "lane", "worker", "seed_hash", "origin"):
        v = receipt.get(k)
        if v not in (None, ""):
            parts.append("%s=%s" % (k, v))
    note = receipt.get("note")
    if note:
        note = _WS.sub(" ", str(note)).strip()
        if _PERSONA_PREFIX.match(note):
            raise InboundError("note looks like persona/system text; refused")
        parts.append('note="%s"' % note.replace('"', "'")[:300])
    ts = None
    for k in ("ts", "finished_at", "completed_at", "created_at", "time"):
        if receipt.get(k) not in (None, ""):
            ts = receipt[k]
            break
    parts.append("at=%s" % ("unknown" if ts is None else local_iso(ts)))
    parts.append("ingested=%s" % local_iso(None))  # 完整性标志:半行不会有它
    row = " ".join(parts)
    if "\n" in row or "\r" in row:
        raise InboundError("row contains newline")
    return row


class InboundWriter(object):
    """单文件。已见键从流本身重建;追加在排他锁内。"""

    def __init__(self, stream_path):
        self.stream_path = stream_path
        self._seen = set()
        self._reload()

    def _reload(self):
        """只有以换行结尾的完整行算收据;末尾没换行的半行是崩溃残留,不算已见。"""
        self._seen = set()
        self._tail_open = False
        if os.path.exists(self.stream_path):
            with open(self.stream_path, "r", encoding="utf-8") as f:
                raw = f.read()
            if raw and not raw.endswith("\n"):
                self._tail_open = True
                raw = raw[:raw.rfind("\n") + 1] if "\n" in raw else ""
            for line in raw.splitlines():
                m = _KEY_IN_ROW.search(line)
                if m and _COMPLETE.search(line):
                    self._seen.add(m.group(1))

    def write(self, receipt):
        """返回 'written' 或 'duplicate'。坏收据抛 InboundError,文件不动。"""
        row = format_receipt_row(receipt)  # 先校验,再看幂等
        key = receipt_key(receipt)
        if key in self._seen:
            return "duplicate"
        with open(self.stream_path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                self._reload()  # 锁内重读:别的进程可能刚写了同键
                if key in self._seen:
                    return "duplicate"
                if self._tail_open:
                    f.write("\n")  # 先把半行封住,新行不与它粘连
                f.write(row + "\n")
                f.flush()
                os.fsync(f.fileno())
                self._seen.add(key)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return "written"

    def backfill(self, receipts):
        """回填。返回 {'written': n, 'duplicate': n, 'rejected': n}。单条坏收据不拖累其余。"""
        out = {"written": 0, "duplicate": 0, "rejected": 0}
        for r in receipts:
            try:
                out[self.write(r)] += 1
            except InboundError:
                out["rejected"] += 1
        return out


def parse_stream(path):
    """读输入流:只回完整行(以换行结尾且含 key=),半行/杂行不回。"""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    if raw and not raw.endswith("\n"):
        raw = raw[:raw.rfind("\n") + 1] if "\n" in raw else ""
    for line in raw.splitlines():
        if _KEY_IN_ROW.search(line) and _COMPLETE.search(line):
            out.append(line)
    return out


def iter_receipts_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"_bad_line": line}


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("usage: grid_inbound.py <receipts.jsonl> <grid_input_stream.txt>")
        sys.exit(2)
    w = InboundWriter(sys.argv[2])
    print(json.dumps(w.backfill(iter_receipts_jsonl(sys.argv[1]))))
