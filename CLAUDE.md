# CLAUDE.md

Project context for Claude Code.

## What this is
A long-horizon multi-agent system that produces a **verified, sourced company due-diligence brief**. It plans a task, executes it across financial-data tools, verifies each step, and recovers when steps fail. It is a research/analysis tool — it surfaces verified facts and **never** gives buy/sell/hold advice.

The differentiator is **reliability over many steps** + **observability**, not the brief itself. Success is measured, not vibes.

## Current milestone
**M0 — build the benchmark first.** 20–30 companies, each with known-correct key facts (revenue, net income, P/E, debt-to-equity, margins) and a success criterion. Plus repo + observability scaffolding. Do NOT start agent logic until the benchmark exists.

Milestone sequence (one-liners — detailed plans get worked out per milestone in conversation, not here):
M0 benchmark → M1 naive executor → M2 planner/executor split → M3 verification+recovery+replanning → M4 memory/context → M5 polish.

## Stack
- Python 3.11+, venv + pip
- LangGraph — orchestration (state graph, checkpointing)
- Claude / GPT — planner + critic reasoning
- Tools via MCP: `yfinance`, SEC EDGAR, a news API, a calculator
- pgvector — memory (only when M4 needs it; keep state simple before then)
- FastAPI — backend; thin viewer for the demo
- Observability: LangSmith or Phoenix (USE it, do not rebuild it)
- Tests/CI: pytest + GitHub Actions (the eval gate)

## Proposed structure
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

## Commands
> Fill these in as they stabilize; keep this section accurate.
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e .`
- Run agent on one company: `python -m src.agent.run --ticker AAPL`
- Run benchmark/eval: `python eval/run_eval.py`
- Tests: `pytest`
- API: `uvicorn api.main:app --reload`

## Design principles (do not violate)
- **Verify before trusting.** Every factual claim in the output must be traceable to a tool result. If the brief says a number, a tool returned that number. A self-consistency check (answer must not contradict tool outputs) is core, not optional.
- **Recovery is the product.** Steps WILL fail (API errors, missing data, silent garbage). Detect, then retry / fallback / replan — never charge ahead on broken assumptions.
- **Measure everything.** Each run emits a trace + metrics (steps, latency, cost, success/failure per step). Metrics changes are how we know we improved.
- **Observability is baked in, not added later.** Wire tracing in at M0.

## How to work with me (important)
- Work in small, reviewable steps — I want to understand and be able to explain every design choice. Do NOT one-shot whole milestones.
- Explain the *why* behind design choices, especially in M3 (recovery/replanning).
- When introducing a concept I may not know (LangGraph state, MCP server, context engineering), explain it briefly before implementing.
- Use planning mode before any large change. Commit per milestone.
- Prefer simple, readable code over clever abstractions — I need to be able to explain every line.

## Guardrails
- No investment advice (no buy/sell/hold, no price prediction). Research/analysis only.
- Free data sources only (yfinance, SEC EDGAR, free news tier). Don't add paid APIs without asking.
