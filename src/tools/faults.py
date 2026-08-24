"""Deliberate fault injection, so recovery has something to recover from.

The M2 benchmark ran clean: yfinance worked on all 25 companies. That makes
retry/fallback/replan unmeasurable -- the code would sit idle and we would have
zero evidence it works. So we break the tools on purpose and measure completion
WITH vs WITHOUT recovery.

Faults have two independent dimensions:

  KIND         LOUD   the tool raises ToolError      -> exercises RECOVERY
               SILENT returns plausible-but-wrong    -> exercises the CRITIC

  PERSISTENCE  TRANSIENT fails once, heals on retry  -> rewards RETRY
               PERMANENT fails every attempt         -> forces REPLAN / ABSTAIN

Both persistences must exist. If every fault healed on retry, the agent would
never need judgement; if none did, retry would be pointless. With both, the
agent has to tell them apart -- retrying a permanently broken tool burns tokens
forever, replanning on a blip throws away work that would have succeeded. That
distinction is the actual lesson in M3.

Silent faults come in two flavours, deliberately:
  subtle       value shifted ~15%  -> self-consistency CANNOT catch it (the
                                      answer faithfully matches the lying tool)
  implausible  wrong sign and 10x  -> a sanity check CAN catch it
Mixing them lets us report the critic's true catch rate instead of rigging the
test to only inject what we already know how to detect.

Determinism: the SCHEDULE (which calls fail, and how) is a pure function of
(seed, tool, ticker), so both the with-recovery and without-recovery runs face
identical failures and are comparable. Only whether a given ATTEMPT gets through
depends on the private call counter.
"""

import hashlib
import random
from collections import Counter
from dataclasses import dataclass, fields, replace

from src.tools.market_data import ToolError


@dataclass
class FaultConfig:
    enabled: bool = False
    rate: float = 0.30            # share of tool call sites that are faulty
    silent_share: float = 0.5     # of faults, share that are SILENT
    transient_share: float = 0.5  # of faults, share that heal on retry
    subtle_share: float = 0.5     # of silent faults, share that are subtle
    seed: int = 0


@dataclass(frozen=True)
class Fault:
    kind: str          # "loud" | "silent"
    persistence: str   # "transient" | "permanent"
    subtle: bool       # only meaningful when kind == "silent"


CONFIG = FaultConfig()

# How many times each (tool, ticker) has been called. Kept HERE rather than
# passed as an argument, so the tool signature stays clean and the agent cannot
# tell it is being tested.
_ATTEMPTS: Counter = Counter()


def reset() -> None:
    """Clear attempt counters. Call at the start of every benchmark run, or
    counts leak between runs and 'retry' silently succeeds for the wrong reason."""
    _ATTEMPTS.clear()


def _rng(name: str, ticker: str) -> random.Random:
    """Deterministic per (seed, tool, ticker) -- NOT per call order, so
    reordering the benchmark cannot change which companies fail."""
    key = f"{CONFIG.seed}|{name}|{ticker}".encode()
    return random.Random(int(hashlib.sha256(key).hexdigest()[:16], 16))


def _schedule(name: str, ticker: str):
    """(Fault | None, rng) for this call site. Attempt-independent."""
    rng = _rng(name, ticker)
    if rng.random() >= CONFIG.rate:
        return None, rng
    kind = "silent" if rng.random() < CONFIG.silent_share else "loud"
    persistence = "transient" if rng.random() < CONFIG.transient_share else "permanent"
    subtle = rng.random() < CONFIG.subtle_share
    return Fault(kind, persistence, subtle), rng


def _numeric_fields(obj) -> list[str]:
    return [f.name for f in fields(obj)
            if isinstance(getattr(obj, f.name), (int, float))
            and getattr(obj, f.name) is not None]


def _corrupt(result, rng: random.Random, subtle: bool):
    """A copy with one numeric field silently wrong (the original is untouched)."""
    names = _numeric_fields(result)
    if not names:
        return result
    target = rng.choice(names)
    value = getattr(result, target)
    bad = value * 1.15 if subtle else -abs(value) * 10
    return replace(result, **{target: round(bad, 2)})


def wrap_tool(fn, name: str):
    """Wrap a tool so it fails on schedule. A no-op unless CONFIG.enabled."""
    def wrapped(ticker: str, fiscal_year: int | None = None):
        if not CONFIG.enabled:
            return fn(ticker, fiscal_year=fiscal_year)

        attempt = _ATTEMPTS[(name, ticker)]
        _ATTEMPTS[(name, ticker)] += 1

        fault, rng = _schedule(name, ticker)
        if fault is None:
            return fn(ticker, fiscal_year=fiscal_year)
        if fault.persistence == "transient" and attempt > 0:
            return fn(ticker, fiscal_year=fiscal_year)      # healed on retry
        if fault.kind == "silent":
            return _corrupt(fn(ticker, fiscal_year=fiscal_year), rng, fault.subtle)
        raise ToolError(f"injected {fault.persistence} fault: {name} failed for {ticker}")

    wrapped.__name__ = getattr(fn, "__name__", name)
    return wrapped


def plan_faults(tool_names, tickers) -> list[dict]:
    """The injection schedule, computed up front, so results can be reported
    against what was actually injected rather than guessed at afterwards."""
    out = []
    for name in tool_names:
        for tk in tickers:
            fault, _ = _schedule(name, tk)
            if fault:
                out.append({"ticker": tk, "tool": name, "kind": fault.kind,
                            "persistence": fault.persistence, "subtle": fault.subtle})
    return out
