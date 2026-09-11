import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness_resident"))
from harness.x402_policy import Policy, X402Policy
TOK="tok"; gate=lambda t,b: t==TOK and b=="m1:pay"
def mk(**kw): return X402Policy(Policy(**kw), gate=gate)
def test_default_denies_everything():
    x=mk(); assert x.authorize("scout",1,"anyone","m1","pay",TOK)[0]=="DENY"
def test_daily_cap_sixth_of_six():
    x=mk(daily_cap={"scout":100},per_tx_cap={"scout":20},payee_whitelist={"p"})
    r=[x.authorize("scout",20,"p","m1","pay",TOK) for _ in range(6)]
    assert [v for v,_ in r]==["ALLOW"]*5+["DENY"] and r[5][1]=="daily_cap"
def test_payee_not_whitelisted():
    x=mk(daily_cap={"scout":100},per_tx_cap={"scout":20},payee_whitelist={"p"})
    assert x.authorize("scout",5,"q","m1","pay",TOK)==("DENY","payee_not_whitelisted")
def test_no_token_denies():
    x=mk(daily_cap={"scout":100},per_tx_cap={"scout":20},payee_whitelist={"p"})
    assert x.authorize("scout",5,"p","m1","pay")==("DENY","no_human_token")
    assert x.authorize("scout",5,"p","m2","pay","tok")==("DENY","token_not_bound")
def test_provenance_chain_replayable():
    x=mk(daily_cap={"scout":100},per_tx_cap={"scout":20},payee_whitelist={"p"})
    for _ in range(3): x.authorize("scout",20,"p","m1","pay",TOK)
    assert len(x.prov.chain)==3 and x.prov.verify()
    x.prov.chain[1]["amount"]=999; assert not x.prov.verify()
