"""Calibration test: the scorer must reproduce the known verdicts of the
hand-written fake answers. If this fails, the measuring instrument is broken
and no downstream metric can be trusted.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "eval"))

from run_eval import load_ground_truth, score  # noqa: E402


def _scored():
    answers = json.loads((ROOT / "eval" / "fake_answers.json").read_text())
    return score(load_ground_truth(), answers)


def test_metrics_match_designed_verdicts():
    s = _scored()
    assert s["required"] == 6
    assert s["attempted"] == 5
    assert s["correct"] == 3
    assert s["wrong"] == 2
    assert abs(s["completion"] - 5 / 6) < 1e-9
    assert abs(s["fact_accuracy"] - 3 / 6) < 1e-9
    assert abs(s["hallucination_rate"] - 2 / 5) < 1e-9


def test_unit_normalization_accepts_rounded_billions():
    """391.0 USD_billions vs truth 391035 USD_millions -> within ±1%."""
    s = _scored()
    verdicts = {(r["ticker"], r["fact"]): r["verdict"] for r in s["results"]}
    assert verdicts[("AAPL", "revenue")] == "correct"


def test_hallucination_is_caught():
    """100000 vs truth 93736 (6.7% off) must FAIL the ±1% tolerance."""
    s = _scored()
    verdicts = {(r["ticker"], r["fact"]): r["verdict"] for r in s["results"]}
    assert verdicts[("AAPL", "net_income")] == "wrong"


def test_missing_fact_is_missing_not_wrong():
    s = _scored()
    verdicts = {(r["ticker"], r["fact"]): r["verdict"] for r in s["results"]}
    assert verdicts[("MSFT", "net_income")] == "missing"
