"""
Layer 3 demo -- the intervention loop over two years (DESIGN.md).

The loop DESIGN.md describes, made concrete:

    change the world (found a mill) -> the index prices the deed -> your standing
    (track record of contribution) grows -> which gated founding the mill in the
    first place -> and the mill keeps the village warm the following winter.

The player supplies wood to the village. Early on, founding a mill is LOCKED --
no track record yet. Through the first winter their wood meets real need, the
index credits it, and their standing crosses the bar. They found the mill (paying
capital, not their own labour) -- income-generating infrastructure that lowers the
village's standing capital-gap problem and, a year later, helps carry it through
winter with far less suffering.

The intervention is a pre-authored, precondition-gated action applying an authored
effect to world-state; the merchant's yes/no is a deterministic gate here (capital
+ standing), the seam where an LLM merchant will later reason at the edge. Nothing
in the sim is invented at runtime.

    python demo_interventions.py
"""
from __future__ import annotations

import sys

import contract as C
from config import Config, Resource
from simcore import SimCore


def _cfg(interventions_enabled: bool) -> Config:
    cfg = Config()
    cfg.years = 2.0
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    cfg.interventions_enabled = interventions_enabled
    return cfg


SAMPLE_DAY = 165        # a summer day in year 2 -- where grown infrastructure shows


def _run(interventions_enabled: bool):
    """Script a player who supplies wood, founds the mill when the gate opens, and
    keeps re-investing capital to GROW it (each Perform upgrades a level). Records
    the capital-gap severity on SAMPLE_DAY and the founding day + first lock reason."""
    core = SimCore(config=_cfg(interventions_enabled), propagation=True)
    founded_day = locked_reason = gap_sample = None
    while not core.done:
        snap = core.begin_turn()
        me = next(a for a in snap.agents if a.is_player)
        menu = {iv[0]: iv for iv in core.interventions()}
        mill = menu["found_mill"]
        if founded_day is None and locked_reason is None and not mill[5]:
            locked_reason = mill[6]                    # the first lock reason seen
        if interventions_enabled and mill[5] and me.money > mill[3] + 20:
            core.submit(C.Perform("found_mill"))       # found, then upgrade with spare capital
            if founded_day is None:
                founded_day = core.day
        else:
            for _ in range(int(me.stamina)):
                core.submit(C.Gather(Resource.WOOD))
            wm = next(m for m in snap.markets if m.resource == Resource.WOOD)
            if me.wood > 4:
                core.submit(C.Trade(Resource.WOOD, "sell", me.wood - 3, wm.ref_price * 0.95))
        core.commit_turn()
        if core.day == SAMPLE_DAY:
            gap_sample = next(p.severity for p in core.snapshot().problems
                              if p.key == "capital_gap:wood")
    me = next(a for a in core.snapshot().agents if a.is_player)
    return core, founded_day, locked_reason, gap_sample, me.woodlot_level


def main() -> int:
    live, founded_day, locked_reason, gap_live, level = _run(interventions_enabled=True)
    ghost, _, _, gap_ghost, _ = _run(interventions_enabled=False)  # mill never available

    print("=" * 70)
    print("THE INTERVENTION LOOP -- found (and grow) a mill, two years")
    print("=" * 70)
    print(f"  early game: founding the mill was LOCKED -- {locked_reason}")
    print(f"  the player supplied wood; through year-1 winter the index credited it")
    print(f"  and their standing crossed the bar.")
    print(f"  -> mill FOUNDED on day {founded_day} "
          f"({live.cfg.season_for_day(founded_day).value}), paid with capital, then grown "
          f"to level {level}.")
    print("-" * 70)
    print(f"{'(measured day '+str(SAMPLE_DAY)+', yr-2 summer)':32}{'with the mill':>16}{'without it':>16}")
    print(f"{'capital-gap:wood severity':32}{gap_live:>16.2f}{gap_ghost:>16.2f}")
    print("-" * 70)
    print(f"  founder standing that unlocked it: {live.score('PLAYER'):.0f} "
          f"(the gate needed 40) -- earned by keeping the village warm.")
    print("\nreading: the deed changed world-state -- the village's standing capital-gap")
    print("problem fell from its no-infrastructure ceiling of 1.00 toward 0 as the mill")
    print("grew -- and the index priced the founder's deeds (standing). That is the whole")
    print("loop: Layer 3 acting on Layer 1, scored by Layer 2. Reputation-via-propagation")
    print("and an LLM merchant plug into the SAME standing and gate seams next, unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
