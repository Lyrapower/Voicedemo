"""web_search_ollama — web.search 主 provider:Ollama 官方 Web Search API(Lyra 已是 Ollama Pro 付费用户)。

事实(2026-09-10 查 docs.ollama.com/capabilities/web-search 官方文档):
- POST https://ollama.com/api/web_search  body {"query": str, "max_results": int(默认 5,最大 10)}
- 头 Authorization: Bearer $OLLAMA_API_KEY(key 在 https://ollama.com/settings/keys 建;免费账号即可用,Pro 已付费)
- 回包 {"results":[{"title","url","content"}]}
- 同一 key 还有 POST https://ollama.com/api/web_fetch {"url"} → {"title","content","links"}(库存,本模块不接)
- 官方文档未写配额/速率数字;本模块只落盘计数(可选上限),不假装知道额度。

规矩:
- 无 env OLLAMA_API_KEY → 不出网,SEARCH_UNAVAILABLE。key 只从 env 读,永不进收据/日志。
- 出网仍过 EGRESS:域名 ollama.com 须在表里;本模块不绕。
- 结果等级恒 unverified;只回 title/url/snippet。
- 与 web_search_brave 同一收据形状,supervisor 可按 provider 表切换;默认 ollama 主、brave 备(备的 key 不在就跳过)。
零依赖,3.9 语法。
"""
import json
import os

ENDPOINT = "https://ollama.com/api/web_search"
DOMAIN = "ollama.com"
ENV_KEY = "OLLAMA_API_KEY"
ENV_CAP = "OLLAMA_SEARCH_MONTHLY_CAP"  # 未设或 0 = 只计数不封顶
MAX_RESULTS = 10


def _unavailable(query, reason, retryable=False):
    return {"status": "error", "error": reason, "query": query, "retryable": retryable,
            "provider": "ollama", "grade": "unverified"}


def search(query, http_post, counter, egress_allows, max_results=5, env=None):
    """http_post(url, headers, body_json:str) -> (status:int, body:str)。
    counter: web_search_brave.MonthlyCounter(必传);egress_allows(domain)->bool 必传,None = 拒。"""
    env = os.environ if env is None else env
    key = env.get(ENV_KEY, "").strip()
    if not key:
        return _unavailable(query, "SEARCH_UNAVAILABLE")
    if egress_allows is None or not egress_allows(DOMAIN):
        return _unavailable(query, "DENIED_EGRESS_NOT_REGISTERED")
    cap = int(env.get(ENV_CAP, "0") or 0)
    try:
        n_used = counter.reserve(cap)  # cap=0 → 只计数;锁内原子
    except Exception as e:  # CounterCorrupt
        if e.__class__.__name__ == "CounterCorrupt":
            return _unavailable(query, "SEARCH_QUOTA_COUNTER_CORRUPT")
        raise
    if n_used is None:
        return _unavailable(query, "SEARCH_BUDGET_EXHAUSTED")

    max_results = max(1, min(int(max_results), MAX_RESULTS))
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    body = json.dumps({"query": query, "max_results": max_results})
    code, resp = http_post(ENDPOINT, headers, body)

    if code in (401, 403):
        return _unavailable(query, "SEARCH_AUTH_%d" % code)
    if code == 429:
        return _unavailable(query, "SEARCH_RATE_LIMITED", retryable=True)
    if code != 200:
        return _unavailable(query, "SEARCH_HTTP_%d" % code, retryable=code >= 500)
    try:
        data = json.loads(resp)
    except ValueError:
        return _unavailable(query, "SEARCH_BAD_JSON")
    results = []
    for it in data.get("results") or []:
        u = it.get("url")
        if not u:
            continue
        results.append({"title": (it.get("title") or "").strip(), "url": u,
                        "snippet": (it.get("content") or "").strip()[:500]})
    out = {"status": "ok", "provider": "ollama", "grade": "unverified", "query": query,
           "results": results, "n_results": len(results), "more": False,
           "n_used": n_used, "cap": cap}
    assert key not in json.dumps(out)
    return out


def search_with_fallback(query, providers):
    """providers: [(name, callable(query)->receipt), ...] 按序试;首个 status=ok 即回;
    全失败回最后一条并附 tried 列表。SEARCH_UNAVAILABLE(无 key)的 provider 直接跳到下一个。"""
    tried = []
    last = None
    for name, fn in providers:
        r = fn(query)
        tried.append((name, r.get("status"), r.get("error")))
        if r.get("status") == "ok":
            r = dict(r)
            r["tried"] = tried
            return r
        last = r
    last = dict(last or _unavailable(query, "SEARCH_UNAVAILABLE"))
    last["tried"] = tried
    return last
