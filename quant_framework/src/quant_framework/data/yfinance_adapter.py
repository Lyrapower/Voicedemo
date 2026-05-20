"""YFinance concrete data adapter with SQLite caching."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from quant_framework.data.adapter import DataAdapter
from quant_framework.data.cache import DataCache

logger = logging.getLogger(__name__)

RATE_LIMIT_SLEEP = 0.25


class YFinanceAdapter(DataAdapter):
    def __init__(self, cache: DataCache) -> None:
        self.cache = cache

    def get_prices(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        tickers = [t.upper() for t in tickers]
        cached = self.cache.get_cached_prices(tickers, start_date, end_date)
        missing = self._tickers_missing_from_cache(tickers, cached, start_date, end_date)

        frames: list[pd.DataFrame] = []
        if not cached.empty:
            frames.append(cached)

        if missing:
            try:
                time.sleep(RATE_LIMIT_SLEEP)
                batch = self._fetch_prices_batch(missing, start_date, end_date)
                for ticker in missing:
                    try:
                        if ticker in batch and not batch[ticker].empty:
                            self.cache.store_prices(batch[ticker])
                            frames.append(batch[ticker])
                            self.cache.log_fetch(ticker, "prices", end_date, True)
                            logger.info("Fetched prices for %s", ticker)
                        else:
                            self.cache.log_fetch(ticker, "prices", end_date, False, "no data")
                    except Exception as e:
                        self.cache.log_fetch(ticker, "prices", end_date, False, str(e))
            except Exception as e:
                logger.warning("Batch price fetch failed, falling back per-ticker: %s", e)
                for ticker in missing:
                    try:
                        time.sleep(RATE_LIMIT_SLEEP)
                        df = self._fetch_prices(ticker, start_date, end_date)
                        if not df.empty:
                            self.cache.store_prices(df)
                            frames.append(df)
                        self.cache.log_fetch(ticker, "prices", end_date, True)
                    except Exception as ex:
                        self.cache.log_fetch(ticker, "prices", end_date, False, str(ex))

        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        return out

    def get_fundamentals(
        self,
        tickers: list[str],
        as_of_date: date,
    ) -> pd.DataFrame:
        tickers = [t.upper() for t in tickers]
        cached = self.cache.get_cached_fundamentals(tickers, as_of_date)
        missing = [t for t in tickers if t not in cached.index]

        frames: list[pd.DataFrame] = []
        if not cached.empty:
            frames.append(cached)

        for ticker in missing:
            try:
                time.sleep(RATE_LIMIT_SLEEP)
                row = self._fetch_fundamentals(ticker)
                if row is not None:
                    df = pd.DataFrame([row], index=[ticker])
                    self.cache.store_fundamentals(df, as_of_date)
                    frames.append(df)
                self.cache.log_fetch(ticker, "fundamentals", as_of_date, True)
                logger.info("Fetched fundamentals for %s", ticker)
            except Exception as e:
                self.cache.log_fetch(ticker, "fundamentals", as_of_date, False, str(e))
                logger.warning("Failed fundamentals for %s: %s", ticker, e)

        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames)
        out = out[~out.index.duplicated(keep="last")]
        return out

    def _tickers_missing_from_cache(
        self,
        tickers: list[str],
        cached: pd.DataFrame,
        start_date: date,
        end_date: date,
    ) -> list[str]:
        missing = []
        for t in tickers:
            if cached.empty:
                missing.append(t)
                continue
            try:
                sub = cached.xs(t, level="ticker")
                if sub.empty:
                    missing.append(t)
            except KeyError:
                missing.append(t)
        return missing

    def _fetch_prices_batch(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        raw = yf.download(
            tickers,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
        )
        result: dict[str, pd.DataFrame] = {}
        if raw.empty:
            return result
        if len(tickers) == 1:
            t = tickers[0]
            result[t] = self._normalize_price_frame(raw, t)
            return result
        for t in tickers:
            try:
                sub = raw[t].dropna(how="all")
                if not sub.empty:
                    result[t] = self._normalize_price_frame(sub, t)
            except (KeyError, TypeError):
                continue
        return result

    def _normalize_price_frame(self, hist: pd.DataFrame, ticker: str) -> pd.DataFrame:
        hist = hist.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        if "Adj Close" in hist.columns:
            hist["adj_close"] = hist["Adj Close"]
        elif "adj_close" not in hist.columns:
            hist["adj_close"] = hist.get("close", hist.get("Close"))
        hist = hist[["open", "high", "low", "close", "volume", "adj_close"]].dropna(subset=["close"])
        hist.index = pd.to_datetime(hist.index).date
        hist["ticker"] = ticker
        return hist.reset_index(names="date").set_index(["date", "ticker"])

    def _fetch_prices(self, ticker: str, start_date: date, end_date: date) -> pd.DataFrame:
        t = yf.Ticker(ticker)
        hist = t.history(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
        if hist.empty:
            return pd.DataFrame()

        hist = hist.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        if "Adj Close" in hist.columns:
            hist["adj_close"] = hist["Adj Close"]
        else:
            hist["adj_close"] = hist["close"]

        return self._normalize_price_frame(hist, ticker)

    def _fetch_fundamentals(self, ticker: str) -> dict | None:
        t = yf.Ticker(ticker)
        info = t.info or {}
        if not info:
            return None

        market_cap = info.get("marketCap")
        book_value = info.get("bookValue")
        shares = info.get("sharesOutstanding")
        if book_value is not None and shares is not None:
            book_value = float(book_value) * float(shares)

        total_revenue = None
        gross_profit = None
        total_assets = None
        try:
            fin = t.financials
            if fin is not None and not fin.empty:
                col = fin.columns[0]
                if "Total Revenue" in fin.index:
                    total_revenue = float(fin.loc["Total Revenue", col])
                elif "Total Revenue" not in fin.index and "Revenue" in fin.index:
                    total_revenue = float(fin.loc["Revenue", col])
                if "Gross Profit" in fin.index:
                    gross_profit = float(fin.loc["Gross Profit", col])
        except Exception:
            pass

        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                col = bs.columns[0]
                if "Total Assets" in bs.index:
                    total_assets = float(bs.loc["Total Assets", col])
                if book_value is None and "Stockholders Equity" in bs.index:
                    book_value = float(bs.loc["Stockholders Equity", col])
                elif book_value is None and "Total Stockholder Equity" in bs.index:
                    book_value = float(bs.loc["Total Stockholder Equity", col])
        except Exception:
            pass

        if market_cap is None and total_assets is None:
            return None

        return {
            "market_cap": float(market_cap) if market_cap else None,
            "book_value": float(book_value) if book_value else None,
            "total_revenue": total_revenue,
            "gross_profit": gross_profit,
            "total_assets": total_assets,
            "shares_outstanding": float(shares) if shares else None,
        }
