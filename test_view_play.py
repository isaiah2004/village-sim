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


def main() -> int:
    all_fails = []
    tests = (("PLAYS-ALL", test_plays_all), ("RENDERS", test_renders),
             ("COMMANDS", test_commands_have_effect))
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
