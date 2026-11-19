from pathlib import Path

import pytest

from um.fixture_score import score_pairs

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "prototype/data/dev/labels.jsonl"  # paraphrased from private stores; absent from the public export


def test_blind_trial_numbers_reproduce():
    t = score_pairs(ROOT / "experiments/blind-trial/findings_test.json", ROOT / "prototype/data/test/labels.jsonl")
    assert (t["tp"], t["fp"], t["fn"]) == (21, 1, 0)


@pytest.mark.skipif(not DEV.exists(), reason="dev split is private")
def test_blind_trial_dev_numbers_reproduce():
    d = score_pairs(ROOT / "experiments/blind-trial/findings_dev.json", DEV)
    assert round(d["precision"], 2) == 0.96 and d["recall"] == 1.0
