import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))

from contract_lint import (  # noqa: E402
    MARKER,
    apply_contract_lint,
    detect_subject_inversion,
)


def test_detects_silence_translation_inversion():
    assert detect_subject_inversion("随时将她的沉默翻译成行动。")


def test_no_flag_without_system_actor():
    assert not detect_subject_inversion("沉默有时也是一种回答。")


def test_no_flag_without_action_verb():
    assert not detect_subject_inversion("我注意到你的沉默。")


def test_appends_marker_without_rewrite():
    src = "随时将她的沉默翻译成行动。"
    r = apply_contract_lint(src)
    assert r.flagged and r.contract_flag == "subject_inversion"
    assert src in r.text and MARKER in r.text
    assert r.text.startswith(src)


def test_idempotent_marker():
    once = apply_contract_lint("随时将她的沉默翻译成行动。")
    twice = apply_contract_lint(once.text)
    assert not twice.flagged
