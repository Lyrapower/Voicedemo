"""8501 store event kind 注册表(单一源)。

RE CROSS PROJECT REVIEW v4 #5 / STOCK_CARD_SCHEMA_v2 "kind 注册表"一节。

- 收录现存所有 emit 端写进 8501 /store/events 的 top-level `kind` 字符串。
- 现存 kind 不改名,只登记;emit 端与消费端一律 import 这些常量,不再硬编码字符串。
- 新 kind 加在本文件并升版本;消费方按 `schema`/`kind` 做版本兼容。
- `integrity_flag` 是 brief payload 内的子字段,不是 top-level kind,不登记。
- `watcher_event` 仅见于 UI 过滤数组,无 emit 端,暂不登记。

分类按 `source` 分组(source 字段本身不在本表,本表只管 `kind`)。
"""

from __future__ import annotations

# ---- source = aether ----
AETHER_SCAN = "aether_scan"
AETHER_FILTER = "aether_filter"
AETHER_MOMENTUM = "aether_momentum"
AETHER_OFFPOOL = "aether_offpool"
AETHER_OFFPOOL_COACH = "aether_offpool_coach"
AETHER_PREMARKET = "aether_premarket"  # legacy(仍被 store 查询引用)
AETHER_PREMARKET_GRID = "aether_premarket_grid"
AETHER_PREMARKET_SONNET = "aether_premarket_sonnet"
AETHER_PREMARKET_DEEPSEEK = "aether_premarket_deepseek"
AETHER_BRIEF = "aether_brief"
AETHER_BRIEF_DRYRUN = "aether_brief_dryrun"
AETHER_SONNET_EARNINGS = "aether_sonnet_earnings"
AETHER_POLICY_PROPOSAL = "aether_policy_proposal"
AETHER_SCOUT_BRIEF = "aether_scout_brief"
AETHER_WATCHDOG = "aether_watchdog"
AETHER_PAPER_WALLET = "aether_paper_wallet"
AETHER_PAPER_FILL = "aether_paper_fill"
AETHER_PAPER_DAILY = "aether_paper_daily"
AETHER_CRYPTO_PAPER_AB = "aether_crypto_paper_ab"
SURFACE_DOCTOR = "surface_doctor"
GRID_CC_SCAN = "grid_cc_scan"
DENY = "deny"

# ---- source = watcher ----
WATCHER_MOMENTUM = "watcher_momentum"
WATCHER_HEALTH = "watcher_health"
WATCHER_ALERT = "watcher_alert"

# ---- source = grid ----
GRID_DIARY = "grid_diary"

# ---- source = post_market ----
HEARTBEAT = "heartbeat"

# ---- 新 kind ----
STOCK_CARD_V1 = "stock_card.v1"

# ---- 分组(供 emit 端/消费端按 source 过滤)----
AETHER_KINDS = frozenset({
    AETHER_SCAN, AETHER_FILTER, AETHER_MOMENTUM, AETHER_OFFPOOL,
    AETHER_OFFPOOL_COACH, AETHER_PREMARKET, AETHER_PREMARKET_GRID,
    AETHER_PREMARKET_SONNET, AETHER_PREMARKET_DEEPSEEK, AETHER_BRIEF,
    AETHER_BRIEF_DRYRUN, AETHER_SONNET_EARNINGS, AETHER_POLICY_PROPOSAL,
    AETHER_SCOUT_BRIEF, AETHER_WATCHDOG, AETHER_PAPER_WALLET,
    AETHER_PAPER_FILL, AETHER_PAPER_DAILY, AETHER_CRYPTO_PAPER_AB,
    SURFACE_DOCTOR, GRID_CC_SCAN, DENY,
})

WATCHER_KINDS = frozenset({WATCHER_MOMENTUM, WATCHER_HEALTH, WATCHER_ALERT})
GRID_KINDS = frozenset({GRID_DIARY})
POST_MARKET_KINDS = frozenset({HEARTBEAT})

# 全集(校验用)
ALL_KINDS = frozenset(AETHER_KINDS | WATCHER_KINDS | GRID_KINDS | POST_MARKET_KINDS | {STOCK_CARD_V1})

# 日记类 kind(对 cloud 工具硬拒——日记层不对外开放)
DIARY_KINDS = frozenset({GRID_DIARY})

# cloud 工具 events.recent 白名单(RE 第五节):aether_* + stock_card.v1,日记类硬拒
CLOUD_TOOL_EVENT_WHITELIST = frozenset(AETHER_KINDS | WATCHER_KINDS | {STOCK_CARD_V1})


def is_valid_kind(kind: str) -> bool:
    return kind in ALL_KINDS


def is_diary_kind(kind: str) -> bool:
    return kind in DIARY_KINDS


def is_cloud_tool_allowed(kind: str) -> bool:
    """cloud 工具 events.recent 是否允许读该 kind。日记类一律拒。"""
    if kind in DIARY_KINDS:
        return False
    return kind in CLOUD_TOOL_EVENT_WHITELIST
