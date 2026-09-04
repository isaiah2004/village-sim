"""
Second-crisis tests: the summer food blight (Track A #2), a flag-gated mechanic.

Proves:
  1. GATED-OFF -- with food_blight_enabled False (the default), a run is
     byte-identical to the untouched baseline. The golden master is safe; the
     flag only does something when a body/demo opts in.
  2. REAL-CRISIS -- with the blight ON and no one helping, a genuine summer food
     shortage appears (village food unmet in summer, ~0 without the blight). The
     village's elasticity does not simply absorb it.
  3. AGENCY -- a player who stocks food in spring and sells into the summer
     shortage collapses that unmet need: player agency reaches the second crisis,
     measured as rescued village welfare.
  4. DETERMINISM -- same seed, blight on, same run.

The blight is food-only at the mechanic level (it scales food gather yield in its
season), but the economy is coupled, so winter-wood outcomes shift indirectly --
this test does NOT assert independence, only the food crisis and its rescue.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import contract as C
from config import Config, Resource, Season
from simcore import SimCore
from world import World


def _summer_food_unmet_from_series(series) -> float:
    return sum(series["village_unmet_food"][i]
               for i, sea in enumerate(series["season"]) if sea == Season.SUMMER.value)


def _cfg(blight: bool) -> Config:
    cfg = Config()
    cfg.years = 1.0
    cfg.food_blight_enabled = blight
    return cfg


def _run_idle(blight: bool) -> SimCore:
    core = SimCore(config=_cfg(blight))
    while not core.done:
        core.step()
    return core


def _run_food_responder(blight: bool) -> SimCore:
    core = SimCore(config=_cfg(blight))
    while not core.done:
        snap = core.begin_turn()
        me = next(a for a in snap.agents if a.is_player)
        fm = next(m for m in snap.markets if m.resource == Resource.FOOD)
        if snap.season == Season.SUMMER.value and me.food > 3.0:
            core.submit(C.Trade(Resource.FOOD, "sell", me.food - 3.0, fm.ref_price * 0.95))
        if snap.season in (Season.SPRING.value, Season.SUMMER.value):
            for _ in range(int(me.stamina)):
                core.submit(C.Gather(Resource.FOOD))
        core.commit_turn()
    return core


def _summer_unmet(core: SimCore) -> float:
    return _summer_food_unmet_from_series(core.world.metrics.series)


def test_gated_off() -> list:
    """Blight off (explicit) must be byte-identical to a config that never
    touches the flag -- so the golden master is unaffected by the feature."""
    fails = []
    off = World(_cfg(False), player_strategy="idle"); off.run()     # flag explicitly off
    untouched_cfg = Config(); untouched_cfg.years = 1.0             # field left at default
    untouched = World(untouched_cfg, player_strategy="idle"); untouched.run()
    if off.metrics.summary() != untouched.metrics.summary():
        fails.append("gated-off: blight-off run differs from the untouched baseline")
    return fails


def test_real_crisis() -> list:
    fails = []
    off = _summer_unmet(_run_idle(False))
    on = _summer_unmet(_run_idle(True))
    if off > 1.0:
        fails.append(f"real-crisis: baseline summer already short ({off:.2f}); not a clean test")
    if on < 15.0:
        fails.append(f"real-crisis: blight produced only {on:.2f} summer food unmet "
                     "(expected a real crisis, >15)")
    if on <= off:
        fails.append(f"real-crisis: blight did not worsen summer food (off={off:.2f} on={on:.2f})")
    return fails


def test_agency() -> list:
    fails = []
    idle = _summer_unmet(_run_idle(True))
    helped = _summer_unmet(_run_food_responder(True))
    if helped >= idle:
        fails.append(f"agency: food player did not help (idle={idle:.2f} helped={helped:.2f})")
    if helped > 0.25 * idle:
        fails.append(f"agency: food player only partly mitigated the crisis "
                     f"(idle={idle:.2f} helped={helped:.2f}, expected a large cut)")
    return fails


def test_determinism() -> list:
    fails = []
    a = _run_idle(True).welfare()
    b = _run_idle(True).welfare()
    if a != b:
        fails.append("determinism: two blight-on runs diverged")
    return fails


def main() -> int:
    all_fails = []
    tests = (("GATED-OFF", test_gated_off), ("REAL-CRISIS", test_real_crisis),
             ("AGENCY", test_agency), ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nBLIGHT TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nBLIGHT TESTS OK -- gated off it's byte-identical to baseline; on it is a\n"
          "real summer food crisis that a food-stocking player can rescue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
