"""
Reputation = deeds propagated (DESIGN.md). A headless demo showing that standing
is not a private tally but a REACH: it grows only as far as word of your deeds
travels the village.

    python demo_reputation.py

Runs frostpine with reputation propagation on and prints, for the biggest
benefactors, their raw contribution vs how far word has reached vs the standing
that actually gates interventions and merchant deals (standing = contribution x
reach). A contributor nobody has heard of is still unproven.
"""
from __future__ import annotations

import scenario
import interventions


def main() -> int:
    w = scenario.make_world("frostpine", player_strategy="idle",
                            reputation_propagation=True)
    w.run()
    contributors = sorted((a for a in w.agents if a.bonus_earned > 0),
                          key=lambda a: -a.bonus_earned)
    print("=" * 60)
    print("REPUTATION AS REACH -- frostpine, end of year")
    print("=" * 60)
    print(f"{'agent':8} {'contribution':>12} {'word reached':>13} {'standing':>10}")
    for a in contributors[:8]:
        reach = w.reputation.reach(a.id, w._active_ids)
        print(f"{a.id:8} {a.bonus_earned:12.1f} {reach*100:12.0f}% {interventions.standing(a, w):10.1f}")
    print("-" * 60)
    print("standing = contribution x reach: a great deed nobody has heard of yet")
    print("earns little standing until word travels the social graph.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
