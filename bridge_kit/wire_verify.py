"""wire_verify — 接线后的只读自证,一条命令,一份报告。不写任何文件。

用法:
  python3 bridge_kit/wire_verify.py --receipts <receipts.jsonl> --stream <Grid 输入流文件> [--jid J-... ...]

判的是:
  A1 receipts.jsonl 里每条收据(有 jid 的)在输入流里都有一条完整行(key=、ingested=)
  A2 输入流里没有重复键
  A3 输入流末尾没有半行
  A4 指定 jid(默认三条真 jid)都在流里
  B1 带 seed_hash/origin 的行,字段能按 parse_row_fields 解析(不是写在 note 里)
每项 PASS/FAIL 带证据;缺文件写 NOT_FOUND。退出码:全 PASS=0,否则 1。
零依赖,3.9 语法。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge_kit import grid_inbound as gi  # noqa: E402
from bridge_kit import h1_job_block as h1  # noqa: E402

DEFAULT_JIDS = ["J-b5050da341d7", "J-dcc3623e086d", "J-0f9f1853fb58"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts", required=True)
    ap.add_argument("--stream", required=True)
    ap.add_argument("--jid", action="append", default=None)
    a = ap.parse_args(argv)
    jids = a.jid or DEFAULT_JIDS
    R = {"verify": "wire_verify v1"}
    ok = True

    if not os.path.exists(a.stream):
        R["stream"] = "NOT_FOUND"
        print(json.dumps(R, ensure_ascii=False, indent=1))
        return 1
    rows = gi.parse_stream(a.stream)
    keys = [h1.parse_row_fields(r).get("key") for r in rows]
    R["stream_rows"] = len(rows)

    raw = open(a.stream, encoding="utf-8").read()
    tail_open = bool(raw) and not raw.endswith("\n")
    R["A3_no_half_line"] = {"result": "FAIL" if tail_open else "PASS", "tail_open": tail_open}
    ok &= not tail_open

    dups = sorted(set(k for k in keys if keys.count(k) > 1))
    R["A2_no_duplicate_keys"] = {"result": "PASS" if not dups else "FAIL", "dups": dups[:10]}
    ok &= not dups

    if os.path.exists(a.receipts):
        want = []
        for rec in gi.iter_receipts_jsonl(a.receipts):
            if rec.get("jid"):
                want.append(gi.receipt_key(rec))
        missing = [k for k in want if k not in keys]
        R["A1_every_receipt_in_stream"] = {"result": "PASS" if not missing else "FAIL",
                                            "receipts": len(want), "missing": missing[:10]}
        ok &= not missing
    else:
        R["A1_every_receipt_in_stream"] = {"result": "NOT_FOUND", "path": a.receipts}
        ok = False

    present = {j: any(("jid=%s " % j) in r or r.endswith("jid=%s" % j) for r in rows) for j in jids}
    R["A4_named_jids_present"] = {"result": "PASS" if all(present.values()) else "FAIL", "present": present}
    ok &= all(present.values())

    bad = []
    n_lineage = 0
    for r in rows:
        f = h1.parse_row_fields(r)
        if "seed_hash" in f or "origin" in f:
            n_lineage += 1
            if len(f.get("seed_hash", "")) != 64 or not f.get("origin"):
                bad.append(r[:120])
    R["B1_lineage_rows_parse"] = {"result": "PASS" if not bad else "FAIL", "lineage_rows": n_lineage, "bad": bad[:5]}
    ok &= not bad

    R["overall"] = "PASS" if ok else "FAIL"
    print(json.dumps(R, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
