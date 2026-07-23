"""Tests for the run_eval CLI — including that the accuracy gate actually fires.

Everything else imports run_eval's *functions*; nothing covered `main()`,
argparse, or the exit codes. That matters twice over:
  1. argparse/file-loading could break while every other test stays green.
  2. A gate that silently never fails is worse than no gate, because you trust
     it. So we assert the failing case explicitly.

We run the real CLI in a subprocess so exit codes are genuinely exercised.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ANSWERS = ROOT / "eval" / "agent_answers.json"


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run_eval.py"),
         "--answers", str(ANSWERS), *args],
        capture_output=True, text=True, cwd=ROOT,
    )


def test_cli_reports_without_a_threshold():
    """No --min-accuracy: report only, always exit 0."""
    r = run_cli()
    assert r.returncode == 0, r.stderr
    assert "fact_accuracy" in r.stdout


def test_gate_passes_when_above_threshold():
    r = run_cli("--min-accuracy", "0.10")
    assert r.returncode == 0, r.stderr
    assert "GATE PASSED" in r.stdout


def test_gate_fails_when_below_threshold():
    """The important one — proves the gate can actually turn CI red."""
    r = run_cli("--min-accuracy", "0.99")
    assert r.returncode == 1
    assert "GATE FAILED" in r.stdout
