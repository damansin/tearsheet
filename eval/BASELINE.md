# Baseline - measured results

## M3: verification + recovery, measured UNDER DELIBERATE FAILURE

M2 left accuracy at 96.2% with only 5 facts wrong, so "raise accuracy" was not a
milestone: 3.8% of headroom, and the 5 errors were only fixable by consulting
SEC XBRL - which is where our ground truth comes from, so a critic that read it
would be grading itself against its own answer key.

Worse, the benchmark never tested reliability at all. yfinance behaved on all 25
companies, so retry/replan would have had nothing to recover from.

So M3 is measured on a different axis: **reliability under injected failure**.
30% of tool calls are broken on purpose (`--inject-faults --seed 18`), split
across four quadrants: loud (raises) / silent (returns plausible garbage) x
transient (heals on retry) / permanent (never heals).

```bash
python eval/run_agent.py --agent planner --inject-faults --seed 18     --out eval/answers_recovery_faults.json
python eval/run_eval.py --answers eval/answers_recovery_faults.json
```

| Under 30% tool failure | Completion | Fact-accuracy | Hallucination |
|---|---|---|---|
| M2 agent (no critic, no recovery) | 86.9% | 76.9% | 11.5% |
| **+ critic** | 83.8% | 76.9% | **8.3%** |
| **+ critic + recovery** | **90.0%** | **83.1%** | **7.7%** |
| *(same agent, no faults injected)* | *100%* | *96.2%* | *3.8%* |

**M3 net: accuracy +6.2pp, hallucination -3.8pp (a 33% relative cut) under
conditions that break one call in three.**

### Why the critic's accuracy is flat - and why that is the win

The critic converts **wrong -> missing**. A caught corruption is discarded, so a
confident lie becomes an honest gap. The scorer counts both as "not correct", so
accuracy does not move - but hallucination fell 11.5% -> 8.3% and **zero correct
answers were lost**.

Recovery then converts **missing -> correct**. That two-step arc is why
verification and recovery are separate concerns, and it is exactly what the
numbers show.

### What recovery actually reclaimed (8 facts, 0 lost)

| ticker | facts | fault |
|---|---|---|
| AAPL, GOOGL, NKE | cash + equity | loud transient -> retry healed it |
| GS | net_income + net_margin | silent transient: **the critic caught the corruption, retry then healed it** |

The GS case is the point of the whole milestone: neither component alone gets
that fact back. Verification without recovery leaves an honest gap; recovery
without verification never notices anything is wrong, because the tool did not
raise.

### What the critic catches, and what it cannot

| silent corruption | count | caught |
|---|---|---|
| implausible (wrong sign / 10x magnitude) | 4 | **4/4** |
| subtle (value shifted ~15%) | 5 | **0/5** |

The subtle ones are invisible **by construction**: the tool returns a plausible
number, the agent faithfully reports it, and self-consistency confirms the answer
matches the tool. Only a second independent source could catch them, and the only
one available is our ground-truth source. This blind spot is documented at the
top of `src/agent/critic.py` rather than papered over.

### Cost of reliability

| | clean M2 | M3 under faults |
|---|---|---|
| tokens / company | 783 | 740 |
| cost / company | $0.00194 | $0.00182 |
| latency p50 / p95 | 4.06s / 5.75s | 6.07s / 9.58s |

Latency rises ~50%, mostly deliberate retry backoff (1.5s then 3.0s). Tokens and
cost are flat-to-lower: retries add tool calls, not LLM calls, and companies that
fail permanently produce shorter outputs.

### Bugs found while building M3 (each one would have produced a false number)

1. **Retry could never succeed.** v1 of the injector keyed its decision on
   (seed, tool, ticker) only, so a retry got the identical verdict. We would have
   measured recovery as worthless - a lie caused by our own test rig. Fixed by
   adding transient/permanent persistence and a private attempt counter.
2. **A verifier that destroys good data.** The first critic rejected the entire
   tool result when one field failed, killing 3 correct answers (GS revenue, MCD
   equity, PG equity). Fixed with field-level rejection.
3. **Guessed thresholds.** `net_income <= 5x revenue` let GS's 10x corruption
   through (ratio 2.67). The real maximum in the benchmark is 0.955 -> 2.0.
   Equity had no rule at all, so CVX's -1,523,180 passed; real max
   |equity|/revenue is 2.78 (BAC) -> 4.0.
4. **Retry storm.** Retrying with no backoff tripped yfinance's *real* rate
   limiter, contaminating a whole run with failures that had nothing to do with
   the experiment. Retrying without backoff attacks the service you depend on.
5. **The agent retried its tools but not itself.** A single transient
   "Connection error" in the synthesizer's LLM call wiped out all 5 facts for
   Costco, dropping a clean run from 96.2% to 92.3%. Recovery covered tool calls
   only; the agent's own model calls were unprotected. Fixed with a bounded
   retry (3 attempts, same backoff) around every LLM call. Found only because a
   re-run produced a worse number and we chased it instead of re-rolling.

Also nearly shipped: sign rules like "net_income must be positive". BA, INTC and
RIVN lost money; BA and MCD have negative equity; RIVN's margins are negative.
Only revenue and cash are never negative in real filings. **For a verifier, a
false positive is worse than a false negative** - it deletes correct answers.

---


## M2: planner/executor agent (LangGraph) - THE LIFT

```bash
python eval/run_agent.py --agent planner --out eval/answers_planner.json
python eval/run_eval.py --answers eval/answers_planner.json
```

| Metric | M1 naive | + fixed tools | **+ planner (M2)** |
|---|---|---|---|
| Completion | 90.8% | 100.0% | **100.0%** |
| **Fact-accuracy** | 57.7% | 63.1% | **96.2%** |
| **Hallucination** | 36.4% | 36.9% | **3.8%** |
| Tokens / company | 347 | ~347 | 783 (2.3x) |
| Cost / company | $0.00108 | ~same | $0.00194 (1.8x) |
| Latency p50 / p95 | 1.63s / 2.52s | ~same | 4.06s / 5.75s (2.5x) |

**Attribution is clean:** the tool fix bought +5.4pp (bank robustness); the
architecture bought **+33.1pp accuracy** (63.1 -> 96.2) and collapsed
hallucination **36.9% -> 3.8%**.

### Where the lift came from (correct/wrong/missing)

| fact | M1 naive | + tools | + planner |
|---|---|---|---|
| revenue | 21/1/3 | 23/2/0 | 23/2/0 |
| net_income | 22/0/3 | 25/0/0 | 25/0/0 |
| gross_margin | 10/0/0 | 10/0/0 | 10/0/0 |
| net_margin | 21/1/3 | 23/2/0 | 23/2/0 |
| **cash** | 1/19/0 | 1/19/0 | **20/0/0** |
| **equity** | 0/22/3 | 0/25/0 | **24/1/0** |

Cash and equity - the two facts the naive agent invented - went from 1 correct
to 44 correct with **zero** wrong. That is the entire lift. Nothing else moved,
because nothing else was broken.

### What is still wrong (5 facts) - and it is all ONE class

| ticker | fact | agent | truth | cause |
|---|---|---|---|---|
| COP | revenue | 54,745 | 49,418 | yfinance "total revenues + other income" vs XBRL "sales & operating revenues" |
| COP | net_margin | 16.89 | 18.71 | cascades from revenue |
| JPM | revenue | 169,439 | 177,556 | bank revenue: gross vs net of interest expense |
| JPM | net_margin | 34.51 | 32.93 | cascades from revenue |
| UNH | equity | 92,658 | 98,268 | yfinance equity EXCLUDES noncontrolling interests; XBRL tag includes them (yfinance also lists 102,591 as a third variant) |

**Zero confabulation remains.** Every surviving error is a *single-source
definitional mismatch* - the agent faithfully reported what its tool said, and
its tool defines the concept differently than the filing does. That is failure
mode #3 from M1, now the dominant one, and it is exactly what M3's cross-source
verification targets: check the agent's number against the filing, not just
against itself.

### New failure mode the architecture introduced

The first benchmark run scored 87.7% because AMZN and BA returned nothing - a
transient LLM failure inside the synthesizer node was caught into
`state["errors"]`, so the graph returned empty answers and the harness printed
"ok". In M1 a failure raised and was loud; in a graph, **errors become data and
can be silently ignored**. Fixed by having `run_planner` raise when errors
produced no answers and warn on partial failure. Retry/fallback is M3.

### Cost of the lift

Two LLM calls per company instead of one (planner + synthesizer), plus a second
tool call: 2.3x tokens, 1.8x cost, 2.5x latency. Accuracy +33pp for ~2x spend is
a good trade here, but it is a real trade and worth stating.

---


## M1 full baseline (25 companies, 130 facts) — THE "before" number

```bash
python eval/run_agent.py                                  # 22 Haiku calls, ~$0.024
python eval/run_eval.py --answers eval/agent_answers.json
```

| Metric | Value |
|---|---|
| Companies / facts | 25 / 130 |
| **Completion** | **90.8%** (118 attempted) |
| **Fact-accuracy** | **57.7%** (75 correct) |
| **Hallucination rate** | **36.4%** (43 wrong) |
| Latency p50 / p95 | 1.63s / 2.52s |
| LLM calls | 22 (25 companies − 3 banks that failed before reaching the LLM) |
| **Input tokens** | **3,597** → $0.0036 (@ $1.00 / 1M) |
| **Output tokens** | **4,034** → $0.0202 (@ $5.00 / 1M) |
| **Total cost** | **$0.023767 · $0.00108 per company** |

> **Cost insight:** output tokens are ~53% of the volume but **~85% of the cost**,
> because output is priced 5× input. To cut LLM spend, shrink the *response*
> before you shrink the prompt. (Verified against the LangSmith UI to the digit.)

### Ablation: naive agent + FIXED tools (M2 Step 2)

Run after adding `get_balance_sheet` and making `gross_profit` optional, but
BEFORE any architecture change. Isolates what the tool fix alone bought, so the
M2 planner does not get credit for it.

```bash
python eval/run_agent.py --out eval/answers_naive_fixedtools.json
python eval/run_eval.py --answers eval/answers_naive_fixedtools.json
```

| Metric | M1 baseline | Naive + fixed tools | Delta |
|---|---|---|---|
| Completion | 90.8% | **100.0%** | +9.2pp |
| Fact-accuracy | 57.7% | **63.1%** | +5.4pp |
| Hallucination | 36.4% | 36.9% | +0.5pp (unchanged) |

Per fact (correct / wrong / missing):

| fact | M1 baseline | fixed tools |
|---|---|---|
| revenue | 21/1/3 | 23/2/0 |
| net_income | 22/0/3 | **25/0/0** |
| gross_margin | 10/0/0 | 10/0/0 |
| net_margin | 21/1/3 | 23/2/0 |
| cash | 1/19/0 | **1/19/0** (identical) |
| equity | 0/22/3 | **0/25/0** |

**The lesson: a capability that exists but is never invoked changes nothing.**
The tool fix removed the bank failure (completion 90.8 -> 100%, no facts
missing), but cash/equity accuracy is byte-for-byte unchanged, because the naive
agent's hard-coded pipeline never calls `get_balance_sheet`. Equity went from
22 wrong + 3 missing to 25 wrong: the banks stopped dying and started
confabulating along with everyone else.

Closing that gap is precisely the planner's job in M2 Step 3 - deciding to
gather balance-sheet data. Attribution is now clean: tool fix = +5.4pp
(robustness), architecture = whatever Step 4 measures on top of 63.1%.

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
