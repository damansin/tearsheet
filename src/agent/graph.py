"""The M2 planner/executor agent, built as a LangGraph state graph.

Where the naive agent hard-codes its pipeline in Python, this one models the
work as an explicit state machine:

    START -> planner -> executor --(plan left?)--yes--> executor
                            |                              |
                            no                             |
                            v                              |
                       synthesizer -> END  <---------------+

Why a graph: control flow becomes data, not nested ifs. M3's critic slots in as
one more node plus a smarter router, without rewriting the executor.

State is one dict that flows through every node; each node returns only the
keys it changed.
"""

import json
import sys
from dataclasses import asdict
from typing import TypedDict

import anthropic
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from langsmith.wrappers import wrap_anthropic

from src.tools.market_data import ToolError, get_balance_sheet, get_financials

load_dotenv()

MODEL = "claude-haiku-4-5"

# The tools the planner may schedule. Adding a tool here is all it takes for the
# planner to be able to use it.
TOOLS = {
    "fetch_income_statement": get_financials,
    "fetch_balance_sheet": get_balance_sheet,
}


class AgentState(TypedDict):
    """The shared notebook every node reads and writes."""
    ticker: str
    fiscal_year: int | None
    plan: list[str]        # steps still to run (executor pops from the front)
    gathered: dict         # step name -> tool result (the evidence)
    errors: list[str]      # what failed; M3 will act on these, M2 just records
    answers: dict          # final output, the scorer's shape


PLANNER_SYSTEM = (
    "You plan the data gathering for a company's financial brief.\n"
    "Available tools:\n"
    "  fetch_income_statement -> revenue, net_income, gross_margin\n"
    "  fetch_balance_sheet    -> cash, equity\n"
    "The brief must report: revenue, net_income, gross_margin, net_margin, "
    "cash, equity.\n"
    'Output ONLY JSON: {"plan": ["<tool>", ...]} listing the tools to call, in '
    "order. Include every tool needed to cover the required facts."
)

SYNTHESIZER_SYSTEM = (
    "You assemble a company's key financials FROM THE GATHERED DATA ONLY.\n"
    "Output ONLY a JSON object with keys drawn from: revenue, net_income, "
    'gross_margin, net_margin, cash, equity. Each maps to {"value": <number>, '
    '"unit": <string>}.\n'
    "Units: USD_millions for revenue, net_income, cash, equity; percent for "
    "gross_margin and net_margin.\n"
    "net_margin = net_income / revenue * 100 (only if both were gathered).\n"
    "CRITICAL: if a value is not present in the gathered data, OMIT that key "
    "entirely. Never estimate, infer, or recall a number from memory. An "
    "omitted fact is correct behaviour; an invented one is a failure."
)


def _client():
    # wrap_anthropic logs each call as an llm span (tokens, latency, cost).
    return wrap_anthropic(anthropic.Anthropic())


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model reply: {text!r}")
    return json.loads(text[start : end + 1])


def _ask(system: str, user: str) -> dict:
    resp = _client().messages.create(
        model=MODEL, max_tokens=700, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return _extract_json(text)


def planner(state: AgentState) -> dict:
    """Decide which tools to call. (With 2 tools this is near-deterministic --
    the architecture is the point; real planning arrives with more tools.)"""
    user = f"Company: {state['ticker']}, fiscal year: {state['fiscal_year']}.\nProduce the plan."
    try:
        plan = _ask(PLANNER_SYSTEM, user).get("plan", [])
    except Exception as exc:  # planner failure must not be silent
        return {"plan": list(TOOLS), "errors": [f"planner fell back to all tools: {exc}"]}
    return {"plan": [s for s in plan if s in TOOLS]}


def executor(state: AgentState) -> dict:
    """Run the next step. A failed step is recorded and the run continues --
    one bad tool call must not zero out the whole company. (Retry/replan is M3.)"""
    step, *remaining = state["plan"]
    gathered = dict(state["gathered"])
    errors = list(state["errors"])
    try:
        result = TOOLS[step](state["ticker"], fiscal_year=state["fiscal_year"])
        gathered[step] = asdict(result)
    except ToolError as exc:
        errors.append(f"{step}: {exc}")
    return {"plan": remaining, "gathered": gathered, "errors": errors}


def synthesizer(state: AgentState) -> dict:
    """Turn the gathered evidence into the scorer's answer shape."""
    if not state["gathered"]:
        return {"answers": {}}
    user = (
        f"Company: {state['ticker']}\n"
        f"Gathered data:\n{json.dumps(state['gathered'], indent=2)}\n\n"
        "Produce the JSON."
    )
    try:
        answers = _ask(SYNTHESIZER_SYSTEM, user)
    except Exception as exc:
        return {"answers": {}, "errors": state["errors"] + [f"synthesizer: {exc}"]}
    return {"answers": answers}


def route(state: AgentState) -> str:
    """The loop, as data: keep executing while steps remain, else synthesize."""
    return "executor" if state["plan"] else "synthesizer"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("planner", planner)
    g.add_node("executor", executor)
    g.add_node("synthesizer", synthesizer)

    g.add_edge(START, "planner")
    # conditional from planner too, so an empty plan skips straight to synthesis
    g.add_conditional_edges("planner", route,
                            {"executor": "executor", "synthesizer": "synthesizer"})
    g.add_conditional_edges("executor", route,
                            {"executor": "executor", "synthesizer": "synthesizer"})
    g.add_edge("synthesizer", END)
    return g.compile(name="planner_agent")


GRAPH = build_graph()


def run_planner(ticker: str, fiscal_year: int | None = None) -> dict:
    """Same contract as run_naive: {fact: {value, unit}} for one company."""
    final = GRAPH.invoke({
        "ticker": ticker.upper(), "fiscal_year": fiscal_year,
        "plan": [], "gathered": {}, "errors": [], "answers": {},
    })
    # A graph collects failures into state instead of raising, which means a
    # node can fail silently and the caller sees only empty answers. Surface
    # them: warn on partial failure, raise when nothing survived. (M2 makes
    # failures VISIBLE; retry/fallback is M3's job.)
    if final["errors"]:
        if not final["answers"]:
            raise RuntimeError(f"{ticker}: {'; '.join(final['errors'])}")
        print(f"  warning {ticker}: {'; '.join(final['errors'])}", file=sys.stderr)
    return final["answers"]
