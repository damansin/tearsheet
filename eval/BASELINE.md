# Baseline — naive agent

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
