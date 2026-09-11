"""Local, durable policy reservations; NEVER a payment client or spend capability.
SQLite journal + budget update commit together. A resource-gate adapter must
validate a token against the complete context. No token is persisted.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

SCALE = 1_000_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def units(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('bad_amount')
    if len(str(value)) > 64:
        raise ValueError('bad_amount')
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n <= 0 or n > Decimal('1000000000'):
            raise ValueError('bad_amount')
        u = n * SCALE
        if u <= 0 or u != u.to_integral_value():
            raise ValueError('amount_precision')
        return int(u)
    except InvalidOperation as exc:
        raise ValueError('bad_amount') from exc


@dataclass
class Policy:
    daily_cap: dict = field(default_factory=dict)
    per_tx_cap: dict = field(default_factory=dict)
    payee_whitelist: set = field(default_factory=set)
    currency: str = 'USD'
    day_key: object = field(default=lambda: datetime.now(timezone.utc).date().isoformat())


class X402Policy:
    def __init__(self, policy: Policy, provenance=None, gate=None, *, state_path=None):
        self.p, self.prov, self.gate = policy, provenance, gate
        # Memory-only authorization is deliberately unavailable.
        self.path = str(state_path) if state_path is not None else None
        if self.path == ':memory:':
            self.path = None
        if self.path:
            with self._connect() as db:
                db.executescript('''
                CREATE TABLE IF NOT EXISTS budget(agent TEXT, day TEXT, currency TEXT,
                    amount INTEGER NOT NULL, PRIMARY KEY(agent,day,currency));
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT UNIQUE, request_hash TEXT NOT NULL,
                    body TEXT NOT NULL, hash TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
                ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA busy_timeout=10000')
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _verify_db(db):
        prev = '0' * 64
        totals = {}
        for body, digest, rid, fingerprint in db.execute('SELECT body,hash,request_id,request_hash FROM events ORDER BY seq'):
            try:
                event = json.loads(body)
                if event['request_id'] != rid or event['request_hash'] != fingerprint:
                    return False
                if event['verdict'] == 'ALLOW':
                    key = (event['agent'], event['day'], event['currency'])
                    totals[key] = totals.get(key, 0) + event['amount_units']
                if event['prev'] != prev:
                    return False
            except (ValueError, KeyError, TypeError):
                return False
            if hashlib.sha256(body.encode()).hexdigest() != digest:
                return False
            prev = digest
        actual = {(a, d, c): n for a, d, c, n in db.execute('SELECT * FROM budget')}
        return actual == totals

    def verify(self):
        if not self.path:
            return False
        try:
            with self._connect() as db:
                return self._verify_db(db)
        except sqlite3.Error:
            return False

    def authorize(self, agent, amount, payee, mission, action, human_token=None,
                  *, request_id=None, currency='USD'):
        if not self.path:
            return 'DENY', 'durable_state_required'
        reason = None
        if not all(isinstance(s, str) and 0 < len(s) <= 256 for s in
                   (agent, payee, mission, action, request_id)):
            return 'DENY', 'bad_identity_or_request_id'
        try:
            amount_u = units(amount)
            daily = units(self.p.daily_cap[agent]) if agent in self.p.daily_cap else 0
            per_tx = units(self.p.per_tx_cap[agent]) if agent in self.p.per_tx_cap else 0
        except (ValueError, TypeError):
            return 'DENY', 'bad_amount_or_cap'
        if currency != self.p.currency or currency != 'USD':
            return 'DENY', 'unsupported_currency'
        try:
            day = self.p.day_key()
            if not isinstance(day, str) or datetime.strptime(day, '%Y-%m-%d').strftime('%Y-%m-%d') != day:
                raise ValueError('bad_day')
        except Exception:
            return 'DENY', 'clock_error'
        context = dict(agent=agent, amount_units=amount_u, currency=currency,
                       payee=payee, mission=mission, action=action, request_id=request_id)
        # Complete context including amount/payee must be bound, not "mission:action".
        if not human_token:
            reason = 'no_human_token'
        elif not callable(self.gate):
            reason = 'gate_required'
        else:
            try:
                if self.gate(human_token, dict(context)) is not True:
                    reason = 'token_not_bound'
            except Exception:
                reason = 'gate_error'
        fingerprint = hashlib.sha256(canonical(dict(context, daily=daily, per_tx=per_tx,
                     whitelisted=payee in self.p.payee_whitelist)).encode()).hexdigest()
        try:
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                try:
                    if not self._verify_db(db):
                        db.rollback()
                        return 'DENY', 'audit_corrupt'
                    old = db.execute('SELECT request_hash,body FROM events WHERE request_id=?',
                                     (request_id,)).fetchone()
                    if old:
                        db.rollback()
                        if old[0] != fingerprint:
                            return 'DENY', 'idempotency_conflict'
                        if reason:
                            return 'DENY', reason
                        prior = json.loads(old[1])
                        # An old reservation cannot be revived as today's authorization.
                        if prior['day'] != day:
                            return 'DENY', 'request_expired'
                        return prior['verdict'], prior['reason']
                    used = db.execute('SELECT amount FROM budget WHERE agent=? AND day=? AND currency=?',
                                      (agent, day, currency)).fetchone()
                    used = used[0] if used else 0
                    if reason is None:
                        if payee not in self.p.payee_whitelist:
                            reason = 'payee_not_whitelisted'
                        elif amount_u > per_tx:
                            reason = 'per_tx_cap'
                        elif used + amount_u > daily:
                            reason = 'daily_cap'
                    verdict = 'DENY' if reason else 'ALLOW'
                    reason = reason or 'ok'
                    if verdict == 'ALLOW':
                        db.execute('INSERT INTO budget VALUES(?,?,?,?) ON CONFLICT(agent,day,currency) '
                                   'DO UPDATE SET amount=excluded.amount', (agent, day, currency, used+amount_u))
                    tail = db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
                    body = canonical(dict(context, request_hash=fingerprint, kind='x402_policy_reservation', day=day,
                        verdict=verdict, reason=reason, prev=tail[0] if tail else '0'*64))
                    digest = hashlib.sha256(body.encode()).hexdigest()
                    db.execute('INSERT INTO events(request_id,request_hash,body,hash) VALUES(?,?,?,?)',
                               (request_id, fingerprint, body, digest))
                    db.commit()
                    return verdict, reason
                except BaseException:
                    db.rollback()
                    raise
        except sqlite3.Error:
            return 'DENY', 'durable_audit_or_state_failure'

    def flush_provenance(self):
        """At-least-once outbox. Consumer MUST deduplicate event_id; True means durable ACK."""
        if self.prov is None or not self.path:
            return {'status': 'pending', 'delivered': 0}
        delivered = 0
        with self._connect() as db:
            if not self._verify_db(db):
                return {'status': 'audit_corrupt', 'delivered': 0}
            for seq, body, digest in db.execute('SELECT seq,body,hash FROM events WHERE delivered=0 ORDER BY seq').fetchall():
                try:
                    ack = self.prov.record_action(event_id=digest, **json.loads(body))
                except Exception:
                    return {'status': 'pending', 'delivered': delivered}
                if ack is not True:
                    return {'status': 'pending', 'delivered': delivered}
                db.execute('UPDATE events SET delivered=1 WHERE seq=?', (seq,))
                delivered += 1
        return {'status': 'synced', 'delivered': delivered}
