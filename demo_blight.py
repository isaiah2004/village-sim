"""
Second-crisis demo (Track A #2): a summer food blight beside the winter wood
crisis, to see whether the loop holds under two competing pressures.

Same validated economy; each scenario only toggles `food_blight_enabled` (and,
for the last, drives the player). The blight cuts food gather yield to 12% in
summer -- food is normally the comfortable good, so this is what turns it scarce
exactly when a farsighted player also wants to be prepping wood for winter. The
machinery reacts on its own: food fear rises, the FOOD market tightens, and the
AIC's fair-value channel lifts food's worth. Nothing is special-cased.

  BLIGHT_OFF        the validated baseline. Summer is comfortable; food unmet ~0.
                    (Byte-identical to the golden model -- the flag is off.)

  BLIGHT_ON_IDLE    the blight bites and no one helps. A real summer food
                    shortage appears -- the second crisis, on par with winter
                    wood. Proves mild cuts wouldn't do it: the village is elastic,
                    so the blight has to outrun their ability to just gather more.

  BLIGHT_ON_PLAYER  the player stocks food in spring and sells into the summer
                    shortage. The crisis collapses -- realized contribution on the
                    FOOD axis, symmetric to keeping the village warm in winter.
                    Agency generalises past the one wood/winter axis.

Honest note: the severity matters. Above ~0.2 yield the village's elastic
response (gather more, over-provision) absorbs the blight and no crisis forms --
the same elasticity the knowledge demo found. A second crisis needs a shock the
myopic-but-adaptive village cannot simply out-gather.

    python demo_blight.py
"""
from __future__ import annotations

import sys

import contract as C
from config import Config, Resource, Season
from simcore import SimCore


def _cfg(blight: bool) -> Config:
    cfg = Config()
    cfg.years = 1.0
    cfg.food_blight_enabled = blight
    return cfg


def _summer_food_unmet(core: SimCore) -> float:
    s = core.world.metrics.series
    return sum(s["village_unmet_food"][i]
               for i, sea in enumerate(s["season"]) if sea == Season.SUMMER.value)


def _run(blight: bool, player=None) -> SimCore:
    core = SimCore(config=_cfg(blight))
    while not core.done:
        snap = core.begin_turn()
        if player is not None:
            player(core, snap)
        core.commit_turn()
    return core


def _food_responder(core: SimCore, snap) -> None:
    """Stock food in spring; sell the surplus into the summer shortage."""
    me = next(a for a in snap.agents if a.is_player)
    fm = next(m for m in snap.markets if m.resource == Resource.FOOD)
    if snap.season == Season.SUMMER.value and me.food > 3.0:
        core.submit(C.Trade(Resource.FOOD, "sell", me.food - 3.0, fm.ref_price * 0.95))
    if snap.season in (Season.SPRING.value, Season.SUMMER.value):
        for _ in range(int(me.stamina)):
            core.submit(C.Gather(Resource.FOOD))


def _summary(core: SimCore) -> dict:
    w = core.welfare()
    return {
        "summer_food_unmet": _summer_food_unmet(core),
        "annual_food_unmet": w["village_unmet_food"],
        "winter_wood_unmet": w["winter_village_unmet_wood"],
    }


def main() -> int:
    off = _summary(_run(False))
    idle = _summary(_run(True))
    resp = _summary(_run(True, player=_food_responder))

    rows = [("BLIGHT_OFF (baseline)", off),
            ("BLIGHT_ON, idle player", idle),
            ("BLIGHT_ON, food player", resp)]
    print("=" * 68)
    print("SECOND CRISIS -- summer food blight (food gather at 12% in summer)")
    print("=" * 68)
    print(f"{'scenario':26} {'summer':>11} {'annual':>11} {'winter':>11}")
    print(f"{'':26} {'food unmet':>11} {'food unmet':>11} {'wood unmet':>11}")
    print("-" * 68)
    for name, s in rows:
        print(f"{name:26} {s['summer_food_unmet']:11.2f} {s['annual_food_unmet']:11.2f} "
              f"{s['winter_wood_unmet']:11.2f}")
    print("-" * 68)

    # the readings, stated plainly (honest coupling + honest scope)
    print("\nreadings:")
    print(f"  * OFF: summer is comfortable (food unmet {off['summer_food_unmet']:.1f}). "
          "The same economy with the blight flag off.")
    print(f"  * ON + idle: a real second crisis -- summer food unmet "
          f"{idle['summer_food_unmet']:.0f}, on par with winter wood.")
    print(f"  * ON + player: the food-stocking player cuts summer food unmet from "
          f"{idle['summer_food_unmet']:.0f} to {resp['summer_food_unmet']:.0f} -- "
          "player agency reaches the second crisis too.")
    d_winter = idle["winter_wood_unmet"] - off["winter_wood_unmet"]
    print(f"  * NOT independent: the summer crisis knocks winter wood unmet by "
          f"{d_winter:+.0f} ({off['winter_wood_unmet']:.0f} -> "
          f"{idle['winter_wood_unmet']:.0f}) through shared money and markets --")
    print("    an emergent coupling, not a designed one. Two pressures that interact\n"
          "    is exactly the interesting case; a real playtest is the judge of fun.")
    print("\n  scope note: the player's help here shows as RESCUED WELFARE, not as a\n"
          "  higher score -- the contribution index credits WOOD consumption only\n"
          "  (world._consumption_phase). Scoring the food axis means extending the\n"
          "  index to food consumption; that changes what the score means and would\n"
          "  re-capture golden, so it's a flag-gated follow-up for the owner to call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
