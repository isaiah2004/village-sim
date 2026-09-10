"""
Scenarios are DATA (DESIGN.md "Modularity contract"). A `Scenario` is a named
bundle that selects and parameterizes the world's axes -- resources, a cyclical
driver, needs, a market model, population, and capital goods. `make_scenario(name)`
builds a fully-configured `Config` from it, and the sim reads those axes generically
(no per-scenario branching anywhere in the sim or the index).

Adding a whole new world archetype is meant to be one data entry here: a name and
values, zero new logic. The baseline `frostpine` reproduces the historical world
exactly, so the golden master stays byte-identical.

Nothing here imports the engine or a renderer; a Scenario is plain data. The world
consumes `cfg.scenario` (attached by `make_scenario`) to drive its mechanics.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from config import Config, Resource, Season, SEASON_ORDER


# ----------------------------------------------------------------- axes (data)
@dataclass(frozen=True)
class ResourceSpec:
    """A good that exists in a world. `consumable` goods deplete daily; capital
    goods (tools, infrastructure) do not. `base_yield` is per gather action;
    `base_consume` is per-agent daily need before the driver modulates it."""
    id: str
    intrinsic_value: float
    consumable: bool = True
    base_yield: float = 0.0
    base_consume: float = 0.0


@dataclass(frozen=True)
class Phase:
    """One phase of a cyclical driver. `yield_mult`/`consume_mult` are per-resource
    multipliers (missing entries default to 1.0)."""
    name: str
    length: int
    yield_mult: dict = field(default_factory=dict)
    consume_mult: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Driver:
    """A named cyclical modulator (winter is one; tides another). Pure data +
    lookup helpers -- adding a driver is a Driver value, never code."""
    name: str
    phases: tuple

    def cycle_length(self) -> int:
        return sum(p.length for p in self.phases)

    def phase_for_day(self, day: int):
        d = day % self.cycle_length()
        for p in self.phases:
            if d < p.length:
                return p
            d -= p.length
        return self.phases[-1]

    def phase_name(self, day: int) -> str:
        return self.phase_for_day(day).name

    def yield_mult(self, day: int, resource: str) -> float:
        return self.phase_for_day(day).yield_mult.get(resource, 1.0)

    def consume_mult(self, day: int, resource: str) -> float:
        return self.phase_for_day(day).consume_mult.get(resource, 1.0)

    def days_until_phase(self, day: int, phase_name: str) -> int:
        cyc = self.cycle_length()
        for ahead in range(0, cyc + 1):
            p = self.phase_for_day(day + ahead)
            # start of that phase == the day whose within-cycle offset begins it
            if p.name == phase_name and self._is_phase_start(day + ahead):
                return ahead
        return cyc

    def _is_phase_start(self, day: int) -> bool:
        d = day % self.cycle_length()
        for p in self.phases:
            if d == 0:
                return True
            if d < p.length:
                return False
            d -= p.length
        return False


@dataclass(frozen=True)
class NeedSpec:
    """A registered problem the index prices: unmet consumption of `resource`.
    `rewarded` = does meeting it pay realized-effect contribution."""
    key: str
    resource: str
    rewarded: bool = True


@dataclass(frozen=True)
class MarketSpec:
    """The market model, selected by name. `call_auction` is the historical
    spread-out double auction; `guild` buys at a capped price up to a daily quota
    and routes overflow to a secondary call_auction at a discount."""
    model: str = "call_auction"
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PopSpec:
    """A population entry: an archetype name + count + params (data). The world
    maps archetype names to agent classes; adding a spawn is a PopSpec value."""
    archetype: str
    count: int
    id_prefix: str
    kwargs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CapitalSpec:
    """A capital good: what it costs, yields, and eats. `output_resource` is what
    it produces daily per level; upkeep is a consumable it eats per level."""
    kind: str
    output_resource: str
    output_per_level: float
    upkeep_resource: str
    upkeep_per_level: float
    build_cost_resource: str
    build_cost: float
    max_level: int = 5


@dataclass(frozen=True)
class Scenario:
    """A named world archetype, entirely data."""
    name: str
    resources: tuple
    driver: Driver
    needs: tuple
    market: MarketSpec
    population: tuple
    primary_resource: str          # the crisis good, for metrics naming (frostpine: wood)
    crisis_phase: str              # the peak-stress phase, for metrics (frostpine: winter)
    capital: tuple = ()
    tunables: dict = field(default_factory=dict)   # scalar Config overrides

    # ---- derived views the world/config read ----
    def resource_ids(self) -> list:
        return [r.id for r in self.resources]

    def consumable_ids(self) -> list:
        return [r.id for r in self.resources if r.consumable]

    def resource(self, rid: str) -> ResourceSpec:
        return next(r for r in self.resources if r.id == rid)


# ================================================================= frostpine
# The baseline world, re-expressed as data. Its values reproduce the historical
# Config exactly, so the golden master stays byte-identical (verified by
# regression.py). Wood + food; the four-season driver; call_auction; villagers +
# (game) dependents; need = winter warmth (wood).
_SEASON_YIELD = {Season.SPRING: 1.1, Season.SUMMER: 1.2, Season.AUTUMN: 1.0, Season.WINTER: 0.6}
_WOOD_PER_DAY = {Season.SPRING: 0.45, Season.SUMMER: 0.3, Season.AUTUMN: 0.7, Season.WINTER: 2.0}


def _frostpine() -> Scenario:
    # The season driver: yield_mult applies the season multiplier to BOTH goods
    # (historically a global gather multiplier); consume_mult reproduces
    # wood_per_day (base wood consume = 1.0, so the multiplier IS the per-day value)
    # while food stays flat at its base (1.0/day).
    phases = tuple(
        Phase(name=s.value, length=30,
              yield_mult={"wood": _SEASON_YIELD[s], "food": _SEASON_YIELD[s]},
              consume_mult={"wood": _WOOD_PER_DAY[s], "food": 1.0})
        for s in SEASON_ORDER
    )
    driver = Driver(name="seasons", phases=phases)
    resources = (
        ResourceSpec("wood", intrinsic_value=5.0, consumable=True, base_yield=2.0, base_consume=1.0),
        ResourceSpec("food", intrinsic_value=6.0, consumable=True, base_yield=2.5, base_consume=1.0),
        ResourceSpec("tool", intrinsic_value=30.0, consumable=False),
        ResourceSpec("woodlot", intrinsic_value=60.0, consumable=False),
    )
    needs = (NeedSpec("wood_heat", "wood", rewarded=True),
             NeedSpec("food_hunger", "food", rewarded=False))
    capital = (CapitalSpec("woodlot", output_resource="wood", output_per_level=1.5,
                           upkeep_resource="food", upkeep_per_level=0.5,
                           build_cost_resource="wood", build_cost=8.0, max_level=5),)
    population = (PopSpec("villager", 8, "v"),
                 PopSpec("dependent", 3, "d"),
                 PopSpec("market_maker", 1, "mk",
                         kwargs={"daily_volume": 16.0, "target_inventory": 40.0}))
    return Scenario(
        name="frostpine", resources=resources, driver=driver, needs=needs,
        market=MarketSpec("call_auction"), population=population,
        primary_resource="wood", crisis_phase="winter", capital=capital,
    )


# The scenario registry -- add a world archetype by adding a builder here (data).
_REGISTRY = {
    "frostpine": _frostpine,
}


def scenario_names() -> list:
    return sorted(_REGISTRY)


def get_scenario(name: str) -> Scenario:
    if name not in _REGISTRY:
        raise KeyError(f"unknown scenario {name!r}; known: {scenario_names()}")
    return _REGISTRY[name]()


def register_scenario(name: str, builder) -> None:
    """Register a scenario builder (used by tests to prove 'a name + values fits')."""
    _REGISTRY[name] = builder


def make_config(name: str = "frostpine", **overrides) -> Config:
    """Build a Config for a named scenario. The Config carries `.scenario` so the
    world reads its axes generically. `overrides` set scalar Config fields (e.g.
    years, seed, flags) on top of the scenario's tunables."""
    sc = get_scenario(name)
    cfg = Config()
    cfg.scenario = sc                                   # the world reads axes from here
    # resource-keyed config maps, rebuilt from scenario data (byte-identical for frostpine)
    cfg.intrinsic_value = {r.id: r.intrinsic_value for r in sc.resources}
    cfg.base_yield = {r.id: r.base_yield for r in sc.resources if r.base_yield}
    for k, v in sc.tunables.items():
        setattr(cfg, k, v)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg
