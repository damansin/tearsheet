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

### Failure modes catalogued (ranked) — these ARE the M2/M3 build targets

| # | Failure mode | Volume | Root cause | Fixed by |
|---|---|---|---|---|
| 1 | **Confabulation of ungathered facts** | ~41 of 43 wrong (cash 19, equity 22) | no balance-sheet tool + no rule against answering beyond evidence | **M2** (planner gathers balance sheet) + **M3** (critic forbids answers unsupported by tool data) |
| 2 | **Tool rigidity on heterogeneous statements** | 12 missing (JPM, BAC, GS) | `get_financials` hardcodes a "Gross Profit" row; banks have none -> `ToolError` kills the whole company | **M2/M3** robustness + recovery (don't let one missing row zero out a company) |
| 3 | **Single-source definitional mismatch** | 2 wrong (COP revenue + cascaded net_margin) | agent's tool (yfinance "total revenue" 54,745) uses a broader definition than the ground-truth source (XBRL "operating revenue" 49,418); +computed facts cascade the error | **M3** cross-source verification (check the agent's number against the filing) |

**Top 2 by volume drive M2/M3.** #1 alone is ~95% of the wrong answers — closing
it is where the accuracy jump comes from. #3 is low-volume but a distinct class
(single-source trust) and a clean motivation for cross-checking against the source.

**Detective notes**
- COP diagnosis: agent revenue 54,745 (yfinance total revenues + other income) vs
  truth 49,418 (XBRL sales & operating revenues). Energy cos have large "other
  income", so the two revenue definitions diverge >1% here where they agreed for
  the other 23. Ground truth left as-is (49,418 is the filed figure); this is a
  real, M3-fixable failure, not a benchmark error.
- Cascading: `net_margin` failed only because `revenue` did. Computed facts
  inherit their inputs' errors — a reason M3 should verify inputs before ratios.

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
