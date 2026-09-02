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

v3(2026-08-26 现场首跑后):USYC 在 Ethereum 的 totalSupply 只有 54.8M 份——我此前写的"预期 ≈3.0B"错了:那是 rwa.xyz 的
跨链合计(Ethereum/BSC/Solana/Sui/Canton;2025-11 上 BSC 后大头在 BSC),不是单链读数。修正:
- 注册表按链分条(USYC 的 Ethereum 与 BSC 地址都来自 Circle 官方文档);每条链用自己的 RPC 对:
  {ETH|BSC}_RPC_URL / {ETH|BSC}_RPC_URL_2;某链 RPC 未设 → 该链整组标 skipped,不装数;
- NAV:oracle latestAnswer 按 oracle decimals() 缩放 → nav_usd;supply_usd_at_nav = 份额 × NAV(USYC NAV ≈ 1.13,非 par);
- 汇总 per-symbol 跨链合计 + 参考值(rwa.xyz 2026-08-17:USYC $2.995B / NAV 1.13 / 36 holders,手填 reference,只用来对照不用来算)。

v4(2026-08-26,Lyra 拍:BNB 免费档只有 Ankr,暂不设第二源):单源链的读数**不是** verified,是 single_source——
- 卡上 confidence = "dual"(双源同区块一致)/ "single"(该链只有主源)/ "unverified"(不一致/第二源故障);
- 汇总分两栏:supply_units_dual 与 supply_units_single 永不混算,合计行两个数字分开印;
- 链级 second_source_policy 从 env 读({PRE}_RPC_SECOND_POLICY=required|optional,默认 required);
  policy=required 而第二源缺 → 该链整组 unverified 并响亮报;policy=optional(BSC 现状)→ single,允许出数但不进 dual 栏。
一句话:单源出的数可以看,不可以当已核实;哪天 BSC 有了第二源,同一份代码自动升 dual,不用改结构。

v5(2026-08-26,Lyra:"NAV 需要装吧"):NAV 是基金属性不是链属性——USYC 只有 Ethereum 有 oracle,v4 里 BSC 那 2.6B 份
因此没有 usd 值,汇总的美元栏等于漏掉大头。修:NAV 按 symbol 解析一次(从带 oracle 的那条链读),再应用到同 symbol 的所有链,
每张卡记 nav_source = {chain, oracle, block, method} —— 跨链套用是显式的、可追的,不是隐式假设。
NAV 缺失时 usd 一律 None(不回退 par、不猜 1.0);NAV 不在 (0.5,5) 区间视为 ABI/缩放不对,同样不装数。
confidence 只描述 supply 的双源状态,NAV 的可信度由 nav_source.confidence 单列(oracle 所在链是 dual 就 dual)。

用法:ETH_RPC_URL=<alchemy> ETH_RPC_URL_2=<quicknode> BSC_RPC_URL=<ankr> python3 rwa_onchain_reader.py [--out dir]
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

CHAINS = {1: "ETH", 56: "BSC"}     # chain_id → env 前缀

DEFAULT_REGISTRY = [
    # USYC(Circle/Hashnote)—— 官方:https://developers.circle.com/tokenized/usyc/smart-contracts(2026-08-26 实读)
    {"symbol": "USYC", "issuer": "Circle (Hashnote)", "chain": "ethereum", "chain_id": 1,
     "address": "0x136471a34f6ef19fE571EFFC1CA711fdb8E49f2b",
     "oracle": "0x74f2199AEb743f68f05943e5715A33EaF2b61f53",
     "source_url": "https://developers.circle.com/tokenized/usyc/smart-contracts", "par_usd": None,
     "reference": {"source": "rwa.xyz 2026-08-17", "total_usd_all_chains": 2995274835, "nav_usd": 1.13, "holders": 36}},
    {"symbol": "USYC", "issuer": "Circle (Hashnote)", "chain": "bsc", "chain_id": 56,
     "address": "0x8D0fA28f221eB5735BC71d3a0Da67EE5bC821311",
     "source_url": "https://developers.circle.com/tokenized/usyc/smart-contracts", "par_usd": None},
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


def _confidence(card: dict, policy: str) -> str:
    """dual = 双源同区块逐位一致;single = 该链按策略只有主源;unverified = 其余(不一致/第二源故障/读不到)。"""
    if not card["verified_symbol"] or card["total_supply"] is None:
        return "unverified"
    ss = card["second_source"] or {}
    if ss.get("match") is True:
        return "dual"
    if ss.get("status") == "absent" and policy == "optional":
        return "single"
    return "unverified"


def read_token(url: str, entry: dict, block: str = "latest", url2: str | None = None, policy: str = "required") -> dict:
    card = {"symbol": entry["symbol"], "issuer": entry.get("issuer"), "chain": entry["chain"], "address": entry.get("address"),
            "source_url": entry.get("source_url"), "verified_symbol": False, "decimals": None, "total_supply": None,
            "supply_units": None, "supply_usd_at_par": None, "nav_usd": None, "supply_usd_at_nav": None,
            "nav_oracle": None, "error": None, "block": block,
            "second_source": {"status": "absent" if not url2 else "pending", "total_supply": None, "match": None},
            "confidence": None,
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
            # NAV oracle:latestAnswer(0x50d25bcd)按 oracle 自己的 decimals(0x313ce567)缩放;任一失败 → null 带原因。
            # v5:此处只读原始 NAV;usd 的计算移到 run() 里按 symbol 统一套用(跨链显式追溯)
            try:
                v = decode_uint(eth_call(url, entry["oracle"], "0x50d25bcd", block))
                od = decode_uint(eth_call(url, entry["oracle"], SEL_DECIMALS, block))
                nav = (v / (10 ** od)) if (v is not None and od is not None) else None
                card["nav_oracle"] = {"address": entry["oracle"], "latestAnswer_raw": v, "decimals": od, "nav_raw_scaled": nav}
                if nav is None or not (0.5 < nav < 5):
                    card["nav_oracle"]["error"] = "NAV=%r 不在 (0.5,5) 合理区间,ABI/缩放待核,不装数" % nav
            except Exception as exc:
                card["nav_oracle"] = {"address": entry["oracle"], "error": str(exc)[:100]}
    except Exception as exc:
        card["error"] = "rpc 读取失败:%s" % str(exc)[:160]
    card["confidence"] = _confidence(card, policy)
    if card["confidence"] == "single" and not card["error"]:
        card["error"] = None
        card["note"] = "单源读数(该链无第二源,policy=optional):可看,不算已核实"
    return card


def run_chain(url: str, entries: list, url2: str | None = None, policy: str = "required") -> dict:
    """单链一轮:primary 定区块,第二源同区块复核;policy=optional 时允许无第二源(卡记 single)。"""
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
    for e in entries:
        if e.get("chain_id") != chain_id:
            skipped.append({"symbol": e["symbol"], "reason": "rpc chainId=%s ≠ 注册表 %s" % (chain_id, e.get("chain_id"))})
            continue
        cards.append(read_token(url, e, block, url2, policy))
    if rpc2_status == "absent" and policy == "required":
        for c in cards:
            c["error"] = (c["error"] or "") + ";该链 second_source_policy=required 但第二源未设 → unverified"
    return {"chain_id": chain_id, "block": block_n, "rpc2_status": rpc2_status, "policy": policy, "cards": cards, "skipped": skipped}


def run(url: str, registry: list, out_dir: str | None, url2: str | None = None, rpc_env: dict | None = None) -> dict:
    """多链:注册表按 chain_id 分组;rpc_env[chain_id] = (primary, second) 或 (primary, second, policy)。
    policy 默认 required;BSC 现状 optional(Lyra 2026-08-26:免费档只有 Ankr)。兼容旧签名:url/url2 = chain_id 1。"""
    rpc_env = dict(rpc_env or {})
    if url:
        rpc_env.setdefault(1, (url, url2))
    groups: dict = {}
    for e in registry:
        groups.setdefault(e.get("chain_id"), []).append(e)
    cards, skipped, chains = [], [], {}
    for cid, entries in groups.items():
        pair = rpc_env.get(cid)
        policy = (pair[2] if pair and len(pair) > 2 and pair[2] else "required")
        if not pair or not pair[0]:
            for e in entries:
                skipped.append({"symbol": e["symbol"], "chain": e.get("chain"), "reason": "chain_id %s 无 RPC(env %s_RPC_URL 未设),整组跳过不装数" % (cid, CHAINS.get(cid, cid))})
            continue
        try:
            r = run_chain(pair[0], entries, pair[1], policy)
        except Exception as exc:
            for e in entries:
                skipped.append({"symbol": e["symbol"], "chain": e.get("chain"), "reason": "chain_id %s primary RPC 失败:%s" % (cid, str(exc)[:100])})
            continue
        chains[str(cid)] = {"block": r["block"], "rpc2_status": r["rpc2_status"], "policy": r["policy"],
                            "confidence": ("dual" if r["rpc2_status"] == "ok" else ("single" if r["policy"] == "optional" else "unverified"))}
        cards += r["cards"]; skipped += r["skipped"]
    # v5:NAV 按 symbol 解析一次(取该 symbol 下 oracle 读数正常的那条链),再套用到同 symbol 所有链的卡
    nav_by_symbol: dict = {}
    for c in cards:
        no = c.get("nav_oracle") or {}
        nav = no.get("nav_raw_scaled")
        if nav is not None and not no.get("error") and 0.5 < nav < 5:
            cur = nav_by_symbol.get(c["symbol"])
            if cur is None or (c["confidence"] == "dual" and cur["confidence"] != "dual"):
                nav_by_symbol[c["symbol"]] = {"nav_usd": round(nav, 6), "chain": c["chain"], "oracle": no.get("address"),
                                              "block": c["block"], "confidence": c["confidence"],
                                              "method": "latestAnswer()/10**decimals()"}
    for c in cards:
        src = nav_by_symbol.get(c["symbol"])
        if not src:
            c["nav_usd"], c["supply_usd_at_nav"] = None, None
            c["nav_source"] = {"status": "absent", "reason": "该 symbol 无可用 NAV oracle 读数,usd 不装数(不回退 par)"}
            continue
        c["nav_usd"] = src["nav_usd"]
        c["nav_source"] = {"status": "same_chain" if src["chain"] == c["chain"] else "cross_chain",
                           "chain": src["chain"], "oracle": src["oracle"], "block": src["block"],
                           "confidence": src["confidence"], "method": src["method"]}
        c["supply_usd_at_nav"] = round(c["supply_units"] * src["nav_usd"], 2) if c["supply_units"] is not None else None
    # per-symbol 跨链汇总(dual/single 两栏永不混算)
    summary = {}
    for c in cards:
        s_ = summary.setdefault(c["symbol"], {"chains": [], "supply_units_dual": 0.0, "usd_at_nav_dual": 0.0,
                                              "supply_units_single": 0.0, "usd_at_nav_single": 0.0, "nav": None, "reference": None})
        s_["chains"].append({"chain": c["chain"], "confidence": c["confidence"], "supply_units": c["supply_units"],
                             "usd_at_nav": c["supply_usd_at_nav"], "nav_source": (c.get("nav_source") or {}).get("status")})
        if s_.get("nav") is None and c.get("nav_usd") is not None:
            s_["nav"] = {"nav_usd": c["nav_usd"], **{k: v for k, v in (c.get("nav_source") or {}).items() if k in ("chain", "oracle", "block", "confidence")}}
        if c["supply_units"] is None:
            continue
        if c["confidence"] == "dual":
            s_["supply_units_dual"] += c["supply_units"]
            s_["usd_at_nav_dual"] += c["supply_usd_at_nav"] or 0.0
        elif c["confidence"] == "single":
            s_["supply_units_single"] += c["supply_units"]
            s_["usd_at_nav_single"] += c["supply_usd_at_nav"] or 0.0
    for e in registry:
        if e.get("reference") and e["symbol"] in summary:
            summary[e["symbol"]]["reference"] = e["reference"]
    doc = {"kind": "rwa_onchain_evidence", "version": 4, "chains": chains,
           "read_ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "cards": cards, "skipped": skipped,
           "summary": summary,
           "n_dual": sum(1 for c in cards if c["confidence"] == "dual"),
           "n_single": sum(1 for c in cards if c["confidence"] == "single"),
           "n_unverified": sum(1 for c in cards if c["confidence"] == "unverified")}
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
    rpc_env = {}
    for cid, pre in CHAINS.items():
        u1, u2 = os.getenv(pre + "_RPC_URL"), os.getenv(pre + "_RPC_URL_2")
        pol = (os.getenv(pre + "_RPC_SECOND_POLICY") or ("optional" if pre == "BSC" else "required")).lower()
        if u1:
            rpc_env[cid] = (u1, u2 or None, pol)
    if not rpc_env:
        sys.exit("未设任何 *_RPC_URL(ETH_RPC_URL / BSC_RPC_URL):出网 RPC 端点由 Lyra 指定,本脚本不内置")
    registry = json.load(open(a.registry, encoding="utf-8")) if a.registry else DEFAULT_REGISTRY
    doc = run(None, registry, a.out, None, rpc_env)
    mark = {"dual": "✓✓", "single": "✓ ", "unverified": "✗ "}
    for c in doc["cards"]:
        print("%-5s %-8s %s supply=%s nav=%s usd@nav=%s %s" % (c["symbol"], c["chain"], mark.get(c["confidence"], "? "),
              c["supply_units"], c["nav_usd"], c["supply_usd_at_nav"], c.get("error") or c.get("note") or ""))
    for s_ in doc["skipped"]:
        print("skip  %-8s %s" % (s_.get("chain", "?"), s_["reason"]))
    for sym, s_ in doc["summary"].items():
        ref = s_.get("reference") or {}
        nv = s_.get("nav") or {}
        print("  NAV %s = %s(源:%s 链 oracle %s @block %s,%s)" % (sym, nv.get("nav_usd"), nv.get("chain"), (nv.get("oracle") or "")[:10], nv.get("block"), nv.get("confidence")))
        print("Σ %s 双源 %.0f 份≈$%.0f | 单源 %.0f 份≈$%.0f(不混算)| 参考 %s:$%s NAV %s" % (
            sym, s_["supply_units_dual"], s_["usd_at_nav_dual"], s_["supply_units_single"], s_["usd_at_nav_single"],
            ref.get("source"), ref.get("total_usd_all_chains"), ref.get("nav_usd")))
    print("chains %s | dual %d · single %d · unverified %d(共 %d 卡)" % (doc["chains"], doc["n_dual"], doc["n_single"], doc["n_unverified"], len(doc["cards"])))


if __name__ == "__main__":
    main()
