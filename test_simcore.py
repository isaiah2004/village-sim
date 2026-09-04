"""
Facade tests for SimCore (Phase 1). Dependency-free; exit 0 = all pass.

Proves:
  1. PARITY  -- driving the sim through SimCore with no intents is identical to a
     direct idle-player World run (the facade adds nothing, perturbs nothing).
  2. INTENTS -- submitted Gather intents actually make the player produce.
  3. SPEAK   -- a Speak intent injects a claim that spreads through the network.
"""
from __future__ import annotations

import sys

import contract as C
from config import Config, Resource
from simcore import SimCore
from world import World

VILLAGE = ("village_unmet_wood", "winter_village_unmet_wood", "village_unmet_food",
           "shortage_days", "player_final_money", "player_bonus_earned")


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_parity() -> list:
    fails = []
    # reference: direct World, idle player, accountant on (== NO_PLAYER scenario)
    ref = World(Config(), player_strategy="idle")
    ref.run()
    ref_sum = ref.metrics.summary()

    # facade: SimCore, no intents ever submitted
    core = SimCore(propagation=False)
    while not core.done:
        core.step()
    got = core.welfare()

    for k in VILLAGE:
        if not approx(ref_sum[k], got[k]):
            fails.append(f"parity.{k}: idle={ref_sum[k]} facade={got[k]}")
    return fails


def test_intents() -> list:
    fails = []
    core = SimCore(propagation=False)
    produced_by_player = 0
    max_player_wood = 0.0
    while not core.done:
        snap = core.begin_turn()
        me = next(a for a in snap.agents if a.is_player)
        # gather wood while we have stamina
        n = int(me.stamina)  # ~ two-three actions
        for _ in range(max(1, n)):
            core.submit(C.Gather(Resource.WOOD))
        core.commit_turn()
        for ev in core.drain_events():
            if isinstance(ev, C.Produced) and ev.agent_id == "PLAYER":
                produced_by_player += 1
        max_player_wood = max(max_player_wood, core.snapshot().agents[-1].wood
                              if core.snapshot().agents[-1].is_player else 0.0)
    # player should have produced wood many times, and be scored for contribution
    if produced_by_player < 10:
        fails.append(f"intents: player produced only {produced_by_player} times (expected many)")
    pv = next(a for a in core.snapshot().agents if a.is_player)
    if pv.wood <= 0 and max_player_wood <= 0:
        fails.append("intents: player never accumulated wood despite gathering")
    return fails


def test_speak() -> list:
    fails = []
    core = SimCore(propagation=True)
    peak_food_awareness = 0.0
    spoke = False
    while not core.done:
        core.begin_turn()
        if core.day == 66 and not spoke:
            core.submit(C.Speak(Resource.FOOD, 0.8, False, "player_rumour", authority=0.7))
            spoke = True
        core.commit_turn()
        for ev in core.drain_events():
            if isinstance(ev, C.BeliefState) and ev.resource == Resource.FOOD:
                peak_food_awareness = max(peak_food_awareness, ev.awareness)
    if peak_food_awareness <= 0.1:
        fails.append(f"speak: rumour barely spread (peak food awareness={peak_food_awareness})")
    return fails


def main() -> int:
    all_fails = []
    for name, fn in (("PARITY", test_parity), ("INTENTS", test_intents), ("SPEAK", test_speak)):
        fails = fn()
        status = "ok" if not fails else "FAIL"
        print(f"[{status}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nSIMCORE TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nSIMCORE TESTS OK -- facade parity, intents, and speak all pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
