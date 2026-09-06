"""
The Need registry -- Layer 2's data-defined notion of "a problem worth solving".

DESIGN.md's core principle: the contribution index is a CALCULATOR, not the game,
and no scenario may be hardcoded inside it. This module is the seam that makes that
true. A "need" is DATA: an identity, the resource whose consumption meets it (and
whose lineage the index credits), a per-agent daily requirement that sets the need's
current severity, and whether meeting it pays realized-effect contribution.

The accountant prices and attributes EVERY registered need through one uniform
pipeline (see accountant.start_day / reward_consumption). Wood was the single
hardcoded instance built to prove the index works; it is re-registered here with no
behaviour change. Food is registered the same way, purely as data -- proof that the
index prices any problem with zero per-scenario code.

This is deliberately scoped to consumption needs (the shape the sim tracks today).
It is the hook Layer 1 will grow into typed, located world-state problems (a
drought, a missing mill), each exposing a severity the index can price the same way.
Nothing here imports the engine; a Need is plain data.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import Config, Resource, Season


@dataclass(frozen=True)
class Need:
    """One registered problem the index can price and (optionally) reward.

    key         -- stable identity, e.g. "wood_heat", "food_hunger".
    resource    -- the good whose consumption meets this need; its lineage is what
                   the index credits when the need is met (the attribution hook).
    requirement -- per-agent units needed, keyed by Season: the severity source the
                   accountant forecasts scarcity against.
    rewarded    -- does meeting this need pay realized-effect contribution up the
                   lineage? (Pricing/fair-value happens either way; payout is opt-in.)
    """
    key: str
    resource: Resource
    requirement: dict          # Season -> per-agent units/day
    rewarded: bool = True

    def daily_requirement(self, cfg: Config, day: int) -> float:
        """Per-agent units this need demands on `day` (its severity driver)."""
        return self.requirement[cfg.season_for_day(day)]


def _flat(value: float) -> dict:
    """A season-independent requirement (same every season)."""
    return {season: value for season in Season}


def build_registry(cfg: Config) -> list[Need]:
    """Assemble the need registry from config DATA.

    Adding a need is a row here (data), never new logic in the index. Wood is
    re-registered EXACTLY as it has always behaved (seasonal requirement, always
    rewarded). Food is registered as a second need with the identical shape; it is
    always priced like wood, and rewarded only when the owner opts in via
    `cfg.reward_food_need` -- so the validated scenarios stay byte-identical until
    someone deliberately turns food-as-rewarded-need on.
    """
    return [
        Need("wood_heat", Resource.WOOD, dict(cfg.wood_per_day), rewarded=True),
        Need("food_hunger", Resource.FOOD, _flat(cfg.food_per_day),
             rewarded=cfg.reward_food_need),
    ]
