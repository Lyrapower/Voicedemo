"""Alpha Platform · Phase 0.5 · jobs.py — 因子回放任务(真实计算,流式进度)。
CHANGELOG: v0.1 (2026-07-25, Fable)
  纪律:进度条只许绑真实计算。本任务对 platform.db 已存的 1-min bars 逐标的回放
  一个朴素动量规则(ret_5m>0 持有,否则空仓),边算边发 progress/point/curve 事件。
  规则本身 v0 未验证——它的意义是给仪式感管道供真数据,不是策略结论。
  无 bars 时任务如实上报 no-data 并结束,不生成假点。
"""
from __future__ import annotations

import threading
import time

import db

_lock = threading.Lock()


def start_factor_replay(watchlist: list[str]) -> int:
    c = db.conn_jobs()
    try:
        cur = c.execute(
            "INSERT INTO jobs(kind, created, status, pct, detail) VALUES('factor_replay', ?, 'running', 0, ?)",
            (int(time.time()), ",".join(watchlist)),
        )
        job_id = cur.lastrowid
        c.commit()
    finally:
        c.close()
    threading.Thread(target=_run, args=(job_id, watchlist), daemon=True).start()
    return job_id


def _run(job_id: int, watchlist: list[str]) -> None:
    with _lock:  # 单并发,防 sqlite 写竞争
        c = db.conn_jobs()
        try:
            total = max(1, len(watchlist))
            any_data = False
            for i, sym in enumerate(watchlist):
                rows = c.execute(
                    "SELECT ts, c FROM bars WHERE symbol=? ORDER BY ts ASC LIMIT 400", (sym,)
                ).fetchall()
                base_pct = i / total * 100
                if len(rows) < 10:
                    db.job_event(c, job_id, base_pct, "symbol_skip", {"symbol": sym, "reason": f"bars={len(rows)} 不足"})
                    c.commit()
                    continue
                any_data = True
                equity = 1.0
                holding = False
                closes = [r[1] for r in rows]
                n = len(rows)
                for k in range(6, n):
                    ret_5m = (closes[k] - closes[k - 5]) / closes[k - 5] if closes[k - 5] else 0.0
                    if holding and closes[k - 1]:
                        equity *= closes[k] / closes[k - 1]
                    holding = ret_5m > 0
                    if k % 10 == 0 or k == n - 1:
                        pct = base_pct + (k / n) * (100 / total)
                        db.job_event(
                            c,
                            job_id,
                            round(pct, 1),
                            "point",
                            {"symbol": sym, "ts": rows[k][0], "equity": round(equity, 5)},
                        )
                        c.commit()
                        time.sleep(0.02)  # 让位读端;非表演延迟
                db.job_event(
                    c,
                    job_id,
                    round(base_pct + 100 / total, 1),
                    "curve_done",
                    {"symbol": sym, "final_equity": round(equity, 5), "bars": n},
                )
                c.commit()
            if not any_data:
                db.job_event(c, job_id, 100.0, "no_data", {"detail": "无足量 bars——等 worker 采几个周期再跑"})
            else:
                db.job_event(c, job_id, 100.0, "done", {"symbols": len(watchlist)})
            c.commit()
        except Exception as exc:
            try:
                db.job_event(c, job_id, 100.0, "error", {"detail": str(exc)[:300]})
                c.execute("UPDATE jobs SET status='error' WHERE id=?", (job_id,))
                c.commit()
            except Exception:
                pass
        finally:
            c.close()
