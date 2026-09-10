"""
A thin, scenario-agnostic BODY that drives ANY world through the SimCore contract.

This is the concrete proof of the mission's "wall": nothing here knows about wood,
fish, cloth, or iron. It picks a scenario by NAME, builds a SimCore, runs the loop,
and renders from the contract's generic reads (Snapshot.scenario / .consumables /
.primary_resource / .village_unmet / MarketView / AgentView.holdings). A 2D pixel
View or UE5 would do exactly this at higher fidelity -- read the snapshot, submit
intents, present it. The sim and the index never change to add a world.

    python demo_scenarios.py                 # run every registered scenario
    python demo_scenarios.py tidewater       # run one by name
    python demo_scenarios.py emberforge --build   # let the player found capital

Imports only the contract + SimCore + the scenario registry (names + builders).
It never touches world.py, the accountant, or any renderer internals.
"""
from __future__ import annotations

import sys

import contract as C
import scenario as scen
from simcore import SimCore


def _forge_builder(core: SimCore) -> None:
    """A tiny scripted player for capital scenarios: work the crisis good by hand
    and invest in the scenario's capital good when it can. Uses ONLY contract
    intents -- Gather + BuildWoodlot (the generic 'establish capital' verb)."""
    snap = core.snapshot()
    prim = snap.primary_resource
    core.submit(C.Gather(prim))
    # feed/fund the capital good from whatever the world's build/upkeep goods are:
    for r in snap.consumables:
        if r != prim:
            core.submit(C.Gather(r))
    core.submit(C.BuildWoodlot())


def run_scenario(name: str, build: bool = False) -> C.Snapshot:
    """Drive one scenario to completion through the contract; return the final
    snapshot. `build` engages the scripted capital-builder player."""
    core = SimCore(
        config=scen.make_config(name, interventions_enabled=build),
        population=scen.build_population(scen.get_scenario(name)),
    )
    while not core.done:
        core.begin_turn()
        if build:
            _forge_builder(core)
        core.commit_turn()
    return core, core.snapshot()


def render(core: SimCore, snap: C.Snapshot) -> str:
    """Render a world from the contract alone -- no scenario knowledge baked in."""
    w = core.welfare()               # metrics.summary(), keyed by this world's ids
    prim = snap.primary_resource
    lines = [
        "=" * 60,
        f"scenario: {snap.scenario}   day {snap.day}   final phase: {snap.season}",
        f"crisis good: {prim}   goods: {', '.join(snap.consumables)}",
        "  market (final):",
    ]
    for m in snap.markets:
        rid = m.resource.value if hasattr(m.resource, "value") else m.resource
        lines.append(f"    {rid:<10} price {m.ref_price:6.2f}   fair {m.fair_price:6.2f}")
    lines.append("  village unmet (whole run):")
    for r in snap.consumables:
        total = w.get(f"village_unmet_{r}", 0.0)
        lines.append(f"    {r:<10} {total:8.1f}")
    lines.append(f"  shortage days: {w.get('shortage_days', 0)}   "
                 f"contribution paid: {w.get('total_reward_paid', 0.0):.1f}")
    # any capital the scripted player founded (generic: read assets off the world)
    assets = {}
    for a in core.world.agents:
        for x in getattr(a, "assets", []):
            assets[x.kind] = max(assets.get(x.kind, 0), x.level)
    if assets:
        lines.append("  capital built: " +
                     ", ".join(f"{k} Lv{v}" for k, v in sorted(assets.items())))
    lines.append("=" * 60)
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    build = "--build" in argv
    names = [a for a in argv if not a.startswith("-")]
    if not names:
        names = scen.scenario_names()
    for name in names:
        if name not in scen.scenario_names():
            print(f"unknown scenario {name!r}; known: {scen.scenario_names()}")
            return 1
        core, snap = run_scenario(name, build=build)
        print(render(core, snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
