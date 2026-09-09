"""Work through the review queue: the human half of the loop.

    python eval/run_agent.py --agent planner --inject-faults --review-queue eval/review_queue.json
    python eval/resolve_review.py --list                     # see what needs attention
    python eval/resolve_review.py                            # walk it interactively
    python eval/resolve_review.py --merge eval/answers.json --out eval/answers_merged.json

Two rules the design enforces, both borrowed from the agent itself:

1. NO CLAIM WITHOUT A CITATION. The agent may not report a number it cannot
   trace to a tool result; a human may not enter one they cannot trace to a
   filing. Applying a looser standard to the person than to the machine would
   make the human the weakest link in a system built for traceability.

2. DERIVED FACTS ARE NEVER HAND-ENTERED. net_margin is computed from revenue
   and net_income. Typing in a margin that disagrees with the two numbers beside
   it would put a contradiction into the brief -- the precise failure this
   project exists to prevent. Those rows are skipped and recomputed on merge.

Everything a human supplies is tagged `source: human` and carries its citation,
so it can never be silently counted as something the agent achieved.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.agent.review import DERIVED, DERIVED_FROM

OPEN = "open"
RESOLVED = "resolved"
UNAVAILABLE = "unavailable"


def load_queue(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_queue(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def actionable(rows: list[dict]) -> list[dict]:
    """Rows a person can actually do something about.

    Derived facts are excluded by design (rule 2), and anything already handled
    is excluded so a second pass only shows what is genuinely left."""
    return [r for r in rows
            if r.get("status", OPEN) == OPEN and r.get("reason") != DERIVED]


def resolve(row: dict, value: float, citation: str) -> dict:
    """Record a human-supplied value. Citation is mandatory (rule 1)."""
    if not citation or not citation.strip():
        raise ValueError("a citation is required: no claim without a source")
    row.update({
        "status": RESOLVED,
        "value": float(value),
        "citation": citation.strip(),
        "source": "human",
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return row


def mark_unavailable(row: dict, note: str = "") -> dict:
    """The fact genuinely cannot be obtained.

    This is a real outcome, not a failure to try. Recording it stops the same
    dead end being re-queued on every future run, and keeps it distinguishable
    from a gap nobody has looked at yet."""
    row.update({
        "status": UNAVAILABLE,
        "note": note.strip(),
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return row


def find(rows: list[dict], ticker: str, fact: str) -> dict:
    for row in rows:
        if row["ticker"] == ticker.upper() and row["fact"] == fact:
            return row
    raise KeyError(f"{ticker.upper()}.{fact} is not in the queue")


def print_queue(rows: list[dict]) -> None:
    if not rows:
        print("queue is empty")
        return
    header = f"{'ticker':<7}{'fact':<14}{'status':<13}{'reason':<20}why"
    print(header)
    print("-" * 100)
    for row in rows:
        status = row.get("status", OPEN)
        print(f"{row['ticker']:<7}{row['fact']:<14}{status:<13}"
              f"{row['reason']:<20}{row['detail'][:44]}")
    counts = {}
    for row in rows:
        key = row.get("status", OPEN)
        counts[key] = counts.get(key, 0) + 1
    print()
    print("  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"actionable now: {len(actionable(rows))}")


def walk(rows: list[dict], path: Path) -> None:
    """Interactive pass. Saves after every answer, so an interrupted session
    never loses work already done."""
    todo = actionable(rows)
    if not todo:
        print("nothing to review")
        return

    print(f"{len(todo)} fact(s) need review. "
          "Enter a value, 'u' if unavailable, 's' to skip, 'q' to stop.")
    for i, row in enumerate(todo, 1):
        print()
        print(f"[{i}/{len(todo)}] {row['ticker']} {row['fiscal_year']} - {row['fact']}")
        print(f"    expected unit : {row['unit']}")
        print(f"    why it is open: {row['reason']} - {row['detail']}")
        print(f"    retries spent : {row['attempts']}")

        raw = input("    value (or u/s/q): ").strip()
        if raw.lower() == "q":
            break
        if raw == "" or raw.lower() == "s":
            continue
        if raw.lower() == "u":
            mark_unavailable(row, input("    why not available: "))
            save_queue(path, rows)
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            print("    not a number, skipping")
            continue
        try:
            resolve(row, value, input("    source (filing + page): "))
        except ValueError as exc:
            print(f"    {exc} - skipping")
            continue
        save_queue(path, rows)

    print()
    print_queue(rows)


def merge(rows: list[dict], answers: dict) -> dict:
    """Fold resolved human values into an answers file, tagged.

    Derived facts are RECOMPUTED from whatever is present afterwards rather than
    copied, so a hand-entered revenue cannot leave a stale margin beside it."""
    merged = {ticker: dict(facts) for ticker, facts in answers.items()}

    for row in rows:
        if row.get("status") != RESOLVED:
            continue
        merged.setdefault(row["ticker"], {})[row["fact"]] = {
            "value": row["value"],
            "unit": row["unit"],
            "source": "human",
            "citation": row["citation"],
        }

    for facts in merged.values():
        for derived, inputs in DERIVED_FROM.items():
            existing = facts.get(derived)
            if existing and existing.get("source") != "computed":
                continue          # the agent's own value stands
            if not all(name in facts for name in inputs):
                continue
            revenue, net_income = (facts[name]["value"] for name in inputs)
            if not revenue:
                continue
            # Provenance propagates. A margin computed from a hand-entered
            # revenue is a human-assisted answer, not an agent one, and has to
            # be labelled that way or it would quietly re-enter the score.
            origins = {facts[name].get("source", "agent") for name in inputs}
            facts[derived] = {
                "value": round(net_income / revenue * 100, 2),
                "unit": "percent",
                "source": "computed_from_human" if "human" in origins else "computed",
                "citation": f"derived from {' and '.join(inputs)}",
            }
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default="eval/review_queue.json")
    parser.add_argument("--list", action="store_true", help="show the queue and exit")
    parser.add_argument(
        "--set", metavar="TICKER:FACT=VALUE",
        help="resolve one item without prompting (needs --citation)",
    )
    parser.add_argument("--citation", help="source for --set, e.g. '10-K FY2024 p.62'")
    parser.add_argument("--unavailable", metavar="TICKER:FACT",
                        help="mark one item as genuinely unobtainable")
    parser.add_argument("--note", default="", help="why, for --unavailable")
    parser.add_argument("--merge", metavar="ANSWERS",
                        help="fold resolved values into this answers file")
    parser.add_argument("--out", help="where to write the merged answers")
    args = parser.parse_args()

    path = Path(args.queue)
    rows = load_queue(path)

    if args.list:
        print_queue(rows)
        return

    if args.set:
        target, _, value = args.set.partition("=")
        ticker, _, fact = target.partition(":")
        if not args.citation:
            parser.error("--set requires --citation: no claim without a source")
        resolve(find(rows, ticker, fact), float(value), args.citation)
        save_queue(path, rows)
        print(f"resolved {ticker.upper()}:{fact} = {value}")
        return

    if args.unavailable:
        ticker, _, fact = args.unavailable.partition(":")
        mark_unavailable(find(rows, ticker, fact), args.note)
        save_queue(path, rows)
        print(f"marked {ticker.upper()}:{fact} unavailable")
        return

    if args.merge:
        if not args.out:
            parser.error("--merge requires --out")
        answers = json.loads(Path(args.merge).read_text(encoding="utf-8"))
        merged = merge(rows, answers)
        Path(args.out).write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        human = sum(1 for r in rows if r.get("status") == RESOLVED)
        print(f"merged {human} human-supplied fact(s) -> {args.out}")
        return

    walk(rows, path)


if __name__ == "__main__":
    main()
