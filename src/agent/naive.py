"""The naive agent — the M0 baseline.

The simplest thing that attempts the task: fetch financials, then ask an LLM to
format them as the scorer's answer JSON. NO verification, NO recovery, NO
planning. It is meant to be *bad*:

  - it uses whatever period `get_financials` returns (the latest annual, e.g.
    FY2025) even though the benchmark asks for FY2024, and
  - it has no step that checks its own output against the source data.

Those gaps are exactly what later milestones fix. Note this is barely an agent:
*our code* calls the tool directly — the LLM only formats the result. The
LLM-driven tool-use loop arrives with LangGraph in M2.
"""

import json

import anthropic
from dotenv import load_dotenv
from langsmith import traceable
from langsmith.wrappers import wrap_anthropic

from src.tools.market_data import get_financials

load_dotenv()  # read ANTHROPIC_API_KEY from .env

MODEL = "claude-haiku-4-5"

SYSTEM = (
    "You are a financial analyst assistant. You are given financial data for a "
    "company. Output ONLY a JSON object (no prose) with exactly these keys: "
    "revenue, net_income, gross_margin. Each maps to an object "
    '{"value": <number>, "unit": <string>}. Use "USD_millions" for revenue and '
    'net_income, and "percent" for gross_margin.'
)


def _extract_json(text: str) -> dict:
    """Pull the first {...} block out of the model's reply and parse it."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model reply: {text!r}")
    return json.loads(text[start : end + 1])


@traceable(run_type="chain", name="naive_agent")
def run_naive(ticker: str, fiscal_year: int | None = None) -> dict:
    """Return {fact: {value, unit}} for one company — the scorer's answer shape."""
    fin = get_financials(ticker, fiscal_year=fiscal_year)  # target the requested year

    user = (
        f"Company: {ticker}\n"
        f"period_end: {fin.period_end}\n"
        f"revenue: {fin.revenue} {fin.unit_currency}\n"
        f"net_income: {fin.net_income} {fin.unit_currency}\n"
        f"gross_margin: {fin.gross_margin} percent\n\n"
        "Produce the JSON."
    )

    # wrap_anthropic auto-logs the LLM call (prompt, response, tokens, latency,
    # cost) as its own span inside the trace.
    client = wrap_anthropic(anthropic.Anthropic())
    resp = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return _extract_json(text)
