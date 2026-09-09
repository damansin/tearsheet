# Tearsheet

**An eval and reliability harness for LLM agents.**

The question it exists to answer: *how do you know an agent can be trusted?*

Not "does the demo look good" — a benchmark with verifiable ground truth, a
scorer calibrated before the agent existed, deliberate fault injection, and a CI
gate that fails the build when quality regresses.

The agent under test produces sourced company due-diligence briefs. **Finance is
the test domain, not the product.** It was chosen because financial facts are
checkable against filed documents, which makes "correct" a measurable thing
rather than a matter of opinion — and that is the only reason any number below
means anything.

*(Research and analysis only. It surfaces verified facts and does **not** provide
investment advice.)*

---

## The instrument was built first

Every design decision here exists to stop the measurement from lying to me.

- **Ground truth is independent of the agent's data source.** Truth comes from
  **SEC XBRL** — the actual filed numbers. The agent fetches from **yfinance**.
  Two different sources on purpose: if the agent read the same place the answer
  key came from, the eval would be circular and the score would mean nothing.
- **The scorer was calibrated against known-verdict fixtures before any agent
  existed**, so a bad score means a bad agent, not a broken measuring stick.
- **Three metrics, three denominators**, because *missing* and *wrong* are
  different sins: completion (`attempted/required`), fact-accuracy
  (`correct/required`), hallucination (`wrong/attempted`).
- **Facts are pinned to a period-end date**, not an "FY2024" label — sources
  label fiscal years differently; a date is unambiguous.
- **Per-fact tolerances**: ±1% for reported figures, ±0.5pp for percentages —
  loose enough to absorb rounding, tight enough to catch a real misstatement.
- **Reliability is tested by breaking things on purpose.** A deterministic
  injector fails **30% of tool calls**, split across loud (raises) / silent
  (returns plausible garbage) × transient (heals on retry) / permanent. Both
  arms of a comparison face identical faults, so the delta is attributable.
- **CI gates on the quality metric**, not just on tests: `--min-accuracy` exits
  non-zero, and the floor ratchets up as the metric improves.

## The agent under test

A LangGraph state graph. One state dict flows through every node; each returns
only what it changed.

```
START → planner → executor → critic ──ok, steps left──→ executor
                     ▲          │
                     │          ├──ok, done──→ synthesizer → verifier → END
                     └─recovery─┘  (failed, retries left)
```

| node | job |
|---|---|
| **planner** | decides which tools to call; invented tool names are filtered out |
| **executor** | runs the step — cache first, then the real tool; a raise is recorded, not fatal |
| **critic** | is this value *possible*? plausible beside the other data? passes → cached |
| **recovery** | re-queues a failed step, bounded to 2 retries with backoff, then gives up cleanly |
| **synthesizer** | assembles the answer **from gathered data only** — omit rather than estimate |
| **verifier** | every number must trace to *this run's* tool output, or it's dropped |

The critic and verifier both convert **wrong → missing**. Recovery converts
**missing → correct**. Neither gets there alone.

---

## Results

25 companies · 130 ground-truth facts from SEC XBRL, pinned to FY2024.

**Clean run** (tools behaving):

| Stage | Fact-accuracy | Hallucination | Completion |
|---|---|---|---|
| naive agent (baseline) | 57.7% | 36.4% | 90.8% |
| **planner / executor (LangGraph)** | **96.2%** | **3.8%** | **100.0%** |

**Under 30% deliberate tool failure** — the reliability test:

| Stage | Fact-accuracy | Hallucination | Completion |
|---|---|---|---|
| same agent, no verification, no recovery | 76.9% | 11.5% | 86.9% |
| + critic (verification) | 76.9% | **8.3%** | 83.8% |
| **+ recovery (bounded retry)** | **83.1%** | **7.7%** | **90.0%** |

**The lift is attributed, not claimed.** An ablation run after fixing the tools
but *before* changing the architecture scored 63.1%. So the tool fix was worth
**+5.4pp** and the architecture **+33.1pp** — separable only because the middle
step was measured.

**Why the critic's accuracy is flat, and why that's the win:** verification turns
a confident lie into an honest gap. The scorer counts both as "not correct", so
accuracy doesn't move — but hallucination fell 11.5% → 8.3% with **zero correct
answers lost**. Recovery then closes the gap. Goldman Sachs' net income came back
only because the critic **caught** the corruption and retry then **healed** it;
neither component alone recovers that fact.

Cost/latency: **$0.00194**/company, p50 4.06s. Full detail and the failure
catalogue: [`eval/BASELINE.md`](eval/BASELINE.md).

---

## What is still broken

Stated up front, because a harness that only reports its wins isn't a harness.

| # | Failure mode | Status |
|---|---|---|
| 1 | Confabulating facts it never gathered | **fixed** — cash/equity went 1 correct → 44, zero wrong |
| 2 | Tool rigidity on heterogeneous filings (banks have no gross profit) | **fixed** |
| 3 | Silent corruption, implausible values | **fixed** — 4/4 caught |
| 4 | Transient tool failures | **fixed** — 8 facts recovered, 0 lost |
| 5 | **Subtle corruption (~15% shift)** | **unfixed — 0/5 caught** |
| 6 | **Single-source definitional mismatch** (COP/JPM/UNH) | **unfixed** |

**5 and 6 are the same structural limit**, and it's worth being precise about it.
A subtly wrong value is plausible to the critic, faithfully reported by the
synthesizer, and *matches the tool* for the verifier — it passes every check,
because every check is a form of self-consistency. Catching it needs a **second
independent source**, and the only one available is SEC XBRL, which is where the
ground truth comes from. Using it would mean grading the agent against its own
answer key.

So it stays broken, measured, and documented at the top of
[`src/agent/critic.py`](src/agent/critic.py) rather than quietly patched. A real
number with a known blind spot beats a better number that means nothing.

The sharpest version: two of those subtle faults were *transient* — a retry would
have fixed them. They stayed wrong because nothing detected they needed
retrying. **Detection is the bottleneck, not recovery.**

## Human in the loop

Verification produces honest blanks instead of confident lies — but a blank is
still a dead end. So every fact the agent failed to deliver becomes a **review
queue** row, tagged with *why* it is open:

| reason | what the reviewer should do |
|---|---|
| `tool_failed` | the tool kept failing after its retries — fix it, or look the number up |
| `rejected_by_critic` | a value arrived but was impossible — the source is lying; read the filing |
| `dropped_by_verifier` | the tool had it and the answer didn't survive — a synthesizer bug, not a data gap |
| `not_gathered` | nothing ever attempted it — a planning gap |
| `derived` | computed from other facts; fix those instead |

**The agent only escalates where it already admitted it didn't know** — not "have
a human check everything", which would defeat the point of automating any of it.
Its own uncertainty is the trigger, which is only possible because of the critic
and the retry budget: *you cannot escalate a failure you never detected.*

A queue, not a blocking interrupt: pausing mid-run is right for one interactive
session and wrong for a 25-company batch, where the whole thing stops dead on
company 3.

Two rules, both borrowed from the agent itself:

- **No claim without a citation.** A human may not enter a number they can't
  trace to a filing, for the same reason the agent may not report one it can't
  trace to a tool result. A looser standard for the person would make the human
  the weakest link in a system built for traceability.
- **Derived facts are never hand-entered.** A typed-in margin can contradict the
  revenue and net income beside it — the exact failure this project prevents.
  They're recomputed from their inputs instead.

**And the metric stays honest.** Human answers are tagged `source: human`,
provenance propagates through derived facts, and the scorer **excludes them by
default** — otherwise anyone could reach 100% by typing in the answer key, the
same circularity trap as letting the critic read filings. Verified: a merged
answers file scores identically to the agent's own output. Combined coverage is
available behind `--include-human`, labelled as coverage, never as accuracy.

---

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env                             # ANTHROPIC_API_KEY (+ LangSmith keys)

pytest                                           # 75 tests, no network or keys needed
```

**The harness:**

```bash
python eval/run_agent.py --agent planner                    # run the agent (~$0.05)
python eval/run_eval.py --answers eval/answers_planner.json # score it
python eval/run_agent.py --inject-faults --seed 18          # break 30% of tool calls
python eval/build_ground_truth.py                           # rebuild truth from SEC XBRL
```

**Human review:**

```bash
python eval/run_agent.py --review-queue eval/review_queue.json
python eval/resolve_review.py --list        # what needs attention, and why
python eval/resolve_review.py               # work through it
python eval/resolve_review.py --merge ANSWERS --out MERGED
```

**Verified-fact cache** — a filed fiscal year is immutable, so a result that
already passed verification can be reused. It is written by the **critic**, never
the executor: caching on "the tool didn't throw" would persist the silent
corruptions the critic exists to catch and re-serve them forever, promoting a
transient fault into a permanent one.

```bash
python eval/run_agent.py --cache                 # reuse verified results
python eval/run_agent.py --cache --clear-cache   # force a cold run for measuring
```

`--cache` with `--inject-faults` is **refused**: a cached good value would
silently repair the faults the run exists to measure.

Single company: `python -m src.agent.run --ticker AAPL`

## Stack

Python 3.11+ · **LangGraph** (orchestration) · **Claude** (Haiku) · **yfinance**
(agent's data) + **SEC EDGAR/XBRL** (ground truth) · **LangSmith** (tracing,
cost, latency) · SQLite (verified-fact cache) · pytest + GitHub Actions (the
quality gate).

## Layout

**The harness** — the instrument, and the part that generalises:

```
eval/benchmark/            25 companies of SEC-sourced ground truth
eval/build_ground_truth.py rebuilds it from the SEC XBRL API
eval/run_eval.py           scorer + CI accuracy gate
eval/run_agent.py          drives the agent across the benchmark
eval/resolve_review.py     human review: resolve, cite, merge
eval/BASELINE.md           every measured result + the failure catalogue
src/tools/faults.py        deterministic fault injection (inert unless enabled)
```

**The agent under test** — the subject:

```
src/agent/graph.py    LangGraph: planner/executor/critic/recovery/synthesizer
src/agent/critic.py   verification: sanity, cross-field, answer-vs-evidence
src/agent/review.py   classifies each unresolved fact for escalation
src/agent/naive.py    the original baseline, kept for A/B
src/tools/            yfinance wrappers
src/memory/cache.py   SQLite cache of VERIFIED facts (written by the critic)
```

`faults.py` sits under `src/tools/` because it has to wrap the tools the agent
calls — but the agent cannot observe it: the wrapper is a no-op unless enabled,
and fault state is private, so a transient/permanent label can never leak into a
decision.
