# Tearsheet

A long-horizon multi-agent system that produces **verified, sourced** company
due-diligence briefs.

Given a company, Tearsheet plans the research, gathers data across financial
sources, **verifies every claim against the source data**, and recovers when
steps fail — producing a brief where each factual claim is traceable.

It is a research and analysis tool. It surfaces verified facts and does **not**
provide investment advice.

**The point of this project is reliability, measured.** Not "here's a demo that
looks good" — here's a benchmark, a baseline, and the numbers moving.

> 🚧 **Work in progress.** M0–M3 complete; M4 (memory + context) next.

---

## Results

Measured on a 25-company benchmark (130 ground-truth facts pulled from SEC XBRL
filings, pinned to FY2024).

**On a clean run** (tools behaving):

| Stage | Fact-accuracy | Hallucination rate | Completion |
|---|---|---|---|
| **M1 — naive agent (baseline)** | 57.7% | 36.4% | 90.8% |
| **M2 — planner / executor (LangGraph)** | **96.2%** | **3.8%** | **100.0%** |

**Under 30% deliberate tool failure** (M3 — the reliability test):

| Stage | Fact-accuracy | Hallucination rate | Completion |
|---|---|---|---|
| M2 agent (no verification, no recovery) | 76.9% | 11.5% | 86.9% |
| + critic (verification) | 76.9% | **8.3%** | 83.8% |
| **+ recovery (bounded retry)** | **83.1%** | **7.7%** | **90.0%** |

**M2 in one line:** splitting the agent into planner → executor → synthesizer,
and forbidding the synthesizer from reporting anything it did not gather, took
fact-accuracy from **57.7% → 96.2%** and hallucination from **36.4% → 3.8%**.

**M3 in one line:** a clean run cannot measure reliability — so 30% of tool calls
are broken on purpose, and verification + recovery claw accuracy back from
**76.9% → 83.1%** while cutting hallucination **11.5% → 7.7%** (a 33% relative
reduction) under conditions that break one call in three.

**Why the critic's accuracy is flat but it still matters:** verification converts
*wrong → missing* (a confident lie becomes an honest gap; zero correct answers
lost). Recovery then converts *missing → correct*. Neither alone gets there —
Goldman Sachs' net income came back only because the critic **caught** the
corruption and retry then **healed** it.

Cost/latency: naive **$0.00108**/company, p50 1.63s · planner **$0.00194**/company,
p50 4.06s.

### What M2 fixed, and what it did not

Cash and equity — the two facts the naive agent had no tool for and therefore
invented — went from **1 correct out of 45** to **44 correct, zero wrong**. That
single change is the entire lift; nothing else moved, because nothing else was
broken.

All **5 remaining errors are one class**: single-source definitional mismatches
(COP revenue, JPM revenue, UNH equity — plus two cascaded margins). The agent
faithfully reports what its tool says; its tool defines the concept differently
than the filing does. **Zero confabulation remains.** That is what M3's
cross-source verification targets.

### Why the naive agent scored 57.7%

The failure signature is not random — it's structural:

| fact | correct | wrong | why |
|---|---:|---:|---|
| revenue, net_income, gross_margin | 53 | 1 | the agent **fetches** these |
| net_margin | 21 | 1 | the agent **computes** it |
| **cash** | **1** | **19** | **never fetched → confabulated** |
| **equity** | **0** | **22** | **never fetched → confabulated (0/22)** |

**What it gathers, it gets right (~97%). What it doesn't gather, it invents
(~2% right).** Asked for balance-sheet facts it has no tool for, the agent
produces confident, plausible, wrong numbers rather than admitting ignorance.

Plus 3 banks (JPM, BAC, GS) fail outright: the tool hard-codes fetching a
"Gross Profit" row, which banks don't have — one missing row zeroes out the
whole company.

### Failure modes → what fixed them

| # | Failure mode | Fixed by | Result |
|---|---|---|---|
| 1 | Confabulating facts it never gathered | M2 planner gathers them | cash/equity: 1 correct → 44 |
| 2 | Tool rigidity on heterogeneous filings (banks) | M2 optional gross profit | banks stopped dying |
| 3 | Silent corruption (implausible values) | M3 critic | 4/4 caught |
| 4 | Transient tool failures | M3 bounded retry | 8 facts recovered |
| 5 | **Subtle corruption (~15% shift)** | **unfixed** | 0/5 caught — needs a second source, which would be circular here |
| 6 | Single-source definitional mismatch (COP/JPM/UNH) | **unfixed** | same circularity constraint |

Full detail: [`eval/BASELINE.md`](eval/BASELINE.md).

---

## How it's measured

- **Ground truth** comes from **SEC XBRL** (the actual filed numbers), so it's
  independent of yfinance — the agent's own data source. Otherwise the eval
  would be circular. See [`eval/benchmark/README.md`](eval/benchmark/README.md).
- Facts are **pinned to a period-end date**, not an "FY2024" label — different
  sources label fiscal years differently, and the date is unambiguous.
- **Per-fact tolerances**: ±1% for reported figures, ±0.5pp for percentages —
  loose enough to absorb rounding, tight enough to catch a real misstatement.
- The **scorer was calibrated against known-verdict fixtures before the agent
  existed**, so a bad score means a bad agent, not a broken measuring stick.
- **Reliability is tested by breaking things on purpose** — a deterministic fault
  injector fails 30% of tool calls (loud/silent × transient/permanent), so
  recovery has something real to recover from and both runs face identical faults.
- **CI enforces an accuracy floor** (`--min-accuracy`) that exits non-zero on a
  regression, and the floor ratchets up as the metric improves.

## Quickstart

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env                             # add ANTHROPIC_API_KEY (+ LangSmith keys)

pytest                                           # 38 tests, no network/keys needed
python -m src.agent.run --ticker AAPL            # one company
python eval/run_agent.py --agent planner         # run the benchmark (~$0.05)
python eval/run_eval.py --answers eval/answers_planner.json
python eval/build_ground_truth.py                # regenerate ground truth from SEC
```

## Stack

Python 3.11+ · **LangGraph** (orchestration, M2+) · **Claude** (Haiku for the
eval loop, larger models for planning/verification) · **yfinance** + **SEC
EDGAR/XBRL** · **LangSmith** (tracing, cost, latency) · pytest + GitHub Actions
(the eval gate) · FastAPI + pgvector (later milestones).

## Project layout

```
src/agent/      graph.py = LangGraph planner/executor/critic/recovery/synthesizer
                critic.py = verification (sanity, cross-field, answer-vs-evidence)
                naive.py = the M1 baseline, kept for A/B
src/tools/      yfinance wrappers + faults.py (deliberate fault injection)
eval/benchmark/ 25 companies of SEC-sourced ground truth
eval/run_eval.py       scorer + CI accuracy gate
eval/run_agent.py      runs the agent across the benchmark
eval/build_ground_truth.py   regenerates ground truth from SEC XBRL
eval/BASELINE.md       measured results + failure catalogue
```
