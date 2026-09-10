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
    requirement: dict          # phase-key -> per-agent units/day (Season enum or phase name)
    rewarded: bool = True

    def daily_requirement(self, cfg: Config, day: int) -> float:
        """Per-agent units this need demands on `day` (its severity driver). Keyed
        by the active driver's phase (frostpine: the season); str-enum equality
        lets a Season-keyed or phase-name-keyed requirement resolve the same."""
        sc = getattr(cfg, "scenario", None)
        phase = sc.driver.phase_name(day) if sc is not None else cfg.season_for_day(day)
        if phase in self.requirement:
            return self.requirement[phase]
        # legacy fallback (Season-keyed requirement indexed by the enum season)
        return self.requirement[cfg.season_for_day(day)]


def _flat(value: float) -> dict:
    """A season-independent requirement (same every season)."""
    return {season: value for season in Season}


def build_registry(cfg: Config) -> list[Need]:
    """Assemble the need registry from DATA.

    When a scenario is attached (the general path), needs come from the scenario:
    each NeedSpec's requirement is the resource's base_consume x the driver's
    per-phase consume multiplier -- pure data, any world's goods. Adding a need is
    a NeedSpec row in the scenario, never logic here.

    The legacy path (no scenario -- e.g. a bare Config() in a unit test) reproduces
    the historical frostpine registry exactly, so byte-identity holds either way.
    `cfg.reward_food_need` still forces food-as-rewarded on the legacy path.
    """
    sc = getattr(cfg, "scenario", None)
    if sc is not None:
        needs = []
        for ns in sc.needs:
            rspec = sc.resource(ns.resource)
            requirement = {ph.name: rspec.base_consume * ph.consume_mult.get(ns.resource, 1.0)
                           for ph in sc.driver.phases}
            rewarded = ns.rewarded or (ns.resource == "food" and cfg.reward_food_need)
            needs.append(Need(ns.key, ns.resource, requirement, rewarded))
        return needs
    return [
        Need("wood_heat", Resource.WOOD, dict(cfg.wood_per_day), rewarded=True),
        Need("food_hunger", Resource.FOOD, _flat(cfg.food_per_day),
             rewarded=cfg.reward_food_need),
    ]
