"""
Scenario-agnostic playable-View test (the "a 2D wrapper can test any world" bar).

Proves the generic body in `view_play.py` can select and play EVERY registered
scenario purely through the SimCore contract -- no per-scenario code, no crash:

  1. PLAYS-ALL   -- view_play.demo_one runs a full year for every registered
     scenario, driving it through the contract to completion.
  2. RENDERS     -- the generic dashboard renders for every scenario from the
     snapshot's generic fields alone (scenario/consumables/primary/markets/
     problems/interventions) -- it never assumes wood/food.
  3. COMMANDS    -- the typed commands map to contract intents for a novel world
     (gather/sell/build), and a player's gathering of the crisis good measurably
     helps vs. doing nothing (the body is actually playable, not inert).
  4. LAYER3-FINANCING -- the body drives the whole Layer-3 loop: build a reputation
     (propagated deeds), negotiate a loan with the merchant, and the sim funds and
     founds the intervention; an unproven borrower is declined.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import scenario as scen
import view_play


def test_plays_all() -> list:
    fails = []
    for name in scen.scenario_names():
        try:
            w = view_play.demo_one(name)
        except Exception as e:  # noqa: BLE001 -- a crash on any world is the failure
            fails.append(f"{name}: demo_one raised {type(e).__name__}: {e}")
            continue
        if not isinstance(w, dict) or "total_reward_paid" not in w:
            fails.append(f"{name}: welfare summary missing")
    return fails


def test_renders() -> list:
    fails = []
    for name in scen.scenario_names():
        core = view_play._core(name)
        core.begin_turn()
        try:
            text = view_play.dashboard(core)
        except Exception as e:  # noqa: BLE001
            fails.append(f"{name}: dashboard raised {type(e).__name__}: {e}")
            continue
        if name not in text or "crisis good:" not in text:
            fails.append(f"{name}: dashboard missing generic header")
    return fails


def test_commands_have_effect() -> list:
    """On a non-frostpine world, a player who works the crisis good every day
    leaves the village less short than an idle player -- the body is playable."""
    fails = []
    import contract as C
    name = "tidewater"
    prim = scen.get_scenario(name).primary_resource

    def run(active: bool) -> float:
        core = view_play._core(name)
        while not core.done:
            core.begin_turn()
            if active:
                core.submit(C.Gather(prim))       # a command view_play issues
                core.submit(C.Trade(prim, "sell", 3.0,
                                    view_play._price_for(core, prim, "sell")))
            core.commit_turn()
        return core.welfare().get(f"village_unmet_{prim}", 0.0)

    idle, played = run(False), run(True)
    if not (played < idle):
        fails.append(f"{name}: playing did not reduce unmet {prim} "
                     f"(idle {idle:.1f}, played {played:.1f})")
    return fails


def test_layer3_financing() -> list:
    """The generic body drives the WHOLE Layer-3 loop on a scenario: build a
    reputation (deeds propagate), negotiate a loan with the merchant to fund an
    intervention, and the sim's hard gate applies it -- a mill founded, a loan
    recorded. An unproven borrower is declined by the merchant (the soft gate)."""
    import contract as C
    fails = []
    core = view_play._core("frostpine")
    p = core.world.by_id["PLAYER"]
    p.bonus_earned = 300.0                       # a strong track record of deeds
    core.begin_turn()
    for _ in range(45):                          # let word of the deed spread
        if core.done:
            break
        core.begin_turn(); core.submit(C.Gather("wood")); core.commit_turn()
    core.begin_turn()
    p.money = 5.0                                # broke -> must finance via a loan
    status = view_play.negotiate_deal(core, "found_mill")
    core.commit_turn()
    resolved = [e for e in core.drain_events() if isinstance(e, C.DealResolved)]
    me = next(a for a in core.snapshot().agents if a.is_player)
    if not (resolved and resolved[0].struck):
        fails.append(f"financing: deal did not resolve struck ({status})")
    if me.woodlot_level < 1:
        fails.append("financing: the loan-funded mill was not founded")
    if not core.snapshot().loans:
        fails.append("financing: no loan was recorded")
    # an unproven borrower is turned away by the merchant (soft gate), no deal
    core2 = view_play._core("tidewater")
    core2.begin_turn()
    st = view_play.negotiate_deal(core2, "haul_relief")
    if "no deal" not in st:
        fails.append(f"financing: an unproven borrower should be declined ({st})")
    return fails


def main() -> int:
    all_fails = []
    tests = (("PLAYS-ALL", test_plays_all), ("RENDERS", test_renders),
             ("COMMANDS", test_commands_have_effect),
             ("LAYER3-FINANCING", test_layer3_financing))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nVIEW-PLAY TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nVIEW-PLAY OK -- one scenario-agnostic body selects and plays every\n"
          "registered world through the contract; a player's actions actually help.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
