"""Score an agent's answers against the ground-truth benchmark.

Usage:
    python eval/run_eval.py --answers eval/fake_answers.json

Answers file shape (what the agent must eventually emit per company):
    {
      "AAPL": {
        "revenue":      {"value": 391.0,  "unit": "USD_billions"},
        "gross_margin": {"value": 46.0,   "unit": "percent"}
      },
      ...
    }

Metrics (kept deliberately separate — missing and wrong are different sins):
    completion         = attempted / required   ("did it finish?")
    fact_accuracy      = correct   / required   ("how much of the job is right?")
    hallucination_rate = wrong     / attempted  ("when it speaks, does it lie?")
"""

import argparse
import json
from pathlib import Path

BENCHMARK_DIR = Path(__file__).parent / "benchmark"

# Unit normalization: convert every value to its family's canonical unit
# (currency -> USD_millions, percentages -> percent) before comparing, so
# "391.0 USD_billions" and "391035 USD_millions" are the same fact.
UNIT_FAMILIES = {
    "USD_millions": ("currency", 1.0),
    "USD_billions": ("currency", 1000.0),
    "USD": ("currency", 1e-6),
    "percent": ("percent", 1.0),
}


def load_ground_truth() -> dict:
    """Load every company file in eval/benchmark/ keyed by ticker."""
    truth = {}
    for path in sorted(BENCHMARK_DIR.glob("*.json")):
        company = json.loads(path.read_text())
        truth[company["ticker"]] = company
    return truth


def normalize(value: float, unit: str) -> tuple[str, float]:
    """Return (unit_family, value_in_canonical_unit)."""
    family, factor = UNIT_FAMILIES[unit]
    return family, value * factor


def check_fact(truth_fact: dict, answer: dict | None) -> str:
    """Verdict for one fact: 'correct', 'wrong', or 'missing'."""
    if answer is None:
        return "missing"

    truth_family, truth_value = normalize(truth_fact["value"], truth_fact["unit"])
    try:
        answer_family, answer_value = normalize(answer["value"], answer["unit"])
    except (KeyError, TypeError):
        return "wrong"  # malformed answer counts against the agent, not the eval

    if answer_family != truth_family:
        return "wrong"  # e.g. answered a percentage where currency was required

    if truth_fact["match"] == "relative":
        ok = abs(answer_value - truth_value) / abs(truth_value) <= truth_fact["tolerance"]
    elif truth_fact["match"] == "absolute_pp":
        ok = abs(answer_value - truth_value) <= truth_fact["tolerance"]
    else:
        raise ValueError(f"Unknown match type: {truth_fact['match']}")
    return "correct" if ok else "wrong"


def score(truth: dict, answers: dict) -> dict:
    """Score all companies; returns per-fact results and the three metrics."""
    results = []
    for ticker, company in truth.items():
        company_answers = answers.get(ticker, {})
        for fact in company["facts"]:
            verdict = check_fact(fact, company_answers.get(fact["fact"]))
            results.append({"ticker": ticker, "fact": fact["fact"], "verdict": verdict})

    required = len(results)
    attempted = sum(r["verdict"] != "missing" for r in results)
    correct = sum(r["verdict"] == "correct" for r in results)
    wrong = sum(r["verdict"] == "wrong" for r in results)

    return {
        "results": results,
        "required": required,
        "attempted": attempted,
        "correct": correct,
        "wrong": wrong,
        "completion": attempted / required if required else 0.0,
        "fact_accuracy": correct / required if required else 0.0,
        "hallucination_rate": wrong / attempted if attempted else 0.0,
    }


def print_report(scored: dict) -> None:
    icons = {"correct": "PASS", "wrong": "FAIL", "missing": "MISS"}
    print(f"{'ticker':<8}{'fact':<16}verdict")
    print("-" * 34)
    for r in scored["results"]:
        print(f"{r['ticker']:<8}{r['fact']:<16}{icons[r['verdict']]}")
    print("-" * 34)
    print(f"required {scored['required']} | attempted {scored['attempted']} "
          f"| correct {scored['correct']} | wrong {scored['wrong']}")
    print(f"completion:         {scored['completion']:.1%}")
    print(f"fact_accuracy:      {scored['fact_accuracy']:.1%}")
    print(f"hallucination_rate: {scored['hallucination_rate']:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", required=True, help="path to answers JSON")
    args = parser.parse_args()

    truth = load_ground_truth()
    answers = json.loads(Path(args.answers).read_text())
    print_report(score(truth, answers))


if __name__ == "__main__":
    main()
