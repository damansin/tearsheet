"""Tests for the yfinance wrapper.

We MOCK yfinance so these run offline and deterministically — they check our
logic (extraction, unit conversion, margin math, error handling), not Yahoo's
uptime. `patch("src.tools.market_data.yf.Ticker")` swaps the real class for a
fake whose `.income_stmt` we control.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from src.tools.market_data import (Financials, ToolError, get_balance_sheet,
                                   get_financials)

# Real AAPL FY2024 figures in raw dollars, as yfinance returns them.
FAKE_INCOME_STMT = pd.DataFrame(
    {
        pd.Timestamp("2024-09-28"): [391035e6, 93736e6, 180683e6],
        pd.Timestamp("2023-09-30"): [383285e6, 96995e6, 169148e6],
    },
    index=["Total Revenue", "Net Income", "Gross Profit"],
)


def _patch(income_stmt):
    """Context manager: make yf.Ticker(...).income_stmt return `income_stmt`."""
    p = patch("src.tools.market_data.yf.Ticker")
    mock = p.start()
    mock.return_value.income_stmt = income_stmt
    return p


def test_extracts_latest_period_and_converts_units():
    p = _patch(FAKE_INCOME_STMT)
    try:
        f = get_financials("AAPL")  # fiscal_year=None -> latest
    finally:
        p.stop()

    assert isinstance(f, Financials)
    assert f.period_end == "2024-09-28"       # newest column
    assert f.revenue == 391035.0              # dollars -> millions
    assert f.net_income == 93736.0
    assert f.gross_margin == 46.21            # 180683 / 391035 * 100
    assert f.unit_currency == "USD_millions"
    assert f.source == "yfinance"
    assert f.ticker == "AAPL"


def test_fiscal_year_selects_the_right_period():
    """fiscal_year=2023 must pick the older column, not the latest."""
    p = _patch(FAKE_INCOME_STMT)
    try:
        f = get_financials("AAPL", fiscal_year=2023)
    finally:
        p.stop()

    assert f.period_end == "2023-09-30"
    assert f.revenue == 383285.0
    assert f.net_income == 96995.0
    assert f.gross_margin == 44.13            # 169148 / 383285 * 100


def test_unknown_fiscal_year_raises_toolerror():
    p = _patch(FAKE_INCOME_STMT)
    try:
        with pytest.raises(ToolError):
            get_financials("AAPL", fiscal_year=2019)
    finally:
        p.stop()


def test_empty_statement_raises_toolerror():
    p = _patch(pd.DataFrame())
    try:
        with pytest.raises(ToolError):
            get_financials("AAPL")
    finally:
        p.stop()


def test_missing_label_raises_toolerror():
    no_revenue = FAKE_INCOME_STMT.drop(index=["Total Revenue"])
    p = _patch(no_revenue)
    try:
        with pytest.raises(ToolError):
            get_financials("AAPL")
    finally:
        p.stop()


def test_nan_value_raises_toolerror():
    nan_rev = FAKE_INCOME_STMT.copy()
    nan_rev.loc["Total Revenue", pd.Timestamp("2024-09-28")] = float("nan")
    p = _patch(nan_rev)
    try:
        with pytest.raises(ToolError):
            get_financials("AAPL")
    finally:
        p.stop()


# --- balance sheet + optional gross profit (M2 Step 2) -----------------------

# Real AAPL FY2024 balance-sheet figures in raw dollars, as yfinance returns them.
FAKE_BALANCE_SHEET = pd.DataFrame(
    {
        pd.Timestamp("2024-09-28"): [29943e6, 56950e6],
        pd.Timestamp("2023-09-30"): [29965e6, 62146e6],
    },
    index=["Cash And Cash Equivalents", "Stockholders Equity"],
)


def _patch_bs(sheet):
    p = patch("src.tools.market_data.yf.Ticker")
    mock = p.start()
    mock.return_value.balance_sheet = sheet
    return p


def test_balance_sheet_extracts_and_converts():
    p = _patch_bs(FAKE_BALANCE_SHEET)
    try:
        bs = get_balance_sheet("AAPL", fiscal_year=2024)
    finally:
        p.stop()

    assert bs.ticker == "AAPL"
    assert bs.period_end == "2024-09-28"
    assert bs.cash == 29943.0        # dollars -> millions
    assert bs.equity == 56950.0
    assert bs.unit_currency == "USD_millions"


def test_balance_sheet_missing_row_is_none_not_error():
    """One absent line must not zero out the rest of the company."""
    no_cash = FAKE_BALANCE_SHEET.drop(index=["Cash And Cash Equivalents"])
    p = _patch_bs(no_cash)
    try:
        bs = get_balance_sheet("AAPL", fiscal_year=2024)
    finally:
        p.stop()

    assert bs.cash is None
    assert bs.equity == 56950.0      # the rest still comes through


def test_balance_sheet_empty_raises_toolerror():
    p = _patch_bs(pd.DataFrame())
    try:
        with pytest.raises(ToolError):
            get_balance_sheet("AAPL")
    finally:
        p.stop()


def test_bank_without_gross_profit_still_returns_financials():
    """The M1 bank failure: no 'Gross Profit' row must no longer kill the company."""
    bank = FAKE_INCOME_STMT.drop(index=["Gross Profit"])
    p = _patch(bank)
    try:
        f = get_financials("JPM", fiscal_year=2024)
    finally:
        p.stop()

    assert f.gross_margin is None    # honestly absent, not invented
    assert f.revenue == 391035.0     # everything else still delivered
    assert f.net_income == 93736.0
