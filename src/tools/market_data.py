"""yfinance wrapper — the agent's market-data tool.

Turns yfinance's messy pandas output into a clean, typed result the rest of
the system can depend on. The mess (weird labels, NaNs, raw-dollar scaling,
network flakiness) is isolated *here*, behind one function.

Contract:
    get_financials("AAPL") -> Financials   (most recent annual report)
    raises ToolError on any failure the caller should handle (bad ticker,
    rate limit, missing data).

Note on period: this returns the MOST RECENT annual report. As of mid-2026
that is FY2025 for AAPL, not FY2024 — the `period_end` field always says which,
so period mismatches are visible rather than silent.
"""

from dataclasses import dataclass

import yfinance as yf

# yfinance row labels we depend on. If Yahoo renames one, this is the single
# place that breaks — not the whole agent.
REVENUE_LABEL = "Total Revenue"
NET_INCOME_LABEL = "Net Income"
GROSS_PROFIT_LABEL = "Gross Profit"


class ToolError(Exception):
    """A tool failed in a way the caller is expected to handle (loud failure).

    Named so the executor/critic in later milestones can catch tool failures
    distinctly from bugs.
    """


@dataclass
class Financials:
    ticker: str
    period_end: str          # e.g. "2025-09-30" — which fiscal year this is
    revenue: float           # USD millions
    net_income: float        # USD millions
    gross_margin: float      # percent
    unit_currency: str = "USD_millions"
    source: str = "yfinance"


def _cell(income_stmt, label: str, column) -> float:
    """Pull one value from the income statement, in raw dollars.

    Raises ToolError if the label is missing or the value is NaN — a missing
    fact is a loud failure, not a silent zero.
    """
    if label not in income_stmt.index:
        raise ToolError(f"label {label!r} not in income statement")
    value = income_stmt.loc[label, column]
    if value != value:  # NaN check (NaN is the only value not equal to itself)
        raise ToolError(f"label {label!r} is NaN for period {column}")
    return float(value)


def get_financials(ticker: str) -> Financials:
    """Fetch the most recent annual financials for `ticker`."""
    try:
        income_stmt = yf.Ticker(ticker).income_stmt
    except Exception as exc:  # network/library errors -> our clean error type
        raise ToolError(f"yfinance request failed for {ticker!r}: {exc}") from exc

    if income_stmt is None or income_stmt.empty:
        raise ToolError(f"no income statement for {ticker!r} (bad ticker or rate limited)")

    latest = income_stmt.columns[0]  # columns are periods, newest first
    revenue = _cell(income_stmt, REVENUE_LABEL, latest)
    net_income = _cell(income_stmt, NET_INCOME_LABEL, latest)
    gross_profit = _cell(income_stmt, GROSS_PROFIT_LABEL, latest)

    return Financials(
        ticker=ticker.upper(),
        period_end=str(latest.date()),
        revenue=round(revenue / 1e6, 2),      # raw dollars -> millions
        net_income=round(net_income / 1e6, 2),
        gross_margin=round(gross_profit / revenue * 100, 2),
    )
