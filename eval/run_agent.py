"""Run the naive agent across the whole benchmark and write an answers file.

    python eval/run_agent.py
    python eval/run_eval.py --answers eval/agent_answers.json

Kept separate from the scorer on purpose: the agent PRODUCES answers, the
scorer JUDGES them. Mixing the two would let a change to one silently
contaminate the other.

If the agent raises for a company (tool error, unparseable reply), we record an
empty answer — the scorer then counts those facts as `missing`, and the failure
is printed so it can be catalogued rather than hidden.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

from src.agent.graph import run_planner
from src.memory import cache
from src.tools import faults
from src.agent.naive import run_naive

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
OUT_PATH = Path(__file__).parent / "agent_answers.json"


def benchmark_targets() -> list[tuple[str, int]]:
    """Every (ticker, fiscal_year) the benchmark defines.

    fiscal_year is the calendar year the pinned period ends in, parsed from
    `period_end` (e.g. "2024-09-28" -> 2024) — the same key the tool matches on.
    """
    targets = []
    for path in sorted(BENCHMARK_DIR.glob("*.json")):
        company = json.loads(path.read_text())
        fiscal_year = int(company["period_end"][:4])
        targets.append((company["ticker"], fiscal_year))
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent", choices=["naive", "planner"], default="planner",
        help="which agent to run across the benchmark",
    )
    parser.add_argument(
        "--inject-faults", action="store_true",
        help="break tools on purpose so recovery has something to recover from",
    )
    parser.add_argument("--fault-rate", type=float, default=0.30)
    # Seed 18 chosen for COVERAGE, not for a favourable score: it is the
    # lowest seed whose fault mix populates all four quadrants (loud/silent x
    # transient/permanent) with >=3 each, so every recovery path gets exercised.
    # Selected from the fault schedule alone, before measuring any agent.
    parser.add_argument("--seed", type=int, default=18)
    parser.add_argument(
        "--cache", action="store_true",
        help="reuse previously VERIFIED tool results instead of refetching",
    )
    parser.add_argument(
        "--cache-path", default=None,
        help="override the cache file (handy for a throwaway measurement run)",
    )
    parser.add_argument(
        "--clear-cache", action="store_true",
        help="empty the cache first, to force a genuinely cold run",
    )
    parser.add_argument(
        "--out", default=str(OUT_PATH),
        help="where to write answers (keep runs side by side for comparison)",
    )
    args = parser.parse_args()
    out_path = Path(args.out)

    # The cache and the fault injector must never run together. A cached good
    # value would satisfy a step whose tool was supposed to fail, silently
    # repairing the very faults the run exists to measure -- the reliability
    # number would rise without the agent having recovered from anything.
    # Refused loudly rather than documented quietly.
    if args.cache and args.inject_faults:
        parser.error(
            "--cache with --inject-faults would mask injected faults with "
            "cached values and inflate the reliability score. Pick one."
        )

    if args.cache:
        cache.CONFIG.enabled = True
        if args.cache_path:
            cache.CONFIG.path = Path(args.cache_path)
        if args.clear_cache:
            cache.clear()
        cache.reset_stats()
        print(f"CACHE ON  path={cache.CONFIG.path}  entries={cache.size()}")

    if args.inject_faults:
        faults.CONFIG.enabled = True
        faults.CONFIG.rate = args.fault_rate
        faults.CONFIG.seed = args.seed
        faults.reset()   # attempt counters must not leak between runs
        print(f"FAULT INJECTION ON  rate={args.fault_rate}  seed={args.seed}\n")

    run = run_naive if args.agent == "naive" else run_planner

    answers: dict[str, dict] = {}
    failures: list[str] = []
    latencies: list[float] = []

    wall_start = time.perf_counter()
    for ticker, fiscal_year in benchmark_targets():
        started = time.perf_counter()
        try:
            answers[ticker] = run(ticker, fiscal_year=fiscal_year)
            elapsed = time.perf_counter() - started
            print(f"{ticker} (FY{fiscal_year}): ok  {elapsed:.2f}s")
        except Exception as exc:  # noqa: BLE001 - baseline agent has no recovery
            elapsed = time.perf_counter() - started
            answers[ticker] = {}
            failures.append(f"{ticker}: {type(exc).__name__}: {exc}")
            print(f"{ticker} (FY{fiscal_year}): FAILED ({type(exc).__name__}: {exc})")
        latencies.append(elapsed)
    wall = time.perf_counter() - wall_start

    out_path.write_text(json.dumps(answers, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")

    # Latency is the metric the cache exists to move, so it is reported right
    # where the run happens rather than eyeballed later in the tracing UI.
    ordered = sorted(latencies)
    print(f"\nlatency  total={wall:.1f}s  mean={statistics.mean(latencies):.2f}s"
          f"  p50={ordered[len(ordered) // 2]:.2f}s"
          f"  p95={ordered[max(0, int(len(ordered) * 0.95) - 1)]:.2f}s")
    if args.cache:
        st = cache.STATS
        print(f"cache    hits={st.hits}  misses={st.misses}  writes={st.writes}"
              f"  hit_rate={st.hit_rate:.0%}  entries={cache.size()}")

    if failures:
        print(f"{len(failures)} agent failure(s):")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
