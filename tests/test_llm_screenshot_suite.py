import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.evaluate_screenshot_suite import (
    LOCKED_SYNTHETIC_CASE_IDS,
    _synthetic_pass,
    _verify_synthetic_split,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/llm/generated/screenshot_corpus_v2"


def test_locked_suite_is_held_out_and_covers_all_formations() -> None:
    _verify_synthetic_split(CORPUS, LOCKED_SYNTHETIC_CASE_IDS)
    index = {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in (CORPUS / "sft_test.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    valid_formations = {
        index[case_id]["metadata"]["formation"]
        for case_id in LOCKED_SYNTHETIC_CASE_IDS
        if index[case_id]["metadata"]["expected_valid"]
    }
    assert valid_formations == {
        "3-4-3",
        "3-5-2",
        "4-3-3",
        "4-4-2",
        "4-5-1",
        "5-2-3",
        "5-3-2",
        "5-4-1",
    }


def test_partial_screenshot_must_fail_closed() -> None:
    exact_visible = {
        "core_team_exact": True,
        "team_valid": False,
        "chips_exact": True,
        "unresolved": ["bench slot 3 is obscured"],
    }
    assert _synthetic_pass(exact_visible, expected_valid=False)
    assert not _synthetic_pass({**exact_visible, "team_valid": True}, expected_valid=False)
    assert not _synthetic_pass({**exact_visible, "unresolved": []}, expected_valid=False)
