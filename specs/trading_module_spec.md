# Trading Module Spec

Locked ticker pool:
- Core: NVDA, TSLA
- Satellite: PLTR, COIN, CORZ, BE (narrative-gated; see `app/router/trade_templates.py`)
- Hedge: SQQQ, GLD
- Backups: AMD, MU, XLE

Hard rules:
- Hedges count toward the 3-trade weekly cap.
- Satellite is NOT a fallback.
- Week = Monday-Friday.
- Preferred entry windows are preferred, not mandatory.
- Most days should be PASS.
- No setup = PASS.

Market regime filter:
- risk-on
- mixed
- risk-off

Context discipline:
- If context fights the setup, output PASS.
