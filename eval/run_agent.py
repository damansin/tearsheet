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


def benchmark_tickers() -> list[str]:
    """Every ticker the benchmark defines."""
    return sorted(
        json.loads(path.read_text())["ticker"]
        for path in BENCHMARK_DIR.glob("*.json")
    )


def main() -> None:
    answers: dict[str, dict] = {}
    failures: list[str] = []

    for ticker in benchmark_tickers():
        try:
            answers[ticker] = run_naive(ticker)
            print(f"{ticker}: ok")
        except Exception as exc:  # noqa: BLE001 - baseline agent has no recovery
            answers[ticker] = {}
            failures.append(f"{ticker}: {type(exc).__name__}: {exc}")
            print(f"{ticker}: FAILED ({type(exc).__name__}: {exc})")

    OUT_PATH.write_text(json.dumps(answers, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH}")
    if failures:
        print(f"{len(failures)} agent failure(s):")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
