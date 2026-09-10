# Scenarios are DATA

A **scenario** is a named world archetype expressed entirely as data — resources,
a cyclical driver, needs, a market model, a population, and capital goods. The sim,
the contribution index, and the contract read those axes generically, with **no
per-scenario branching anywhere**. Adding a whole new world is therefore a single
data entry: a name and values, zero new logic.

This is the modularity contract from `DESIGN.md`, and it is enforced by
`test_modularity.py` (which adds a throwaway world and proves it runs headlessly
and through the contract with no engine change) and by `regression.py` (which pins
every scenario's numbers byte-for-byte).

## The axes (all live in `scenario.py`)

| Axis | Type | What it selects |
|---|---|---|
| **Resources** | `ResourceSpec(id, intrinsic_value, consumable, base_yield, base_consume)` | The goods that exist. `consumable` goods deplete daily; capital goods (tools, infrastructure) don't. |
| **Driver** | `Driver(name, phases=(Phase(name, length, yield_mult, consume_mult), …))` | The cyclical modulator (frostpine's seasons, tidewater's tides). Per-resource `yield_mult`/`consume_mult` per phase; missing entries default to 1.0. |
| **Needs** | `NeedSpec(key, resource, rewarded, consumer)` | The problems the index prices. `rewarded` = does meeting it pay realized-effect contribution. `consumer` scopes WHO holds the need: `""` = every agent (the universal village need); an archetype name = only that archetype (a **demand-side** need, e.g. only a war quartermaster needs monster parts). |
| **Market** | `MarketSpec(model, params)` | `"call_auction"` (the double auction) or `"guild"` (a support bid buys up to `params["quota"]` of `params["resource"]` at a capped floor `params["price"]` and **exports** it — a buyer of last resort that floors producer income; it clears through the ordinary auction, so it steps aside whenever real demand lifts the price above the floor). |
| **Population** | `PopSpec(archetype, count, id_prefix, kwargs)` | Rows of agents. `archetype` maps to an agent class via `agents.ARCHETYPES` (`villager`, `dependent`, `market_maker`, `merchant`, `buyer`). A `villager` given `kwargs={"produces": "<good>"}` gathers that TRADE GOOD for the market even if it does not consume it (an adventurer's monster parts). A `buyer` (`InstitutionBuyer`) is an off-town institution that enters the market during a demand window to buy `kwargs["demand_good"]` at a `kwargs["premium"]`. |
| **Capital** | `CapitalSpec(kind, output_resource, output_per_level, upkeep_resource, upkeep_per_level, build_cost_resource, build_cost, max_level)` | A buildable asset that converts upkeep into output each day (frostpine's woodlot, emberforge's forge). |
| **primary_resource / crisis_phase** | `str` | The crisis good and the peak-stress phase — used for metrics naming and the anti-hoard watch. |
| **tunables** | `dict` | Scalar `Config` overrides (e.g. `{"capital_goods_enabled": True}`). |

## Add a scenario in three steps

1. **Write a builder** in `scenario.py` that returns a `Scenario` value:

   ```python
   def _myworld() -> Scenario:
       phases = tuple(
           Phase(name=n, length=30,
                 yield_mult={"glimmer": g[n], "bread": 1.0},
                 consume_mult={"glimmer": 1.0, "bread": 1.0})
           for n in ("waxing", "full", "waning", "dark"))
       return Scenario(
           name="myworld",
           resources=(ResourceSpec("glimmer", 5.0, True, base_yield=2.0, base_consume=1.0),
                      ResourceSpec("bread",   6.0, True, base_yield=2.5, base_consume=1.0)),
           driver=Driver("moons", phases),
           needs=(NeedSpec("glimmer_need", "glimmer", rewarded=True),
                  NeedSpec("bread_need",   "bread",   rewarded=False)),
           market=MarketSpec("call_auction"),
           population=(PopSpec("villager", 8, "g"),
                       PopSpec("dependent", 3, "b", kwargs={"produces": "bread"}),
                       PopSpec("market_maker", 1, "mk",
                               kwargs={"daily_volume": 16.0, "target_inventory": 40.0})),
           primary_resource="glimmer", crisis_phase="dark")
   ```

2. **Register it** in the `_REGISTRY` dict at the bottom of `scenario.py`:

   ```python
   _REGISTRY = { "frostpine": _frostpine, …, "myworld": _myworld }
   ```

   (Tests can register at runtime with `scenario.register_scenario(name, builder)`.)

3. **Run it** — headlessly, or through the contract, with no other change:

   ```bash
   python demo_scenarios.py myworld           # thin contract-only body renders it
   ```
   ```python
   import scenario
   world = scenario.make_world("myworld")      # fully-configured World
   world.run()
   print(world.metrics.report("myworld"))
   ```

That's it. `make_config(name)` builds the `Config` (attaching the live scenario and
the resource-keyed maps); `make_world(name)` also builds the population; the world
reads every axis off `cfg.scenario`.

## Anchor it in the golden master

New scenarios are added to `regression.py`'s `_named_scenarios()` list and captured
**additively** — new rows only, existing scenarios byte-identical:

```bash
python regression.py            # confirm existing rows still match (new ones flagged)
python regression.py --capture  # write the new rows into golden.json
python regression.py            # now green
```

Never re-capture to silence a failure on an existing scenario — that erases the
safety net. A change to a shipped scenario's numbers is a real regression.

## The registered worlds

| Scenario | Proves | Crisis good / phase | Notes |
|---|---|---|---|
| **frostpine** | The baseline, byte-identical to the historical world. | wood / winter | Seasons; woodlot capital; the golden anchor. |
| **tidewater** | A **driver + resources are pure data**. | fish / storm | Tide driver; grain staple; net-menders garden grain. |
| **guildhall** | The **market model is a data axis** + a **demand-side crisis**. | monster_parts / war | Adventurer city on the guild market. A war-prep **demand event** draws a government **quartermaster** (a new `buyer` archetype) who pays a premium for parts; the front's demand outstrips town supply, so the index pays the adventurers who supply it. |
| **emberforge** | **Multi-resource structural scarcity relieved by capital**. | iron / war | Iron is gathered slower than consumed; a forge (built from ore, fuelled by charcoal) closes the gap. |
| **dustveil** | A **cyclical supply crisis + capital relief**, combined as data. | water / drought | A drought driver collapses the water draw; a cistern (built from grain, fuelled by grain) stores the wet season against the dry. |
| **fallowmere** | A **substitution crisis** — one driver flips yield on one good and demand onto another. | roots / blight | The blight phase poisons the grain harvest (yield collapse) and switches the town's demand to the slower-dug roots, so roots go short exactly in blight. |

`plaguewatch` is a **second demand event as pure data** — same machinery as
guildhall, different values: a plague draws an **apothecary** who pays a premium
for a herb, on the ordinary call auction (proving the demand crisis is independent
of the guild market). `test_demand.py` adds a third (a festival vintner) at runtime
to prove a demand event is one data entry with zero new logic.

### Demand-event worlds (a crisis with no shortfall)

Some worlds have no supply crisis — the crisis is a **demand event** that makes a
good suddenly precious and draws a new buyer. Express it as data:
1. a **demand-side driver** — a phase whose `consume_mult` on the good spikes
   (raising the buyer's *need*, never the good's yield);
2. a **demand-scoped need** — `NeedSpec(..., consumer="buyer")`, so only the
   institution carries it (the town's residents never "need" the export good);
3. a **producer** — `PopSpec("villager", …, kwargs={"produces": good})` gathers
   the good for market without consuming it;
4. an **institutional buyer** — `PopSpec("buyer", 1, …, kwargs={"demand_good": good, "premium": …, "capacity": …})`.

Set the peak demand *above* the town's production capacity so the front runs a
real deficit — that unmet demand is the scarcity the index prices. See
`scenario._demand_event`, which builds guildhall and plaguewatch from one call.

`test_modularity.py`'s **saltmarsh** (peat-cutters) is a fifth, throwaway world that
exists only to prove the claim — it is defined in the test, not the registry.
