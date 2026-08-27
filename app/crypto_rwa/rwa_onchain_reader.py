#!/usr/bin/env python3
"""rwa_onchain_reader.py · v1(2026-08-26,Lyra 拍:RWA 链上读 YES)

用 JSON-RPC eth_call 直读代币化 RWA 的 ERC-20 事实:symbol / decimals / totalSupply(+ 可选 NAV oracle),
写成证据卡(替代此前五张网页标题)。零第三方依赖,零推断:
- 地址只来自官方文档,注册表每条带 source_url;运行期自证:链上 symbol() 必须等于注册表 symbol,不等 = 该条作废并响亮报;
- eth_chainId 必须等于注册表 chain_id(1=Ethereum),不等 = 整轮作废;
- RPC 端点只从 env ETH_RPC_URL 读,不内置任何出网地址(出网链路由 Lyra 定,README 给候选);
- 读不到 = 卡上 null 带原因,不装数。

v2(2026-08-26,Lyra 拍:Alchemy 为 primary ETH_RPC_URL,架构保留独立第二 RPC 复核):
- ETH_RPC_URL(primary)+ ETH_RPC_URL_2(独立提供商);同一区块号上两边 eth_call totalSupply 必须逐位相等,
  相等 → verified_second_source=true;不等/第二源不可达 → false 带原因,卡仍出但 n_verified 不计;第二源未设 → "absent"。
- 两个端点 chainId 都须 = 注册表 chain_id;区块号取 primary 的 latest,第二源按该区块号读(不用 latest,避免高度差)。

用法:ETH_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/<key> ETH_RPC_URL_2=https://... python3 rwa_onchain_reader.py [--registry f.json] [--out dir]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request

SEL_SYMBOL = "0x95d89b41"
SEL_DECIMALS = "0x313ce567"
SEL_TOTAL_SUPPLY = "0x18160ddd"

DEFAULT_REGISTRY = [
    # USYC(Circle/Hashnote)—— 官方:https://developers.circle.com/tokenized/usyc/smart-contracts(2026-08-26 实读)
    {"symbol": "USYC", "issuer": "Circle (Hashnote)", "chain": "ethereum", "chain_id": 1,
     "address": "0x136471a34f6ef19fE571EFFC1CA711fdb8E49f2b",
     "oracle": "0x74f2199AEb743f68f05943e5715A33EaF2b61f53",
     "source_url": "https://developers.circle.com/tokenized/usyc/smart-contracts", "par_usd": 1.0},
    # 下面三条地址待官方文档核实后填(Securitize/Ondo 文档),现在留空 → 读取器拒读并响亮报,不猜
    {"symbol": "BUIDL", "issuer": "BlackRock / Securitize", "chain": "ethereum", "chain_id": 1, "address": None,
     "source_url": "TODO Securitize 官方文档", "par_usd": 1.0},
    {"symbol": "OUSG", "issuer": "Ondo", "chain": "ethereum", "chain_id": 1, "address": None,
     "source_url": "TODO https://github.com/ondoprotocol 部署清单", "par_usd": None},
    {"symbol": "USDY", "issuer": "Ondo", "chain": "ethereum", "chain_id": 1, "address": None,
     "source_url": "TODO https://github.com/ondoprotocol/usdy 部署清单", "par_usd": None},
]


def rpc(url: str, method: str, params: list, timeout: int = 20):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "grid-rwa-reader/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        doc = json.loads(r.read().decode("utf-8"))
    if "error" in doc:
        raise RuntimeError("rpc error: %s" % doc["error"])
    return doc.get("result")


def eth_call(url: str, to: str, selector: str, block: str = "latest") -> str:
    return rpc(url, "eth_call", [{"to": to, "data": selector}, block])


def decode_string(hexdata: str) -> str | None:
    """ABI string 返回;兼容 bytes32 老合约。"""
    if not hexdata or hexdata == "0x":
        return None
    raw = bytes.fromhex(hexdata[2:])
    if len(raw) == 32:                       # bytes32 symbol
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    if len(raw) >= 64:
        off = int.from_bytes(raw[0:32], "big")
        ln = int.from_bytes(raw[off:off + 32], "big")
        return raw[off + 32:off + 32 + ln].decode("utf-8", errors="replace")
    return None


def decode_uint(hexdata: str) -> int | None:
    if not hexdata or hexdata == "0x":
        return None
    return int(hexdata, 16)


def read_token(url: str, entry: dict, block: str = "latest", url2: str | None = None) -> dict:
    card = {"symbol": entry["symbol"], "issuer": entry.get("issuer"), "chain": entry["chain"], "address": entry.get("address"),
            "source_url": entry.get("source_url"), "verified_symbol": False, "decimals": None, "total_supply": None,
            "supply_units": None, "supply_usd_at_par": None, "nav_oracle": None, "error": None, "block": block,
            "second_source": {"status": "absent" if not url2 else "pending", "total_supply": None, "match": None},
            "read_ts": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if not entry.get("address"):
        card["error"] = "注册表无地址(待官方文档核实),拒读不猜"
        return card
    try:
        sym = decode_string(eth_call(url, entry["address"], SEL_SYMBOL, block))
        card["onchain_symbol"] = sym
        if not sym or sym.upper() != entry["symbol"].upper():
            card["error"] = "链上 symbol=%r ≠ 注册表 %r:地址错或非该代币,本条作废" % (sym, entry["symbol"])
            return card
        card["verified_symbol"] = True
        dec = decode_uint(eth_call(url, entry["address"], SEL_DECIMALS, block))
        ts = decode_uint(eth_call(url, entry["address"], SEL_TOTAL_SUPPLY, block))
        card["decimals"], card["total_supply"] = dec, ts
        if url2:
            try:
                ts2 = decode_uint(eth_call(url2, entry["address"], SEL_TOTAL_SUPPLY, block))
                card["second_source"] = {"status": "ok", "total_supply": ts2, "match": (ts2 == ts)}
                if ts2 != ts:
                    card["error"] = "第二源 totalSupply 不一致(同区块 %s):primary=%s rpc2=%s" % (block, ts, ts2)
            except Exception as exc:
                card["second_source"] = {"status": "error", "total_supply": None, "match": None, "error": str(exc)[:120]}
        if dec is not None and ts is not None:
            units = ts / (10 ** dec)
            card["supply_units"] = round(units, 2)
            if entry.get("par_usd"):
                card["supply_usd_at_par"] = round(units * float(entry["par_usd"]), 2)
        if entry.get("oracle"):
            # USYC Oracle:不猜 ABI——只记录地址与一次 latestAnswer 尝试(0x50d25bcd),失败写 null 带原因
            try:
                v = decode_uint(eth_call(url, entry["oracle"], "0x50d25bcd", block))
                card["nav_oracle"] = {"address": entry["oracle"], "latestAnswer_raw": v, "note": "ABI 未核实,原始值仅供对照"}
            except Exception as exc:
                card["nav_oracle"] = {"address": entry["oracle"], "error": str(exc)[:100]}
    except Exception as exc:
        card["error"] = "rpc 读取失败:%s" % str(exc)[:160]
    return card


def run(url: str, registry: list, out_dir: str | None, url2: str | None = None) -> dict:
    chain_id = decode_uint(rpc(url, "eth_chainId", []))
    block_n = decode_uint(rpc(url, "eth_blockNumber", []))
    block = hex(block_n)
    rpc2_status = "absent"
    if url2:
        try:
            cid2 = decode_uint(rpc(url2, "eth_chainId", []))
            rpc2_status = "ok" if cid2 == chain_id else "chainId mismatch(%s≠%s)" % (cid2, chain_id)
            if cid2 != chain_id:
                url2 = None
        except Exception as exc:
            rpc2_status = "unreachable:%s" % str(exc)[:100]; url2 = None
    cards, skipped = [], []
    for e in registry:
        if e.get("chain_id") != chain_id:
            skipped.append({"symbol": e["symbol"], "reason": "rpc chainId=%s ≠ 注册表 %s" % (chain_id, e.get("chain_id"))})
            continue
        cards.append(read_token(url, e, block, url2))
    doc = {"kind": "rwa_onchain_evidence", "version": 2, "chain_id": chain_id, "block": block_n, "rpc2_status": rpc2_status,
           "read_ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "cards": cards, "skipped": skipped,
           "n_verified": sum(1 for c in cards if c["verified_symbol"] and c["total_supply"] is not None and c["second_source"].get("match") is True)}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        p = os.path.join(out_dir, "rwa-onchain-%s.json" % datetime.date.today().isoformat())
        json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        doc["path"] = p
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    url = os.getenv("ETH_RPC_URL")
    if not url:
        sys.exit("ETH_RPC_URL 未设:出网 RPC 端点由 Lyra 指定(primary=Alchemy),本脚本不内置")
    url2 = os.getenv("ETH_RPC_URL_2") or None
    registry = json.load(open(a.registry, encoding="utf-8")) if a.registry else DEFAULT_REGISTRY
    doc = run(url, registry, a.out, url2)
    for c in doc["cards"]:
        print("%-6s %s supply=%s usd@par=%s %s" % (c["symbol"], "✓" if c["verified_symbol"] else "✗", c["supply_units"], c["supply_usd_at_par"], c["error"] or ""))
    print("block %s chain %s rpc2=%s verified(双源一致) %d/%d" % (doc["block"], doc["chain_id"], doc["rpc2_status"], doc["n_verified"], len(doc["cards"])))


if __name__ == "__main__":
    main()
