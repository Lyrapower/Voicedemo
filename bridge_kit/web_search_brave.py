"""web_search_brave — web.search 的 Brave provider(替换 DDG html 抓页)。

事实(2026-09-10 查 api-dashboard.search.brave.com 官方文档):
- 端点 GET https://api.search.brave.com/res/v1/web/search?q=...&count=...&offset=...
- 头 X-Subscription-Token: <key>,Accept: application/json
- 回包 web.results[] 各含 title / url / description;query.more_results_available 标有无下一页
- 计费(多源 2026-06):无免费档,所有计划绑卡,每月 $5 额度 ≈ 1000 次,超出 $5/千次

规矩:
- 无 env BRAVE_API_KEY → 不出网,回 SEARCH_UNAVAILABLE(retryable=false)。key 只从 env 读,永不进收据/日志。
- 月上限 BRAVE_MONTHLY_CAP(默认 900)锁内落盘预留,到顶回 SEARCH_BUDGET_EXHAUSTED 不出网。这是本机防超发,不是账单封顶:同账户别的 key/调用者、计费月边界都不归它管。
  这是钱的门,写死在代码不在 prompt;改上限归 Lyra。
- 结果等级恒 unverified(与 EGRESS 9-07 定案一致);只回 title/url/snippet。
- 出网仍过 EGRESS:域名 api.search.brave.com 须在表里,由 web.fetch 同一张表核,本模块不绕。
零依赖,3.9 语法。
"""
import fcntl
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DOMAIN = "api.search.brave.com"
ENV_KEY = "BRAVE_API_KEY"
ENV_CAP = "BRAVE_MONTHLY_CAP"
DEFAULT_CAP = 900
MAX_COUNT = 20


class CounterCorrupt(RuntimeError):
    pass


class MonthlyCounter(object):
    """{"month": "2026-09", "n": 12} 落盘;换月归零。文件存在但读不出 → CounterCorrupt,不归零(归零=偷偷放开额度)。
    increment 在 fcntl 锁内读-改-写,多进程不丢计数。"""

    def __init__(self, path, now=None):
        self.path = path
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _month(self):
        return self._now().strftime("%Y-%m")

    def _load(self):
        if not os.path.exists(self.path):
            return {"month": self._month(), "n": 0}
        with open(self.path, "r", encoding="utf-8") as f:
            raw = f.read()
        try:
            d = json.loads(raw)
            month, n = d["month"], int(d["n"])
        except (ValueError, KeyError, TypeError):
            raise CounterCorrupt("quota counter %s unreadable; refusing to reset to 0" % self.path)
        if month != self._month():
            return {"month": self._month(), "n": 0}
        return {"month": month, "n": n}

    def _lock_path(self):
        return self.path + ".lock"

    def used(self):
        return self._load()["n"]

    def increment(self):
        with open(self._lock_path(), "a") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                d = self._load()
                d["n"] += 1
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
                return d["n"]
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)

    def reserve(self, cap):
        """锁内原子预留:used<cap 才 +1 并返回 n,否则返回 None。并发两进程 cap=1 只有一个拿到。"""
        with open(self._lock_path(), "a") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                d = self._load()
                if cap > 0 and d["n"] >= cap:
                    return None
                d["n"] += 1
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
                return d["n"]
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)


def _unavailable(query, reason, retryable=False):
    return {"status": "error", "error": reason, "query": query, "retryable": retryable,
            "provider": "brave", "grade": "unverified"}


def search(query, http_get, counter, egress_allows, count=10, offset=0, env=None):
    """http_get(url, headers) -> (status:int, body:str)。egress_allows(domain) -> bool,必传;None = 拒(没有校验器就不出网)。
    返回收据 dict:status=ok 时含 results[{title,url,snippet}] / more / n_used。"""
    env = os.environ if env is None else env
    key = env.get(ENV_KEY, "").strip()
    if not key:
        return _unavailable(query, "SEARCH_UNAVAILABLE")
    if egress_allows is None or not egress_allows(DOMAIN):
        return _unavailable(query, "DENIED_EGRESS_NOT_REGISTERED")
    cap = int(env.get(ENV_CAP, DEFAULT_CAP))
    try:
        n_used = counter.reserve(cap)  # 锁内原子预留,先扣再出网(失败请求 Brave 也可能计费)
    except CounterCorrupt:
        return _unavailable(query, "SEARCH_QUOTA_COUNTER_CORRUPT")
    if n_used is None:
        return _unavailable(query, "SEARCH_BUDGET_EXHAUSTED")

    count = max(1, min(int(count), MAX_COUNT))
    url = ENDPOINT + "?" + urlencode({"q": query, "count": count, "offset": int(offset)})
    headers = {"Accept": "application/json", "X-Subscription-Token": key}
    code, body = http_get(url, headers)

    if code == 401 or code == 403:
        return _unavailable(query, "SEARCH_AUTH_%d" % code)
    if code == 429:
        return _unavailable(query, "SEARCH_RATE_LIMITED", retryable=True)
    if code == 422:
        return _unavailable(query, "SEARCH_BAD_QUERY")
    if code != 200:
        return _unavailable(query, "SEARCH_HTTP_%d" % code, retryable=code >= 500)
    try:
        data = json.loads(body)
    except ValueError:
        return _unavailable(query, "SEARCH_BAD_JSON")
    items = (data.get("web") or {}).get("results") or []
    results = []
    for it in items:
        u = it.get("url")
        if not u:
            continue
        results.append({"title": (it.get("title") or "").strip(),
                        "url": u,
                        "snippet": (it.get("description") or "").strip()})
    more = bool((data.get("query") or {}).get("more_results_available"))
    out = {"status": "ok", "provider": "brave", "grade": "unverified", "query": query,
           "results": results, "n_results": len(results), "more": more,
           "n_used": n_used, "cap": cap}
    assert key not in json.dumps(out)
    return out
