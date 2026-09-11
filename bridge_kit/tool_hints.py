"""tool_hints — 戌问题 4 / 6 / 7 的确定性部分。

- check_web_fetch_url:worker 拿 web.fetch 打 api.grants.gov Search2(9-08 已证只有 grants.catalog 的 POST 能 200)
  → 回 INVALID_TOOL_CALL 进 prior,不出网、不烧 job。
- search_unavailable:web.search 五 provider SEARCH_CHALLENGE,在 Lyra 定新源前恒回此收据,worker 不重试。
- lane_for_job:EGRESS lane 只取 job.lane;缺 → 报错。不再有 worker→lane 表(v3 的 flash→deep 表是把角色当授权,撤)。
- is_challenge_body:DDG 人机验证页(captcha / 410b)判定,status=ok 但语义空时给收据加 semantic=challenge。
零依赖,3.9 语法。
"""
import re
from urllib.parse import urlparse

GRANTS_SEARCH2_HOST = "api.grants.gov"
GRANTS_SEARCH2_PATH = "/v1/api/search2"

_CHALLENGE = re.compile(r"captcha|410b|anomaly|unusual traffic|verify you are", re.IGNORECASE)


def check_web_fetch_url(url):
    """None = 放行;dict = 拦截收据(进 prior)。"""
    try:
        u = urlparse(url)
    except Exception:
        return {"status": "error", "error": "INVALID_URL", "hint": "unparseable url"}
    if u.hostname == GRANTS_SEARCH2_HOST and (u.path or "").rstrip("/").endswith(GRANTS_SEARCH2_PATH):
        return {"status": "error", "error": "INVALID_TOOL_CALL",
                "hint": "use grants.catalog (POST Search2 via runner); web.fetch GET returns 403"}
    return None


def search_unavailable(query):
    return {"status": "error", "error": "SEARCH_UNAVAILABLE",
            "hint": "all registered search providers return SEARCH_CHALLENGE; source decision pending",
            "query": query, "retryable": False}


class LaneMissing(KeyError):
    pass


ALLOWED_LANES = ("research", "deep", "full", "cc", "scout", "rwa", "maintainer", "local", "fast")


def lane_for_job(job):
    """EGRESS lane 只来自 job.lane(衔拍 9-08:lane 是授权,显式字段进收据,不由 worker 名/措辞决定)。
    没有 job.lane → LaneMissing,不从 worker 名推,不默认 deep(Astra v4.1 R13:alias 不继承更高 lane)。"""
    lane = (job or {}).get("lane")
    if not lane:
        raise LaneMissing("job %r has no lane; create_job must set it (worker=%r is a role, not a lane)"
                          % ((job or {}).get("jid"), (job or {}).get("worker")))
    if lane not in ALLOWED_LANES:
        raise LaneMissing("job lane %r not in EGRESS lane set" % lane)
    return lane


def is_challenge_body(text):
    return bool(text) and bool(_CHALLENGE.search(text))


def annotate_semantic(receipt, body):
    """status=ok 的 web.fetch 收据加 semantic 字段:challenge / empty / content。"""
    r = dict(receipt)
    if not body or not body.strip():
        r["semantic"] = "empty"
    elif is_challenge_body(body):
        r["semantic"] = "challenge"
    else:
        r["semantic"] = "content"
    return r
