"""Tests for the human-in-the-loop resolve/merge step.

The single most important test here is
`test_human_answers_cannot_inflate_the_agent_score`. Everything else is
plumbing; that one protects the meaning of the headline metric. `check_fact`
reads only `value` and `unit`, so a merged answers file scores perfectly
happily with human-supplied numbers counted as agent wins -- which would let
anyone reach 100% by typing in the answer key. Excluding them has to be the
DEFAULT, and it has to be tested.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import resolve_review as rr  # noqa: E402
from run_eval import check_fact, drop_human_answers, score  # noqa: E402

from src.agent import review  # noqa: E402


def row(**overrides) -> dict:
    base = {
        "ticker": "NVDA", "fiscal_year": 2024, "fact": "revenue",
        "unit": "USD_millions", "reason": review.TOOL_FAILED,
        "detail": "injected permanent fault", "attempts": 2, "status": "open",
    }
    base.update(overrides)
    return base


# --- rule 1: no claim without a source ------------------------------------

def test_a_value_without_a_citation_is_refused():
    """The agent may not report a number it cannot trace to a tool result. A
    human gets the same rule, or the person becomes the weakest link in a
    system built for traceability."""
    with pytest.raises(ValueError, match="citation"):
        rr.resolve(row(), 60922.0, "")
    with pytest.raises(ValueError):
        rr.resolve(row(), 60922.0, "   ")


def test_a_resolved_row_records_who_and_from_where():
    resolved = rr.resolve(row(), 60922.0, "NVDA 10-K FY2024, income statement")
    assert resolved["status"] == rr.RESOLVED
    assert resolved["source"] == "human"
    assert resolved["citation"] == "NVDA 10-K FY2024, income statement"
    assert resolved["resolved_at"]


def test_unavailable_is_a_real_outcome_not_a_failure_to_try():
    """Recording it stops the same dead end being re-queued forever, and keeps
    it distinguishable from a gap nobody has looked at yet."""
    marked = rr.mark_unavailable(row(), "source is down")
    assert marked["status"] == rr.UNAVAILABLE
    assert marked["note"] == "source is down"
    assert marked not in rr.actionable([marked])


# --- rule 2: derived facts are never hand-entered -------------------------

def test_derived_rows_are_never_offered_to_a_human():
    """Typing in a margin that disagrees with the revenue and net_income beside
    it would put a contradiction into the brief."""
    rows = [row(fact="net_margin", reason=review.DERIVED), row()]
    assert [r["fact"] for r in rr.actionable(rows)] == ["revenue"]


def test_merge_recomputes_a_derived_fact_from_the_human_inputs():
    rows = [
        rr.resolve(row(fact="revenue"), 60922.0, "10-K"),
        rr.resolve(row(fact="net_income"), 29760.0, "10-K"),
    ]
    merged = rr.merge(rows, {"NVDA": {}})
    assert merged["NVDA"]["net_margin"]["value"] == pytest.approx(48.85, abs=0.01)
    assert merged["NVDA"]["net_margin"]["source"] == "computed_from_human"


def test_provenance_propagates_through_a_derived_fact():
    """A margin computed from a hand-entered revenue is a human-assisted
    answer. If it were tagged plain 'computed' it would slip back into the
    agent's score through the derived path."""
    rows = [rr.resolve(row(fact="revenue"), 100.0, "10-K")]
    answers = {"NVDA": {"net_income": {"value": 10.0, "unit": "USD_millions"}}}
    merged = rr.merge(rows, answers)
    assert merged["NVDA"]["net_margin"]["source"] == "computed_from_human"
    assert drop_human_answers(merged)[1] == 2   # the revenue AND the margin


def test_merge_never_overwrites_a_value_the_agent_produced():
    """The agent got this one on its own; a human answer must not silently
    replace it, or the queue becomes a way to edit the agent's output."""
    answers = {"NVDA": {"net_margin": {"value": 48.85, "unit": "percent"}}}
    rows = [rr.resolve(row(fact="revenue"), 100.0, "10-K"),
            rr.resolve(row(fact="net_income"), 10.0, "10-K")]
    merged = rr.merge(rows, answers)
    assert merged["NVDA"]["net_margin"]["value"] == 48.85
    assert "source" not in merged["NVDA"]["net_margin"]


def test_unresolved_rows_contribute_nothing_to_the_merge():
    rows = [row(), row(fact="cash", status=rr.UNAVAILABLE)]
    assert rr.merge(rows, {"NVDA": {}}) == {"NVDA": {}}


# --- the honesty invariant ------------------------------------------------

TRUTH = {
    "NVDA": {"ticker": "NVDA", "facts": [
        {"fact": "revenue", "value": 60922.0, "unit": "USD_millions",
         "match": "relative", "tolerance": 0.01},
        {"fact": "cash", "value": 7280.0, "unit": "USD_millions",
         "match": "relative", "tolerance": 0.01},
    ]},
}


def test_human_answers_cannot_inflate_the_agent_score():
    """THE test. Scoring a merged file must give exactly the same number as
    scoring the agent's own output -- a human filling gaps is coverage, not
    agent accuracy. Same circularity trap as letting the critic read the answer
    key: the score would rise while the agent got no better."""
    agent_only = {"NVDA": {"cash": {"value": 7280.0, "unit": "USD_millions"}}}
    rows = [rr.resolve(row(fact="revenue"), 60922.0, "10-K")]
    merged = rr.merge(rows, agent_only)

    scrubbed, removed = drop_human_answers(merged)
    assert removed == 1
    assert score(TRUTH, scrubbed)["fact_accuracy"] == score(TRUTH, agent_only)["fact_accuracy"]


def test_the_combined_number_is_available_but_has_to_be_asked_for():
    """Coverage is a legitimate thing to report -- it just must never be the
    default, and never the CI gate."""
    agent_only = {"NVDA": {"cash": {"value": 7280.0, "unit": "USD_millions"}}}
    merged = rr.merge([rr.resolve(row(fact="revenue"), 60922.0, "10-K")], agent_only)
    assert score(TRUTH, merged)["fact_accuracy"] == 1.0            # with humans
    assert score(TRUTH, drop_human_answers(merged)[0])["fact_accuracy"] == 0.5


def test_a_human_tag_does_not_change_how_the_fact_itself_is_judged():
    """The extra keys must not confuse the scorer -- a human answer that is
    wrong still scores wrong."""
    truth_fact = TRUTH["NVDA"]["facts"][0]
    tagged = {"value": 60922.0, "unit": "USD_millions",
              "source": "human", "citation": "10-K"}
    assert check_fact(truth_fact, tagged) == "correct"
    assert check_fact(truth_fact, {**tagged, "value": 1.0}) == "wrong"


def test_files_without_any_source_tags_are_untouched():
    """Every answers file committed before this feature existed must score
    exactly as it did before."""
    legacy = {"NVDA": {"revenue": {"value": 60922.0, "unit": "USD_millions"}}}
    kept, removed = drop_human_answers(legacy)
    assert kept == legacy and removed == 0
