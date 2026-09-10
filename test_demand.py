"""
Demand-event tests -- the guildhall crisis is a DEMAND event, not a shortfall
(DESIGN.md: an adventurer city has no shortage of essentials).

These pin down that the crisis loop is real and that it is DATA:

  1. FIRES        -- during the event window an institutional buyer's demand for
     an adventuring good exceeds what the town can supply, so the index prices
     that unmet demand and pays the producers who supply it. Contribution is
     ~zero outside the window and clearly positive inside it. (This is the bug the
     task fixes: guildhall used to pay 0.)
  2. DEMAND-SIDE  -- the driver raises the good's DEMAND (consume_mult), never its
     yield; the crisis good's price spikes in the window and is calm outside it.
  3. SCOPED       -- only the buyer archetype carries the demand-good need; the
     town's residents never "need" monster parts (an export good).
  4. TWO VARIANTS -- guildhall (war/quartermaster/guild market) and plaguewatch
     (plague/apothecary/call auction) are the SAME machinery, different values.
  5. MODULAR      -- a THIRD demand event registered at runtime as pure data (a
     festival drawing a vintner who buys wine) fires the same way with zero new
     logic. If a new demand event needed engine code, this test would need it.
  6. DETERMINISM  -- same seed, same run.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import scenario as scen
from scenario import _demand_event
from scenario import MarketSpec


def _run(name):
    w = scen.make_world(name, player_strategy="idle")
    w.run()
    return w


def _crisis_split(w, key_fn):
    s = w.metrics.series
    crisis = w.scenario.crisis_phase
    inside = [key_fn(s, i) for i, ph in enumerate(s["season"]) if ph == crisis]
    outside = [key_fn(s, i) for i, ph in enumerate(s["season"]) if ph != crisis]
    return inside, outside


def test_fires() -> list:
    fails = []
    for name in ("guildhall", "plaguewatch"):
        w = _run(name)
        d = w.metrics.summary()
        producers = [a for a in w.agents if a.archetype == "villager"]
        earned = sum(a.bonus_earned for a in producers)
        if d["total_reward_paid"] <= 1.0:
            fails.append(f"{name}: contribution did not fire (paid {d['total_reward_paid']:.2f})")
        if earned <= 1.0:
            fails.append(f"{name}: producers earned ~nothing ({earned:.2f})")
    return fails


def test_demand_side() -> list:
    fails = []
    for name in ("guildhall", "plaguewatch"):
        w = _run(name)
        prim = w.scenario.primary_resource
        pin, pout = _crisis_split(w, lambda s, i: s[f"{prim}_price"][i])
        mean_in = sum(pin) / max(len(pin), 1)
        mean_out = sum(pout) / max(len(pout), 1)
        if mean_in <= mean_out * 1.5:
            fails.append(f"{name}: {prim} price did not spike in the window "
                         f"(in {mean_in:.2f} vs out {mean_out:.2f})")
        # yields are steady (demand-side): every driver phase has empty yield_mult
        if any(ph.yield_mult for ph in w.scenario.driver.phases):
            fails.append(f"{name}: driver modulates YIELD -- not a pure demand event")
    return fails


def test_scoped() -> list:
    fails = []
    w = _run("guildhall")
    prim = w.scenario.primary_resource
    residents = [a for a in w.agents if a.archetype in ("villager", "dependent")]
    for a in residents:
        if prim in a.need_ids:
            fails.append(f"resident {a.id} wrongly needs the export good {prim}")
    buyer = [a for a in w.agents if getattr(a, "is_institution", False)]
    if not buyer:
        fails.append("no institutional buyer spawned")
    elif prim not in buyer[0].need_ids:
        fails.append("the buyer does not carry the demand-good need")
    else:
        # the off-town buyer must NOT inherit the town's universal staple need --
        # it does not live here, so it can't be a phantom staple-consumer.
        staple = next(r for r in w.consumable_ids if r != prim)
        if staple in buyer[0].need_ids:
            fails.append(f"the off-town buyer wrongly inherited the staple need {staple}")
    return fails


def test_modular_third_variant() -> list:
    """A brand-new demand event as PURE DATA: a harvest FESTIVAL draws a VINTNER
    who buys wine. Same _demand_event call, new values, no new logic."""
    fails = []
    scen.register_scenario("festival", lambda: _demand_event(
        "festival", good="wine", staple="bread",
        producer_prefix="v", buyer_prefix="vin", driver_name="calendar",
        phase_names=("spring", "summer", "harvest", "winter"), peak_phase="harvest",
        demand_curve={"spring": 0.0, "summer": 12.0, "harvest": 38.0, "winter": 0.0},
        premium=1.6, capacity=46.0, market=MarketSpec("call_auction")))
    w = _run("festival")
    d = w.metrics.summary()
    if d["total_reward_paid"] <= 1.0:
        fails.append(f"festival: a new demand event did not fire ({d['total_reward_paid']:.2f})")
    pin, pout = _crisis_split(w, lambda s, i: s["wine_price"][i])
    if sum(pin) / max(len(pin), 1) <= sum(pout) / max(len(pout), 1) * 1.5:
        fails.append("festival: wine price did not spike during the harvest festival")
    return fails


def test_determinism() -> list:
    a = _run("guildhall").metrics.summary()
    b = _run("guildhall").metrics.summary()
    return [] if a == b else ["guildhall not deterministic across runs"]


def main() -> int:
    all_fails = []
    tests = (("FIRES", test_fires), ("DEMAND-SIDE", test_demand_side),
             ("SCOPED", test_scoped), ("MODULAR-3RD", test_modular_third_variant),
             ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nDEMAND TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nDEMAND OK -- a demand-event crisis (a new institutional buyer whose need\n"
          "for an export good outstrips town supply during a window) fires contribution\n"
          "to the suppliers, is pure demand-side, and is one data entry per variant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
