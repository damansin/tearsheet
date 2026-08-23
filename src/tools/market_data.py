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
from langsmith import traceable

# yfinance row labels we depend on. If Yahoo renames one, this is the single
# place that breaks — not the whole agent.
REVENUE_LABEL = "Total Revenue"
NET_INCOME_LABEL = "Net Income"
GROSS_PROFIT_LABEL = "Gross Profit"
# Balance-sheet labels. Verified against SEC XBRL ground truth to the dollar for
# AAPL/MSFT/INTC/KO/JPM. Do NOT swap these for their near-neighbours:
# "Cash Cash Equivalents And Short Term Investments" and "Common Stock Equity"
# are DIFFERENT concepts and disagree with the filings.
CASH_LABEL = "Cash And Cash Equivalents"
EQUITY_LABEL = "Stockholders Equity"


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
    gross_margin: float | None   # percent; None when the filing has no gross profit (banks)
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


def _cell_optional(statement, label: str, column) -> float | None:
    """Like _cell, but returns None instead of raising when the row is absent.

    Used for genuinely optional concepts. Banks report no "Gross Profit" (they
    earn net interest income, not revenue - COGS), so a missing row there is a
    fact about the company, not a failure - it must not kill the whole company.
    """
    try:
        return _cell(statement, label, column)
    except ToolError:
        return None


def _select_period(income_stmt, fiscal_year: int | None):
    """Pick the income-statement column for `fiscal_year`.

    `fiscal_year` = the calendar year the fiscal period ENDS in (Apple's FY2024
    ends 2024-09-28 -> 2024). None picks the most recent report. Columns are
    periods, newest first. Missing year is a loud failure, not a silent
    fall-back to the wrong year.
    """
    if fiscal_year is None:
        return income_stmt.columns[0]
    for column in income_stmt.columns:
        if column.year == fiscal_year:
            return column
    available = sorted({c.year for c in income_stmt.columns})
    raise ToolError(f"no annual report ending in {fiscal_year}; available: {available}")


@traceable(run_type="tool")
def get_financials(ticker: str, fiscal_year: int | None = None) -> Financials:
    """Fetch annual financials for `ticker`.

    fiscal_year: calendar year the fiscal period ends in (e.g. 2024). None =
    most recent annual report.
    """
    try:
        income_stmt = yf.Ticker(ticker).income_stmt
    except Exception as exc:  # network/library errors -> our clean error type
        raise ToolError(f"yfinance request failed for {ticker!r}: {exc}") from exc

    if income_stmt is None or income_stmt.empty:
        raise ToolError(f"no income statement for {ticker!r} (bad ticker or rate limited)")

    column = _select_period(income_stmt, fiscal_year)
    revenue = _cell(income_stmt, REVENUE_LABEL, column)
    net_income = _cell(income_stmt, NET_INCOME_LABEL, column)
    gross_profit = _cell_optional(income_stmt, GROSS_PROFIT_LABEL, column)

    return Financials(
        ticker=ticker.upper(),
        period_end=str(column.date()),
        revenue=round(revenue / 1e6, 2),      # raw dollars -> millions
        net_income=round(net_income / 1e6, 2),
        gross_margin=(round(gross_profit / revenue * 100, 2)
                      if gross_profit is not None else None),
    )


@dataclass
class BalanceSheet:
    ticker: str
    period_end: str          # e.g. "2024-09-28"
    cash: float | None       # USD millions
    equity: float | None     # USD millions
    unit_currency: str = "USD_millions"
    source: str = "yfinance"


@traceable(run_type="tool")
def get_balance_sheet(ticker: str, fiscal_year: int | None = None) -> BalanceSheet:
    """Fetch cash + shareholders' equity for `ticker`.

    The facts the naive agent had no way to obtain (and therefore invented).
    Both are optional: a missing row yields None rather than an error, so one
    absent line never zeroes out the rest of the company.
    """
    try:
        sheet = yf.Ticker(ticker).balance_sheet
    except Exception as exc:
        raise ToolError(f"yfinance balance sheet failed for {ticker!r}: {exc}") from exc

    if sheet is None or sheet.empty:
        raise ToolError(f"no balance sheet for {ticker!r} (bad ticker or rate limited)")

    column = _select_period(sheet, fiscal_year)
    cash = _cell_optional(sheet, CASH_LABEL, column)
    equity = _cell_optional(sheet, EQUITY_LABEL, column)

    return BalanceSheet(
        ticker=ticker.upper(),
        period_end=str(column.date()),
        cash=round(cash / 1e6, 2) if cash is not None else None,
        equity=round(equity / 1e6, 2) if equity is not None else None,
    )
