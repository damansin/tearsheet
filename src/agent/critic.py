"""Verification: the agent may not assert what it cannot support.

Two checks, both pure Python (no LLM, no network) so they are cheap and testable:

  check_tool_result  did the TOOL return something possible?
                     -> catches implausible corruption before it reaches the answer
  check_answers      does every number in the ANSWER trace to gathered data?
                     -> catches the synthesizer inventing or mistranscribing values

Deliberately NOT here: cross-source verification against SEC XBRL. XBRL is where
our ground truth comes from, so a critic that consulted it would be reading the
answer key -- the score would rise without the agent getting better. That leaves
a real blind spot, documented below, rather than a fake number.

BLIND SPOT (stated up front, not discovered later): a subtly wrong value -- say
revenue shifted 15% -- is plausible, internally consistent, and faithfully
reported. Self-consistency cannot catch it by construction. Only a second
independent source could, and we ruled that out above.

FALSE POSITIVES ARE WORSE THAN FALSE NEGATIVES here: a critic that rejects good
data destroys correct answers. Every threshold below was checked against the
real benchmark, which contains legitimately negative values:
    net_income   negative for BA, INTC, RIVN
    equity       negative for BA (-3,908) and MCD
    gross_margin negative for BA and RIVN (-24.1%)
    net_margin   RIVN is -95.5%
Only revenue (min 4,970) and cash (min 1,043) are never negative, so only those
get a sign rule. Equity gets no bound at all -- there is no safe one.
"""

from dataclasses import dataclass, field

# Facts that are never legitimately negative in real filings.
NON_NEGATIVE = ("revenue", "cash")

# Generous ranges: RIVN is legitimately -95.5% net margin and -24.1% gross margin.
RANGES = {
    "gross_margin": (-200.0, 100.0),
    "net_margin": (-1000.0, 100.0),
}

# CALIBRATED, not guessed. The highest |net_income|/revenue in the benchmark is
# 0.955 (RIVN, a loss-maker); next is 0.488 (NVDA). 2.0 leaves >2x headroom over
# anything real while still catching a 10x corruption on a company whose margin
# exceeds ~20%. An earlier guess of 5.0 was too loose and let GS through
# (14,276 -> -142,760, ratio 2.67). Widen this if the universe ever includes
# companies with large one-off gains.
MAX_NET_INCOME_TO_REVENUE = 2.0

# Equity gets no SIGN rule -- BA (-3,908) and MCD (-3,796) are legitimately
# negative. A magnitude rule works instead: the highest real |equity|/revenue in
# the benchmark is 2.78 (BAC; banks carry the most equity per unit of revenue),
# so 4.0 leaves ~44% headroom. It catches CVX's corrupted -1,523,180 (ratio 7.9).
MAX_EQUITY_TO_REVENUE = 4.0

MATCH_TOLERANCE = 0.005      # 0.5% -- answers must match the evidence they cite
MARGIN_TOLERANCE = 0.5       # percentage points, for derived margins


@dataclass
class Verdict:
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    bad_fields: list[str] = field(default_factory=list)

    def fail(self, field_name: str, why: str) -> None:
        """Record WHICH field failed, not just that something did.

        Rejection is per-field on purpose. Dropping the whole tool result would
        punish good values for a neighbour's failure: when GS's net_income was
        corrupted, whole-result rejection also destroyed its correct revenue.
        The checks below identify the exact offending field, so only that one
        is discarded."""
        self.ok = False
        self.problems.append(why)
        if field_name not in self.bad_fields:
            self.bad_fields.append(field_name)


def check_tool_result(step: str, data: dict) -> Verdict:
    """Sanity + cross-field checks on one tool's output."""
    v = Verdict()

    for name in NON_NEGATIVE:
        value = data.get(name)
        if isinstance(value, (int, float)) and value < 0:
            v.fail(name, f"{name} is negative ({value:,.1f})")

    for name, (lo, hi) in RANGES.items():
        value = data.get(name)
        if isinstance(value, (int, float)) and not (lo <= value <= hi):
            v.fail(name, f"{name} out of range ({value:,.1f} not in [{lo}, {hi}])")

    revenue, net_income = data.get("revenue"), data.get("net_income")
    if isinstance(revenue, (int, float)) and isinstance(net_income, (int, float)):
        if revenue > 0 and abs(net_income) > MAX_NET_INCOME_TO_REVENUE * revenue:
            v.fail("net_income",
                   f"net_income ({net_income:,.1f}) implausible vs revenue ({revenue:,.1f})")

    return v


def check_against_context(data: dict, context: dict) -> Verdict:
    """Checks needing a value from ANOTHER tool call.

    Balance-sheet facts have no internal anchor -- equity alone is unbounded --
    so plausibility is judged against revenue from the income statement. This is
    still self-consistency (both numbers come from our own tools), not a second
    source."""
    v = Verdict()
    equity, revenue = data.get("equity"), context.get("revenue")
    if isinstance(equity, (int, float)) and isinstance(revenue, (int, float)) and revenue > 0:
        if abs(equity) > MAX_EQUITY_TO_REVENUE * revenue:
            v.fail("equity",
                   f"equity ({equity:,.1f}) implausible vs revenue ({revenue:,.1f})")
    return v


def _evidence(gathered: dict) -> dict:
    """Flatten every numeric value the tools actually returned."""
    out = {}
    for data in gathered.values():
        for key, value in data.items():
            if isinstance(value, (int, float)):
                out[key] = value
    return out


def check_answers(answers: dict, gathered: dict) -> tuple[dict, list[str]]:
    """Drop any answer that does not trace to gathered data.

    Returns (kept_answers, problems). This is the project's core rule made
    executable: if the brief states a number, a tool returned that number.
    """
    evidence = _evidence(gathered)
    kept, problems = {}, []

    for fact, payload in answers.items():
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), (int, float)):
            problems.append(f"{fact}: malformed answer, dropped")
            continue
        value = payload["value"]

        if fact in evidence:
            truth = evidence[fact]
            same = (abs(value - truth) <= MARGIN_TOLERANCE if "margin" in fact
                    else abs(value - truth) <= abs(truth) * MATCH_TOLERANCE)
            if not same:
                problems.append(
                    f"{fact}: answer {value:,.2f} contradicts tool value {truth:,.2f}, dropped")
                continue
            kept[fact] = payload
        elif fact == "net_margin":
            revenue, net_income = evidence.get("revenue"), evidence.get("net_income")
            if revenue in (None, 0) or net_income is None:
                problems.append("net_margin: no evidence to derive it from, dropped")
                continue
            expected = net_income / revenue * 100
            if abs(value - expected) > MARGIN_TOLERANCE:
                problems.append(
                    f"net_margin: {value:,.2f} != net_income/revenue ({expected:,.2f}), dropped")
                continue
            kept[fact] = payload
        else:
            problems.append(f"{fact}: no supporting tool data, dropped")

    return kept, problems
