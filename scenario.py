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


# ================================================================= tidewater
# A fisher village. Proves a DRIVER + RESOURCES are pure data: "Tides" behaves
# like winter for its own values, with no new code. Fish is the crisis good (a
# tide-driven catch that fails in storms); grain is the comfortable staple. Same
# machinery as frostpine, different data.
def _tidewater() -> Scenario:
    tide = {"spring_run": 1.4, "summer": 1.0, "neap": 0.7, "storm": 0.2}
    grain_tide = {"spring_run": 1.1, "summer": 1.2, "neap": 1.0, "storm": 0.9}
    phases = tuple(
        Phase(name=name, length=30,
              yield_mult={"fish": tide[name], "grain": grain_tide[name]},
              consume_mult={"fish": 1.0, "grain": 1.0})
        for name in ("spring_run", "summer", "neap", "storm")
    )
    driver = Driver(name="tides", phases=phases)
    resources = (
        ResourceSpec("fish", intrinsic_value=5.0, consumable=True, base_yield=2.0, base_consume=1.0),
        ResourceSpec("grain", intrinsic_value=6.0, consumable=True, base_yield=2.5, base_consume=1.0),
    )
    needs = (NeedSpec("fish_need", "fish", rewarded=True),
             NeedSpec("grain_need", "grain", rewarded=False))
    population = (PopSpec("villager", 8, "f"),                      # fishers
                 PopSpec("dependent", 3, "n", kwargs={"produces": "grain"}),  # net-menders garden grain, can't fish
                 PopSpec("market_maker", 1, "mk",
                         kwargs={"daily_volume": 16.0, "target_inventory": 40.0}))
    return Scenario(
        name="tidewater", resources=resources, driver=driver, needs=needs,
        market=MarketSpec("call_auction"), population=population,
        primary_resource="fish", crisis_phase="storm",
    )


# ================================================================= guildhall
# A weaving town whose economy is stabilized by a GUILD. Proves the MARKET MODEL
# is a data axis: MarketSpec.model == "guild" means the guild hall posts a
# standing support bid (buy up to `quota` of cloth at a capped `price`), putting
# a floor under weavers when a glut would otherwise collapse the price; supply
# beyond the quota overflows to the ordinary call auction. Cloth is the crisis
# good (over-made in the glut season); grain is the comfortable staple.
def _guildhall() -> Scenario:
    cloth_yield = {"boom": 1.0, "fair": 1.2, "glut": 2.0, "lean": 0.8}
    grain_yield = {"boom": 1.1, "fair": 1.1, "glut": 1.0, "lean": 0.9}
    phases = tuple(
        Phase(name=name, length=30,
              yield_mult={"cloth": cloth_yield[name], "grain": grain_yield[name]},
              consume_mult={"cloth": 1.0, "grain": 1.0})
        for name in ("boom", "fair", "glut", "lean")
    )
    driver = Driver(name="trade_seasons", phases=phases)
    # Cloth is structurally OVER-made (far more woven than the town consumes), so
    # in a glut its open-market price would collapse toward the hard floor -- the
    # weavers' wage evaporates. Grain is a comfortable, balanced staple.
    resources = (
        ResourceSpec("cloth", intrinsic_value=5.0, consumable=True, base_yield=3.2, base_consume=0.6),
        ResourceSpec("grain", intrinsic_value=6.0, consumable=True, base_yield=2.5, base_consume=1.0),
    )
    needs = (NeedSpec("cloth_need", "cloth", rewarded=True),
             NeedSpec("grain_need", "grain", rewarded=False))
    population = (PopSpec("villager", 8, "w"),                       # weavers
                 PopSpec("dependent", 3, "g", kwargs={"produces": "grain"}),
                 PopSpec("market_maker", 1, "mk",                    # the guild hall
                         kwargs={"daily_volume": 16.0, "target_inventory": 40.0}))
    # the guild floor: buy up to 60 cloth/day at 4.5 (below intrinsic 5.0) so a
    # glut can't drive the price through the floor -- weavers keep a fair wage.
    market = MarketSpec("guild", params={"resource": "cloth", "price": 4.5, "quota": 60.0})
    return Scenario(
        name="guildhall", resources=resources, driver=driver, needs=needs,
        market=market, population=population,
        primary_resource="cloth", crisis_phase="glut",
    )


# ================================================================= emberforge
# A forge town with MULTI-RESOURCE STRUCTURAL SCARCITY relieved by CAPITAL. Iron
# is the crisis good: it is needed daily but gathered far slower than it is
# consumed (base_yield 0.8 < base_consume 1.0), so hand-labour alone can never
# keep up -- a permanent deficit, worst in "war" when iron demand doubles. The
# relief is a CAPITAL GOOD: a forge (built from ore, fuelled by charcoal) that
# smelts iron far faster than gathering. Proves the capital-goods system is
# generic DATA: frostpine's woodlot and this forge are the same machinery.
def _emberforge() -> Scenario:
    iron_consume = {"peace": 1.0, "muster": 1.3, "war": 2.0, "recovery": 0.8}
    phases = tuple(
        Phase(name=name, length=30,
              yield_mult={},                                  # scarcity is structural, not cyclical
              consume_mult={"iron": iron_consume[name], "charcoal": 1.0, "ore": 1.0})
        for name in ("peace", "muster", "war", "recovery")
    )
    driver = Driver(name="forge_cycle", phases=phases)
    resources = (
        # iron: needed daily, gathered far too slowly by hand -> structural deficit.
        ResourceSpec("iron", intrinsic_value=8.0, consumable=True, base_yield=0.8, base_consume=1.0),
        # ore: the raw input the forge is built from (no daily need of its own).
        ResourceSpec("ore", intrinsic_value=3.0, consumable=True, base_yield=2.0, base_consume=0.0),
        # charcoal: fuel; a mild daily need and the forge's upkeep.
        ResourceSpec("charcoal", intrinsic_value=4.0, consumable=True, base_yield=2.5, base_consume=0.5),
        # forge: the capital good (non-consumable asset).
        ResourceSpec("forge", intrinsic_value=40.0, consumable=False),
    )
    needs = (NeedSpec("iron_need", "iron", rewarded=True),
             NeedSpec("charcoal_need", "charcoal", rewarded=False))
    # the forge: built from ore, fuelled by charcoal, smelts iron. output_per_level
    # (1.2) comfortably exceeds the per-smith hand yield (0.8), so a few forges
    # turn a chronic deficit into a surplus -- capital relieving structural scarcity.
    capital = (CapitalSpec("forge", output_resource="iron", output_per_level=1.2,
                           upkeep_resource="charcoal", upkeep_per_level=0.8,
                           build_cost_resource="ore", build_cost=6.0, max_level=5),)
    population = (PopSpec("villager", 8, "s"),                        # smiths (gather iron + charcoal)
                 PopSpec("dependent", 3, "m", kwargs={"produces": "ore"}),  # miners feed the forges
                 PopSpec("market_maker", 1, "mk",
                         kwargs={"daily_volume": 16.0, "target_inventory": 40.0}))
    return Scenario(
        name="emberforge", resources=resources, driver=driver, needs=needs,
        market=MarketSpec("call_auction"), population=population,
        primary_resource="iron", crisis_phase="war", capital=capital,
        tunables={"capital_goods_enabled": True},
    )


# The scenario registry -- add a world archetype by adding a builder here (data).
_REGISTRY = {
    "frostpine": _frostpine,
    "tidewater": _tidewater,
    "guildhall": _guildhall,
    "emberforge": _emberforge,
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


def build_population(sc: Scenario) -> list:
    """Turn a scenario's PopSpec rows (archetype names + data) into SpawnSpecs.
    Pure data mapping -- adding a population entry is a PopSpec, never code here."""
    from agents import ARCHETYPES, SpawnSpec
    specs = []
    for ps in sc.population:
        cls = ARCHETYPES.get(ps.archetype)
        if cls is None:
            raise KeyError(f"unknown archetype {ps.archetype!r}; known: {sorted(ARCHETYPES)}")
        specs.append(SpawnSpec(cls, ps.count, ps.id_prefix, dict(ps.kwargs)))
    return specs


def make_world(name: str = "frostpine", player_strategy: str = "idle", **overrides):
    """Build a fully-configured World for a named scenario (config + population all
    from data). The headless entry point for running any scenario's loop."""
    from world import World
    cfg = make_config(name, **overrides)
    return World(cfg, player_strategy=player_strategy, population=build_population(cfg.scenario))


def make_config(name: str = "frostpine", **overrides) -> Config:
    """Build a Config for a named scenario. The Config carries `.scenario` so the
    world reads its axes generically. `overrides` set scalar Config fields (e.g.
    years, seed, flags) on top of the scenario's tunables."""
    sc = get_scenario(name)
    cfg = Config()
    cfg.scenario_name = name                            # serialized, so a save reloads the right world
    cfg.scenario = sc                                   # the world reads axes from here
    # resource-keyed config maps, rebuilt from scenario data (byte-identical for frostpine)
    cfg.intrinsic_value = {r.id: r.intrinsic_value for r in sc.resources}
    cfg.base_yield = {r.id: r.base_yield for r in sc.resources if r.base_yield}
    for k, v in sc.tunables.items():
        setattr(cfg, k, v)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg
