"""
Per-day metrics collection, text reporting, and optional plotting.

Records the time series an analyst would want to see: prices, aggregate
reserves, advertised incentives, unmet need (shortages), reward paid out, and
the Player's wealth. `summary()` distils the headline numbers; `report()`
prints a comparison-friendly block; `plot()` writes PNGs if matplotlib is
available.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import Config, Resource, Season


@dataclass
class Metrics:
    cfg: Config
    days: list = field(default_factory=list)
    last_clearing = None

    def __post_init__(self):
        self.series = {
            k: [] for k in (
                "season", "wood_price", "food_price", "wood_reserve", "food_reserve",
                "wood_bounty", "village_unmet_wood", "village_unmet_food",
                "unmet_wood", "unmet_food", "n_short", "village_fear_wood",
                "village_fear_food",
                "reward_today", "reward_total", "penalty_total",
                "player_money", "player_wood", "player_bonus", "hoard_flags",
                # knowledge propagation (0 on legacy runs)
                "rumour_wood", "rumour_food", "aware_food", "aware_wood",
                "roots_food", "roots_wood",
            )
        }

    def record(self, world, ctx) -> None:
        self.days.append(ctx.day)
        s = self.series
        s["season"].append(ctx.season.value if hasattr(ctx.season, "value") else ctx.season)
        s["wood_price"].append(world.ref_price[Resource.WOOD])
        s["food_price"].append(world.ref_price[Resource.FOOD])
        s["wood_reserve"].append(sum(a.qty(Resource.WOOD) for a in world.agents))
        s["food_reserve"].append(sum(a.qty(Resource.FOOD) for a in world.agents))
        s["wood_bounty"].append(world.accountant.state.bounty.get(Resource.WOOD, 0.0))
        s["village_unmet_wood"].append(world.village_unmet[Resource.WOOD])
        s["village_unmet_food"].append(world.village_unmet[Resource.FOOD])
        s["unmet_wood"].append(world.day_unmet[Resource.WOOD])
        s["unmet_food"].append(world.day_unmet[Resource.FOOD])
        s["n_short"].append(world.day_short_agents)
        villagers = [a for a in world.agents
                     if not a.is_player and not a.is_market_maker]
        s["village_fear_wood"].append(
            sum(a.fear(Resource.WOOD) for a in villagers) / max(len(villagers), 1))
        s["village_fear_food"].append(
            sum(a.fear(Resource.FOOD) for a in villagers) / max(len(villagers), 1))
        s["reward_today"].append(world.accountant.state.paid_today)
        s["reward_total"].append(world.accountant.state.total_paid)
        s["penalty_total"].append(world.accountant.state.total_penalty)
        s["player_money"].append(world.player.money)
        s["player_wood"].append(world.player.qty(Resource.WOOD))
        s["player_bonus"].append(world.player.bonus_earned)
        s["hoard_flags"].append(len(world.accountant.state.hoard_flags))
        # knowledge propagation series
        s["rumour_wood"].append(world.rumour_avg[Resource.WOOD])
        s["rumour_food"].append(world.rumour_avg[Resource.FOOD])
        if world.prop is not None:
            vids = {a.id for a in villagers}
            s["aware_food"].append(world.prop.aware_fraction(Resource.FOOD, vids))
            s["aware_wood"].append(world.prop.aware_fraction(Resource.WOOD, vids))
            s["roots_food"].append(world.prop.distinct_roots(Resource.FOOD, vids))
            s["roots_wood"].append(world.prop.distinct_roots(Resource.WOOD, vids))
        else:
            for k in ("aware_food", "aware_wood", "roots_food", "roots_wood"):
                s[k].append(0.0)

    # ---------- analysis ----------
    def summary(self) -> dict:
        s = self.series
        winter_idx = [i for i, sea in enumerate(s["season"]) if sea == Season.WINTER.value]
        winter_village_unmet_wood = sum(s["village_unmet_wood"][i] for i in winter_idx)
        return {
            # village welfare (the metric that matters: how much did *villagers* suffer)
            "village_unmet_wood": sum(s["village_unmet_wood"]),
            "winter_village_unmet_wood": winter_village_unmet_wood,
            "village_unmet_food": sum(s["village_unmet_food"]),
            "shortage_days": sum(1 for x in s["n_short"] if x > 0),
            # market signals
            "max_wood_price": max(s["wood_price"]),
            "mean_wood_price": sum(s["wood_price"]) / len(s["wood_price"]),
            "winter_max_wood_price": max((s["wood_price"][i] for i in winter_idx), default=0.0),
            "mean_village_fear_wood": sum(s["village_fear_wood"]) / max(len(s["village_fear_wood"]), 1),
            "max_village_fear_wood": max(s["village_fear_wood"]) if s["village_fear_wood"] else 0.0,
            # AIC ledger
            "total_reward_paid": s["reward_total"][-1] if s["reward_total"] else 0.0,
            "total_penalty": s["penalty_total"][-1] if s["penalty_total"] else 0.0,
            "flag_days": sum(1 for x in s["hoard_flags"] if x > 0),
            # player
            "player_final_money": s["player_money"][-1] if s["player_money"] else 0.0,
            "player_bonus_earned": s["player_bonus"][-1] if s["player_bonus"] else 0.0,
        }

    def report(self, title: str) -> str:
        d = self.summary()
        return (
            f"=== {title} ===\n"
            f"  VILLAGE welfare:\n"
            f"    shortage days .................. {d['shortage_days']:>8}\n"
            f"    villagers' unmet wood (total)... {d['village_unmet_wood']:>8.1f}\n"
            f"      of which during WINTER........ {d['winter_village_unmet_wood']:>8.1f}\n"
            f"    villagers' unmet food (total)... {d['village_unmet_food']:>8.1f}\n"
            f"    mean / max villager fear (wood)  {d['mean_village_fear_wood']:>6.2f} / {d['max_village_fear_wood']:>6.2f}\n"
            f"  MARKET:\n"
            f"    wood price mean/max/winter-max.. "
            f"{d['mean_wood_price']:>5.2f} / {d['max_wood_price']:>5.2f} / {d['winter_max_wood_price']:>5.2f}\n"
            f"  AIC ledger:\n"
            f"    bounty paid out (total)......... {d['total_reward_paid']:>8.1f}\n"
            f"    hoarding penalty (total)........ {d['total_penalty']:>8.1f}"
            f"   (flagged on {d['flag_days']} days)\n"
            f"  PLAYER:\n"
            f"    final money..................... {d['player_final_money']:>8.1f}\n"
            f"    bounty earned (realized)........ {d['player_bonus_earned']:>8.1f}\n"
        )

    # ---------- plotting ----------
    def plot(self, path: str, title: str) -> bool:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception:
            return False
        s = self.series
        days = self.days
        fig, ax = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
        fig.suptitle(title)

        ax[0].plot(days, s["wood_price"], label="wood price", color="saddlebrown")
        ax[0].plot(days, s["food_price"], label="food price", color="green", alpha=0.6)
        ax[0].set_ylabel("price"); ax[0].legend(loc="upper left")

        ax[1].plot(days, s["wood_reserve"], label="aggregate wood reserve", color="saddlebrown")
        ax[1].plot(days, s["wood_bounty"], label="AIC bounty (player channel)", color="orange")
        ax[1].plot(days, [f * 50 for f in s["village_fear_wood"]],
                   label="avg village fear (x50)", color="purple", alpha=0.6)
        ax[1].set_ylabel("reserve / bounty / fear"); ax[1].legend(loc="upper left")

        ax[2].bar(days, s["village_unmet_wood"], label="village unmet wood", color="red", width=1.0)
        ax[2].plot(days, s["reward_today"], label="bounty paid/day", color="blue", alpha=0.7)
        ax[2].set_ylabel("shortage / payout"); ax[2].set_xlabel("day"); ax[2].legend(loc="upper left")

        # shade winters
        for i, sea in enumerate(s["season"]):
            if sea == Season.WINTER.value:
                for a in ax:
                    a.axvspan(days[i] - 0.5, days[i] + 0.5, color="steelblue", alpha=0.05)

        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return True
