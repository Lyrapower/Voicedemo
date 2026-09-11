"""Theta v3 read-only shadow estimates. No orders, no fills, no automatic ATM guess.
A leg must name expiration + strike. Local PT windows are converted to ET.
"""
from __future__ import annotations
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
PT = ZoneInfo('America/Los_Angeles')
COMMISSION_PER_CONTRACT = Decimal('0.65')  # Modeling assumption, not a broker quote.


class ThetaError(Exception):
    pass


def number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError('invalid_number')
    if len(str(value)) > 64:
        raise ValueError('invalid_number')
    try:
        n = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid_number') from exc
    if not n.is_finite() or n < 0 or n > Decimal('1000000000') or (positive and n == 0) or (0 < n < Decimal('0.00000001')):
        raise ValueError('invalid_number')
    return n


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}|\d{8}', value):
        raise ValueError('invalid_date')
    return datetime.strptime(value.replace('-', ''), '%Y%m%d').date()


def pt_to_et_minute(d: date, hhmm: str) -> str:
    if not isinstance(hhmm, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', hhmm):
        raise ValueError('minute_boundary_only')
    t = datetime.combine(d, datetime.strptime(hhmm, '%H:%M').time(), PT)
    out = t.astimezone(ET)
    if out.date() != d:
        raise ValueError('cross_date_window')
    return out.strftime('%H:%M:00.000')


def mid(q):
    try:
        b, a = number(q['bid'], positive=True), number(q['ask'], positive=True)
        if a < b:
            return None, None
        return (a+b)/2, a-b
    except (ValueError, KeyError, TypeError):
        return None, None


def settle(mid_in, spr_in, mid_out, spr_out, contracts=1, *, multiplier=100,
           commission_per_contract=COMMISSION_PER_CONTRACT):
    if type(contracts) is not int or not 1 <= contracts <= 10000 or multiplier != 100:
        raise ValueError('unsupported_contracts_or_multiplier')
    mi, si, mo, so = [number(v) for v in (mid_in, spr_in, mid_out, spr_out)]
    commission = number(commission_per_contract)
    gross = (mo-mi)*100*contracts
    comm = commission*2*contracts
    slip = (si+so)/2*100*contracts
    money = lambda v: float(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    return dict(gross=money(gross), commission=money(comm), slippage=money(slip), net=money(gross-comm-slip))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ThetaError('redirect_refused')


class Theta:
    def __init__(self, base='http://127.0.0.1:25503', opener=None, timeout=5):
        p = urllib.parse.urlsplit(base)
        if p.scheme != 'http' or p.hostname not in ('127.0.0.1', '::1') or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
            raise ValueError('theta_base_must_be_loopback_http')
        if p.port is not None and not 1 <= p.port <= 65535:
            raise ValueError('bad_port')
        self.base = base.rstrip('/')
        self.open = opener
        self.timeout = timeout
        self.log = []
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, path, **params):
        if path not in ('/v3/option/list/expirations', '/v3/option/at_time/quote', '/v3/calendar/on_date'):
            raise ValueError('endpoint_not_allowed')
        url = self.base + path + '?' + urllib.parse.urlencode(dict(params, format='json'))
        receipt = {'url': url, 'status': 'pending'}
        try:
            if self.open:
                body = self.open(url)
                raw = body.encode() if isinstance(body, str) else body
            else:
                with self.http.open(url, timeout=self.timeout) as response:
                    raw = response.read(2_000_001)
            if not isinstance(raw, bytes) or len(raw) > 2_000_000:
                raise ThetaError('response_too_large_or_invalid')
            receipt['sha256'] = hashlib.sha256(raw).hexdigest()
            data = json.loads(raw.decode('utf-8'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite_json')))
            if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
                raise ThetaError('schema_error')
            receipt['status'] = 'ok'
            return data
        except urllib.error.HTTPError as exc:
            receipt['status'] = f'http_{exc.code}'
            raise ThetaError(receipt['status']) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            receipt['status'] = 'theta_down'
            raise ThetaError('theta_down') from exc
        except (ValueError, UnicodeError, ThetaError) as exc:
            receipt['status'] = str(exc) if isinstance(exc, ThetaError) else 'schema_error'
            raise ThetaError(receipt['status']) from exc
        finally:
            self.log.append(receipt)

    def expirations(self, symbol):
        rows = self.get('/v3/option/list/expirations', symbol=symbol)
        try:
            return sorted({parse_date(r['expiration']).isoformat() for r in rows if r.get('symbol') == symbol})
        except (KeyError, ValueError, TypeError) as exc:
            raise ThetaError('schema_error') from exc

    def calendar(self, d):
        rows = self.get('/v3/calendar/on_date', date=d.strftime('%Y%m%d'))
        if len(rows) != 1 or rows[0].get('type') not in ('open', 'early_close', 'full_close', 'weekend'):
            raise ThetaError('calendar_schema_error')
        return rows[0]

    def at_time_quote(self, symbol, expiration, right, d, tod_et, *, strike):
        if not isinstance(tod_et, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d:00\.000', tod_et):
            raise ValueError('minute_boundary_only')
        if right not in ('call', 'put'):
            raise ValueError('invalid_right')
        return self.get('/v3/option/at_time/quote', symbol=symbol,
                        expiration=parse_date(expiration).strftime('%Y%m%d'), right=right,
                        strike=str(number(strike, positive=True)), start_date=d.strftime('%Y%m%d'),
                        end_date=d.strftime('%Y%m%d'), time_of_day=tod_et)


def _window(value, d):
    if not isinstance(value, str) or value.count('-') != 1:
        raise ValueError('invalid_window')
    a, b = value.split('-')
    start, end = pt_to_et_minute(d, a), pt_to_et_minute(d, b)
    if start > end:
        raise ValueError('invalid_window')
    return start, end


def _quote(rows, symbol, expiration, strike, right, target, max_age, contracts):
    matches = []
    for row in rows:
        try:
            if (row['symbol'], parse_date(row['expiration']), number(row['strike']), row['right']) != (symbol, expiration, strike, right):
                continue
            ts = datetime.fromisoformat(row['timestamp'])
            ts = ts.replace(tzinfo=ET) if ts.tzinfo is None else ts.astimezone(ET)
            if ts.date() != target.date() or not 0 <= (target-ts).total_seconds() <= max_age:
                continue
            if any(type(row.get(k)) is not int or row[k] < contracts for k in ('bid_size', 'ask_size')):
                continue
            m, s = mid(row)
            if m is not None:
                matches.append((m, s, row['timestamp']))
        except (ValueError, KeyError, TypeError):
            continue
    if len(matches) != 1:
        return None
    return matches[0]


def settle_leg(theta: Theta, leg: dict, d: date):
    result = {'leg': leg, 'date': d.isoformat(), 'mode': 'shadow', 'live_execution': False}
    start_log = len(theta.log)
    def done(status, **kw):
        return dict(result, status=status, **kw, data_receipts=theta.log[start_log:])
    try:
        symbol, right = leg['ticker'], leg['direction']
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,14}', symbol) or right not in ('call', 'put'):
            return done('rejected:invalid_contract')
        if 'strike' not in leg or 'expiration' not in leg:
            return done('unsettled:contract_not_selected')
        strike, expiration = number(leg['strike'], positive=True), parse_date(leg['expiration'])
        if expiration < d:
            return done('rejected:expired_contract')
        if leg.get('position', 'long') != 'long' or leg.get('multiplier', 100) != 100:
            return done('rejected:unsupported_position_or_multiplier')
        contracts = leg.get('contracts', 1)
        if type(contracts) is not int or not 1 <= contracts <= 10000:
            return done('rejected:contracts')
        age = leg.get('max_quote_age_s', 60)
        if type(age) is not int or not 0 <= age <= 60:
            return done('rejected:max_quote_age')
        entry = _window(leg['entry_window_pst'], d)
        exit_ = _window(leg['exit_window_pst'], d)
        if exit_[0] < entry[1] or exit_[1] <= entry[0]:
            return done('rejected:exit_before_entry')
        calendar = theta.calendar(d)
        if calendar['type'] in ('weekend', 'full_close'):
            return done('unsettled:market_closed')
        op, cl = calendar['open'], calendar['close']
        if not all(isinstance(v, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d', v) for v in (op, cl)) or op >= cl:
            return done('unsettled:calendar_schema_error')
        # Conservative regular equity session; never invent extended option hours.
        if entry[0][:8] < op or exit_[1][:8] > cl:
            return done('unsettled:outside_session')
        exps = theta.expirations(symbol)
        if not exps:
            return done('unsettled:no_chain')
        if expiration.isoformat() not in exps:
            return done('unsettled:no_expiration')
        values = []
        for tod in (entry[0], exit_[1]):
            target = datetime.fromisoformat(d.isoformat()+'T'+tod).replace(tzinfo=ET)
            rows = theta.at_time_quote(symbol, expiration.isoformat(), right, d, tod, strike=strike)
            q = _quote(rows, symbol, expiration, strike, right, target, age, contracts)
            if q is None:
                return done('unsettled:no_valid_quote', strike=str(strike), expiration=expiration.isoformat())
            values.append(q)
        (mi, si, tsi), (mo, so, tso) = values
        return done('settled', strike=str(strike), expiration=expiration.isoformat(),
                    mid_in=float(mi), mid_out=float(mo), quote_in_at=tsi, quote_out_at=tso,
                    price_rule='entry_ask_exit_bid', selection_rule='explicit_contract',
                    estimate_only=True, multiplier=100, contracts=contracts,
                    **settle(mi, si, mo, so, contracts))
    except ThetaError as exc:
        return done('unsettled:'+str(exc))
    except (KeyError, ValueError, TypeError):
        return done('rejected:invalid_leg')
