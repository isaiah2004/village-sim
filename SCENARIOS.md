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
| **Needs** | `NeedSpec(key, resource, rewarded)` | The problems the index prices. `rewarded` = does meeting it pay realized-effect contribution. |
| **Market** | `MarketSpec(model, params)` | `"call_auction"` (the double auction) or `"guild"` (a support bid buys up to `params["quota"]` of `params["resource"]` at a capped `params["price"]`; overflow clears on the open auction). |
| **Population** | `PopSpec(archetype, count, id_prefix, kwargs)` | Rows of agents. `archetype` maps to an agent class via `agents.ARCHETYPES` (`villager`, `dependent`, `market_maker`, `merchant`). |
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

## The four MVP worlds (`DESIGN.md` "First-MVP scenarios")

| Scenario | Proves | Crisis good / phase | Notes |
|---|---|---|---|
| **frostpine** | The baseline, byte-identical to the historical world. | wood / winter | Seasons; woodlot capital; the golden anchor. |
| **tidewater** | A **driver + resources are pure data**. | fish / storm | Tide driver; grain staple; net-menders garden grain. |
| **guildhall** | The **market model is a data axis**. | potion / delve | Adventurer town; a guild support bid floors adventurers' pay against a delve glut (takings ≈ 5.5× vs a plain auction). |
| **emberforge** | **Multi-resource structural scarcity relieved by capital**. | iron / war | Iron is gathered slower than consumed; a forge (built from ore, fuelled by charcoal) closes the gap. |

`test_modularity.py`'s **saltmarsh** (peat-cutters) is a fifth, throwaway world that
exists only to prove the claim — it is defined in the test, not the registry.
