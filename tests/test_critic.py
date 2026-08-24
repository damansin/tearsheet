"""Tests for verification.

A critic has two ways to be wrong, and the second is worse:
  false negative  misses a bad value  -> a hallucination survives
  false positive  rejects a GOOD value -> correct data is destroyed
So these test both directions, and the false-positive tests run against the
REAL benchmark values (which include legitimately negative income, equity and
margins) rather than invented ones.
"""

import json
import pathlib

from src.agent.critic import check_answers, check_tool_result

ROOT = pathlib.Path(__file__).parent.parent


def _usd(v):
    return {"value": v, "unit": "USD_millions"}


def _pct(v):
    return {"value": v, "unit": "percent"}


# --- catching bad values ----------------------------------------------------

def test_catches_negative_revenue():
    assert not check_tool_result("x", {"revenue": -3910350.0}).ok


def test_catches_negative_cash():
    assert not check_tool_result("x", {"cash": -94820.0}).ok


def test_catches_out_of_range_margin():
    assert not check_tool_result("x", {"gross_margin": -462.1}).ok


def test_catches_net_income_implausible_vs_revenue():
    """The GS case: 14,276 -> -142,760 is a 2.67x ratio, must be rejected."""
    assert not check_tool_result("x", {"revenue": 53512.0, "net_income": -142760.0}).ok


# --- NOT rejecting real companies (the dangerous direction) -----------------

def test_no_false_positives_on_any_real_company():
    for path in sorted((ROOT / "eval" / "benchmark").glob("*.json")):
        company = json.loads(path.read_text())
        facts = {f["fact"]: f["value"] for f in company["facts"]}
        verdict = check_tool_result("x", facts)
        assert verdict.ok, f"{company['ticker']} wrongly rejected: {verdict.problems}"


def test_legitimately_negative_values_pass():
    assert check_tool_result("x", {"revenue": 4970.0, "net_income": -4746.0,
                                   "gross_margin": -24.1}).ok      # RIVN
    assert check_tool_result("x", {"cash": 13801.0, "equity": -3908.0}).ok  # BA


# --- answer-vs-evidence -----------------------------------------------------

GATHERED = {"fetch_income_statement": {"revenue": 391035.0, "net_income": 93736.0,
                                       "gross_margin": 46.21}}


def test_drops_answers_with_no_supporting_data():
    kept, problems = check_answers({"cash": _usd(29943.0)}, GATHERED)
    assert kept == {}
    assert "no supporting tool data" in problems[0]


def test_drops_answers_that_contradict_the_tool():
    kept, _ = check_answers({"revenue": _usd(400000.0)}, GATHERED)
    assert kept == {}                       # the classic $40B vs $36B hallucination


def test_keeps_answers_that_match_the_tool():
    kept, _ = check_answers({"revenue": _usd(391035.0)}, GATHERED)
    assert "revenue" in kept


def test_derived_net_margin_kept_when_consistent():
    kept, _ = check_answers({"net_margin": _pct(23.97)}, GATHERED)
    assert "net_margin" in kept


def test_derived_net_margin_dropped_when_arithmetic_is_wrong():
    kept, problems = check_answers({"net_margin": _pct(35.0)}, GATHERED)
    assert kept == {}
    assert "net_income/revenue" in problems[0]
