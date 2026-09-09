# CLAUDE.md — Tearsheet

Full project context for Claude Code. This is the single source of truth for what Tearsheet is, why it's built this way, and how to work on it.

---

## 1. What this is

**An eval and reliability harness for LLM agents** — answering *how do you know an agent can be trusted?* Finance is the **test domain, not the product**: it was chosen because financial facts are checkable against filed documents, which is what makes "correct" measurable rather than a matter of opinion. The harness (independent ground truth, a pre-calibrated scorer, fault injection, a CI quality gate) is the instrument; the agent below is what it was pointed at.

The agent under test is a long-horizon multi-agent system that takes a company and autonomously produces a **verified, sourced due-diligence brief**. It plans the research, executes it across financial-data tools, **verifies every step against the source data**, and recovers when steps fail — producing a structured analyst brief where every factual claim is traceable to a source.

It is a **research and analysis tool**. It surfaces verified facts. It does **not** give investment advice, recommendations, or price predictions.

**The differentiator is reliability over many steps + observability — not the brief itself.** Success is measured against ground-truth facts, not vibes. The headline question the project answers: *how much does verification and recovery actually improve task completion?*

## 2. What it produces (the task)

Input: a company (ticker + fiscal year).

**What it actually produces**, six facts per company, each traceable to a tool
result: `revenue`, `net_income`, `gross_margin`, `net_margin`, `cash`, `equity`.

**Scope was cut deliberately, and the reason is the same each time:** the original
plan also listed P/E and debt ratios, trend summaries, risk flags from filings,
and recent news. Every one of those was dropped because it could not be *scored*.
Price-dependent ratios need a pinned price snapshot; risk flags and news have no
verifiable ground truth to grade against. Adding unmeasurable output to a project
whose entire point is measurement would have been the wrong trade — a wider brief
nobody could check. Six checkable facts across 25 companies beats twenty
uncheckable ones.

## 3. Why this shape (design logic)

- **Verifiable ground truth.** Revenue, margins, ratios have correct values checkable against a source — so task success is *measurable*, which is what makes the eval/recovery story real.
- **Genuinely long-horizon.** fetch price → fetch financials → fetch filings → compute ratios → cross-check → gather news → synthesize → cite. Many steps = many places to fail and recover. That recovery work is the hard, frontier part and the whole point.
- **Great failure modes to engineer around.** The classic one: the agent states revenue is $40B when the filing says $36B. That's a hallucination catchable with a self-consistency check ("the answer must not contradict tool outputs"). Concrete to demo, concrete to talk about.

## 4. Architecture (LangGraph state graph)

- **Planner** — decides which tools to call; invented tool names are filtered out.
- **Executor** — runs the step: cache first, then the real tool. A raise is recorded, not fatal.
- **Critic** — after each step: is this value *possible*? plausible beside the other data? A clean verdict is what admits it to the cache.
- **Recovery** — re-queues a failed step, bounded to 2 retries with backoff, then gives up cleanly (an honest blank, never a guess).
- **Synthesizer** — assembles the answer **from gathered data only**; omit rather than estimate.
- **Verifier** — every number in the answer must trace to *this run's* tool output, or it is dropped.

```
START → planner → executor → critic ──ok, steps left──→ executor
                     ▲          │
                     │          ├──ok, done──→ synthesizer → verifier → END
                     └─recovery─┘  (failed, retries left)
```

**Replanning was scoped but not built, on evidence.** With two tools and every
step required, there is nothing for a replanner to revise — no alternative route
to the same fact. Recovery here is retry plus bounded give-up, and the docs say
so rather than dressing it up as replanning.

## 5. The hard part (the depth this project is built to show)

Making that loop **reliable over many steps**. Concretely:
1. **Failure detection** — distinguish success / loud failure (tool errored) / silent failure (plausible garbage).
2. **Recovery & replanning** — retry, try a different approach, or revise the plan.
3. **Context engineering** — decide what state to carry forward so late steps still have what they need without drowning in earlier transcript.
4. **Measurement** — benchmark of 20–30 companies with known-correct facts; track completion rate, failure location, cost, latency, hallucination rate.

## 6. Observability (baked in, not bolted on)

Wire tracing in at M0, not later. Every run emits a trace + metrics: steps taken, p50/p95 latency, cost-per-run (and per-step), and quality metrics (fact-accuracy, hallucination rate). A **CI regression gate** runs the benchmark on every PR and blocks merges that regress. Use LangSmith or Arize Phoenix for this — **do not rebuild it.**

## 7. Stack

*What is actually in use — items dropped along the way are marked, with the reason, because "why didn't you use X" is a fair question.*

- Python 3.11+, venv + pip
- **LangGraph** — orchestration (state graph)
- **Claude Haiku** — planner + synthesizer
- **yfinance** — the agent's data source
- **SEC EDGAR / XBRL** — ground truth ONLY. The agent never reads it; that separation is what keeps the eval from being circular.
- **SQLite** — the verified-fact cache
- **LangSmith** — observability (use, don't rebuild)
- **pytest + GitHub Actions** — the CI eval gate

Dropped, deliberately:
- **PostgreSQL + pgvector** — no query needed it. Runs are 2 tool calls deep; adding a vector DB because the stack list mentioned it would be theatre.
- **FastAPI viewer** — a good README plus real LangSmith traces is the demo path.
- **MCP tool wrapping** — direct Python wrappers were enough at two tools.
- **News API** — the benchmark scores numeric facts against filings; news has no verifiable ground truth, so it could not be measured.

## 8. Repo structure (proposed — adjust as it stabilizes)

```
src/            # THE AGENT UNDER TEST
  agent/        # planner, executor, critic, recovery, synthesizer, graph
  tools/        # yfinance wrappers + faults.py (fault injection)
  memory/       # cache.py — SQLite store of VERIFIED facts
eval/           # THE HARNESS
  benchmark/    # 25 companies + ground-truth facts from SEC XBRL
  run_eval.py   # scores completion, fact-accuracy, hallucination + CI gate
  run_agent.py  # drives the agent across the benchmark
  resolve_review.py  # human-in-the-loop: resolve, cite, merge
tests/
.github/workflows/  # CI eval gate
```

Tracing is done with LangSmith decorators at the call sites (`@traceable`,
`wrap_anthropic`), not in a separate module — there was no `observability/` code
worth having, so the empty package was removed. `api/` (FastAPI viewer) was
dropped in M5: a good README plus real LangSmith traces is the demo path.

## 9. Milestones (full plan)

Detailed *implementation* for each milestone is worked out in conversation when that milestone starts — the descriptions below are scope + "done" criteria, not step-by-step plans.

**Status: M0–M4 complete and measured; M5 framing done. See README for results.**

**M0 — Walking skeleton (thin end-to-end slice)** `[x]`
- Goal: prove the whole loop end-to-end on a TINY scale before gold-plating anything. Build the eval scorer + a tiny 2–3 company ground-truth benchmark + repo/observability scaffolding + a dead-simple naive agent — wired together so one company runs start-to-finish and gets scored.
- Why this shape (chosen over pure benchmark-first): still honors "measure before you trust" — the scorer and ground truth exist *before* the agent is trusted — but you watch the agent actually fail before designing the full benchmark, so you don't curate 20–30 companies blind. De-risks scope, fastest learning.
- Done when: `run_eval.py` scores a real (bad) agent run on the tiny benchmark; one trace is visible in the observability UI; CI runs the eval.
- Then: scale the benchmark to 20–30 companies in M1 with what you learned.

**M1 — Full benchmark + baseline numbers**
- Goal: scale the benchmark to 20–30 companies using the schema proven in M0, and record the naive agent's baseline (no recovery) across all of them. It will do badly — that's the point.
- Done when: 20–30 companies with ground-truth facts exist, and the baseline completion rate + hallucination rate are recorded (e.g. ~25%).

**M2 — Planner / executor split**
- Goal: separate planning from execution. Planner decomposes the goal into steps; executor runs them in sequence.
- Done when: planner produces step plans, executor runs them, and the lift over the M1 baseline is measured.

**M3 — Verification + recovery + replanning** *(the core — ~60% of the real learning)*
- Goal: detect step failures (loud and silent), recover (retry / fallback / alternative approach), and replan when the plan breaks. Self-consistency checks so output can't contradict tool data.
- Done when: completion rate jumps materially, the dominant failure modes are catalogued, and recovery is shown to drive the metric up.

**M4 — Reliability plumbing** *(rescoped; original scope deliberately dropped)*
- Originally: persistent memory + context engineering + pgvector. **Dropped, on evidence.** Runs are 2 tool calls and 2 LLM calls deep — nothing is drowning in transcript, so there is no context problem to engineer and pgvector would be a database added because the stack list mentioned it. "I didn't build it because the data didn't justify it" is the honest answer, and it is only sayable because the metrics were there to check.
- **M4a — verified-fact cache.** Reuse results that already passed verification, since a filed fiscal year is immutable. The write is issued by the *critic*, never the executor: caching on "the tool didn't throw" would persist the silent corruptions M3 exists to catch. Refused alongside `--inject-faults`. Buys latency, not cost.
- **M4b — human in the loop.** Every unresolved fact becomes a queue row tagged with *why*, and a person supplies a value **with a citation** or marks it unobtainable. The agent only escalates where it already admitted it didn't know — which is only possible because the critic and retry budget produce honest blanks. Human answers are tagged and **excluded from scoring by default**, so they can never inflate agent accuracy.
- Done when: both are wired, tested, and the scorer provably reports the same number with and without human contributions. ✅

**M5 — Polish + writeup**
- Goal: demo, trace viewer, README with the results table filled in, and a blog post telling the headline story.
- Done when: someone can run it in ~5 minutes, the metrics table is populated, and the writeup is published.

**Headline result driving the whole project:**
> "Naive agent ~25% → with recovery/replanning ~78% task completion. Here are the top 3 failure modes I engineered around."

## 10. Design principles (do not violate)

- **Verify before trusting.** Every factual claim in the output must trace to a tool result. If the brief says a number, a tool returned that number. The self-consistency check (answer must not contradict tool outputs) is core, not optional.
- **Recovery is the product.** Steps WILL fail (API errors, missing data, silent garbage). Detect, then retry / fallback / replan — never charge ahead on broken assumptions.
- **Measure everything.** Each run emits a trace + metrics. Metrics changes are how we know we improved.
- **Observability is baked in, not added later.** Wire tracing at M0.
- **Simple over clever.** Prefer readable code I can fully explain over abstractions I can't.

## 11. How to work with me (important)

- I'm building this to LEARN the stack deeply for interviews. Do NOT one-shot whole milestones or dump large code blocks.
- Work in small, reviewable steps. Explain the *why* behind design choices — especially in M3 (recovery/replanning).
- Before implementing anything using a concept I may not know (LangGraph state, MCP servers, context engineering, eval design), explain the concept briefly first.
- Use planning mode before any large change. Commit per milestone.
- Push back if I'm about to make a weak call. Direct and honest over agreeable.
- Treat me like a strong junior engineer you're mentoring, not a customer you're delivering to.

## 12. Guardrails

- No investment advice (no buy/sell/hold, no price prediction). Research/analysis only.
- Free data sources only (yfinance, SEC EDGAR, free news tier). Don't add paid APIs without asking.

## 13. Commands (keep accurate as they stabilize)

- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e .`
- Run agent on one company: `python -m src.agent.run --ticker AAPL`
- Run benchmark/eval: `python eval/run_eval.py`
- Reuse verified facts (M4a cache): add `--cache` to either runner; `--clear-cache`
  forces a cold run. Refused alongside `--inject-faults`.
- Human review: `python eval/run_agent.py --review-queue eval/review_queue.json`,
  then `python eval/resolve_review.py --list` / `--set TICKER:FACT=VALUE --citation ...`
  / `--merge ANSWERS --out MERGED`. Human answers are excluded from scoring by
  default; `--include-human` shows coverage.
- Tests: `pytest`
