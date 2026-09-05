import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper.account import PaperAccount, RiskLimits
from paper import engine as E
from paper.audit import audit, format_report
from paper.options_ledger import _open_entries

def test_account_must_be_paper():
    try:
        PaperAccount(mode="live"); assert False, "应拒绝非paper"
    except AssertionError as e:
        assert "paper" in str(e)

def test_broker_execution_hardwired_false():
    assert E.BROKER_EXECUTION is False

def test_position_cap_enforced():
    acc = PaperAccount()
    marks = {"NVDA": 100.0}
    # 想下 50% 仓,超过 20% 上限 → 拒绝并留痕
    rec = E.enter(acc, "NVDA", 100.0, 0.50, "score high", marks)
    assert not rec["allowed"] and "exceeds_cap" in rec["risk_note"]
    assert "NVDA" not in acc.positions
    print("  仓位上限守卫:", rec["risk_note"])

def test_normal_entry_and_stop():
    acc = PaperAccount()
    marks = {"NVDA": 100.0}
    rec = E.enter(acc, "NVDA", 100.0, 0.20, "aether score 67", marks)
    assert rec["allowed"] and "NVDA" in acc.positions
    assert acc.positions["NVDA"].stop_price == 85.0  # 15% 止损
    # 价格跌破止损 → 强制离场
    marks["NVDA"] = 80.0
    stops = E.check_stops(acc, marks)
    assert len(stops) == 1 and stops[0]["reason"] == "stop_loss_hit"
    assert "NVDA" not in acc.positions
    print("  止损执行:", stops[0]["pnl_pct"])

def test_max_positions():
    acc = PaperAccount(risk=RiskLimits(max_positions=2, max_position_pct=0.2, max_total_exposure_pct=0.9))
    marks = {"A":10.,"B":10.,"C":10.}
    E.enter(acc,"A",10.,0.2,"x",marks); E.enter(acc,"B",10.,0.2,"x",marks)
    rec = E.enter(acc,"C",10.,0.2,"x",marks)
    assert not rec["allowed"] and "max_positions" in rec["risk_note"]
    print("  持仓数守卫:", rec["risk_note"])

def test_options_ledger_excludes_closed_entries():
    rows = [
        {"action": "entry", "symbol": "NVDA", "entry_premium": 6.4},
        {"action": "entry", "symbol": "AMD", "entry_premium": 3.2},
        {"action": "exit", "symbol": "NVDA", "exit_premium": 7.1},
    ]
    assert [row["symbol"] for row in _open_entries(rows)] == ["AMD"]

def test_audit_is_behavior_not_return():
    # 模拟一串决策:2进场 1被拒(想冒险) 1止损
    decisions = [
        {"action":"enter","symbol":"A","want_pct":0.2,"allowed":True,"risk_note":"ok","reason":"score"},
        {"action":"enter","symbol":"B","want_pct":0.5,"allowed":False,"risk_note":"position_size_0.50_exceeds_cap_0.2","reason":"greedy"},
        {"action":"enter","symbol":"C","want_pct":0.15,"allowed":True,"risk_note":"ok","reason":"score"},
        {"action":"exit","symbol":"A","pnl":-30,"pnl_pct":-0.15,"reason":"stop_loss_hit"},
    ]
    a = audit(decisions, 1000, 970)
    assert a["verdict_type"] == "behavior_audit_NOT_return"
    assert a["discipline"]["never_all_in"] is True   # 被拒的那笔没进场
    assert a["discipline"]["risk_rejections"] == 1    # 抓到它想冒险一次
    assert a["risk_awareness"]["n_stop_hits"] == 1    # 止损执行了
    print("\n" + format_report(a))


def test_wallet_emit_dedupe_skips_unchanged():
    from unittest.mock import patch
    from paper import emit as em

    em.reset_wallet_emit_cache()
    payload = {
        "lane": "equity",
        "status": "ready",
        "cash": 1000.0,
        "equity": 1000.0,
        "start_equity": 1000.0,
        "return_pct_background": 0.0,
        "exposure_pct": 0.0,
        "positions": [],
        "position_state": "flat",
    }
    with patch.object(em, "emit_aether", return_value=True) as post:
        assert em._emit_paper_wallet_payload(payload) is True
        assert em._emit_paper_wallet_payload(payload) is True
        assert post.call_count == 1


def test_wallet_emit_dedupe_skips_mark_noise():
    from unittest.mock import patch
    from paper import emit as em

    em.reset_wallet_emit_cache()
    base = {
        "lane": "equity",
        "status": "ready",
        "position_state": "held",
        "positions": [{"sym": "NVDA", "qty": 1, "entry": 100.0}],
    }
    with patch.object(em, "emit_aether", return_value=True) as post:
        assert em._emit_paper_wallet_payload({**base, "equity": 1000.0, "cash": 900.0}) is True
        assert em._emit_paper_wallet_payload({**base, "equity": 1000.4, "cash": 899.6}) is True
        assert post.call_count == 1


def test_wallet_emit_force_bypasses_dedupe():
    from unittest.mock import patch
    from paper import emit as em

    em.reset_wallet_emit_cache()
    payload = {
        "lane": "crypto_cli",
        "status": "uninitialized",
        "position_state": "flat",
    }
    with patch.object(em, "emit_aether", return_value=True) as post:
        assert em._emit_paper_wallet_payload(payload) is True
        assert em._emit_paper_wallet_payload(payload, force=True) is True
        assert post.call_count == 2
