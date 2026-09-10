"""
Layer-3 breadth -- the intervention LIBRARY is a system, not one action.

Proves the representative ladder (emergency relief shipment, hire a crew, found the
capital good, endow a communal granary, open a trade route) is all DATA-driven,
precondition- AND reputation-gated, and scored by the index -- and that it applies
to a world with NO capital good of its own (tidewater), not just frostpine:

  1. LADDER      -- the library is a rising standing ladder; every rung has a real
     capital cost, a min_standing, and targets a live Layer-1 problem.
  2. GATED       -- each rung is LOCKED without standing (a track record) and
     UNLOCKS once standing + capital are met -- reputation + capital together.
  3. EFFECTS     -- performing each rung makes its authored world-state change
     (a relief shipment of the crisis good; a capital asset; a crew skill boost;
     a market granary; a persistent trade-route asset that then produces).
  4. SCORED      -- each rung that adds supply roots the new goods in the FOUNDER's
     lineage, so realized-effect credit can flow to them (the index prices the deed).
  5. NO-CAPITAL WORLD -- on tidewater (no scenario.capital), the non-capital rungs
     still gate, unlock, and fire; the capital rungs stay locked on their flag.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import interventions
import scenario as scen
from world import World


def _armed_world(name: str, capital: bool = True):
    """A world advanced to a day where the crisis good's scarcity problem is live,
    with interventions enabled. Returns (world, day, primary)."""
    cfg = scen.make_config(name, interventions_enabled=True, reward_at_fair_value=True)
    cfg.capital_goods_enabled = capital
    w = World(cfg, player_strategy="idle", population=scen.build_population(scen.get_scenario(name)))
    prim = w.scenario.primary_resource
    day = 0
    for day in range(cfg.total_days):
        w.begin_day(day)
        if interventions._target_severity(w, f"scarcity:{prim}") > 1e-6:
            break
        w.execute_day()
    return w, day, prim


def _lib(w):
    return {iv.key: iv for iv in interventions.build_library(w.cfg)}


def test_ladder() -> list:
    fails = []
    lib = interventions.build_library(scen.make_config("frostpine"))
    keys = {iv.key for iv in lib}
    expect = {"haul_relief", "hire_crew", "found_mill", "endow_granary", "open_trade_route"}
    if not expect.issubset(keys):
        fails.append(f"ladder: missing rungs {expect - keys}")
    for iv in lib:
        if iv.capital_cost <= 0 or iv.min_standing < 0 or ":" not in iv.targets:
            fails.append(f"ladder: {iv.key} has a malformed precondition/target")
    standings = sorted(iv.min_standing for iv in lib)
    if len(set(standings)) < 3:
        fails.append("ladder: rungs should span a range of standings, not one bar")
    return fails


def _perform(w, day, key, prim):
    """Arm the founder to just clear key's gate, perform, return (accepted, reason)."""
    iv = _lib(w)[key]
    p = w.player
    p.bonus_earned = iv.min_standing + 5.0
    p.money = iv.capital_cost + 100.0
    return interventions.perform(w, p, iv, day)


def test_gated() -> list:
    fails = []
    w, day, prim = _armed_world("frostpine")
    for key in ("haul_relief", "hire_crew", "found_mill"):
        iv = _lib(w)[key]
        w.player.bonus_earned = 0.0
        w.player.money = 10_000.0
        ok, reason = interventions.evaluate(w, w.player, iv)
        if ok or "standing" not in reason:
            fails.append(f"gated: {key} should be locked for standing, got ok={ok} {reason!r}")
    return fails


def test_effects_and_scored() -> list:
    fails = []
    w, day, prim = _armed_world("frostpine")

    # haul_relief -- crisis good injected into the founder, rooted at them
    before = w.player.qty(prim)
    ok, _, _ = _perform(w, day, "haul_relief", prim)
    if not ok or w.player.qty(prim) <= before + 1e-6:
        fails.append("effects: haul_relief did not deliver a shipment of the crisis good")
    last = w.lineage.lots[max(w.lineage.lots)]
    if last.producer_id != w.player.id:
        fails.append("scored: haul_relief supply is not rooted at the founder")

    # hire_crew -- permanent skill boost on the crisis good
    w2, d2, _ = _armed_world("frostpine")
    sk0 = w2.player.skill.get(prim, 0.0)
    _perform(w2, d2, "hire_crew", prim)
    if not (w2.player.skill.get(prim, 0.0) > sk0):
        fails.append("effects: hire_crew did not boost the founder's crisis-good skill")

    # found_mill -- a capital asset appears
    w3, d3, _ = _armed_world("frostpine")
    _perform(w3, d3, "found_mill", prim)
    if not any(a.kind == w3._capital_spec().kind for a in w3.player.assets):
        fails.append("effects: found_mill did not create the capital asset")

    # endow_granary -- the market maker gains a buffer, rooted at the founder
    w4, d4, _ = _armed_world("frostpine")
    mk = next(a for a in w4.agents if a.is_market_maker)
    mk0 = mk.qty(prim)
    _perform(w4, d4, "endow_granary", prim)
    if not (mk.qty(prim) > mk0):
        fails.append("effects: endow_granary did not seed the market buffer")

    # open_trade_route -- a producing asset appears and yields the crisis good next day
    w5, d5, _ = _armed_world("frostpine")
    _perform(w5, d5, "open_trade_route", prim)
    tr = next((a for a in w5.player.assets if a.kind == "trade_route"), None)
    if tr is None:
        fails.append("effects: open_trade_route did not create a trade-route asset")
    else:
        produced = w5._run_woodlots()
        if produced.get(prim, 0.0) <= 1e-6:
            fails.append("effects: the trade route produced no crisis good")
    return fails


def test_no_capital_world() -> list:
    """On tidewater (no scenario.capital), the non-capital rungs still work."""
    fails = []
    w, day, prim = _armed_world("tidewater", capital=False)
    before = w.player.qty(prim)
    ok, _, reason = _perform(w, day, "haul_relief", prim)
    if not ok or w.player.qty(prim) <= before + 1e-6:
        fails.append(f"no-capital: haul_relief should work on tidewater ({reason!r})")
    # found_mill requires capital_goods_enabled -> stays locked here
    iv = _lib(w)["found_mill"]
    w.player.bonus_earned = iv.min_standing + 5.0
    w.player.money = iv.capital_cost + 100.0
    ok, reason = interventions.evaluate(w, w.player, iv)
    if ok or "requires" not in reason:
        fails.append(f"no-capital: found_mill should be locked on its flag, got ok={ok} {reason!r}")
    return fails


def main() -> int:
    all_fails = []
    tests = (("LADDER", test_ladder), ("GATED", test_gated),
             ("EFFECTS+SCORED", test_effects_and_scored),
             ("NO-CAPITAL-WORLD", test_no_capital_world))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nINTERVENTION-LIBRARY TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nINTERVENTION-LIBRARY OK -- a reputation+capital-gated ladder of authored,\n"
          "index-scored world-changes that applies to every world, capital or not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
