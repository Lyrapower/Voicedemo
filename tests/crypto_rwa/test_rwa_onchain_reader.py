"""stub RPC 冒烟(v5):NAV 按 symbol 跨链显式套用;BSC optional 单源不进 dual 栏。"""
from app.crypto_rwa import rwa_onchain_reader as R

def enc_str(s):
    b = s.encode(); return "0x" + (32).to_bytes(32, "big").hex() + len(b).to_bytes(32, "big").hex() + (b + b"\x00" * (32 - len(b) % 32)).hex()
def enc_uint(n): return "0x" + n.to_bytes(32, "big").hex()

ETH_USYC = "0x136471a34f6ef19fe571effc1ca711fdb8e49f2b"
BSC_USYC = "0x8d0fa28f221eb5735bc71d3a0da67ee5bc821311"
ORACLE = "0x74f2199aeb743f68f05943e5715a33eaf2b61f53"
STATE = {"eth_supply": 54_848_168_000_000, "bsc_supply": 2_600_000_000_000_000, "bsc2_supply": 2_600_000_000_000_000, "nav_raw": 1_130_000, "nav_dec": 6}
CALLS = []
def fake_rpc(url, method, params, timeout=20):
    CALLS.append((url, method, params))
    chain = "0x1" if url.startswith("http://eth") else ("0x38" if url.startswith("http://bsc") else "0x0")
    if method == "eth_chainId": return chain
    if method == "eth_blockNumber": return hex(25843230 if chain == "0x1" else 60000000)
    to, data = params[0]["to"].lower(), params[0]["data"]
    if to == ETH_USYC:
        return {R.SEL_SYMBOL: enc_str("USYC"), R.SEL_DECIMALS: enc_uint(6), R.SEL_TOTAL_SUPPLY: enc_uint(STATE["eth_supply"])}[data]
    if to == BSC_USYC:
        sup = STATE["bsc2_supply"] if url == "http://bsc2" else STATE["bsc_supply"]
        return {R.SEL_SYMBOL: enc_str("USYC"), R.SEL_DECIMALS: enc_uint(6), R.SEL_TOTAL_SUPPLY: enc_uint(sup)}[data]
    if to == ORACLE:
        return {"0x50d25bcd": enc_uint(STATE["nav_raw"]), R.SEL_DECIMALS: enc_uint(STATE["nav_dec"])}[data]
    if to == "0x00000000000000000000000000000000deadbeef":
        return {R.SEL_SYMBOL: enc_str("WRONG"), R.SEL_DECIMALS: enc_uint(18), R.SEL_TOTAL_SUPPLY: enc_uint(1)}[data]
    raise RuntimeError("unknown " + to)
R.rpc = fake_rpc

def test_rwa_onchain_reader_v5():
    CALLS.clear()
    STATE["bsc2_supply"] = 2_600_000_000_000_000
    STATE["nav_dec"] = 6
    reg = list(R.DEFAULT_REGISTRY) + [{"symbol": "FAKE", "issuer": "x", "chain": "ethereum", "chain_id": 1, "address": "0x00000000000000000000000000000000deadbeef", "source_url": "x"},
                                       {"symbol": "SOLX", "issuer": "x", "chain": "solana", "chain_id": 900, "address": "abc", "source_url": "x"}]
    env = {1: ("http://eth1", "http://eth2", "required"), 56: ("http://bsc1", "http://bsc2", "optional")}
    doc = R.run(None, reg, None, None, env)
    by = {(c["symbol"], c["chain"]): c for c in doc["cards"]}
    u_eth, u_bsc = by[("USYC", "ethereum")], by[("USYC", "bsc")]
    assert u_eth["verified_symbol"] and u_eth["supply_units"] == 54848168.0 and u_eth["second_source"]["match"] is True
    assert u_eth["nav_usd"] == 1.13 and u_eth["supply_usd_at_nav"] == round(54848168.0 * 1.13, 2), u_eth
    assert u_bsc["verified_symbol"] and u_bsc["supply_units"] == 2_600_000_000.0 and u_bsc["second_source"]["match"] is True
    assert u_bsc["nav_usd"] == 1.13 and u_bsc["supply_usd_at_nav"] == round(2_600_000_000.0 * 1.13, 2)
    assert u_bsc["nav_source"]["status"] == "cross_chain" and u_bsc["nav_source"]["chain"] == "ethereum" and u_bsc["nav_source"]["confidence"] == "dual"
    assert u_eth["nav_source"]["status"] == "same_chain"
    assert doc["summary"]["USYC"]["usd_at_nav_dual"] == round(54848168.0 * 1.13, 2) + round(2_600_000_000.0 * 1.13, 2)
    assert doc["summary"]["USYC"]["nav"]["nav_usd"] == 1.13 and doc["summary"]["USYC"]["nav"]["chain"] == "ethereum"
    assert all(p[2][1] in (hex(25843230), hex(60000000)) for p in CALLS if p[1] == "eth_call")
    assert doc["summary"]["USYC"]["supply_units_dual"] == 54848168.0 + 2_600_000_000.0 and doc["summary"]["USYC"]["reference"]["total_usd_all_chains"] == 2995274835
    assert by[("BUIDL", "ethereum")]["error"].startswith("注册表无地址") and not by[("FAKE", "ethereum")]["verified_symbol"]
    assert any(s["symbol"] == "SOLX" and "无 RPC" in s["reason"] for s in doc["skipped"])
    assert doc["n_dual"] == 2 and doc["chains"]["1"]["confidence"] == "dual" and doc["chains"]["56"]["confidence"] == "dual"
    assert u_eth["confidence"] == "dual" and u_bsc["confidence"] == "dual"
    env_ank = {1: ("http://eth1", "http://eth2", "required"), 56: ("http://bsc1", None, "optional")}
    d_a = R.run(None, reg, None, None, env_ank)
    by_a = {(c["symbol"], c["chain"]): c for c in d_a["cards"]}
    b_a = by_a[("USYC", "bsc")]
    assert b_a["confidence"] == "single" and b_a["supply_units"] == 2_600_000_000.0 and "不算已核实" in b_a["note"]
    assert d_a["n_dual"] == 1 and d_a["n_single"] == 1
    sm = d_a["summary"]["USYC"]
    assert sm["supply_units_dual"] == 54848168.0 and sm["supply_units_single"] == 2_600_000_000.0, sm
    assert d_a["chains"]["56"] == {"block": 60000000, "rpc2_status": "absent", "policy": "optional", "confidence": "single"}
    env_req = {1: ("http://eth1", None, "required")}
    d_r = R.run(None, reg, None, None, env_req)
    e_r = {(c["symbol"], c["chain"]): c for c in d_r["cards"]}[("USYC", "ethereum")]
    assert e_r["confidence"] == "unverified" and "policy=required" in e_r["error"] and d_r["n_dual"] == 0
    STATE["bsc2_supply"] += 1
    doc2 = R.run(None, reg, None, None, env)
    assert doc2["n_dual"] == 1 and doc2["n_unverified"] >= 1 and doc2["summary"]["USYC"]["supply_units_dual"] == 54848168.0 and doc2["summary"]["USYC"]["supply_units_single"] == 0.0
    STATE["bsc2_supply"] -= 1
    STATE["nav_dec"] = 2
    doc3 = R.run(None, reg, None, None, env)
    c3 = {(c["symbol"], c["chain"]): c for c in doc3["cards"]}
    u3, b3 = c3[("USYC", "ethereum")], c3[("USYC", "bsc")]
    assert u3["nav_usd"] is None and "合理区间" in u3["nav_oracle"]["error"] and u3["supply_usd_at_nav"] is None
    assert b3["nav_usd"] is None and b3["nav_source"]["status"] == "absent" and "不回退 par" in b3["nav_source"]["reason"]
    assert doc3["summary"]["USYC"]["usd_at_nav_dual"] == 0.0 and doc3["summary"]["USYC"]["supply_units_dual"] > 0
    STATE["nav_dec"] = 6
    doc4 = R.run(None, reg, None, None, {1: ("http://eth1", "http://eth2", "required")})
    assert any(s["chain"] == "bsc" and "整组跳过" in s["reason"] for s in doc4["skipped"]) and doc4["n_dual"] == 1


def test_phase2_evidence_grade_mapping():
    """Phase 2:confidence → §八 等级梯映射。dual=witnesses_agree(商业 RPC 双源,非自建节点);single=witness_only;unverified=unverified。"""
    CALLS.clear()
    STATE["bsc2_supply"] = 2_600_000_000_000_000
    reg = list(R.DEFAULT_REGISTRY)
    env = {1: ("http://eth1", "http://eth2", "required"), 56: ("http://bsc1", "http://bsc2", "optional")}
    doc = R.run(None, reg, None, None, env)
    by = {(c["symbol"], c["chain"]): c for c in doc["cards"]}
    assert by[("USYC", "ethereum")]["evidence_grade"] == "witnesses_agree", by[("USYC", "ethereum")]
    assert by[("USYC", "bsc")]["evidence_grade"] == "witnesses_agree"
    # BUIDL 无地址 → unverified
    assert by[("BUIDL", "ethereum")]["evidence_grade"] == "unverified"
    # 单源 BSC → witness_only
    env_single = {1: ("http://eth1", "http://eth2", "required"), 56: ("http://bsc1", None, "optional")}
    d_s = R.run(None, reg, None, None, env_single)
    b_s = {(c["symbol"], c["chain"]): c for c in d_s["cards"]}[("USYC", "bsc")]
    assert b_s["evidence_grade"] == "witness_only", b_s
    # required 无第二源 → unverified
    env_req = {1: ("http://eth1", None, "required")}
    d_r = R.run(None, reg, None, None, env_req)
    e_r = {(c["symbol"], c["chain"]): c for c in d_r["cards"]}[("USYC", "ethereum")]
    assert e_r["evidence_grade"] == "unverified", e_r


def test_phase1_emit_provenance_receipt():
    """Phase 1:emit_provenance=True → 产 FactualReceipt 写 provenance.jsonl,verify_chain PASS,带 evidence_grade。"""
    import os
    import tempfile
    from app.harness import provenance
    CALLS.clear()
    STATE["bsc2_supply"] = 2_600_000_000_000_000
    reg = list(R.DEFAULT_REGISTRY)
    env = {1: ("http://eth1", "http://eth2", "required"), 56: ("http://bsc1", "http://bsc2", "optional")}
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
    tmp.close()
    old = os.environ.get("HARNESS_PROVENANCE_LOG")
    os.environ["HARNESS_PROVENANCE_LOG"] = tmp.name
    try:
        doc = R.run(None, reg, None, None, env, emit_provenance=True)
        ev = provenance.read_events()
        assert len(ev) >= 1, "provenance 未写入"
        receipt_ev = [e for e in ev if e.get("kind") == "receipt"][0]
        assert receipt_ev["status"] == "EXECUTED"
        assert receipt_ev["evidence_grade"] in R.GRADE_ORDER, receipt_ev
        # 聚合等级 = 最低可信(有 BUIDL unverified → aggregate = unverified)
        assert receipt_ev["evidence_grade"] == "unverified", receipt_ev
        assert provenance.verify_chain(ev), "provenance hash 链断裂"
        # 不带 emit_provenance → 不写
        n_before = len(provenance.read_events())
        R.run(None, reg, None, None, env, emit_provenance=False)
        assert len(provenance.read_events()) == n_before, "emit_provenance=False 仍写了 provenance"
    finally:
        if old is None:
            os.environ.pop("HARNESS_PROVENANCE_LOG", None)
        else:
            os.environ["HARNESS_PROVENANCE_LOG"] = old
        os.unlink(tmp.name)


def test_phase1_emit_provenance_grade_monotone_descent():
    """Phase 1+3 联动:同一 action 重复 emit,等级只降不升;对账层严格降。"""
    import os
    import tempfile
    from app.harness import provenance
    from app.harness.action_envelope import FactualReceipt
    CALLS.clear()
    STATE["bsc2_supply"] = 2_600_000_000_000_000
    reg = list(R.DEFAULT_REGISTRY)
    env = {1: ("http://eth1", "http://eth2", "required"), 56: ("http://bsc1", "http://bsc2", "optional")}
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
    tmp.close()
    old = os.environ.get("HARNESS_PROVENANCE_LOG")
    os.environ["HARNESS_PROVENANCE_LOG"] = tmp.name
    try:
        R.run(None, reg, None, None, env, emit_provenance=True)  # 首次 emit
        ev1 = provenance.read_events()
        action_id = [e for e in ev1 if e.get("kind") == "receipt"][0]["event_id"]
        mission_id = [e for e in ev1 if e.get("kind") == "receipt"][0]["mission_id"]
        # 升级 receipt(同 action,grade 从 unverified 升到 attested)→ 拒(处决案②)
        r_up = FactualReceipt(mission_id=mission_id, action_id=action_id, status="EXECUTED", executed=True,
                             metadata={"evidence_grade": "attested"})
        raised = False
        try:
            provenance.record_receipt(r_up)
        except ValueError:
            raised = True
        assert raised, "升级 receipt 应被拒(§八 ②)"
        # 降级 receipt(同 action,unverified → 已是最低,再写同 grade 一般允许)
        r_same = FactualReceipt(mission_id=mission_id, action_id=action_id, status="EXECUTED", executed=True,
                               metadata={"evidence_grade": "unverified"})
        provenance.record_receipt(r_same)  # 相同 grade,一般 receipt 允许
        assert provenance.verify_chain(provenance.read_events())
    finally:
        if old is None:
            os.environ.pop("HARNESS_PROVENANCE_LOG", None)
        else:
            os.environ["HARNESS_PROVENANCE_LOG"] = old
        os.unlink(tmp.name)

if __name__ == "__main__":
    test_rwa_onchain_reader_v5()
    print("✓ v5:ETH 54.8M×NAV1.13≈$62M、BSC 2.6B 各自双源同区块一致,跨链汇总带 rwa.xyz 参考;NAV 按 symbol 解析并跨链显式套用(BSC 2.6B 现在有美元值,来源标 cross_chain);BSC 单源(Ankr)=single 不混进双源栏、required 无第二源=unverified、不一致/NAV 离谱/无链 RPC 全部不装数")
    test_phase2_evidence_grade_mapping()
    print("✓ phase2:confidence→§八等级梯映射(dual=witnesses_agree / single=witness_only / unverified=unverified)")
    test_phase1_emit_provenance_receipt()
    print("✓ phase1:emit_provenance=True 产 FactualReceipt 写 provenance.jsonl,verify_chain PASS,带 evidence_grade")
    test_phase1_emit_provenance_grade_monotone_descent()
    print("✓ phase1+3:同 action 重复 emit 等级只降不升,升级被拒")

