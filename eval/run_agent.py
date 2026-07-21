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

import json
from pathlib import Path

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
    answers: dict[str, dict] = {}
    failures: list[str] = []

    for ticker, fiscal_year in benchmark_targets():
        try:
            answers[ticker] = run_naive(ticker, fiscal_year=fiscal_year)
            print(f"{ticker} (FY{fiscal_year}): ok")
        except Exception as exc:  # noqa: BLE001 - baseline agent has no recovery
            answers[ticker] = {}
            failures.append(f"{ticker}: {type(exc).__name__}: {exc}")
            print(f"{ticker} (FY{fiscal_year}): FAILED ({type(exc).__name__}: {exc})")

    OUT_PATH.write_text(json.dumps(answers, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH}")
    if failures:
        print(f"{len(failures)} agent failure(s):")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
