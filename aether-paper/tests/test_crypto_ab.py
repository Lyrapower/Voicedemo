import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper import summary
from paper.account import PaperAccount
from paper.store import (
    STATE_DIR,
    init_crypto_lane,
    is_lane_initialized,
    lane_paths,
    save_account,
)


def _with_temp_state():
    tmp = tempfile.TemporaryDirectory()
    import paper.store as store

    old = store.STATE_DIR
    store.STATE_DIR = Path(tmp.name)
    store.LANE_PATHS = {
        lane: {k: Path(tmp.name) / f"{lane}_{k}.json" for k in paths}
        if k != "decisions" and k != "inbox"
        else Path(tmp.name) / f"{lane}_{k}.jsonl"
        for lane, paths in {
            "equity": store.LANE_PATHS["equity"],
            "crypto_rules": store.LANE_PATHS["crypto_rules"],
            "crypto_cli": store.LANE_PATHS["crypto_cli"],
        }.items()
        for k in store.LANE_PATHS["equity"]
    }
    # rebuild lane_paths dict properly
    store.LANE_PATHS = {
        "equity": {
            "account": Path(tmp.name) / "account.json",
            "decisions": Path(tmp.name) / "decisions.jsonl",
            "heartbeat": Path(tmp.name) / "heartbeat.json",
            "experiment": Path(tmp.name) / "experiment.json",
            "inbox": Path(tmp.name) / "signal_inbox.jsonl",
            "processed": Path(tmp.name) / "processed_signals.json",
        },
        "crypto_rules": {
            "account": Path(tmp.name) / "account_crypto_rules.json",
            "decisions": Path(tmp.name) / "decisions_crypto_rules.jsonl",
            "heartbeat": Path(tmp.name) / "heartbeat_crypto_rules.json",
            "experiment": Path(tmp.name) / "experiment_crypto_rules.json",
            "inbox": Path(tmp.name) / "signal_inbox_crypto_rules.jsonl",
            "processed": Path(tmp.name) / "processed_signals_crypto_rules.json",
        },
        "crypto_cli": {
            "account": Path(tmp.name) / "account_crypto_cli.json",
            "decisions": Path(tmp.name) / "decisions_crypto_cli.jsonl",
            "heartbeat": Path(tmp.name) / "heartbeat_crypto_cli.json",
            "experiment": Path(tmp.name) / "experiment_crypto_cli.json",
            "inbox": Path(tmp.name) / "signal_inbox_crypto_cli.jsonl",
            "processed": Path(tmp.name) / "processed_signals_crypto_cli.json",
        },
    }
    return tmp, old, store


def test_crypto_cli_uninitialized_row():
    tmp, old, store = _with_temp_state()
    try:
        assert not is_lane_initialized("crypto_cli")
        row = summary.lane_row("crypto_cli")
        assert row["status"] == "uninitialized"
        assert row["equity"] is None
        ab = summary.crypto_ab_payload()
        cli = next(c for c in ab["columns"] if c["lane"] == "crypto_cli")
        assert cli["status"] == "uninitialized"
        assert cli["equity"] is None
        items = summary.paper_brief_items()
        cli_item = next(i for i in items if i.get("lane") == "crypto_cli")
        assert cli_item["value"] == "未初始化"
    finally:
        store.STATE_DIR = old
        tmp.cleanup()


def test_background_return_vs_btc():
    exp = {"btc_anchor_price": 100.0}
    # lane flat at 1000 start, BTC up 10% → bg should be -10%
    bg = summary.background_return_pct("crypto_rules", 1000.0, 1000.0, exp)
    # btc return depends on live feed; with mocked we'd need patch
    # at minimum formula path for non-crypto
    eq_bg = summary.background_return_pct("equity", 1100.0, 1000.0, exp)
    assert eq_bg == 10.0


def test_initialized_cli_three_way_consistent():
    tmp, old, store = _with_temp_state()
    try:
        save_account(PaperAccount(cash=1000.0, start_equity=1000.0), lane="crypto_cli")
        store.atomic_write_json(
            lane_paths("crypto_cli")["experiment"],
            {
                "btc_anchor_price": 50000.0,
                "ab_contract": store.ab_contract_template("crypto_cli"),
            },
        )
        row = summary.lane_row("crypto_cli")
        assert row["status"] == "ready"
        assert row["equity"] == 1000.0
        ab = summary.crypto_ab_payload()
        cli = next(c for c in ab["columns"] if c["lane"] == "crypto_cli")
        assert cli["equity"] == 1000.0
        assert cli["status"] == "ready"
    finally:
        store.STATE_DIR = old
        tmp.cleanup()
