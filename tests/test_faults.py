"""Tests for the fault injector.

The injector is test equipment, so it needs testing more than most code: if it
silently stops injecting, every M3 measurement becomes meaningless while still
looking fine. These lock the three properties the measurements depend on:
  1. off by default (normal runs are untouched)
  2. the schedule is deterministic (with/without-recovery runs are comparable)
  3. transient heals on retry, permanent never does
"""

from dataclasses import dataclass

import pytest

from src.tools import faults
from src.tools.market_data import ToolError


@dataclass
class FakeResult:
    ticker: str
    value: float


def fake_tool(ticker, fiscal_year=None):
    return FakeResult(ticker=ticker, value=100.0)


@pytest.fixture(autouse=True)
def clean_config():
    """Every test starts from a known config and empty counters."""
    original = faults.CONFIG
    faults.CONFIG = faults.FaultConfig()
    faults.reset()
    yield
    faults.CONFIG = original
    faults.reset()


def _tool(**cfg):
    for k, v in cfg.items():
        setattr(faults.CONFIG, k, v)
    return faults.wrap_tool(fake_tool, "faketool")


def test_disabled_is_a_pass_through():
    tool = _tool(enabled=False)
    assert tool("AAPL") == FakeResult("AAPL", 100.0)


def test_permanent_loud_fault_never_heals():
    tool = _tool(enabled=True, rate=1.0, silent_share=0.0, transient_share=0.0)
    for _ in range(3):
        with pytest.raises(ToolError):
            tool("AAPL")


def test_transient_loud_fault_heals_on_retry():
    """The property retry depends on -- without it, recovery measures as useless."""
    tool = _tool(enabled=True, rate=1.0, silent_share=0.0, transient_share=1.0)
    with pytest.raises(ToolError):
        tool("AAPL")                      # attempt 1 fails
    assert tool("AAPL").value == 100.0    # attempt 2 heals


def test_silent_fault_returns_wrong_value_without_raising():
    tool = _tool(enabled=True, rate=1.0, silent_share=1.0, transient_share=0.0)
    result = tool("AAPL")                 # no exception -- that is the danger
    assert result.value != 100.0


def test_reset_clears_attempt_counters():
    tool = _tool(enabled=True, rate=1.0, silent_share=0.0, transient_share=1.0)
    with pytest.raises(ToolError):
        tool("AAPL")
    tool("AAPL")                          # healed
    faults.reset()
    with pytest.raises(ToolError):        # counter cleared -> fails again
        tool("AAPL")


def test_schedule_is_deterministic():
    faults.CONFIG.enabled = True
    faults.CONFIG.seed = 42
    tickers = ["AAPL", "MSFT", "JPM", "COP", "NVDA"]
    first = faults.plan_faults(["a", "b"], tickers)
    second = faults.plan_faults(["a", "b"], tickers)
    assert first == second


def test_seed_changes_the_schedule():
    faults.CONFIG.enabled = True
    tickers = ["AAPL", "MSFT", "JPM", "COP", "NVDA"]
    faults.CONFIG.seed = 1
    a = faults.plan_faults(["a", "b"], tickers)
    faults.CONFIG.seed = 999
    b = faults.plan_faults(["a", "b"], tickers)
    assert a != b
