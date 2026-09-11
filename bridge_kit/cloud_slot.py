"""cloud_slot — 戌问题 5:8501 云槽 running_max=1 / queue_max=2,并行投 job → 429 / RETRY_EXHAUSTED。

不动 8501。8630 supervisor 侧:
- CloudSlot(max_running) 与 8501 的 running_max 同值(戌从 8501 config grep 出来填,不猜)。
  只约束本进程;别的 8501 客户端不受它管(Astra v4.1 R10),所以验收不是"8501 零 429",
  是:本进程并发不超上限、重试有界、无重复副作用。
- 429 退避(R11):算 attempt;Retry-After 是等待下限(抖动只能加不能减);指数 + 抖动;绝对 deadline 按单调钟算一次不重复扣;最多 max_attempts;
  等待时**不占槽**(run_with_backoff 在槽外 sleep,槽内只发请求);401/403/4xx 不重试。
- sleep/时钟/随机可注入,单测不真等。
零依赖,3.9 语法。
"""
import random
import threading
import time


class BackoffExhausted(RuntimeError):
    pass


class CloudSlot(object):
    def __init__(self, max_running):
        if max_running < 1:
            raise ValueError("max_running must be >= 1")
        self.max_running = max_running
        self._sem = threading.BoundedSemaphore(max_running)
        self._lock = threading.Lock()
        self.peak_concurrent = 0
        self._cur = 0

    def run(self, fn):
        with self._sem:
            with self._lock:
                self._cur += 1
                self.peak_concurrent = max(self.peak_concurrent, self._cur)
            try:
                return fn()
            finally:
                with self._lock:
                    self._cur -= 1


def _retry_after(resp):
    try:
        h = (resp.get("headers") or {}) if isinstance(resp, dict) else {}
        v = h.get("Retry-After") or h.get("retry-after")
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def run_with_backoff(slot, call, status_of, base=5.0, cap=120.0, max_attempts=6, deadline_s=600.0,
                     sleep=time.sleep, now=time.monotonic, rng=random.random, log=None):
    """slot.run(call) 发请求;status_of(resp)->int。
    429/5xx → 槽外退避重试;其他 4xx → 立刻返回不重试。
    返回 (resp, attempts, waited)。超 max_attempts 或 deadline → BackoffExhausted。"""
    t0 = now()
    waited = 0.0
    for attempt in range(1, max_attempts + 1):
        resp = slot.run(call)
        code = status_of(resp)
        if code == 429 or 500 <= code < 600:
            if attempt == max_attempts:
                raise BackoffExhausted("gave up after %d attempts (last=%d)" % (attempt, code))
            ra = _retry_after(resp)
            delay = min(cap, base * (2 ** (attempt - 1))) * (0.5 + rng())  # 抖动 0.5x–1.5x
            if ra is not None:
                delay = max(delay, ra)  # Retry-After 是下限:抖动不能把它压短
            remaining = deadline_s - (now() - t0)  # now 已含已等时间,不再减 waited(否则重复扣)
            if delay > remaining:
                raise BackoffExhausted("deadline %.0fs would be exceeded (attempt %d, last=%d)"
                                       % (deadline_s, attempt, code))
            if log:
                log("%d from 8501: sleep %.1fs outside slot (attempt %d/%d)" % (code, delay, attempt, max_attempts))
            sleep(delay)
            waited += delay
            continue
        return resp, attempt, waited
    raise BackoffExhausted("unreachable")
