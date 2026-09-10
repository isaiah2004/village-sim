"""
The foundation gate -- one command to prove the Phase-1 core is intact.

    python check.py

Runs, in order and fail-fast-reporting (but always to the end):
  1. golden-master regression   -- no validated scenario's numbers moved
  2. contract conformance        -- sim + bodies still match the frozen v1 contract
  3. save/load round-trip        -- state persists byte-identically through JSON
  4. behavioural unit tests       -- facade parity, capital goods, dependents

Exit 0 = the foundation holds. Exit 1 = something regressed (see the report).

The golden ritual: `golden.json` is RE-CAPTURED only on an intentional, reviewed
change to sim behaviour (`python regression.py --capture`), never to silence a
red bar. A surprise regression here means investigate, not re-capture.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

# (label, argv) -- each runs as its own process so a crash can't poison the rest
STEPS = [
    ("golden regression",    [sys.executable, "regression.py"]),
    ("contract conformance", [sys.executable, "test_contract.py"]),
    ("save/load round-trip", [sys.executable, "test_persistence.py"]),
    ("facade parity",        [sys.executable, "test_simcore.py"]),
    ("capital goods",        [sys.executable, "test_capital.py"]),
    ("dependents",           [sys.executable, "test_dependents.py"]),
    ("npc dialogue",         [sys.executable, "test_dialogue.py"]),
    ("game save/load",       [sys.executable, "test_save_load_game.py"]),
    ("food blight",          [sys.executable, "test_blight.py"]),
    ("need registry",        [sys.executable, "test_needs.py"]),
    ("problem board",        [sys.executable, "test_problems.py"]),
    ("interventions",        [sys.executable, "test_interventions.py"]),
    ("merchant negotiation", [sys.executable, "test_merchant.py"]),
    ("loans",                [sys.executable, "test_loans.py"]),
    ("modularity",           [sys.executable, "test_modularity.py"]),
    ("demand events",        [sys.executable, "test_demand.py"]),
]


def main() -> int:
    print("=" * 64)
    print("FOUNDATION CHECK -- Phase-1 core")
    print("=" * 64)
    results = []
    for label, argv in STEPS:
        print(f"\n>>> {label}")
        proc = subprocess.run(argv, cwd=HERE, capture_output=True, text=True)
        out = (proc.stdout or "").rstrip()
        if out:
            print(out)
        if proc.returncode != 0:
            err = (proc.stderr or "").rstrip()
            if err:
                print(err)
        results.append((label, proc.returncode == 0))

    print("\n" + "=" * 64)
    ok = all(passed for _, passed in results)
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    print("=" * 64)
    print("FOUNDATION HOLDS." if ok else "FOUNDATION BROKEN -- see failures above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
