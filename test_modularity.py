"""
The MODULARITY ACCEPTANCE test (the mission's headline claim, DESIGN.md
"Modularity contract -- scenarios are DATA").

It proves that adding a WHOLE NEW WORLD is a single data entry -- a name plus
values -- with ZERO new logic anywhere in the sim, the index, or the contract.
The test does the only thing a new world is allowed to require: it builds a
`Scenario` VALUE (novel resources, a novel driver, a novel need, a novel capital
good) and registers it. Then it drives that world:

  1. HEADLESS     -- scenario.make_world(name).run() completes a full year and the
     world's mechanics (driver phases, per-resource needs, market, capital) all
     operate on the new resource ids with no code that names them.
  2. THROUGH THE CONTRACT -- a SimCore renders the new world entirely through the
     generic contract reads (Snapshot.scenario / .consumables / .primary_resource
     / .village_unmet, MarketView, AgentView.holdings). A body needs no new code.
  3. CRISIS EMERGES -- the driver's crisis phase actually bites (unmet crisis good
     concentrates there), proving the DATA drove real behaviour, not a stub.
  4. GOLDEN SAFE  -- registering a throwaway world does not perturb frostpine; the
     baseline resources are still exactly wood/food (regression.py owns the full
     byte-identity proof; this asserts isolation directly).

If this test ever needs a change to world.py / accountant.py / contract.py to make
a new scenario run, the modularity contract is broken. It doesn't.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import contract as C
import scenario as scen
from scenario import (CapitalSpec, Driver, MarketSpec, NeedSpec, Phase, PopSpec,
                      ResourceSpec, Scenario)
from simcore import SimCore


# ---------------------------------------------------------------------------
# THE ENTIRE COST OF A NEW WORLD: one Scenario value. No engine code below.
# "saltmarsh" -- peat-cutters. Peat (the crisis fuel) is cut fast in dry spells
# and barely at all when the marsh floods; reed is the comfortable staple. A
# drying-kiln (capital, built from reed, fuelled by reed) bakes extra peat.
# ---------------------------------------------------------------------------
def _saltmarsh() -> Scenario:
    peat_yield = {"thaw": 1.1, "dry": 1.5, "flood": 0.2, "frost": 0.7}
    phases = tuple(
        Phase(name=n, length=30,
              yield_mult={"peat": peat_yield[n], "reed": 1.0},
              consume_mult={"peat": 1.0, "reed": 1.0})
        for n in ("thaw", "dry", "flood", "frost")
    )
    driver = Driver(name="marsh_tides", phases=phases)
    resources = (
        ResourceSpec("peat", intrinsic_value=5.0, consumable=True, base_yield=2.0, base_consume=1.0),
        ResourceSpec("reed", intrinsic_value=6.0, consumable=True, base_yield=2.5, base_consume=1.0),
        ResourceSpec("kiln", intrinsic_value=50.0, consumable=False),
    )
    needs = (NeedSpec("peat_fire", "peat", rewarded=True),
             NeedSpec("reed_thatch", "reed", rewarded=False))
    capital = (CapitalSpec("kiln", output_resource="peat", output_per_level=1.3,
                           upkeep_resource="reed", upkeep_per_level=0.5,
                           build_cost_resource="reed", build_cost=7.0, max_level=4),)
    population = (PopSpec("villager", 8, "p"),
                 PopSpec("dependent", 3, "r", kwargs={"produces": "reed"}),
                 PopSpec("market_maker", 1, "mk",
                         kwargs={"daily_volume": 16.0, "target_inventory": 40.0}))
    return Scenario(
        name="saltmarsh", resources=resources, driver=driver, needs=needs,
        market=MarketSpec("call_auction"), population=population,
        primary_resource="peat", crisis_phase="flood", capital=capital,
        tunables={"capital_goods_enabled": True},
    )


def _register():
    scen.register_scenario("saltmarsh", _saltmarsh)


def test_headless() -> list:
    fails = []
    w = scen.make_world("saltmarsh", player_strategy="idle")
    w.run()
    # the world iterated the new resource ids with no code that names them
    if set(w.consumable_ids) != {"peat", "reed"}:
        fails.append(f"consumable_ids wrong: {w.consumable_ids}")
    if w.day < w.cfg.total_days - 1:
        fails.append(f"did not run a full year: day={w.day} of {w.cfg.total_days}")
    d = w.metrics.summary()
    # a full-year peat crisis exists (the whole point of the world)
    if d.get("village_unmet_peat", 0.0) <= 0.0:
        fails.append("expected some unmet peat over the year (crisis good)")
    return fails


def test_through_contract() -> list:
    fails = []
    core = SimCore(config=scen.make_config("saltmarsh"),
                   population=scen.build_population(scen.get_scenario("saltmarsh")))
    while not core.done:
        core.step()
    snap = core.snapshot()
    if snap.scenario != "saltmarsh":
        fails.append(f"snapshot scenario wrong: {snap.scenario}")
    if snap.primary_resource != "peat":
        fails.append(f"primary_resource wrong: {snap.primary_resource}")
    if tuple(snap.consumables) != ("peat", "reed"):
        fails.append(f"consumables wrong: {snap.consumables}")
    # generic reads carry the novel goods with no contract change
    if "peat" not in snap.village_unmet or "reed" not in snap.village_unmet:
        fails.append(f"village_unmet missing novel goods: {snap.village_unmet}")
    mkts = {m.resource.value if hasattr(m.resource, "value") else m.resource for m in snap.markets}
    if mkts != {"peat", "reed"}:
        fails.append(f"markets wrong: {mkts}")
    any_player = next((a for a in snap.agents if a.is_player), None)
    if any_player is None or "peat" not in any_player.holdings:
        fails.append("AgentView.holdings does not carry the novel goods")
    return fails


def test_crisis_emerges() -> list:
    """The driver's DATA must produce real behaviour: peat unmet concentrates in
    the flood phase (peat yield collapses to 0.2 there)."""
    fails = []
    w = scen.make_world("saltmarsh", player_strategy="idle")
    w.run()
    s = w.metrics.series
    flood_unmet = sum(s["village_unmet_peat"][i]
                      for i, ph in enumerate(s["season"]) if ph == "flood")
    other_unmet = sum(s["village_unmet_peat"][i]
                      for i, ph in enumerate(s["season"]) if ph != "flood")
    if flood_unmet <= other_unmet:
        fails.append(f"crisis did not concentrate in flood: flood={flood_unmet:.1f} "
                     f"other={other_unmet:.1f}")
    return fails


def test_golden_isolation() -> list:
    """Registering a throwaway world must not perturb the baseline."""
    fails = []
    fp = scen.get_scenario("frostpine")
    if set(fp.consumable_ids()) != {"wood", "food"}:
        fails.append(f"frostpine consumables changed: {fp.consumable_ids()}")
    w = scen.make_world("frostpine", player_strategy="idle")
    w.run()
    d = w.metrics.summary()
    # frostpine still reports its historical wood-crisis keys
    for k in ("winter_village_unmet_wood", "max_wood_price", "village_unmet_wood"):
        if k not in d:
            fails.append(f"frostpine summary missing {k}")
    return fails


def main() -> int:
    _register()
    all_fails = []
    tests = (("HEADLESS", test_headless),
             ("THROUGH-CONTRACT", test_through_contract),
             ("CRISIS-EMERGES", test_crisis_emerges),
             ("GOLDEN-ISOLATION", test_golden_isolation))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nMODULARITY TEST FAILED ({len(all_fails)})")
        return 1
    print("\nMODULARITY OK -- a whole new world ('saltmarsh': novel resources, driver,\n"
          "need, and capital good) was added as ONE Scenario value and runs headlessly\n"
          "AND through the contract with ZERO new logic in the sim, index, or contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
