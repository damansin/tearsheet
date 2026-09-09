"""A cache for VERIFIED facts, keyed by (tool, ticker, fiscal_year).

Why this is safe to cache at all
--------------------------------
Only immutable data goes in here. A closed fiscal year's revenue is filed and
final: AAPL FY2024 will report the same number forever. That is what makes a
cache with no expiry correct rather than reckless. A stock price, by contrast,
must never be cached -- if a live-quote tool is ever added, it does NOT get a
cache key.

There is still a way for a cached value to go stale: the TOOL can change shape
(a renamed field, a different unit). A time-based TTL would not catch that, so
instead every row carries SCHEMA_VERSION. Bump it and old rows stop matching --
they are ignored rather than deserialised into the wrong shape.

Why the critic writes, not the executor
---------------------------------------
The write path is deliberately NOT here-and-now on tool return. M3 showed that
tools sometimes return plausible garbage. Caching on return would persist that
garbage and re-serve it on every future run -- turning a transient fault into a
permanent one and making the cache actively worse than no cache. So the graph
only calls put() from the critic, after verification passed. Nothing unverified
is admissible.

Storage is SQLite: stdlib, one file, survives across processes and sessions,
and keeps CI hermetic (no server to stand up).
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

# Bump when a tool's output shape changes. Old rows then no longer match, which
# is the invalidation story -- there is no TTL because the data never expires.
SCHEMA_VERSION = 1

# Repo-root/.cache/facts.db (gitignored). Derived rather than hard-coded so the
# path is right regardless of the working directory the agent is run from.
DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".cache" / "facts.db"


@dataclass
class CacheConfig:
    """Off by default. The agent must behave identically with the cache
    disabled -- it is an optimisation, never a correctness dependency."""
    enabled: bool = False
    path: Path = DEFAULT_PATH


@dataclass
class CacheStats:
    """Counters, so a run can report its own hit rate instead of us guessing."""
    hits: int = 0
    misses: int = 0
    writes: int = 0

    @property
    def hit_rate(self) -> float:
        looked_up = self.hits + self.misses
        return self.hits / looked_up if looked_up else 0.0


CONFIG = CacheConfig()
STATS = CacheStats()


def reset_stats() -> None:
    """Zero the counters between runs so measurements do not bleed together."""
    STATS.hits = STATS.misses = STATS.writes = 0


def _connect() -> sqlite3.Connection:
    CONFIG.path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CONFIG.path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS facts (
               tool           TEXT    NOT NULL,
               ticker         TEXT    NOT NULL,
               fiscal_year    INTEGER NOT NULL,
               schema_version INTEGER NOT NULL,
               payload        TEXT    NOT NULL,
               stored_at      REAL    NOT NULL,
               PRIMARY KEY (tool, ticker, fiscal_year, schema_version)
           )"""
    )
    return conn


def _key(tool: str, ticker: str, fiscal_year: int | None) -> tuple:
    # fiscal_year=None means "latest". It cannot be stored as SQL NULL: NULL is
    # not equal to itself, so it would neither match on lookup nor collide in
    # the primary key -- the table would fill with unreachable duplicate rows.
    # -1 is an impossible real year, so it is a safe stand-in.
    return (tool, ticker.upper(), -1 if fiscal_year is None else fiscal_year,
            SCHEMA_VERSION)


def get(tool: str, ticker: str, fiscal_year: int | None) -> dict | None:
    """Return a previously verified result, or None on a miss."""
    if not CONFIG.enabled:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT payload FROM facts "
            "WHERE tool=? AND ticker=? AND fiscal_year=? AND schema_version=?",
            _key(tool, ticker, fiscal_year),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        STATS.misses += 1
        return None
    STATS.hits += 1
    return json.loads(row[0])


def put(tool: str, ticker: str, fiscal_year: int | None, payload: dict) -> None:
    """Store a result. Callers MUST have verified it first -- see module docs.

    INSERT OR REPLACE, so a re-run after a SCHEMA_VERSION bump or a corrected
    value overwrites cleanly instead of erroring on the primary key."""
    if not CONFIG.enabled:
        return
    conn = _connect()
    try:
        with conn:  # transaction: commits on success, rolls back on error
            conn.execute(
                "INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?, ?, ?)",
                (*_key(tool, ticker, fiscal_year), json.dumps(payload), time.time()),
            )
    finally:
        conn.close()
    STATS.writes += 1


def delete(tool: str, ticker: str, fiscal_year: int | None) -> None:
    """Evict one entry.

    Used when a CACHED value fails verification. That should be impossible --
    it passed the critic on the way in -- but it can happen if the file was
    edited, or was written by an older critic with looser thresholds. Left in
    place it would be re-served forever, so a failed cached value is evicted
    and the retry then refetches it from the real tool."""
    if not CONFIG.enabled:
        return
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "DELETE FROM facts "
                "WHERE tool=? AND ticker=? AND fiscal_year=? AND schema_version=?",
                _key(tool, ticker, fiscal_year),
            )
    finally:
        conn.close()


def clear() -> None:
    """Empty the cache. Used to force a cold run when measuring."""
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM facts")
    finally:
        conn.close()


def size() -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    finally:
        conn.close()
