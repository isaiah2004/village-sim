"""
Per-day metrics collection, text reporting, and optional plotting.

Records the time series an analyst would want: prices, aggregate reserves,
advertised incentives, unmet need (shortages), reward paid out, and the Player's
wealth. The series are keyed by the scenario's resource ids and the driver's phase
names, so metrics work for ANY world (DESIGN.md). For frostpine those ids/phases
are wood/food and the four seasons, so the keys and values are byte-identical to
the historical metrics; a scenario like tidewater produces fish/grain + tide-phase
keys captured additively.

`summary()` distils the headline numbers (per-consumable unmet, the crisis-phase
unmet of the primary good, prices/fear of the primary good, the ledger, player).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import Config, Resource, Season


def _rid(r):
    return r.value if hasattr(r, "value") else r


@dataclass
class Metrics:
    cfg: Config
    days: list = field(default_factory=list)
    last_clearing = None

    def __post_init__(self):
        sc = getattr(self.cfg, "scenario", None)
        if sc is not None:
            self.consumables = [_rid(r) for r in sc.consumable_ids()]
            self.primary = _rid(sc.primary_resource)
            self.crisis = sc.crisis_phase
        else:                                   # legacy frostpine defaults
            self.consumables = ["wood", "food"]
            self.primary = "wood"
            self.crisis = "winter"
        base = ["season", "n_short", "reward_today", "reward_total", "penalty_total",
                "player_money", "player_bonus", "hoard_flags",
                f"player_{self.primary}"]
        per = []
        for r in self.consumables:
            per += [f"{r}_price", f"{r}_reserve", f"{r}_bounty", f"village_unmet_{r}",
                    f"unmet_{r}", f"village_fear_{r}", f"rumour_{r}", f"aware_{r}", f"roots_{r}"]
        self.series = {k: [] for k in base + per}

    def record(self, world, ctx) -> None:
        self.days.append(ctx.day)
        s = self.series
        s["season"].append(ctx.season.value if hasattr(ctx.season, "value") else ctx.season)
        s["n_short"].append(world.day_short_agents)
        s["reward_today"].append(world.accountant.state.paid_today)
        s["reward_total"].append(world.accountant.state.total_paid)
        s["penalty_total"].append(world.accountant.state.total_penalty)
        s["player_money"].append(world.player.money)
        s["player_bonus"].append(world.player.bonus_earned)
        s["hoard_flags"].append(len(world.accountant.state.hoard_flags))
        s[f"player_{self.primary}"].append(world.player.qty(self.primary))
        villagers = [a for a in world.agents
                     if not a.is_player and not a.is_market_maker
                     and not getattr(a, "is_institution", False)]
        vids = {a.id for a in villagers}
        n = max(len(villagers), 1)
        for r in self.consumables:
            s[f"{r}_price"].append(world.ref_price.get(r, 0.0))
            s[f"{r}_reserve"].append(sum(a.qty(r) for a in world.agents))
            s[f"{r}_bounty"].append(world.accountant.state.bounty.get(r, 0.0))
            s[f"village_unmet_{r}"].append(world.village_unmet.get(r, 0.0))
            s[f"unmet_{r}"].append(world.day_unmet.get(r, 0.0))
            s[f"village_fear_{r}"].append(sum(a.fear(r) for a in villagers) / n)
            s[f"rumour_{r}"].append(world.rumour_avg.get(r, 0.0))
            if world.prop is not None:
                s[f"aware_{r}"].append(world.prop.aware_fraction(r, vids))
                s[f"roots_{r}"].append(world.prop.distinct_roots(r, vids))
            else:
                s[f"aware_{r}"].append(0.0)
                s[f"roots_{r}"].append(0.0)

    # ---------- analysis ----------
    def summary(self) -> dict:
        s = self.series
        prim, crisis = self.primary, self.crisis
        crisis_idx = [i for i, ph in enumerate(s["season"]) if ph == crisis]
        pp = s[f"{prim}_price"]
        fear = s[f"village_fear_{prim}"]
        out = {
            f"{crisis}_village_unmet_{prim}": sum(s[f"village_unmet_{prim}"][i] for i in crisis_idx),
            "shortage_days": sum(1 for x in s["n_short"] if x > 0),
            f"max_{prim}_price": max(pp) if pp else 0.0,
            f"mean_{prim}_price": (sum(pp) / len(pp)) if pp else 0.0,
            f"{crisis}_max_{prim}_price": max((pp[i] for i in crisis_idx), default=0.0),
            f"mean_village_fear_{prim}": (sum(fear) / len(fear)) if fear else 0.0,
            f"max_village_fear_{prim}": max(fear) if fear else 0.0,
            "total_reward_paid": s["reward_total"][-1] if s["reward_total"] else 0.0,
            "total_penalty": s["penalty_total"][-1] if s["penalty_total"] else 0.0,
            "flag_days": sum(1 for x in s["hoard_flags"] if x > 0),
            "player_final_money": s["player_money"][-1] if s["player_money"] else 0.0,
            "player_bonus_earned": s["player_bonus"][-1] if s["player_bonus"] else 0.0,
        }
        # per-consumable total unmet (village welfare)
        for r in self.consumables:
            out[f"village_unmet_{r}"] = sum(s[f"village_unmet_{r}"])
        return out

    def report(self, title: str) -> str:
        d = self.summary()
        prim, crisis = self.primary, self.crisis
        lines = [f"=== {title} ===", "  VILLAGE welfare:",
                 f"    shortage days .................. {d['shortage_days']:>8}"]
        for r in self.consumables:
            lines.append(f"    villagers' unmet {r:<8}...... {d[f'village_unmet_{r}']:>8.1f}")
        lines.append(f"      of which {prim} during {crisis}.. {d[f'{crisis}_village_unmet_{prim}']:>8.1f}")
        lines += [
            f"    mean/max villager fear ({prim})  "
            f"{d[f'mean_village_fear_{prim}']:>6.2f} / {d[f'max_village_fear_{prim}']:>6.2f}",
            "  MARKET:",
            f"    {prim} price mean/max/{crisis}-max.. "
            f"{d[f'mean_{prim}_price']:>5.2f} / {d[f'max_{prim}_price']:>5.2f} / {d[f'{crisis}_max_{prim}_price']:>5.2f}",
            "  AIC ledger:",
            f"    bounty paid out (total)......... {d['total_reward_paid']:>8.1f}",
            f"    hoarding penalty (total)........ {d['total_penalty']:>8.1f}"
            f"   (flagged on {d['flag_days']} days)",
            "  PLAYER:",
            f"    final money..................... {d['player_final_money']:>8.1f}",
            f"    bounty earned (realized)........ {d['player_bonus_earned']:>8.1f}",
        ]
        return "\n".join(lines) + "\n"

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
        prim = self.primary
        fig, ax = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
        fig.suptitle(title)
        for r in self.consumables:
            ax[0].plot(days, s[f"{r}_price"], label=f"{r} price")
        ax[0].set_ylabel("price"); ax[0].legend(loc="upper left")
        ax[1].plot(days, s[f"{prim}_reserve"], label=f"aggregate {prim} reserve", color="saddlebrown")
        ax[1].plot(days, s[f"{prim}_bounty"], label="AIC bounty (player channel)", color="orange")
        ax[1].plot(days, [f * 50 for f in s[f"village_fear_{prim}"]],
                   label="avg village fear (x50)", color="purple", alpha=0.6)
        ax[1].set_ylabel("reserve / bounty / fear"); ax[1].legend(loc="upper left")
        ax[2].bar(days, s[f"village_unmet_{prim}"], label=f"village unmet {prim}", color="red", width=1.0)
        ax[2].plot(days, s["reward_today"], label="bounty paid/day", color="blue", alpha=0.7)
        ax[2].set_ylabel("shortage / payout"); ax[2].set_xlabel("day"); ax[2].legend(loc="upper left")
        for i, ph in enumerate(s["season"]):
            if ph == self.crisis:
                for a in ax:
                    a.axvspan(days[i] - 0.5, days[i] + 0.5, color="steelblue", alpha=0.05)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return True
