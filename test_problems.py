"""
Layer 1 tests -- the world-state problem model (DESIGN.md).

Proves "what is the problem?" (question 2 of the four) is now first-class DATA the
sim tracks, not a hardcoded wood/winter case:

  1. TYPED-LOCATED-DATA -- the board is a set of typed, located problems with
     normalised severities; two distinct TYPES ship (scarcity, capital_gap).
  2. TRACKED           -- severity is READ from world-state and moves as the world
     moves: wood scarcity climbs toward winter; it is not a constant.
  3. READS-WORLD-STATE -- the capital-gap problem falls when the player builds
     infrastructure (a woodlot) -- proof severity reflects the actual world, so an
     intervention could target it and drive it down.
  4. INDEX-ALIGNED     -- a scarcity problem's severity IS the index's own scarcity
     signal (accountant), not a second definition -- so Layer 2 prices exactly the
     problem Layer 1 names.
  5. EXPOSED / SORTED  -- the board is on the contract snapshot and SimCore.problems()
     returns it worst-first.
  6. DETERMINISM.

The board is observational (regression.py proves the 140 golden metrics stay
byte-identical); these tests exercise the model itself. Dependency-free.
"""
from __future__ import annotations

import sys

import contract as C
from config import Config, Resource
from simcore import SimCore


def _run_to(core: SimCore, day: int):
    """Advance an idle core to `day` and return its begin-of-day snapshot."""
    snap = core.begin_turn()
    while core.day < day and not core.done:
        core.commit_turn()
        snap = core.begin_turn()
    return snap


def _sev(core: SimCore, key: str) -> float:
    return next((p.severity for p in core.snapshot().problems if p.key == key), None)


def test_typed_located_data() -> list:
    fails = []
    core = SimCore(config=Config())
    core.begin_turn()
    board = core.snapshot().problems
    keys = {p.key for p in board}
    if keys != {"scarcity:wood", "scarcity:food", "capital_gap:wood"}:
        fails.append(f"typed-located-data: unexpected board {sorted(keys)}")
    kinds = {p.kind for p in board}
    if kinds != {"scarcity", "capital_gap"}:
        fails.append(f"typed-located-data: expected two problem TYPES, got {sorted(kinds)}")
    for p in board:
        if p.location != "village":
            fails.append(f"typed-located-data: {p.key} not located ({p.location!r})")
        if not (0.0 <= p.severity <= 1.0):
            fails.append(f"typed-located-data: {p.key} severity out of range ({p.severity})")
    return fails


def test_tracked() -> list:
    """Wood-scarcity severity must move with the world -- higher as winter nears
    than in early spring."""
    fails = []
    cfg = Config(); cfg.years = 1.0
    core = SimCore(config=cfg)
    _run_to(core, 8)
    early = _sev(core, "scarcity:wood")
    _run_to(core, 78)                    # late autumn, winter forecast looming
    pre_winter = _sev(core, "scarcity:wood")
    if early is None or pre_winter is None:
        fails.append("tracked: scarcity:wood missing from the board")
    elif not (pre_winter > early + 0.05):
        fails.append(f"tracked: wood scarcity did not climb toward winter "
                     f"(spring={early:.3f} pre-winter={pre_winter:.3f})")
    return fails


def test_reads_world_state() -> list:
    """Building infrastructure must lower the capital-gap severity -- the problem
    reflects the real world, so an intervention could target and reduce it."""
    fails = []
    def gap_at(day, build):
        cfg = Config(); cfg.years = 1.0; cfg.capital_goods_enabled = True
        core = SimCore(config=cfg)
        snap = core.begin_turn()
        while core.day < day and not core.done:
            if build and core.day in (2, 3, 4, 5, 6):
                core.submit(C.Gather(Resource.WOOD))
                core.submit(C.BuildWoodlot())
            core.commit_turn()
            snap = core.begin_turn()
        return _sev(core, "capital_gap:wood")
    without = gap_at(20, build=False)
    with_woodlot = gap_at(20, build=True)
    if without is None or with_woodlot is None:
        fails.append("reads-world-state: capital_gap:wood missing")
    elif not (with_woodlot < without - 0.05):
        fails.append(f"reads-world-state: building a woodlot did not lower the capital gap "
                     f"(no-build={without:.3f} built={with_woodlot:.3f})")
    return fails


def test_index_aligned() -> list:
    """A scarcity problem's severity must equal the index's OWN scarcity signal --
    one definition of 'how bad is it', shared by Layer 1 and Layer 2."""
    fails = []
    cfg = Config(); cfg.years = 1.0
    core = SimCore(config=cfg)
    _run_to(core, 70)
    sev = _sev(core, "scarcity:wood")
    index_ratio = round(core.world.accountant.state.scarcity.get(Resource.WOOD, 0.0), 6)
    if sev != index_ratio:
        fails.append(f"index-aligned: problem severity {sev} != index scarcity {index_ratio}")
    return fails


def test_exposed_sorted() -> list:
    fails = []
    cfg = Config(); cfg.years = 1.0
    core = SimCore(config=cfg)
    _run_to(core, 70)
    ranked = core.problems()
    if not ranked or not all(isinstance(p, C.ProblemView) for p in ranked):
        fails.append("exposed-sorted: problems() did not return ProblemView list")
        return fails
    sev = [p.severity for p in ranked]
    if sev != sorted(sev, reverse=True):
        fails.append(f"exposed-sorted: problems() not worst-first: {sev}")
    return fails


def test_determinism() -> list:
    fails = []
    def board_at(day):
        core = SimCore(config=Config())
        _run_to(core, day)
        return [(p.key, p.severity) for p in core.problems()]
    if board_at(60) != board_at(60):
        fails.append("determinism: two runs produced different boards")
    return fails


def main() -> int:
    all_fails = []
    tests = (("TYPED-LOCATED-DATA", test_typed_located_data), ("TRACKED", test_tracked),
             ("READS-WORLD-STATE", test_reads_world_state), ("INDEX-ALIGNED", test_index_aligned),
             ("EXPOSED-SORTED", test_exposed_sorted), ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nPROBLEM TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nPROBLEM TESTS OK -- problems are typed, located, severity-tracked DATA read\n"
          "from world-state; the index prices the same severity Layer 1 names.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
