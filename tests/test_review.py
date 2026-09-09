"""Tests for the review-queue classifier.

The queue's whole value is the REASON attached to each gap. A queue that says
"equity is missing" 13 times is busywork; one that distinguishes "the tool kept
failing" from "the value was impossible" tells a reviewer what to actually do.
So these tests are mostly about the reason being right, not the gap being found.
"""

from src.agent import review

FACTS = [
    {"fact": "revenue", "value": 1000.0, "unit": "USD_millions"},
    {"fact": "net_income", "value": 100.0, "unit": "USD_millions"},
    {"fact": "net_margin", "value": 10.0, "unit": "percent"},
    {"fact": "cash", "value": 50.0, "unit": "USD_millions"},
    {"fact": "equity", "value": 200.0, "unit": "USD_millions"},
]


def diagnostics(**overrides) -> dict:
    base = {
        "ticker": "TEST", "fiscal_year": 2024,
        "errors": [], "verdicts": [], "attempts": {}, "gathered": {},
    }
    base.update(overrides)
    return base


def reasons(queue: list[dict]) -> dict:
    return {row["fact"]: row["reason"] for row in queue}


def test_facts_the_agent_delivered_are_not_queued():
    answers = {f["fact"]: {"value": 1.0, "unit": "x"} for f in FACTS}
    assert review.build_queue(FACTS, answers, diagnostics()) == []


def test_a_failed_tool_is_reported_as_a_tool_failure():
    diag = diagnostics(
        errors=["fetch_balance_sheet: injected permanent fault: failed for TEST"],
        attempts={"fetch_balance_sheet": 2},
        gathered={"fetch_income_statement": {"revenue": 1000.0, "net_income": 100.0}},
    )
    answers = {"revenue": {"value": 1000.0, "unit": "USD_millions"},
               "net_income": {"value": 100.0, "unit": "USD_millions"},
               "net_margin": {"value": 10.0, "unit": "percent"}}
    queue = review.build_queue(FACTS, answers, diag)
    assert reasons(queue) == {"cash": review.TOOL_FAILED, "equity": review.TOOL_FAILED}
    assert queue[0]["attempts"] == 2          # the reviewer sees it was retried
    assert queue[0]["unit"] == "USD_millions"  # ...and the expected scale


def test_a_critic_rejection_is_reported_as_such_not_as_a_tool_failure():
    """The critic rejection ALSO lands in errors, so the more specific reason
    has to win -- otherwise every rejection reads as a broken tool and the
    reviewer goes and debugs a tool that worked fine."""
    diag = diagnostics(
        errors=["fetch_balance_sheet: rejected by critic: equity implausible"],
        verdicts=[{"step": "fetch_balance_sheet", "ok": False,
                   "problems": ["equity (-1,523,180.0) implausible vs revenue (1,000.0)"],
                   "bad_fields": ["equity"]}],
        gathered={"fetch_income_statement": {"revenue": 1000.0, "net_income": 100.0},
                  "fetch_balance_sheet": {"cash": 50.0}},
    )
    answers = {"revenue": {"value": 1000.0, "unit": "USD_millions"},
               "net_income": {"value": 100.0, "unit": "USD_millions"},
               "net_margin": {"value": 10.0, "unit": "percent"},
               "cash": {"value": 50.0, "unit": "USD_millions"}}
    queue = review.build_queue(FACTS, answers, diag)
    assert reasons(queue) == {"equity": review.REJECTED_BY_CRITIC}
    assert "implausible" in queue[0]["detail"]


def test_rejection_is_not_blamed_on_the_field_named_in_the_message():
    """The equity rejection message literally contains the word "revenue".
    Classifying by string search would blame revenue and send the reviewer to
    the wrong number; the critic's recorded bad_fields is used instead."""
    diag = diagnostics(
        errors=["fetch_balance_sheet: rejected by critic: equity vs revenue"],
        verdicts=[{"step": "fetch_balance_sheet", "ok": False,
                   "problems": ["equity (-1,523,180.0) implausible vs revenue (1,000.0)"],
                   "bad_fields": ["equity"]}],
    )
    reason, _ = review.classify("revenue", {}, diag)
    assert reason != review.REJECTED_BY_CRITIC


def test_gathered_but_absent_from_the_answer_is_a_verifier_drop():
    """The data was there and the answer still did not have it -- that is a
    synthesizer/verifier problem, not a data gap. A reviewer sent to look up
    the filing would be wasting their time."""
    diag = diagnostics(
        gathered={"fetch_balance_sheet": {"cash": 50.0, "equity": 200.0}})
    reason, _ = review.classify("cash", {}, diag)
    assert reason == review.DROPPED_BY_VERIFIER


def test_a_fact_nothing_ever_attempted_is_a_planning_gap():
    reason, _ = review.classify("equity", {}, diagnostics())
    assert reason == review.NOT_GATHERED


def test_derived_facts_are_flagged_so_nobody_types_them_in_by_hand():
    """Hand-entering a margin that disagrees with the revenue and net_income
    beside it puts a contradiction into the brief -- the exact failure the
    project exists to prevent. It gets recomputed instead."""
    reason, detail = review.classify("net_margin", {}, diagnostics())
    assert reason == review.DERIVED
    assert "revenue" in detail and "net_income" in detail


def test_retry_bookkeeping_is_not_mistaken_for_a_failure():
    """Recovery writes "retry 1/2" into errors. That is progress, not a cause;
    if it were treated as one it would mask the real reason underneath."""
    diag = diagnostics(errors=["fetch_balance_sheet: retry 1/2"],
                       gathered={"fetch_balance_sheet": {"cash": 50.0}})
    reason, _ = review.classify("cash", {}, diag)
    assert reason == review.DROPPED_BY_VERIFIER
