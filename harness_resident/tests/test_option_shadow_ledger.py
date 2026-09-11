import copy
import json
import unittest
from datetime import date
from urllib.parse import parse_qs, urlsplit
from harness.option_shadow_ledger import Theta, ThetaError, pt_to_et_minute, mid, settle, settle_leg
D=date(2026,9,9)
LEG=dict(ticker='SPY',direction='call',strike='100',expiration='2026-09-11',entry_window_pst='06:45-07:15',exit_window_pst='12:30-12:55')


def row(tod,bid,ask):
    return dict(symbol='SPY',expiration='2026-09-11',strike=100,right='call',
                timestamp='2026-09-09T'+tod,bid=bid,ask=ask,bid_size=10,ask_size=10)


def fake(*, entry=None, exit_=None, calendar=None, exps=None):
    entry=[row('09:45:00.000',1,1.1)] if entry is None else entry
    exit_=[row('15:55:00.000',1.4,1.6)] if exit_ is None else exit_
    def op(url):
        if '/calendar/' in url:
            return json.dumps([calendar or dict(type='open',open='09:30:00',close='16:00:00')])
        if '/list/' in url:
            return json.dumps([dict(symbol='SPY',expiration='2026-09-11')] if exps is None else exps)
        q=parse_qs(urlsplit(url).query)
        return json.dumps(entry if q['time_of_day']==['09:45:00.000'] else exit_)
    return Theta(opener=op)


class OptionTests(unittest.TestCase):
    def test_dst(self): self.assertEqual(pt_to_et_minute(D,'06:45'),'09:45:00.000')
    def test_winter(self): self.assertEqual(pt_to_et_minute(date(2026,12,10),'06:45'),'09:45:00.000')
    def test_strict_time(self):
        for v in ('6:45','06:45:00','24:00','06:60','00:00\n'):
            with self.subTest(v=v), self.assertRaises(ValueError): pt_to_et_minute(D,v)
    def test_cross_date(self):
        with self.assertRaises(ValueError): pt_to_et_minute(D,'23:00')
    def test_minute_guard(self):
        with self.assertRaises(ValueError): Theta().at_time_quote('SPY','20260911','call',D,'09:30:10.000',strike=100)
    def test_settle_split(self): self.assertEqual(settle(1,.1,1.5,.1),dict(gross=50,commission=1.3,slippage=10,net=38.7))
    def test_settle_bad_inputs(self):
        for q in (float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError): settle(q,.1,1,.1)
        with self.assertRaises(ValueError): settle(1,.1,1,.1,contracts=True)
    def test_crossed_quote(self): self.assertEqual(mid({'bid':2,'ask':1}),(None,None))
    def test_bad_quotes(self):
        for value in (0,-1,float('nan'),float('inf'),None): self.assertEqual(mid({'bid':value,'ask':1}),(None,None))
    def test_same_contract_settles(self):
        th=fake(); r=settle_leg(th,LEG,D)
        self.assertEqual(r['status'],'settled')
        self.assertEqual((r['gross'],r['commission'],r['slippage'],r['net']),(45,1.3,15,28.7))
        calls=[parse_qs(urlsplit(e['url']).query) for e in th.log if '/at_time/' in e['url']]
        self.assertEqual([c['strike'] for c in calls],[['100'],['100']])
        self.assertFalse(any('strike_range' in c for c in calls))
        self.assertEqual(calls[1]['time_of_day'],['15:55:00.000'])
        self.assertTrue(all(len(e['sha256'])==64 for e in r['data_receipts']))
        self.assertTrue(r['estimate_only']); self.assertFalse(r['live_execution'])
    def test_explicit_contract_required(self):
        leg=dict(LEG); del leg['strike']
        th=fake(); self.assertEqual(settle_leg(th,leg,D)['status'],'unsettled:contract_not_selected')
        self.assertEqual(th.log,[])
    def test_no_chain(self): self.assertEqual(settle_leg(fake(exps=[]),LEG,D)['status'],'unsettled:no_chain')
    def test_missing_expiration(self):
        self.assertEqual(settle_leg(fake(),dict(LEG,expiration='2026-09-18'),D)['status'],'unsettled:no_expiration')
    def test_mixed_date_format(self): self.assertEqual(settle_leg(fake(),dict(LEG,expiration='20260911'),D)['status'],'settled')
    def test_exit_before_entry(self):
        self.assertEqual(settle_leg(fake(),dict(LEG,exit_window_pst='06:00-06:30'),D)['status'],'rejected:exit_before_entry')
    def test_reverse_window(self):
        self.assertEqual(settle_leg(fake(),dict(LEG,entry_window_pst='07:15-06:45'),D)['status'],'rejected:invalid_leg')
    def test_holiday(self):
        self.assertEqual(settle_leg(fake(calendar={'type':'full_close'}),LEG,D)['status'],'unsettled:market_closed')
    def test_early_close(self):
        self.assertEqual(settle_leg(fake(calendar=dict(type='early_close',open='09:30:00',close='13:00:00')),LEG,D)['status'],'unsettled:outside_session')
    def test_stale_or_future_quote(self):
        for t in ('09:43:00.000','09:45:00.001'):
            with self.subTest(t=t): self.assertEqual(settle_leg(fake(entry=[row(t,1,1.1)]),LEG,D)['status'],'unsettled:no_valid_quote')
    def test_wrong_day(self):
        r=row('09:45:00.000',1,1.1); r['timestamp']='2026-09-08T09:45:00.000'
        self.assertEqual(settle_leg(fake(entry=[r]),LEG,D)['status'],'unsettled:no_valid_quote')
    def test_identity_mismatch(self):
        for key,value in [('symbol','QQQ'),('expiration','2026-09-18'),('right','put'),('strike',101)]:
            r=row('09:45:00.000',1,1.1); r[key]=value
            with self.subTest(key=key): self.assertEqual(settle_leg(fake(entry=[r]),LEG,D)['status'],'unsettled:no_valid_quote')
    def test_duplicate_quote(self):
        r=row('09:45:00.000',1,1.1)
        self.assertEqual(settle_leg(fake(entry=[r,r]),LEG,D)['status'],'unsettled:no_valid_quote')
    def test_missing_timestamp_or_size(self):
        for key in ('timestamp','bid_size'):
            r=row('09:45:00.000',1,1.1); del r[key]
            self.assertEqual(settle_leg(fake(entry=[r]),LEG,D)['status'],'unsettled:no_valid_quote')
    def test_insufficient_size(self):
        self.assertEqual(settle_leg(fake(),dict(LEG,contracts=11),D)['status'],'unsettled:no_valid_quote')
    def test_short_unsupported(self):
        self.assertEqual(settle_leg(fake(),dict(LEG,position='short'),D)['status'],'rejected:unsupported_position_or_multiplier')
    def test_payload_schema_error(self):
        for payload in ('{"error":"subscription"}', '[NaN]', '<html>error</html>', ''):
            with self.subTest(payload=payload): self.assertEqual(settle_leg(Theta(opener=lambda u:payload),LEG,D)['status'],'unsettled:schema_error')
    def test_response_limit(self):
        th=Theta(opener=lambda u:' '*2_000_001)
        self.assertEqual(settle_leg(th,LEG,D)['status'],'unsettled:response_too_large_or_invalid')
    def test_failed_request_receipt(self):
        def down(u): raise ConnectionRefusedError()
        th=Theta(opener=down)
        self.assertEqual(settle_leg(th,LEG,D)['status'],'unsettled:theta_down')
        self.assertEqual(th.log[0]['status'],'theta_down')
    def test_remote_base_refused(self):
        for base in ('http://evil.example','http://user:pw@127.0.0.1:25503','http://127.0.0.1:25503/api','https://127.0.0.1'):
            with self.assertRaises(ValueError): Theta(base)
