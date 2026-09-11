import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness_resident"))
import pytest
from datetime import date
from harness.option_shadow_ledger import *
D=date(2026,9,9)
def test_pt_to_et_dst(): assert pt_to_et_minute(D,"06:45")=="09:45:00.000"
def test_pt_to_et_winter(): assert pt_to_et_minute(date(2026,12,10),"06:45")=="09:45:00.000"
def test_minute_boundary_guard():
    with pytest.raises(ValueError): Theta(opener=lambda u:"[]").at_time_quote("SPY","20260911","call",D,"09:30:10.000")
def test_settle_split():
    r=settle(1.00,0.10,1.50,0.10); assert r=={"gross":50.0,"commission":1.3,"slippage":10.0,"net":38.7}
def fake(rows_in, rows_out, exps='[{"expiration":"2026-09-11"},{"expiration":"2026-09-18"}]'):
    calls={"n":0}
    def op(u):
        if "list/expirations" in u: return exps
        calls["n"]+=1; return rows_in if calls["n"]==1 else rows_out
    return Theta(opener=op)
ROW=lambda k,b,a: f'{{"strike":{k},"bid":{b},"ask":{a},"right":"call","expiration":"2026-09-11"}}'
def test_leg_settles_and_logs_hash():
    th=fake(f'[{ROW(99,1,1.1)},{ROW(100,1.0,1.1)},{ROW(101,1,1.1)}]', f'[{ROW(99,1,1)},{ROW(100,1.4,1.6)},{ROW(101,1,1)}]')
    r=settle_leg(th,{"ticker":"SPY","direction":"call","entry_window_pst":"06:45-07:15","exit_window_pst":"12:30-12:55"},D)
    assert r["status"]=="settled" and r["strike"]==100
    assert (r["gross"],r["commission"],r["slippage"],r["net"])==(45.0,1.3,15.0,28.7)
    assert "time_of_day=09%3A45%3A00.000" in th.log[1]["url"] and "time_of_day=15%3A55%3A00.000" in th.log[2]["url"]
    assert all(len(e["sha256"])==64 for e in th.log)
def test_no_chain(): assert settle_leg(fake("[]","[]",exps="[]"),{"ticker":"ZZZZ","direction":"call","entry_window_pst":"06:45-07:15","exit_window_pst":"12:30-12:55"},D)["status"]=="unsettled:no_chain"
def test_exit_before_entry(): assert settle_leg(fake("[]","[]"),{"ticker":"SPY","direction":"call","entry_window_pst":"12:30-12:55","exit_window_pst":"06:45-07:15"},D)["status"]=="rejected:exit_before_entry"
def test_zero_bid_unsettled():
    th=fake(f'[{ROW(99,0,1)},{ROW(100,0,1.1)},{ROW(101,0,1)}]','[]')
    assert settle_leg(th,{"ticker":"SPY","direction":"call","entry_window_pst":"06:45-07:15","exit_window_pst":"12:30-12:55"},D)["status"]=="unsettled:no_quote"
