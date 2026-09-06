"""
Layer 3 tests -- the intervention library (DESIGN.md's "how the player changes
the world"), first piece.

Proves the authored, deterministic spine of the loop
  change the world -> the index prices it -> (reputation) -> gates the next:

  1. LIBRARY-DATA -- interventions are data (key, title, targets a real Layer-1
     problem, capital + standing preconditions).
  2. GATED-OFF    -- with interventions disabled (default), Perform is a no-op:
     rejected with a reason, no capital spent, no world-change. (regression.py
     separately proves the 140 golden metrics stay byte-identical.)
  3. PRECONDITIONS-- found_mill is LOCKED without standing/capital and UNLOCKS
     when both are met -- the reputation/capital gate.
  4. EFFECT       -- performing it changes world-state: the founder gains the
     mill (a capital asset), the capital-gap problem's severity FALLS, and the
     index credits the founder as the mill's wood meets needs.
  5. EVENT        -- InterventionPerformed reports accepted/reason through the
     contract.
  6. DETERMINISM.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import contract as C
import interventions
from config import Config, Resource
from simcore import SimCore


def _game_cfg(**over) -> Config:
    cfg = Config()
    cfg.years = over.pop("years", 2.0)
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    cfg.interventions_enabled = over.pop("interventions_enabled", True)
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def _found_mill_run(cfg: Config):
    """Script a player who supplies wood (earning standing + capital) and founds
    the mill as soon as the gate opens. Returns (core, founded_day, events)."""
    core = SimCore(config=cfg, propagation=True)
    founded_day = None
    perform_events = []
    while not core.done:
        snap = core.begin_turn()
        me = next(a for a in snap.agents if a.is_player)
        menu = {iv[0]: iv for iv in core.interventions()}
        if founded_day is None and menu["found_mill"][5]:      # can_perform
            core.submit(C.Perform("found_mill"))
            founded_day = core.day
        else:
            for _ in range(int(me.stamina)):
                core.submit(C.Gather(Resource.WOOD))
            wm = next(m for m in snap.markets if m.resource == Resource.WOOD)
            if me.wood > 4:
                core.submit(C.Trade(Resource.WOOD, "sell", me.wood - 3, wm.ref_price * 0.95))
        core.commit_turn()
        for ev in core.drain_events():
            if isinstance(ev, C.InterventionPerformed):
                perform_events.append(ev)
    return core, founded_day, perform_events


def test_library_data() -> list:
    fails = []
    lib = {iv.key: iv for iv in interventions.build_library(Config())}
    if "found_mill" not in lib:
        fails.append("library-data: found_mill missing from the library")
        return fails
    iv = lib["found_mill"]
    if iv.targets != "capital_gap:wood":
        fails.append(f"library-data: found_mill targets {iv.targets!r}, expected a real problem key")
    if iv.capital_cost <= 0 or iv.min_standing <= 0:
        fails.append("library-data: found_mill should have real capital/standing preconditions")
    return fails


def test_gated_off() -> list:
    """Disabled: Perform is a no-op with a reason; nothing changes."""
    fails = []
    core = SimCore(config=_game_cfg(interventions_enabled=False, years=1.0), propagation=True)
    snap = core.begin_turn()
    me0 = next(a for a in snap.agents if a.is_player)
    money_before = me0.money
    core.submit(C.Perform("found_mill"))
    core.commit_turn()
    evs = [e for e in core.drain_events() if isinstance(e, C.InterventionPerformed)]
    if not evs or evs[0].accepted:
        fails.append("gated-off: disabled Perform should be rejected")
    elif "disabled" not in evs[0].reason:
        fails.append(f"gated-off: reason should mention disabled, got {evs[0].reason!r}")
    me1 = next(a for a in core.snapshot().agents if a.is_player)
    if any(getattr(a, "woodlot_level", 0) for a in core.snapshot().agents if a.is_player):
        fails.append("gated-off: a mill was built while interventions were disabled")
    if abs(me1.money - money_before) > 1e-9:
        fails.append("gated-off: capital was spent while disabled")
    return fails


def test_preconditions() -> list:
    """Locked without standing/capital; unlocked once both are met."""
    fails = []
    core = SimCore(config=_game_cfg(years=1.0), propagation=True)
    core.begin_turn()
    player = core.world.by_id["PLAYER"]

    player.bonus_earned = 0.0                       # no track record
    menu = {iv[0]: iv for iv in core.interventions()}
    can, reason = menu["found_mill"][5], menu["found_mill"][6]
    if can or "standing" not in reason:
        fails.append(f"preconditions: should be locked for standing, got can={can} reason={reason!r}")

    lib_iv = next(iv for iv in interventions.build_library(core.cfg))
    player.bonus_earned = lib_iv.min_standing + 5    # earned standing
    player.money = 0.0                               # but broke
    menu = {iv[0]: iv for iv in core.interventions()}
    can, reason = menu["found_mill"][5], menu["found_mill"][6]
    if can or "capital" not in reason:
        fails.append(f"preconditions: should be locked for capital, got can={can} reason={reason!r}")

    player.money = lib_iv.capital_cost + 10          # now afford it
    menu = {iv[0]: iv for iv in core.interventions()}
    if not menu["found_mill"][5]:
        fails.append(f"preconditions: should unlock once standing+capital met "
                     f"(reason={menu['found_mill'][6]!r})")
    return fails


def test_effect() -> list:
    """Founding the mill changes world-state and the index credits the founder."""
    fails = []
    core, founded_day, evs = _found_mill_run(_game_cfg())
    if founded_day is None:
        fails.append("effect: the player never met the gate to found the mill")
        return fails
    accepted = [e for e in evs if e.accepted and e.key == "found_mill"]
    if not accepted:
        fails.append("effect: no accepted found_mill event")
    me = next(a for a in core.snapshot().agents if a.is_player)
    if me.woodlot_level < 1:
        fails.append("effect: the founder has no mill after founding")
    # the capital-gap problem must have fallen from its no-capital ceiling of 1.0
    gap = next((p.severity for p in core.snapshot().problems if p.key == "capital_gap:wood"), 1.0)
    if not (gap < 1.0):
        fails.append(f"effect: capital gap did not fall after founding a mill ({gap})")
    # the index credited the founder (standing = realized contribution) meaningfully
    if core.score("PLAYER") <= 0.0:
        fails.append("effect: the index credited the founder nothing")
    return fails


def test_determinism() -> list:
    fails = []
    a = _found_mill_run(_game_cfg())
    b = _found_mill_run(_game_cfg())
    if a[1] != b[1] or round(a[0].score("PLAYER"), 6) != round(b[0].score("PLAYER"), 6):
        fails.append("determinism: two identical scripted runs diverged")
    return fails


def main() -> int:
    all_fails = []
    tests = (("LIBRARY-DATA", test_library_data), ("GATED-OFF", test_gated_off),
             ("PRECONDITIONS", test_preconditions), ("EFFECT", test_effect),
             ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nINTERVENTION TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nINTERVENTION TESTS OK -- interventions are precondition-gated, authored\n"
          "world-changes: gated off by default, unlocked by standing+capital, and when\n"
          "performed they change world-state and the index prices the deed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
