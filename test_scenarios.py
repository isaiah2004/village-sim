"""
Cross-scenario hardening -- one guard that holds for EVERY registered world.

Adding a scenario is meant to be one data entry; this test makes sure a new world
can't quietly ship broken or inert. For every name in the registry it asserts:

  1. HEADLESS   -- make_world(name).run() completes a full year.
  2. CRISIS FIRES -- the world is not inert: over the year the crisis good runs a
     real shortfall (total unmet > 0) AND realized-effect contribution is paid
     (someone's resource did stabilising work) AND the crisis is felt in the
     market (the crisis phase's mean price of the crisis good exceeds the calm
     phases'). This catches a scenario whose driver/needs/market don't actually
     bite.
  3. SAVE/LOAD  -- a SimCore for the world serializes, reloads into a fresh core,
     and re-serializes BYTE-IDENTICALLY (the round-trip is faithful for its goods,
     archetypes, and driver phases).
  4. CONTRACT   -- the world drives fully through the SimCore contract to
     completion, and its snapshot exposes the generic reads a body needs
     (scenario / primary_resource / consumables / markets).

If any registered scenario fails, this is a real regression -- fix the scenario or
the engine, never weaken the assertion.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import scenario as scen
import persistence
from simcore import SimCore


def _fresh(name: str) -> SimCore:
    return SimCore(config=scen.make_config(name),
                   population=scen.build_population(scen.get_scenario(name)))


def test_headless() -> list:
    fails = []
    for name in scen.scenario_names():
        w = scen.make_world(name)
        w.run()
        if w.day < w.cfg.total_days - 1:
            fails.append(f"{name}: did not run a full year (day {w.day})")
    return fails


def test_crisis_fires() -> list:
    fails = []
    for name in scen.scenario_names():
        sc = scen.get_scenario(name)
        prim, crisis = sc.primary_resource, sc.crisis_phase
        w = scen.make_world(name)
        w.run()
        s = w.metrics.series
        d = w.metrics.summary()
        total_unmet = sum(s[f"unmet_{prim}"])
        if total_unmet <= 1e-6:
            fails.append(f"{name}: inert -- no unmet {prim} all year")
        if d["total_reward_paid"] <= 1e-6:
            fails.append(f"{name}: inert -- no contribution ever paid")
        cp = [s[f"{prim}_price"][i] for i, ph in enumerate(s["season"]) if ph == crisis]
        ncp = [s[f"{prim}_price"][i] for i, ph in enumerate(s["season"]) if ph != crisis]
        mean_c = sum(cp) / len(cp) if cp else 0.0
        mean_n = sum(ncp) / len(ncp) if ncp else 0.0
        if not (mean_c > mean_n):
            fails.append(f"{name}: crisis not felt in market ({crisis} price "
                         f"{mean_c:.2f} <= calm {mean_n:.2f})")
    return fails


def test_save_load_byte_identical() -> list:
    fails = []
    for name in scen.scenario_names():
        core = _fresh(name)
        for _ in range(60):
            core.step()
        blob1 = persistence.serialize_core(core)
        core2 = _fresh(name)
        persistence.deserialize_core(core2, blob1)
        blob2 = persistence.serialize_core(core2)
        if blob1 != blob2:
            # find a first differing key for a useful message
            diff = next((k for k in set(blob1) | set(blob2)
                         if blob1.get(k) != blob2.get(k)), "?")
            fails.append(f"{name}: save/load not byte-identical (first diff at {diff!r})")
    return fails


def test_drives_through_contract() -> list:
    fails = []
    for name in scen.scenario_names():
        core = _fresh(name)
        while not core.done:
            core.step()
        snap = core.snapshot()
        if snap.scenario != name:
            fails.append(f"{name}: snapshot.scenario is {snap.scenario!r}")
        if not snap.consumables or not snap.markets:
            fails.append(f"{name}: snapshot missing generic reads")
        prim = scen.get_scenario(name).primary_resource
        prim = prim.value if hasattr(prim, "value") else prim
        if snap.primary_resource != prim:
            fails.append(f"{name}: snapshot.primary_resource is {snap.primary_resource!r}")
    return fails


def main() -> int:
    all_fails = []
    tests = (("HEADLESS", test_headless), ("CRISIS-FIRES", test_crisis_fires),
             ("SAVE/LOAD", test_save_load_byte_identical),
             ("CONTRACT", test_drives_through_contract))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nCROSS-SCENARIO TESTS FAILED ({len(all_fails)})")
        return 1
    print(f"\nCROSS-SCENARIO OK -- all {len(scen.scenario_names())} registered worlds run\n"
          "a full year, fire a real crisis, save/load byte-identically, and drive\n"
          "through the contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
