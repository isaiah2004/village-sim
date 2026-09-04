"""
Capital-goods test (Phase 1): does the contribution index generalise past
consumables to OWNED INFRASTRUCTURE?

The player invests labour once to build a woodlot, then never gathers wood again
-- they only gather food (to sustain themselves and feed the woodlot's workers)
and sell what the woodlot produces. If the realized-effect payout is sound, the
player should still earn contribution: credit for wood the WOODLOT produced that
later kept a villager warm, flowing back through the lineage to its builder.

That's "infrastructure as contribution" -- income without direct labour on the
scarce good -- and it's the property the whole vision leans on (roads, mills,
irrigation as contributions). Exit 0 = pass.
"""
from __future__ import annotations

import copy
import sys

import contract as C
from config import Config, Resource
from simcore import SimCore


def main() -> int:
    cfg = copy.deepcopy(Config())
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True   # score realized impact, not marginal deficit
    core = SimCore(config=cfg, propagation=False)

    sell_price = round(cfg.intrinsic_value[Resource.WOOD] * 0.5, 2)   # cheap: clears easily
    built_day = None
    wood_from_woodlot = 0.0     # PLAYER wood produced AFTER the build == woodlot output
    player_gathered_wood_after_build = 0

    while not core.done:
        snap = core.begin_turn()
        me = next(a for a in snap.agents if a.is_player)

        if built_day is None:
            if me.wood >= cfg.woodlot_wood_cost:
                core.submit(C.BuildWoodlot())
                built_day = core.day
            else:
                for _ in range(6):
                    core.submit(C.Gather(Resource.WOOD))   # earn enough to build
        else:
            # subsistence only: gather FOOD (never wood again). Sell the woodlot's wood
            # INTO SCARCITY -- when the AIC's fair value says wood is short (as a good
            # supplier does) -- rather than dumping it and killing its own marginal value.
            core.submit(C.Gather(Resource.FOOD))
            core.submit(C.Gather(Resource.FOOD))
            # sell the woodlot's wood CONTINUOUSLY (never stockpile -> no hoard flag).
            # It clears cheap in abundant seasons and into panic bids in winter; the
            # winter share, burned by cold villagers, is what earns realized contribution.
            if me.wood > 1.0:
                ask = cfg.intrinsic_value[Resource.WOOD] * 0.7
                core.submit(C.Trade(Resource.WOOD, "sell", me.wood - 1.0, ask))

        core.commit_turn()
        for ev in core.drain_events():
            if built_day is not None and isinstance(ev, C.Produced) \
                    and ev.agent_id == "PLAYER" and ev.resource == Resource.WOOD:
                wood_from_woodlot += ev.qty

    pv = next(a for a in core.snapshot().agents if a.is_player)
    contribution = pv.contribution_earned

    fails = []
    if built_day is None:
        fails.append("player never built a woodlot")
    if pv.woodlots != 1:
        fails.append(f"expected 1 woodlot, snapshot shows {pv.woodlots}")
    if wood_from_woodlot < 30:
        fails.append(f"woodlot produced too little wood after build ({wood_from_woodlot:.1f})")
    if contribution <= 0:
        fails.append(f"builder earned NO contribution from the woodlot ({contribution:.2f}) -- "
                     "capital did not credit its owner")

    print(f"  woodlot built on day .......... {built_day}")
    print(f"  wood produced by the woodlot .. {wood_from_woodlot:.1f}")
    print(f"  contribution earned (capital) . {contribution:.2f}")
    print(f"  player final money ............ {pv.money:.1f}")

    if fails:
        print("\nCAPITAL-GOODS TEST FAILED:")
        for f in fails:
            print("  " + f)
        return 1
    print("\nCAPITAL-GOODS TEST OK -- infrastructure earned contribution for its builder,")
    print("without the builder gathering the scarce good themselves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
