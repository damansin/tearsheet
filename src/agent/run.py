"""CLI: run the naive agent on one company.

    python -m src.agent.run --ticker AAPL

Prints the answer JSON (the scorer's input shape). Scoring against the
benchmark happens in eval/run_eval.py (M0 Step 6).
"""

import argparse
import json

from src.agent.naive import run_naive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="e.g. AAPL")
    args = parser.parse_args()

    answer = run_naive(args.ticker)
    print(json.dumps({args.ticker.upper(): answer}, indent=2))


if __name__ == "__main__":
    main()
