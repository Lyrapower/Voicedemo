"""stub RPC 冒烟:symbol 不符作废、无地址拒读、chainId 不符整条跳过、正常读出供应量。"""
from app.crypto_rwa import rwa_onchain_reader as R

def enc_str(s):
    b = s.encode(); return "0x" + (32).to_bytes(32, "big").hex() + len(b).to_bytes(32, "big").hex() + (b + b"\x00" * (32 - len(b) % 32)).hex()
def enc_uint(n): return "0x" + n.to_bytes(32, "big").hex()

CALLS = []
SECOND = {"supply": 3_012_345_678_901_234, "chain": "0x1", "up": True}
def fake_rpc(url, method, params, timeout=20):
    CALLS.append((url, method, params))
    if url == "http://rpc2":
        if not SECOND["up"]: raise RuntimeError("timeout")
        if method == "eth_chainId": return SECOND["chain"]
        if method == "eth_call" and params[0]["data"] == R.SEL_TOTAL_SUPPLY: return enc_uint(SECOND["supply"])
        return "0x"
    if method == "eth_chainId": return "0x1"
    if method == "eth_blockNumber": return hex(23000000)
    to, data = params[0]["to"].lower(), params[0]["data"]
    if to == "0x136471a34f6ef19fe571effc1ca711fdb8e49f2b":
        return {R.SEL_SYMBOL: enc_str("USYC"), R.SEL_DECIMALS: enc_uint(6), R.SEL_TOTAL_SUPPLY: enc_uint(3_012_345_678_901_234)}[data]
    if to == "0x74f2199aeb743f68f05943e5715a33eaf2b61f53":
        return enc_uint(110_123_456)
    if to == "0x00000000000000000000000000000000deadbeef":
        return {R.SEL_SYMBOL: enc_str("WRONG"), R.SEL_DECIMALS: enc_uint(18), R.SEL_TOTAL_SUPPLY: enc_uint(1)}[data]
    raise RuntimeError("unknown")
R.rpc = fake_rpc

def test_rwa_onchain_reader_v2():
    CALLS.clear()
    SECOND["supply"] = 3_012_345_678_901_234
    SECOND["chain"] = "0x1"
    SECOND["up"] = True
    reg = list(R.DEFAULT_REGISTRY) + [{"symbol": "FAKE", "issuer": "x", "chain": "ethereum", "chain_id": 1, "address": "0x00000000000000000000000000000000deadbeef", "source_url": "x", "par_usd": 1.0},
                                       {"symbol": "BASEONLY", "issuer": "x", "chain": "base", "chain_id": 8453, "address": "0x00000000000000000000000000000000deadbeef", "source_url": "x"}]
    doc = R.run("http://stub", reg, None, "http://rpc2")
    by = {c["symbol"]: c for c in doc["cards"]}
    assert doc["chain_id"] == 1 and doc["block"] == 23000000 and doc["rpc2_status"] == "ok"
    assert by["USYC"]["second_source"] == {"status": "ok", "total_supply": 3_012_345_678_901_234, "match": True}
    assert all(p[2][1] == hex(23000000) for p in CALLS if p[1] == "eth_call"), "eth_call 必须钉在同一区块号"
    assert by["USYC"]["verified_symbol"] and by["USYC"]["decimals"] == 6 and by["USYC"]["supply_units"] == 3012345678.9 and by["USYC"]["supply_usd_at_par"] == 3012345678.9
    assert by["USYC"]["nav_oracle"]["latestAnswer_raw"] == 110_123_456
    assert by["BUIDL"]["error"].startswith("注册表无地址") and by["BUIDL"]["total_supply"] is None
    assert not by["FAKE"]["verified_symbol"] and "≠ 注册表" in by["FAKE"]["error"] and by["FAKE"]["total_supply"] is None
    assert doc["skipped"] == [{"symbol": "BASEONLY", "reason": "rpc chainId=1 ≠ 注册表 8453"}]
    assert doc["n_verified"] == 1
    SECOND["supply"] = 3_012_345_678_901_235
    doc2 = R.run("http://stub", reg, None, "http://rpc2"); u2 = {c["symbol"]: c for c in doc2["cards"]}["USYC"]
    assert u2["second_source"]["match"] is False and "不一致" in u2["error"] and doc2["n_verified"] == 0
    SECOND["supply"] = 3_012_345_678_901_234; SECOND["chain"] = "0x2105"
    doc3 = R.run("http://stub", reg, None, "http://rpc2"); assert doc3["rpc2_status"].startswith("chainId mismatch") and doc3["n_verified"] == 0
    SECOND["chain"] = "0x1"; SECOND["up"] = False
    doc4 = R.run("http://stub", reg, None, "http://rpc2"); assert doc4["rpc2_status"].startswith("unreachable") and doc4["n_verified"] == 0
    doc5 = R.run("http://stub", reg, None, None); assert doc5["rpc2_status"] == "absent" and doc5["n_verified"] == 0

if __name__ == "__main__":
    test_rwa_onchain_reader_v2()
    print("✓ v2 双源:同区块一致=verified;不一致/chainId 错/不可达/未设 全部不计 verified 且带原因")
    print("✓ rwa_onchain_reader:USYC 读出 3.01B(小数 6,par 1.0)、无地址拒读、symbol 不符作废、chainId 不符跳过、oracle 原始值记录")
