import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from harness.x402_policy import Policy, X402Policy


def valid_gate(token, context):
    return token == 'fixture-token' and context['mission'] == 'm1' and context['action'] == 'pay'


def attempt(path, rid):
    p = Policy(daily_cap={'a': 100}, per_tx_cap={'a': 20}, payee_whitelist={'p'})
    return X402Policy(p, gate=valid_gate, state_path=path).authorize('a', 20, 'p', 'm1', 'pay', 'fixture-token', request_id=rid)


def crash_after_commit(path):
    attempt(path, 'lost-response')
    os._exit(78)


def crash_transaction(path):
    db = sqlite3.connect(path)
    db.execute('BEGIN IMMEDIATE')
    db.execute("INSERT INTO budget VALUES('a','2099-01-01','USD',999999)")
    os._exit(77)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'state.sqlite')
        self.policy = Policy(daily_cap={'a':100}, per_tx_cap={'a':20}, payee_whitelist={'p'})
        self.x = X402Policy(self.policy, gate=valid_gate, state_path=self.path)
    def auth(self, **kw):
        args = dict(agent='a', amount=20, payee='p', mission='m1', action='pay', human_token='fixture-token', request_id='r1')
        args.update(kw)
        return self.x.authorize(**args)
    def test_default_deny(self):
        x = X402Policy(Policy(), gate=valid_gate, state_path=self.path)
        self.assertEqual(x.authorize('a',1,'p','m1','pay','fixture-token',request_id='d')[0], 'DENY')
    def test_requires_durable_state(self):
        self.assertEqual(X402Policy(self.policy, gate=valid_gate).authorize('a',1,'p','m1','pay','x')[1], 'durable_state_required')
    def test_missing_gate(self):
        self.x.gate = None
        self.assertEqual(self.auth()[1], 'gate_required')
    def test_missing_token(self): self.assertEqual(self.auth(human_token=None)[1], 'no_human_token')
    def test_bad_bound_token(self): self.assertEqual(self.auth(mission='other')[1], 'token_not_bound')
    def test_full_binding_context(self):
        captured = []
        self.x.gate = lambda t,c: captured.append(c) or True
        self.auth()
        self.assertEqual(set(captured[0]), {'agent','amount_units','currency','payee','mission','action','request_id'})
        self.assertEqual(captured[0]['amount_units'], 20_000_000)
    def test_truthy_not_true(self):
        self.x.gate = lambda *a: 'yes'
        self.assertEqual(self.auth()[1], 'token_not_bound')
    def test_gate_exception(self):
        def bad(*args): raise RuntimeError('secret')
        self.x.gate = bad
        self.assertEqual(self.auth()[1], 'gate_error')
    def test_bad_amounts(self):
        for i,v in enumerate((float('nan'), float('inf'), True, -1, 0, '0.0000001', '1e-999999999', [], None)):
            with self.subTest(v=v): self.assertEqual(self.auth(amount=v,request_id=str(i))[0], 'DENY')
    def test_daily_sixth(self):
        rows = [self.auth(request_id=str(i))[0] for i in range(6)]
        self.assertEqual(rows, ['ALLOW']*5+['DENY'])
    def test_decimal_exact(self):
        self.policy.daily_cap={'a':'0.3'}; self.policy.per_tx_cap={'a':'0.1'}
        self.assertEqual([self.auth(amount='0.1',request_id=str(i))[0] for i in range(4)], ['ALLOW']*3+['DENY'])
    def test_restart(self):
        for i in range(5): self.auth(request_id=str(i))
        self.assertEqual(attempt(self.path,'restart')[1], 'daily_cap')
    def test_idempotency(self):
        for _ in range(9): self.assertEqual(self.auth()[0], 'ALLOW')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT amount FROM budget').fetchone()[0],20_000_000)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
    def test_idempotency_conflict(self):
        self.auth(); self.assertEqual(self.auth(amount=19)[1], 'idempotency_conflict')
    def test_no_revival_next_day(self):
        self.policy.day_key=lambda:'2026-09-10'; self.auth()
        self.policy.day_key=lambda:'2026-09-11'
        self.assertEqual(self.auth()[1], 'request_expired')
        self.assertEqual(self.auth(request_id='nextday')[0], 'ALLOW')
    def test_missing_id(self): self.assertEqual(self.auth(request_id=None)[0], 'DENY')
    def test_currency(self): self.assertEqual(self.auth(currency='ETH')[1], 'unsupported_currency')
    def test_not_whitelisted(self): self.assertEqual(self.auth(payee='evil')[1], 'payee_not_whitelisted')
    def test_thread_race(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(lambda i:attempt(self.path,str(i)),range(30)))
        self.assertEqual(sum(r[0]=='ALLOW' for r in rows),5)
        self.assertTrue(self.x.verify())
    def test_process_race(self):
        with multiprocessing.get_context('spawn').Pool(4) as pool:
            rows=pool.starmap(attempt,[(self.path,str(i)) for i in range(12)])
        self.assertEqual(sum(r[0]=='ALLOW' for r in rows),5)
    def test_crash_before_commit(self):
        self.auth()
        proc=multiprocessing.get_context('spawn').Process(target=crash_transaction,args=(self.path,))
        proc.start(); proc.join(10)
        self.assertEqual(proc.exitcode,77)
        self.assertTrue(self.x.verify())
        self.assertEqual(attempt(self.path,'after')[0],'ALLOW')
    def test_commit_then_crash_retry(self):
        proc=multiprocessing.get_context('spawn').Process(target=crash_after_commit,args=(self.path,))
        proc.start(); proc.join(10)
        self.assertEqual(proc.exitcode,78)
        self.assertEqual(attempt(self.path,'lost-response')[0],'ALLOW')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT amount FROM budget').fetchone()[0],20_000_000)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
    def test_audit_tamper(self):
        self.auth()
        with sqlite3.connect(self.path) as db: db.execute("UPDATE events SET body='{}'")
        self.assertFalse(self.x.verify())
        self.assertEqual(self.auth(request_id='after')[1],'audit_corrupt')
    def test_budget_tamper(self):
        self.auth()
        with sqlite3.connect(self.path) as db: db.execute('UPDATE budget SET amount=0')
        self.assertFalse(self.x.verify())
        self.assertEqual(self.auth(request_id='after')[1],'audit_corrupt')
    def test_transaction_audit_failure(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'fail'); END")
        self.assertEqual(self.auth()[1],'durable_audit_or_state_failure')
        with sqlite3.connect(self.path) as db: self.assertEqual(db.execute('SELECT count(*) FROM budget').fetchone()[0],0)
    def test_no_token_in_audit(self):
        self.auth()
        with sqlite3.connect(self.path) as db:
            self.assertNotIn('fixture-token',db.execute('SELECT body FROM events').fetchone()[0])
    def test_outbox_failure_and_recovery(self):
        self.auth()
        class Sink:
            def record_action(self,**kw): raise OSError('offline')
        self.x.prov=Sink(); self.assertEqual(self.x.flush_provenance()['status'],'pending')
        seen=[]
        self.x.prov.record_action=lambda **kw: seen.append(kw['event_id']) or True
        self.assertEqual(self.x.flush_provenance()['delivered'],1)
        self.assertEqual(self.x.flush_provenance()['delivered'],0)
        self.assertEqual(len(seen),1)
