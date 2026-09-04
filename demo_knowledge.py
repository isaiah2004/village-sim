"""
Knowledge-Propagation demo (Stage 3): information as a causal force.

Same validated economy; each scenario only toggles `propagation_enabled` and
injects a claim. The economic machinery (belief -> reserve target -> market ->
shortage) is the unchanged core. The player is held IDLE so any change in
village welfare is caused purely by what villagers came to BELIEVE.

The village's defining weakness (from the core sim) is MYOPIA: villagers see
only ~4 days ahead, so they never prepare for winter and suffer every year.
That makes it the perfect testbed for whether INFORMATION can change outcomes.

  QUIET          gossip on, no injected claim. Control.

  TRUE_WARNING   a TRUE claim about the coming winter wood shortage, injected
                 before winter through the tavern hub (the isekai edge: someone
                 who can see winter coming tells the village). Villagers who
                 cannot normally foresee winter now prepare -> winter hurts far
                 less. INFORMATION AS CONTRIBUTION.

  FALSE_RUMOUR   a FALSE food-shortage claim whispered to ONE villager in calm
                 autumn. Demonstrates the epistemics: it spreads in AWARENESS
                 but, from a single source, its CONFIDENCE stays capped at
                 "plausible" (echo cap) -- popularity is not truth.

  SEED_PANIC     the player seeds the false rumour and trades it. The player-as-
                 information-node, and the seam where the AIC's contribution
                 scoring extends from goods to information.

Honest finding (reported, not hidden): a scarcity LIE does not manufacture a
famine here, because supply is elastic -- villagers just gather more, and panic
becomes wasteful over-provisioning rather than starvation. Manufacturing real
harm from misinformation needs supply inelasticity or wealth inequality, which
is the next thing to model. What IS robust is that information -- true or false --
measurably moves belief, behaviour, and the market.
"""
from __future__ import annotations

import copy
import sys

from config import Config, Resource
from knowledge import Claim
from world import World

# calendar (30-day seasons, 2 yrs): yr1 spring0-29 summer30-59 autumn60-89 winter90-119
WARN_DAY = 82            # just before winter1 -> time to act on a true wood warning
LIE_DAY = 66             # calm autumn -> clean test of a false food rumour
PRE_WINTER = range(WARN_DAY, 90)
AUTUMN = range(LIE_DAY, 90)


def build(cfg, strategy, inject=None):
    cfg = copy.deepcopy(cfg)
    cfg.propagation_enabled = True
    w = World(cfg, player_strategy=strategy)
    for spec in (inject or []):
        w.schedule_injection(**spec)
    return w


def run_all(cfg):
    scen = {
        "QUIET": build(cfg, "idle"),
        "TRUE_WARNING": build(cfg, "idle", [dict(
            day=WARN_DAY, target="hub",
            claim=Claim(Resource.WOOD, 0.85, True, "warning:winter_wood", WARN_DAY),
            authority=0.9, by_player=True)]),
        "FALSE_RUMOUR": build(cfg, "idle", [dict(
            day=LIE_DAY, target="random",
            claim=Claim(Resource.FOOD, 0.8, False, "rumour:food_panic", LIE_DAY),
            authority=0.6)]),
    }
    for w in scen.values():
        w.run()
    return scen


def wmax(series, window):
    return max((series[i] for i in window if i < len(series)), default=0.0)


def wsum(series, window):
    return sum(series[i] for i in window if i < len(series))


def summarize(scen):
    q = scen["QUIET"].metrics
    print("=" * 82)
    print("KNOWLEDGE PROPAGATION  --  information as a causal force in a living economy")
    print("=" * 82)

    print("\n[A]  INFORMATION AS CONTRIBUTION")
    print("     Villagers are myopic: they can't foresee winter and suffer it every year.")
    print("     A TRUE early warning, spread through the village, lets them prepare.\n")
    print(f"     {'scenario':<15}{'pre-winter wood fear':>22}{'winter wood shortage':>22}")
    for name in ("QUIET", "TRUE_WARNING"):
        m = scen[name].metrics
        fear = wmax(m.series["village_fear_wood"], PRE_WINTER)
        winter = m.summary()["winter_village_unmet_wood"]
        print(f"     {name:<15}{fear:>22.2f}{winter:>22.1f}")
    qw = q.summary()["winter_village_unmet_wood"]
    tw = scen["TRUE_WARNING"].metrics.summary()["winter_village_unmet_wood"]
    print(f"     -> the warning cut winter suffering by {(1-tw/qw)*100:.0f}% "
          f"({qw:.1f} -> {tw:.1f}). Information overcame the myopia.")

    print("\n[B]  EPISTEMICS: popularity is not truth (the echo cap)")
    print("     Same propagation machinery, two very different claims. Awareness spreads")
    print("     either way; CONFIDENCE only climbs when INDEPENDENT sources corroborate.\n")
    fr = scen["FALSE_RUMOUR"]
    lie_aware = wmax(fr.metrics.series["aware_food"], AUTUMN)
    lie_belief = wmax(fr.metrics.series["village_fear_food"], AUTUMN)
    lie_roots = wmax(fr.metrics.series["roots_food"], AUTUMN)
    # the real winter shortage (in the QUIET control) is the corroboration case
    WINTER = range(90, 120)
    true_aware = wmax(q.series["aware_wood"], WINTER)
    true_belief = wmax(q.series["village_fear_wood"], WINTER)
    true_roots = wmax(q.series["roots_wood"], WINTER)
    print(f"     FALSE food rumour  (1 source, repeated): "
          f"{lie_aware*100:>3.0f}% aware,  belief peaks {lie_belief:.2f}  from {lie_roots:.0f} root")
    print(f"     REAL winter shortage (many witnesses)  : "
          f"{true_aware*100:>3.0f}% aware,  belief peaks {true_belief:.2f}  from {true_roots:.0f} roots")
    print("     -> the lie is widely KNOWN yet stays 'plausible' (echo-capped);")
    print("        independently-witnessed truth corroborates into conviction and drives action.")

    print("\n[C]  INFORMATION CONTRIBUTION INDEX  (realized welfare effect vs QUIET control)")
    print("     The AIC's realized-effect logic, applied to information instead of goods.")
    base = q.summary()
    base_harm = base["village_unmet_food"] + base["village_unmet_wood"]
    for name in ("TRUE_WARNING", "FALSE_RUMOUR"):
        d = scen[name].metrics.summary()
        harm = d["village_unmet_food"] + d["village_unmet_wood"]
        ici = base_harm - harm
        truth = "TRUE" if name == "TRUE_WARNING" else "FALSE"
        tag = {
            "TRUE_WARNING": "true foresight, given away -> contribution",
            "FALSE_RUMOUR": "false; elastic supply turned panic into over-provision, not famine",
        }[name]
        print(f"     {name:<14} claim={truth:<6} ICI={ici:>+7.1f}   {tag}")
    print("     (the exploitation twin -- a lie spread FOR PROFIT that harms the village --")
    print("      needs supply inelasticity / inequality to bite; that's the next extension.)")
    print()


def plot_hero(scen, path="plot_information_as_contribution.png"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    q = scen["QUIET"].metrics.series
    w = scen["TRUE_WARNING"].metrics.series
    days = scen["TRUE_WARNING"].metrics.days

    fig, ax = plt.subplots(3, 1, figsize=(11, 9.5), sharex=True)
    fig.suptitle("INFORMATION AS CONTRIBUTION\n"
                 "a true warning, spread through a myopic village, averts the winter it could not foresee",
                 fontsize=12, fontweight="bold")

    ax[0].plot(days, w["village_fear_wood"], color="purple", lw=2, label="wood fear (village was warned)")
    ax[0].plot(days, q["village_fear_wood"], color="gray", label="wood fear (no warning, control)")
    ax[0].set_ylabel("foresight / fear"); ax[0].legend(loc="upper left"); ax[0].set_ylim(bottom=0)

    ax[1].plot(days, w["wood_reserve"], color="saddlebrown", lw=2, label="village wood reserve (warned)")
    ax[1].plot(days, q["wood_reserve"], color="gray", label="village wood reserve (control)")
    ax[1].set_ylabel("wood stockpiled"); ax[1].legend(loc="upper left")

    ax[2].bar(days, q["village_unmet_wood"], color="gray", width=1.0, label="winter suffering (control)")
    ax[2].bar(days, w["village_unmet_wood"], color="red", width=1.0, alpha=0.85, label="winter suffering (warned)")
    ax[2].set_ylabel("REAL unmet wood"); ax[2].set_xlabel("day"); ax[2].legend(loc="upper left")

    for a in ax:
        a.axvline(WARN_DAY, color="black", ls=":", alpha=0.8)
        for yr in (0, 1):
            a.axvspan(90 + 120 * yr, 120 + 120 * yr, color="steelblue", alpha=0.06)
    ax[0].annotate("the warning is given\n(TRUE: winter is coming)",
                   xy=(WARN_DAY, 0.05), xytext=(WARN_DAY - 60, 0.5),
                   arrowprops=dict(arrowstyle="->"), fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=115)
    plt.close(fig)
    return True


def main(argv):
    scen = run_all(Config())
    summarize(scen)
    if "--no-plot" not in argv and plot_hero(scen):
        print("hero plot saved -> plot_information_as_contribution.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
