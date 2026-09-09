"""The escalation path: turn an agent run into a queue of things a human
should look at.

Why this exists
---------------
M3 made the agent produce honest blanks instead of confident lies. A blank is
better than a wrong answer, but it is still a dead end -- nothing ever goes back
and fills it in. This module is the other half: collect every fact the agent
failed to deliver, say WHY, and hand that to a person.

The important property is that the agent only escalates where it already
admitted it did not know. It is not "have a human check everything" -- that
would defeat the point of automating any of it. The agent's own uncertainty is
the trigger, which is only possible BECAUSE of the critic and the retry budget.
You cannot escalate a failure you never detected.

The reason matters as much as the gap
-------------------------------------
"equity is missing" tells a reviewer nothing. The four reasons below each imply
a different next action:

    tool_failed          the tool kept failing -> go fix the tool, or look the
                         number up by hand
    rejected_by_critic   a value arrived but was impossible -> the source is
                         lying; read the filing
    dropped_by_verifier  the tool had it but the answer did not survive
                         self-consistency -> a synthesizer bug, not a data gap
    not_gathered         no attempt reached it at all -> a planning gap
    derived              nobody should type this in; it is computed from other
                         facts, so fix those instead
"""

# Which step is expected to produce each fact. Small and explicit on purpose:
# deriving it from the planner's prompt would be clever and fragile.
FACT_SOURCES = {
    "revenue": "fetch_income_statement",
    "net_income": "fetch_income_statement",
    "gross_margin": "fetch_income_statement",
    "cash": "fetch_balance_sheet",
    "equity": "fetch_balance_sheet",
}

# Facts the agent computes rather than fetches, and what they are computed from.
# A human must never hand-enter these: typing in a margin that disagrees with
# the revenue and net_income beside it would put a contradiction into the brief,
# which is the exact failure the whole project exists to prevent.
DERIVED_FROM = {
    "net_margin": ("revenue", "net_income"),
}

TOOL_FAILED = "tool_failed"
REJECTED_BY_CRITIC = "rejected_by_critic"
DROPPED_BY_VERIFIER = "dropped_by_verifier"
NOT_GATHERED = "not_gathered"
DERIVED = "derived"


def _rejected_fields(diagnostics: dict) -> dict:
    """fact -> the critic's stated reason, for every field the critic threw out."""
    out = {}
    for verdict in diagnostics.get("verdicts", []):
        if verdict.get("ok", True):
            continue
        reason = "; ".join(verdict.get("problems", []))
        for fact in verdict.get("bad_fields", []):
            out[fact] = reason
    return out


def _step_errors(diagnostics: dict) -> dict:
    """step -> the error text, for steps whose TOOL failed.

    Critic rejections are also recorded in errors, but they are handled above
    and would otherwise mask the more specific reason."""
    out = {}
    for error in diagnostics.get("errors", []):
        step, _, detail = error.partition(": ")
        if "rejected by critic" in detail or detail.startswith("retry "):
            continue
        out.setdefault(step, detail)
    return out


def _gathered_fields(diagnostics: dict) -> set:
    """Every field name that survived to the evidence, across all steps."""
    return {field
            for data in diagnostics.get("gathered", {}).values()
            for field in data}


def classify(fact: str, answers: dict, diagnostics: dict) -> tuple[str, str]:
    """Why is `fact` not in the answers? Returns (reason, detail).

    Ordered most-specific first. A fact can look like several things at once --
    a step whose tool failed AND whose value the critic rejected on an earlier
    attempt -- and the most specific reason is the one that tells the reviewer
    what to actually do."""
    if fact in DERIVED_FROM:
        inputs = ", ".join(DERIVED_FROM[fact])
        return DERIVED, f"computed from {inputs}; resolve those instead"

    rejected = _rejected_fields(diagnostics)
    if fact in rejected:
        return REJECTED_BY_CRITIC, rejected[fact]

    step = FACT_SOURCES.get(fact)
    errors = _step_errors(diagnostics)
    if step in errors:
        return TOOL_FAILED, errors[step]

    if fact in _gathered_fields(diagnostics):
        return DROPPED_BY_VERIFIER, "the tool returned it but the answer did not survive verification"

    return NOT_GATHERED, f"no step produced {fact}"


def build_queue(required_facts: list[dict], answers: dict, diagnostics: dict) -> list[dict]:
    """One review row per required fact the agent did not deliver.

    `required_facts` comes from the benchmark, so the queue carries the expected
    unit -- a reviewer typing 98268 needs to know whether that is millions or
    dollars, and guessing is how a scale error gets in."""
    queue = []
    for fact in required_facts:
        name = fact["fact"]
        if name in answers:
            continue
        reason, detail = classify(name, answers, diagnostics)
        queue.append({
            "ticker": diagnostics["ticker"],
            "fiscal_year": diagnostics.get("fiscal_year"),
            "fact": name,
            "unit": fact.get("unit"),
            "reason": reason,
            "detail": detail,
            "attempts": diagnostics.get("attempts", {}).get(FACT_SOURCES.get(name), 0),
            "status": "open",
        })
    return queue
