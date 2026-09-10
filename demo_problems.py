"""
Layer 1 demo -- the world's problem board over a year (DESIGN.md).

Problems are DATA now: typed, located, each with a severity the sim reads from
world-state every day. This shows the board tracking a single idle year -- no
player -- so every movement is the world itself, not intervention. It is the
answer to DESIGN.md's question 2 ("what is the problem?"), made legible: the
same severities Layer 2 prices when someone drives them down, and that Layer 3
interventions will target.

    python demo_problems.py

Read it as: wood scarcity is near zero in spring, climbs as the winter forecast
looms, and eases once winter is mostly in the past horizon; food scarcity stays
mild (food is the comfortable good); and the capital gap sits high all year --
the village never builds income-generating infrastructure on its own, which is
exactly the standing problem a "build a mill / woodlot" intervention would target.
"""
from __future__ import annotations

import sys

from config import Config, Season
from simcore import SimCore

SAMPLE_DAYS = [5, 20, 45, 70, 85, 100, 115]


def main() -> int:
    core = SimCore(config=_one_year())
    board_keys = [p.key for p in core.begin_turn().problems]
    samples = {}
    while not core.done:
        snap = core.begin_turn()
        if core.day in SAMPLE_DAYS:
            samples[core.day] = ({p.key: p.severity for p in snap.problems}, snap.season)
        core.commit_turn()

    print("=" * 72)
    print("THE VILLAGE PROBLEM BOARD -- severity (0..1) over one idle year")
    print("=" * 72)
    header = f"{'day':>4} {'season':>7}  " + "  ".join(f"{k:>16}" for k in board_keys)
    print(header)
    print("-" * len(header))
    for day in SAMPLE_DAYS:
        if day not in samples:
            continue
        sev, season = samples[day]
        row = f"{day:>4} {season:>7}  " + "  ".join(f"{sev.get(k, 0.0):>16.2f}" for k in board_keys)
        print(row)
    print("-" * len(header))

    # the worst problem at winter's approach -- what an intervention would target
    core2 = SimCore(config=_one_year())
    snap = core2.begin_turn()
    while core2.day < 82 and not core2.done:
        core2.commit_turn(); snap = core2.begin_turn()
    worst = core2.problems()[0]
    print("\nreadings:")
    print("  * problems are DATA the sim tracks: severity is READ from world-state "
          "each day,\n    not hardcoded. Two TYPES here -- 'scarcity' and 'capital_gap' "
          "-- prove the model\n    holds more than resource shortage.")
    print(f"  * at day 82 (winter looming) the board's worst problem is "
          f"'{worst.key}' (severity {worst.severity:.2f})\n    in the {worst.location} -- "
          "exactly what question 2 ('what is the problem?') should surface.")
    print("  * the index (Layer 2) prices whoever drives a severity down; "
          "interventions\n    (Layer 3) will target these same rows. The board is the "
          "seam that joins them.")
    return 0


def _one_year() -> Config:
    cfg = Config()
    cfg.years = 1.0
    return cfg


if __name__ == "__main__":
    raise SystemExit(main())
