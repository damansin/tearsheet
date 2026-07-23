# Baseline — naive agent

## M1 full baseline (25 companies, 130 facts) — THE "before" number

```bash
python eval/run_agent.py                                  # 25 Haiku calls, ~$0.02
python eval/run_eval.py --answers eval/agent_answers.json
```

| Metric | Value |
|---|---|
| Companies / facts | 25 / 130 |
| **Completion** | **90.8%** (118 attempted) |
| **Fact-accuracy** | **57.7%** (75 correct) |
| **Hallucination rate** | **36.4%** (43 wrong) |
| Latency p50 / p95 | 1.63s / 2.52s |
| Tokens/run · cost | ~347 · ~$0.019 total |

### Accuracy by fact — the thesis in one table

| fact | correct | wrong | missing | note |
|---|---:|---:|---:|---|
| revenue | 21 | 1 | 3 | agent fetches it |
| net_income | 22 | 0 | 3 | agent fetches it |
| gross_margin | 10 | 0 | 0 | agent fetches it (only 10 cos have it) |
| net_margin | 21 | 1 | 3 | agent computes it |
| **cash** | **1** | **19** | 0 | **NOT fetched -> confabulated** |
| **equity** | **0** | **22** | 3 | **NOT fetched -> confabulated (0/22 right)** |

**The lesson:** the 4 facts the agent gathers/computes are ~97% correct; the 2 it
doesn't gather are ~2% correct. **Reliability tracks whether the agent actually
fetched the data** — everything else it invents, confidently. `equity` was
hallucinated 22/22 times and never once correct.

### Failure modes catalogued (ranked)
1. **Confabulation of ungathered facts (dominant, ~41 of 43 wrong).** The agent
   has no balance-sheet tool, but the prompt asks for cash + equity, so it makes
   up plausible numbers instead of admitting it lacks them. -> Fix: M2 planner
   gathers balance-sheet data; M3 critic forbids answering beyond tool data.
2. **Bank tool failure (JPM, BAC, GS -> 12 missing facts).** `get_financials`
   hardcodes fetching a "Gross Profit" row; banks have none -> `ToolError` ->
   whole company yields nothing. -> Fix: M2/M3 robustness to heterogeneous
   statements.
3. **1 revenue miss (+ its net_margin)** — a single company where the agent's
   value fell outside tolerance. Investigate in Step 5 (likely yfinance vs XBRL
   definitional gap).

---

## M1 update (period-aware tool)

Making `get_financials` accept a target `fiscal_year` (M1 Step 1) — with no
other change — moved the 2-company baseline from **0% -> 100% accuracy**. This
confirms the M0 failure was entirely the tool's inability to fetch the requested
year, not agent reasoning. This 100% is on 2 clean mega-caps with 3 copy-paste
facts; the meaningful low baseline returns once M1 adds messy companies
(banks, loss-makers) and harder facts. Everything below is the original M0 run,
kept for the record.

---

# M0 Baseline — naive agent (original, pre-period-fix)

First measured run of the naive agent against the ground-truth benchmark.
Reproduce with:

```bash
python eval/run_agent.py
python eval/run_eval.py --answers eval/agent_answers.json
```

## Result

| Metric | Value |
|---|---|
| Companies | 2 (AAPL, MSFT) |
| Facts required | 6 |
| **Completion** | **100.0%** |
| **Fact-accuracy** | **0.0%** |
| **Hallucination rate** | **100.0%** |

The agent attempted every fact and got every one wrong — the worst possible
trust profile. Completion alone would have read as "success"; only accuracy and
hallucination rate expose the truth. This is why the three metrics are tracked
separately.

## What it actually answered

| ticker | fact | agent | truth (FY2024) | delta |
|---|---|---|---|---|
| AAPL | revenue | 416,161 | 391,035 | +6.4% |
| AAPL | net_income | 112,010 | 93,736 | +19.5% |
| AAPL | gross_margin | 46.9 | 46.2 | +0.7pp |
| MSFT | revenue | 281,724 | 245,122 | +14.9% |
| MSFT | net_income | 101,832 | 88,136 | +15.5% |
| MSFT | gross_margin | 68.8 | 69.8 | -0.9pp |

## Failure modes catalogued

**#1 — Period mismatch (root cause of all 6 failures).**
`get_financials` returns the most recent annual report (FY2025); the benchmark
is pinned to FY2024. The agent has no step that reconciles the period it
*received* with the period it was *asked about*, so it reported real, verifiable,
correctly-formatted numbers — for the wrong fiscal year.

This is a textbook **silent failure**: nothing errored, the output is
well-formed, and the values are genuinely Apple's and Microsoft's. A human
skimming the brief would not catch it. That is precisely why a self-consistency
/ verification step (M3) is the core of this project rather than a nice-to-have.

**Not observed at this scale (expect in M1):** tool errors, unparseable model
output, fabricated values. With only 2 companies and a single well-behaved data
source, the naive agent never hit them.

## Notes

- The LLM was *faithful* here — it copied the fetched numbers accurately. The
  failure is agent-design (no period reconciliation), not model hallucination.
  The metric name "hallucination rate" measures *claims contradicting ground
  truth*, regardless of which layer produced the error.
- Observability: a run traces as 3 spans (chain -> tool + llm), ~2.3s, ~251
  tokens. LLM call is ~65% of latency.
