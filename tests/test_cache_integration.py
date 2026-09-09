"""Tests for the cache as wired into the graph.

The unit tests in test_cache.py prove the STORE works. These prove the POLICY
works, which is the part that can quietly go wrong:

  the executor READS  -- a hit must skip the tool entirely
  the critic  WRITES  -- and only after a clean verdict

That split is the whole design. If the write ever migrates into the executor,
a silently corrupted value gets persisted and re-served on every future run --
a transient fault promoted to a permanent one, which is strictly worse than
having no cache at all. These tests fail if that happens.

No network and no LLM: the graph's nodes are called directly with a fake tool.
"""

from dataclasses import dataclass

import pytest

from src.agent import graph
from src.memory import cache


@dataclass
class FakeIncome:
    ticker: str = "AAPL"
    period_end: str = "2024-09-28"
    revenue: float = 391035.0
    net_income: float = 93736.0
    gross_margin: float = 46.2
    unit_currency: str = "USD_millions"
    source: str = "yfinance"


STEP = "fetch_income_statement"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path):
    cache.CONFIG.path = tmp_path / "facts.db"
    cache.CONFIG.enabled = True
    cache.reset_stats()
    yield
    cache.CONFIG = cache.CacheConfig()
    cache.reset_stats()


@pytest.fixture
def spy_tool(monkeypatch):
    """Replaces the real tool with one that counts how often it was called --
    the only way to prove a cache hit actually avoided the network."""
    calls = []

    def fake(ticker, fiscal_year=None, result=None):
        calls.append((ticker, fiscal_year))
        return FakeIncome()

    monkeypatch.setitem(graph.TOOLS, STEP, fake)
    return calls


def make_state(**overrides) -> dict:
    state = {
        "ticker": "AAPL", "fiscal_year": 2024, "plan": [STEP], "gathered": {},
        "errors": [], "answers": {}, "last_step": None, "last_ok": True,
        "verdicts": [], "attempts": {}, "from_cache": False,
    }
    state.update(overrides)
    return state


def step_through(state: dict) -> dict:
    """Run executor then critic, merging each node's partial return the way
    LangGraph does, so the assertions see the same state the graph would."""
    state = {**state, **graph.executor(state)}
    return {**state, **graph.critic(state)}


def test_miss_calls_the_tool_and_a_clean_verdict_caches_it(spy_tool):
    final = step_through(make_state())
    assert len(spy_tool) == 1                 # the tool really was called
    assert final["from_cache"] is False
    assert cache.size() == 1                  # ...and the critic stored it
    assert cache.get(STEP, "AAPL", 2024)["revenue"] == 391035.0


def test_hit_serves_from_cache_and_never_touches_the_tool(spy_tool):
    step_through(make_state())                # warm it
    spy_tool.clear()

    final = step_through(make_state())
    assert spy_tool == []                     # THE point of the cache
    assert final["from_cache"] is True
    assert final["gathered"][STEP]["revenue"] == 391035.0
    assert cache.STATS.writes == 1            # a hit must not rewrite the row


def test_a_failed_verdict_is_never_cached(monkeypatch):
    """Negative revenue is impossible, so the critic rejects it. Caching it
    would make one bad fetch permanent."""
    monkeypatch.setitem(graph.TOOLS, STEP,
                        lambda t, fiscal_year=None: FakeIncome(revenue=-391035.0))
    final = step_through(make_state())
    assert final["last_ok"] is False
    assert cache.size() == 0


def test_a_partial_verdict_caches_nothing(monkeypatch):
    """net_income is corrupted but revenue is fine. The critic keeps revenue --
    but the step still caches NOTHING: a record missing the rejected field
    would hit forever and never retry it."""
    monkeypatch.setitem(graph.TOOLS, STEP,
                        lambda t, fiscal_year=None: FakeIncome(net_income=-937360.0))
    final = step_through(make_state())
    assert "net_income" not in final["gathered"][STEP]   # dropped
    assert final["gathered"][STEP]["revenue"] == 391035.0  # neighbour survived
    assert cache.size() == 0


def test_a_bad_cached_value_is_evicted_so_the_retry_refetches(spy_tool):
    """Defence in depth. Nothing bad should ever be in the cache, but a file
    edited by hand -- or written by an older critic with looser thresholds --
    could contain one. Re-verifying on read catches it; eviction stops it being
    re-served, and the retry then refetches from the real tool."""
    poison = {"ticker": "AAPL", "revenue": -391035.0, "net_income": 93736.0}
    cache.put(STEP, "AAPL", 2024, poison)
    assert cache.size() == 1

    final = step_through(make_state())
    assert spy_tool == []                     # the hit did skip the tool...
    assert final["last_ok"] is False          # ...but verification caught it
    assert cache.size() == 0                  # and it is gone


def test_cache_disabled_changes_nothing(spy_tool):
    """The cache is an optimisation, never a correctness dependency: with it
    off the agent must behave exactly as it did before M4."""
    cache.CONFIG.enabled = False
    first = step_through(make_state())
    second = step_through(make_state())
    assert len(spy_tool) == 2                 # every run pays for its own fetch
    assert first["gathered"] == second["gathered"]
    assert first["from_cache"] is False and second["from_cache"] is False
