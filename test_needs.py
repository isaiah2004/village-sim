"""
Need-registry tests -- proof that Layer 2 is UNIVERSAL (DESIGN.md).

The contribution index must price/reward ANY registered problem through one
pipeline, with no per-scenario code. These tests pin that down:

  1. DATA-DEFINED  -- the registry is assembled from config data: wood (seasonal
     requirement, always rewarded) and food (flat requirement, rewarded only on
     opt-in). No resource is hardcoded into the index's logic.
  2. GATED-DEFAULT -- by default food is NOT a rewarded need, so no food
     contribution ever flows (the golden master is safe). regression.py proves the
     126 existing metrics are byte-identical; this asserts the mechanism directly.
  3. UNIVERSAL     -- flipping ONE data flag (reward_food_need) makes food route
     through the SAME reward_consumption + lineage + contrib_events path as wood:
     food producers earn realized-effect contribution for feeding the hungry, and
     food's fair value rises with its scarcity -- all with zero food-specific code.
  4. DETERMINISM   -- same seed, food-need on, same run.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

from accountant import Accountant
from config import Config, Resource, Season
from needs import build_registry
from world import World


def _run_collect_contrib(cfg: Config):
    """Run a full year, accumulating cross-agent contribution by resource from the
    accountant's own contrib_events (the felt 'who did my resource help' ledger)."""
    w = World(cfg, player_strategy="idle")
    paid = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}
    peak_food_fair = 0.0
    for day in range(cfg.total_days):
        w.begin_day(day)
        w.execute_day()
        peak_food_fair = max(peak_food_fair, w.accountant.state.fair_price[Resource.FOOD])
        for (_pid, _cid, _ck, res, amt, _rate, _seas) in w.accountant.state.contrib_events:
            if res in paid:
                paid[res] += amt
    return paid, peak_food_fair


def test_data_defined() -> list:
    fails = []
    reg = build_registry(Config())
    by_key = {n.key: n for n in reg}
    if set(by_key) != {"wood_heat", "food_hunger"}:
        fails.append(f"data-defined: unexpected registry keys {sorted(by_key)}")
        return fails
    wood, food = by_key["wood_heat"], by_key["food_hunger"]
    if wood.resource != Resource.WOOD or food.resource != Resource.FOOD:
        fails.append("data-defined: need resources wired wrong")
    # wood requirement mirrors the seasonal config; food is flat at food_per_day
    cfg = Config()
    if wood.requirement != cfg.wood_per_day:
        fails.append("data-defined: wood requirement is not the seasonal config data")
    if any(food.requirement[s] != cfg.food_per_day for s in Season):
        fails.append("data-defined: food requirement is not flat food_per_day")
    if not wood.rewarded:
        fails.append("data-defined: wood must be a rewarded need")
    if food.rewarded:
        fails.append("data-defined: food must NOT be rewarded by default (golden safety)")
    return fails


def test_gated_default() -> list:
    """By default, no food contribution may flow -- the mechanism, not just the
    golden numbers, must be off."""
    fails = []
    ac = Accountant(Config())
    if [n.key for n in ac.rewarded_needs()] != ["wood_heat"]:
        fails.append(f"gated-default: rewarded needs should be wood only, got "
                     f"{[n.key for n in ac.rewarded_needs()]}")
    paid, _ = _run_collect_contrib(Config())
    if paid[Resource.FOOD] > 1e-9:
        fails.append(f"gated-default: food contribution flowed while off ({paid[Resource.FOOD]:.4f})")
    return fails


def test_universal() -> list:
    """One data flag turns food into a rewarded need routed through the SAME
    pipeline as wood -- food producers earn, and food fair value tracks scarcity."""
    fails = []
    cfg = Config()
    cfg.reward_food_need = True          # pure data: register food as rewarded
    cfg.reward_at_fair_value = True      # price at fair value (the index's heart)
    cfg.food_blight_enabled = True       # create a real food scarcity to price

    ac = Accountant(cfg)
    if [n.key for n in ac.rewarded_needs()] != ["wood_heat", "food_hunger"]:
        fails.append("universal: food not registered as a rewarded need after opt-in")

    paid, peak_food_fair = _run_collect_contrib(cfg)
    if paid[Resource.FOOD] <= 1.0:
        fails.append(f"universal: no food contribution flowed ({paid[Resource.FOOD]:.4f}) -- "
                     "food-as-need did not route through the reward pipeline")
    if paid[Resource.WOOD] <= 1.0:
        fails.append(f"universal: wood contribution vanished ({paid[Resource.WOOD]:.4f}) -- "
                     "the refactor broke the original need")
    # food's fair value must rise above its intrinsic when food is scarce -- proof
    # the SAME pricing code prices food's severity, no special-casing.
    intrinsic_food = cfg.intrinsic_value[Resource.FOOD]
    if peak_food_fair <= intrinsic_food + 1e-6:
        fails.append(f"universal: food fair value never rose above intrinsic "
                     f"({peak_food_fair:.2f} vs {intrinsic_food:.2f}) despite scarcity")
    return fails


def test_determinism() -> list:
    fails = []
    cfg = Config(); cfg.reward_food_need = True; cfg.food_blight_enabled = True
    a = _run_collect_contrib(cfg)[0]
    b = _run_collect_contrib(cfg)[0]
    if a != b:
        fails.append("determinism: two food-need runs diverged")
    return fails


def main() -> int:
    all_fails = []
    tests = (("DATA-DEFINED", test_data_defined), ("GATED-DEFAULT", test_gated_default),
             ("UNIVERSAL", test_universal), ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nNEEDS TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nNEEDS TESTS OK -- the index prices/rewards needs from a data registry;\n"
          "wood is unchanged and food, added as pure data, routes through the same\n"
          "pipeline with zero food-specific code. Layer 2 is universal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
