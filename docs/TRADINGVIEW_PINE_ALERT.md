# TradingView Pine Alert Notes

Pine Script is needed so TradingView calculates and sends `price`, `vwap`, `open_range_high`, `rvol`, and `iv_rank` if available.
Jarvis does not fetch live market data.
TradingView sends alerts to Jarvis.

If `iv_rank` is missing, Jarvis returns `CASH` with failed check `IV_UNKNOWN`.
Use alert frequency: Once Per Bar Close.
Create separate alerts for MU, AMD, and IREN.
Do not create TSLA alert.

Starter Pine file:
`tradingview/jarvis_orh_vwap_rvol_gate.pine`
