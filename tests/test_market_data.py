"""Tests for the yfinance wrapper.

We MOCK yfinance so these run offline and deterministically — they check our
logic (extraction, unit conversion, margin math, error handling), not Yahoo's
uptime. `patch("src.tools.market_data.yf.Ticker")` swaps the real class for a
fake whose `.income_stmt` we control.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from src.tools.market_data import Financials, ToolError, get_financials

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
        f = get_financials("AAPL")
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
