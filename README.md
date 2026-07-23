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

> 🚧 **Work in progress.** M0 and M1 complete; M2 (planner/executor) next.

---

## Results

Measured on a 25-company benchmark (130 ground-truth facts pulled from SEC XBRL
filings, pinned to FY2024).

| Stage | Fact-accuracy | Hallucination rate | Completion |
|---|---|---|---|
| **M1 — naive agent (baseline)** | **57.7%** | **36.4%** | 90.8% |
| M2 — planner / executor | _pending_ | _pending_ | _pending_ |
| M3 — verification + recovery | _pending_ | _pending_ | _pending_ |

Cost/latency at baseline: **$0.0238** for the full 25-company run
(**$0.00108/company**), p50 **1.63s**, p95 **2.52s**.

### Why the naive agent scores 57.7%

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

### Failure modes → what fixes them

| # | Failure mode | Share of errors | Fixed by |
|---|---|---|---|
| 1 | Confabulating facts it never gathered | ~95% | M2 (gather) + M3 (verify) |
| 2 | Tool rigidity on heterogeneous filings (banks) | 12 facts missing | M2/M3 robustness |
| 3 | Single-source trust (yfinance vs filing definitions) | 2 facts | M3 cross-checking |

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
- **CI enforces an accuracy floor** (`--min-accuracy`) that exits non-zero on a
  regression, and the floor ratchets up as the metric improves.

## Quickstart

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env                             # add ANTHROPIC_API_KEY (+ LangSmith keys)

pytest                                           # 16 tests, no network/keys needed
python -m src.agent.run --ticker AAPL            # one company
python eval/run_agent.py                         # run the benchmark (~$0.024)
python eval/run_eval.py --answers eval/agent_answers.json
python eval/build_ground_truth.py                # regenerate ground truth from SEC
```

## Stack

Python 3.11+ · **LangGraph** (orchestration, M2+) · **Claude** (Haiku for the
eval loop, larger models for planning/verification) · **yfinance** + **SEC
EDGAR/XBRL** · **LangSmith** (tracing, cost, latency) · pytest + GitHub Actions
(the eval gate) · FastAPI + pgvector (later milestones).

## Project layout

```
src/agent/      planner, executor, critic, replanner (naive agent today)
src/tools/      yfinance wrapper (typed, raises ToolError)
eval/benchmark/ 25 companies of SEC-sourced ground truth
eval/run_eval.py       scorer + CI accuracy gate
eval/run_agent.py      runs the agent across the benchmark
eval/build_ground_truth.py   regenerates ground truth from SEC XBRL
eval/BASELINE.md       measured results + failure catalogue
```
