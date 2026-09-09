"""Tests for the verified-fact cache.

A cache is a correctness hazard disguised as a performance feature: it can
serve a stale or wrong value long after the bug that produced it is fixed.
These lock the properties the agent relies on:
  1. off by default -- a disabled cache never reads, writes, or counts
  2. a hit returns exactly what was stored, a miss returns None
  3. the key really discriminates (tool, ticker, fiscal_year all matter)
  4. fiscal_year=None round-trips (it is stored as a sentinel, not SQL NULL)
  5. a SCHEMA_VERSION bump invalidates old rows instead of misreading them
"""

import pytest

from src.memory import cache

PAYLOAD = {"ticker": "AAPL", "revenue": 391035.0, "net_income": 93736.0}


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path):
    """Every test gets its own empty database file, so tests cannot leak state
    into each other or into the developer's real cache."""
    cache.CONFIG.path = tmp_path / "facts.db"
    cache.CONFIG.enabled = True
    cache.reset_stats()
    yield
    cache.CONFIG = cache.CacheConfig()      # back to the shipped defaults
    cache.reset_stats()


def test_disabled_cache_is_completely_inert():
    """The agent must behave identically with the cache off -- including not
    creating the database file, so a disabled cache leaves no trace."""
    cache.CONFIG.enabled = False
    cache.put("fetch_income_statement", "AAPL", 2024, PAYLOAD)
    assert cache.get("fetch_income_statement", "AAPL", 2024) is None
    assert (cache.STATS.hits, cache.STATS.misses, cache.STATS.writes) == (0, 0, 0)
    assert not cache.CONFIG.path.exists()


def test_miss_then_hit_round_trips_the_payload():
    assert cache.get("fetch_income_statement", "AAPL", 2024) is None
    cache.put("fetch_income_statement", "AAPL", 2024, PAYLOAD)
    assert cache.get("fetch_income_statement", "AAPL", 2024) == PAYLOAD
    assert (cache.STATS.misses, cache.STATS.hits, cache.STATS.writes) == (1, 1, 1)


def test_ticker_is_case_insensitive():
    """Tickers arrive upper-cased from the agent but lower-cased from a CLI;
    both must hit the same row rather than storing the company twice."""
    cache.put("fetch_income_statement", "aapl", 2024, PAYLOAD)
    assert cache.get("fetch_income_statement", "AAPL", 2024) == PAYLOAD


@pytest.mark.parametrize(
    "tool,ticker,year",
    [
        ("fetch_balance_sheet", "AAPL", 2024),   # different tool
        ("fetch_income_statement", "MSFT", 2024),  # different company
        ("fetch_income_statement", "AAPL", 2023),  # different year
    ],
)
def test_every_part_of_the_key_discriminates(tool, ticker, year):
    """If any component were ignored, one company's numbers would be served for
    another -- a silent, confident, completely wrong answer."""
    cache.put("fetch_income_statement", "AAPL", 2024, PAYLOAD)
    assert cache.get(tool, ticker, year) is None


def test_latest_period_round_trips():
    """fiscal_year=None ("latest") is stored as a sentinel because SQL NULL is
    not equal to itself -- as NULL it would never match on lookup."""
    cache.put("fetch_income_statement", "AAPL", None, PAYLOAD)
    assert cache.get("fetch_income_statement", "AAPL", None) == PAYLOAD
    assert cache.get("fetch_income_statement", "AAPL", 2024) is None
    assert cache.size() == 1


def test_schema_bump_invalidates_old_rows(monkeypatch):
    """The real staleness risk is not age, it is the tool changing shape. A
    bumped version must MISS, not deserialise the old payload."""
    cache.put("fetch_income_statement", "AAPL", 2024, PAYLOAD)
    monkeypatch.setattr(cache, "SCHEMA_VERSION", cache.SCHEMA_VERSION + 1)
    assert cache.get("fetch_income_statement", "AAPL", 2024) is None


def test_put_is_idempotent():
    """Re-running the agent must overwrite, not collide on the primary key."""
    cache.put("fetch_income_statement", "AAPL", 2024, PAYLOAD)
    cache.put("fetch_income_statement", "AAPL", 2024, {"revenue": 1.0})
    assert cache.size() == 1
    assert cache.get("fetch_income_statement", "AAPL", 2024) == {"revenue": 1.0}


def test_clear_empties_the_store():
    """Needed to force a genuinely cold run when measuring cold vs warm."""
    cache.put("fetch_income_statement", "AAPL", 2024, PAYLOAD)
    cache.clear()
    assert cache.size() == 0
    assert cache.get("fetch_income_statement", "AAPL", 2024) is None


def test_hit_rate_is_zero_when_nothing_was_looked_up():
    """Guards the empty-run divide-by-zero."""
    assert cache.STATS.hit_rate == 0.0
    cache.get("fetch_income_statement", "AAPL", 2024)
    cache.put("fetch_income_statement", "AAPL", 2024, PAYLOAD)
    cache.get("fetch_income_statement", "AAPL", 2024)
    assert cache.STATS.hit_rate == 0.5
