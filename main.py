"""
Entry point: run the redesigned scenarios.

The AIC is now an OBSERVER. Villagers do not see its bounty. Whether the village
survives winter is determined by PLAYER AGENCY -- the player either chases the
bounties posted on their privileged information channel or doesn't.

Scenarios (all use the same seed):
  1. NO_PLAYER            -- player is idle (zero stamina, no orders). Pure
                             villager economy under the AIC's gaze.
  2. PLAYER_IGNORES       -- player exists, lives like a villager, ignores
                             the bounty channel. Shows that mere presence
                             doesn't stabilize anything.
  3. PLAYER_RESPONDS      -- player chases the AIC's published bounties
                             (merchant archetype). This is where player agency
                             actually moves the village outcome.
  4. PLAYER_HOARDS        -- exploiter archetype: corners wood through winter.
                             AIC's realized-effect payout + surveillance bite.

  + ACCOUNTANT_OFF        -- baseline reference: world without the AIC at all.
                             (Identical to NO_PLAYER on village welfare since
                              villagers ignore the bounty anyway -- proves it.)

Usage:
    python main.py            # run all, print reports, save plots
    python main.py --no-plot  # skip PNG generation
"""
from __future__ import annotations

import copy
import sys

from agents import Merchant, SpawnSpec, Villager
from config import Config
from world import World


def run_scenario(cfg: Config, player_strategy: str, accountant_enabled: bool,
                 population: list | None = None):
    cfg = copy.deepcopy(cfg)
    cfg.accountant_enabled = accountant_enabled
    world = World(cfg, player_strategy=player_strategy, population=population)
    metrics = world.run()
    return world, metrics


def main(argv: list[str]) -> int:
    do_plot = "--no-plot" not in argv
    cfg = Config()

    # Population: each entry is (title, strategy, AIC on/off, plot_path, population).
    # `population=None` uses the default village. Last scenario shows the spawn
    # registry: just adding 3 Merchants to the population -- no other code changes.
    village_with_merchants = [
        SpawnSpec(Villager, cfg.n_villagers, id_prefix="v"),
        SpawnSpec(Merchant, 3, id_prefix="m"),
    ]
    scenarios = [
        ("ACCOUNTANT_OFF (no AIC, idle player)",  "idle",       False, "plot_aic_off.png",       None),
        ("NO_PLAYER (AIC observes, no player)",   "idle",       True,  "plot_no_player.png",     None),
        ("PLAYER_IGNORES (lives as villager)",    "ignore",     True,  "plot_player_ignores.png",None),
        ("PLAYER_RESPONDS (chases bounties)",     "responsive", True,  "plot_player_responds.png",None),
        ("PLAYER_HOARDS (exploiter)",             "hoarder",    True,  "plot_player_hoards.png", None),
        ("WITH_MERCHANTS (3 merchants added)",    "idle",       True,  "plot_merchants.png",     village_with_merchants),
    ]

    results = []
    for title, strat, enabled, png, pop in scenarios:
        world, metrics = run_scenario(cfg, strat, enabled, population=pop)
        print(metrics.report(title))
        if do_plot:
            ok = metrics.plot(png, title)
            if ok:
                print(f"  (plot saved -> {png})\n")
        results.append((title, world, metrics))

    print("=" * 70)
    print("HEAD-TO-HEAD on village welfare (winter unmet wood) and player wealth")
    print("=" * 70)
    print(f"{'scenario':<42} {'winter_unmet':>13} {'shortage_d':>11} {'player_$':>10}")
    for title, _w, m in results:
        d = m.summary()
        print(f"{title[:42]:<42} {d['winter_village_unmet_wood']:>13.1f} "
              f"{d['shortage_days']:>11d} {d['player_final_money']:>10.0f}")
    print()
    print("Key reads:")
    print("  * AIC_OFF and NO_PLAYER should match on village welfare -- the AIC's")
    print("    bounty does NOT change villager behaviour. (Proof of observer stance.)")
    print("  * PLAYER_IGNORES should also match -- the player's mere presence is")
    print("    not enough; they must act on the bounty channel.")
    print("  * PLAYER_RESPONDS should be the only run where winter unmet drops")
    print("    meaningfully -- that's player agency, paid for by realized effect.")
    print("  * PLAYER_HOARDS should make the village WORSE off than NO_PLAYER and")
    print("    leave the player poorer than PLAYER_RESPONDS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
