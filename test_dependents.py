"""
Dependent-subgroup test (Phase 1): the vulnerable are why the economy, capital,
and information all matter to each other. This adds households that garden food
but can't chop wood and must BUY it, and checks two things:

  1. VULNERABILITY -- dependents suffer far more unmet wood than gatherers,
     because they can be priced out of a scarce market.
  2. SERVING THEM IS CONTRIBUTION -- a player who supplies wood into winter
     scarcity measurably reduces the dependents' cold AND is credited for it.

(That a false wood-panic can harm them is proven in the standalone knowledge
model; in the FULL economy, gatherers over-gather under fear -- elastic supply --
so the robust integrated claim is the positive one above.)

Exit 0 = pass.
"""
from __future__ import annotations

import copy

from agents import Dependent, SpawnSpec, Villager, MarketMaker
from config import Config, Resource
from world import World


def mixed_population(cfg):
    # 9 gatherers + 3 dependents + the trading post
    return [
        SpawnSpec(Villager, 9, id_prefix="v"),
        SpawnSpec(Dependent, 3, id_prefix="d"),
        SpawnSpec(MarketMaker, 1, id_prefix="mk"),
    ]


def run(cfg, player_strategy="idle"):
    cfg = copy.deepcopy(cfg)
    w = World(cfg, player_strategy=player_strategy, population=mixed_population(cfg))
    w.run()
    return w


def wood_unmet_by_group(world):
    dep = [a for a in world.agents if a.is_dependent]
    gat = [a for a in world.agents if isinstance(a, Villager) and not a.is_dependent]
    d = sum(a.unmet_need[Resource.WOOD] for a in dep) / max(len(dep), 1)
    g = sum(a.unmet_need[Resource.WOOD] for a in gat) / max(len(gat), 1)
    return d, g


def player_contribution(world):
    return world.player.bonus_earned


def main() -> int:
    cfg = Config()
    cfg.reward_at_fair_value = True   # score realized impact, not marginal deficit
    fails = []

    # 1. vulnerability -- idle player, dependents vs gatherers
    base = run(cfg, "idle")
    dep_base, gat_base = wood_unmet_by_group(base)
    if not (dep_base > gat_base * 2):
        fails.append(f"vulnerability: dependents ({dep_base:.1f}) not clearly worse "
                     f"than gatherers ({gat_base:.1f})")

    # 2. a responsive supplier reduces the dependents' cold (real, measurable impact)
    supplied = run(cfg, "responsive")
    dep_supplied, _ = wood_unmet_by_group(supplied)
    contrib = player_contribution(supplied)
    if not (dep_supplied < dep_base - 3):
        fails.append(f"serving: a supplier didn't relieve dependents "
                     f"(idle={dep_base:.1f} vs supplied={dep_supplied:.1f})")
    if not (contrib > 0):
        fails.append(f"serving: supplier earned no contribution ({contrib:.2f}) -- "
                     "fair-value payout should reward relieving the vulnerable")

    print(f"  gatherers' cold (avg unmet wood) ........ {gat_base:.1f}")
    print(f"  dependents' cold, no supplier ........... {dep_base:.1f}")
    print(f"  dependents' cold, with a supplier ....... {dep_supplied:.1f}")
    print(f"  supplier's contribution (fair-value) .... {contrib:.1f}")
    print(f"  -> dependents ~{dep_base / max(gat_base, 0.1):.0f}x more vulnerable; "
          f"supplier cut their cold by {dep_base - dep_supplied:.0f} and was credited for it")

    if fails:
        print("\nDEPENDENTS TEST FAILED:")
        for f in fails:
            print("  " + f)
        return 1
    print("\nDEPENDENTS TEST OK -- the vulnerable suffer first in scarcity, and serving")
    print("them is measurable contribution: the whole point of the index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
