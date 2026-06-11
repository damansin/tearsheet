# CLAUDE.md — Tearsheet

Full project context for Claude Code. This is the single source of truth for what Tearsheet is, why it's built this way, and how to work on it.

---

## 1. What this is

A long-horizon multi-agent system that takes a company and autonomously produces a **verified, sourced due-diligence brief**. It plans the research, executes it across financial-data tools, **verifies every step against the source data**, and recovers when steps fail — producing a structured analyst brief where every factual claim is traceable to a source.

It is a **research and analysis tool**. It surfaces verified facts. It does **not** give investment advice, recommendations, or price predictions.

**The differentiator is reliability over many steps + observability — not the brief itself.** Success is measured against ground-truth facts, not vibes. The headline question the project answers: *how much does verification and recovery actually improve task completion?*

## 2. What it produces (the task)

Input: a company (ticker or name).
Output: a structured brief containing:
- Latest financials (revenue, net income, margins, cash, debt)
- Key ratios computed from that data (P/E, debt-to-equity, gross/operating margin, revenue growth)
- A short trend summary (revenue/margin direction over recent periods)
- Risk flags pulled from the company's filings
- Recent relevant news
- **A citation for every factual claim**

## 3. Why this shape (design logic)

- **Verifiable ground truth.** Revenue, margins, ratios have correct values checkable against a source — so task success is *measurable*, which is what makes the eval/recovery story real.
- **Genuinely long-horizon.** fetch price → fetch financials → fetch filings → compute ratios → cross-check → gather news → synthesize → cite. Many steps = many places to fail and recover. That recovery work is the hard, frontier part and the whole point.
- **Great failure modes to engineer around.** The classic one: the agent states revenue is $40B when the filing says $36B. That's a hallucination catchable with a self-consistency check ("the answer must not contradict tool outputs"). Concrete to demo, concrete to talk about.

## 4. Architecture (LangGraph state graph)

- **Planner** — decomposes the goal into a step plan (task graph).
- **Executor** — runs each step using tools.
- **Critic / Verifier** — after each step, checks: did it succeed? does the output contradict the data the tools returned (self-consistency)?
- **Replanner** — on failure or changed state, revises the plan instead of charging ahead.
- **Memory / state** — carries verified findings across steps without flooding the context window.
- **Synthesizer** — assembles the final cited brief.

```
Goal → Planner → Executor → Critic ——ok——> more steps? ——no——> Synthesizer → Brief
                    ▲           │
                    └──replan───┘ (on failure)
```

## 5. The hard part (the depth this project is built to show)

Making that loop **reliable over many steps**. Concretely:
1. **Failure detection** — distinguish success / loud failure (tool errored) / silent failure (plausible garbage).
2. **Recovery & replanning** — retry, try a different approach, or revise the plan.
3. **Context engineering** — decide what state to carry forward so late steps still have what they need without drowning in earlier transcript.
4. **Measurement** — benchmark of 20–30 companies with known-correct facts; track completion rate, failure location, cost, latency, hallucination rate.

## 6. Observability (baked in, not bolted on)

Wire tracing in at M0, not later. Every run emits a trace + metrics: steps taken, p50/p95 latency, cost-per-run (and per-step), and quality metrics (fact-accuracy, hallucination rate). A **CI regression gate** runs the benchmark on every PR and blocks merges that regress. Use LangSmith or Arize Phoenix for this — **do not rebuild it.**

## 7. Stack

- Python 3.11+, venv + pip
- **LangGraph** — orchestration (state graph + checkpointing)
- Claude / GPT — planner + critic reasoning; optional cheaper model for simple sub-steps (cost engineering)
- Tools via **MCP**: `yfinance` (market + fundamentals), SEC EDGAR (filings), a news API, a calculator
- **PostgreSQL + pgvector** — structured data (companies, runs, scores) *and* vector memory. One DB, double duty. (Vectors not needed until M4 — keep state simple before then.)
- **FastAPI** — backend; thin viewer for the demo
- **LangSmith / Phoenix** — observability (use, don't rebuild)
- **pytest + GitHub Actions** — the CI eval gate

## 8. Repo structure (proposed — adjust as it stabilizes)

```
src/
  agent/        # planner, executor, critic, replanner, graph definition
  tools/        # yfinance, edgar, news, calculator (wrapped as MCP/tools)
  memory/       # state + (later) pgvector
  observability/# tracing, metrics (latency p50/p95, cost, quality)
eval/
  benchmark/    # 20-30 companies + ground-truth facts
  run_eval.py   # scores completion rate, fact-accuracy, hallucination rate
api/            # FastAPI app + viewer
tests/
.github/workflows/  # CI eval gate
```

## 9. Milestones (full plan)

Detailed *implementation* for each milestone is worked out in conversation when that milestone starts — the descriptions below are scope + "done" criteria, not step-by-step plans.

**M0 — Walking skeleton (thin end-to-end slice)** *(current)*
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

**M4 — Memory + context management**
- Goal: persistent state across steps (and sessions via pgvector); context engineering so longer, multi-part tasks don't degrade.
- Done when: longer tasks complete reliably and context stays bounded as step count grows.

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
- Tests: `pytest`
- API: `uvicorn api.main:app --reload`
