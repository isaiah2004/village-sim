"""
Golden-master regression harness (Phase 1 safety net).

Captures the full summary metrics of every validated scenario -- the economy
head-to-head (main.py) and the knowledge-propagation scenarios (demo_knowledge.py)
-- into `golden.json`. Any later refactor that changes a number is caught here.

    python regression.py --capture    # (re)write golden.json from current code
    python regression.py              # check current code against golden.json

Exit code 0 = all scenarios match; 1 = a mismatch (prints the offending fields).
Deterministic: the sim is seeded, so matches must be exact (tolerance 1e-6).

This is intentionally dependency-free (stdlib only), mirroring the rest of the
project, so it can run anywhere the sim runs.
"""
from __future__ import annotations

import copy
import json
import os
import sys

from agents import Merchant, SpawnSpec, Villager
from config import Config, Resource
from world import World

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden.json")
TOL = 1e-6


# --------------------------------------------------------------------------
# scenario builders -- these mirror main.py and demo_knowledge.py exactly.
# --------------------------------------------------------------------------
def _economy_scenarios(cfg: Config):
    village_with_merchants = [
        SpawnSpec(Villager, cfg.n_villagers, id_prefix="v"),
        SpawnSpec(Merchant, 3, id_prefix="m"),
    ]
    # (name, player_strategy, accountant_enabled, population)
    return [
        ("ACCOUNTANT_OFF", "idle",       False, None),
        ("NO_PLAYER",      "idle",       True,  None),
        ("PLAYER_IGNORES", "ignore",     True,  None),
        ("PLAYER_RESPONDS", "responsive", True, None),
        ("PLAYER_HOARDS",  "hoarder",    True,  None),
        ("WITH_MERCHANTS", "idle",       True,  village_with_merchants),
    ]


def _run_economy(cfg: Config, strategy, accountant_enabled, population):
    cfg = copy.deepcopy(cfg)
    cfg.accountant_enabled = accountant_enabled
    world = World(cfg, player_strategy=strategy, population=population)
    world.run()
    return world.metrics


def _need_scenarios():
    """Scenarios that exercise the data-defined need registry (DESIGN.md Layer 2).
    Each is a (name, strategy, cfg-mutator) triple; the mutator flips only config
    DATA -- no code path is special-cased. These prove the index prices/rewards a
    SECOND need (food) through the identical pipeline. Additive: they add new
    golden rows and leave the original 9 scenarios untouched."""
    def food_need_blight(cfg: Config) -> None:
        cfg.food_blight_enabled = True      # make food genuinely scarce (a real problem)
        cfg.reward_food_need = True         # register food as a REWARDED need (pure data)
        cfg.reward_at_fair_value = True     # price the met need at fair value (the index's heart)
    return [("FOOD_NEED_BLIGHT", "idle", food_need_blight)]


def _run_need(cfg: Config, strategy, mutate):
    cfg = copy.deepcopy(cfg)
    mutate(cfg)
    world = World(cfg, player_strategy=strategy)
    world.run()
    return world.metrics


def _run_propagation(cfg: Config, strategy, inject):
    from knowledge import Claim  # local import: only needed for these scenarios
    cfg = copy.deepcopy(cfg)
    cfg.propagation_enabled = True
    world = World(cfg, player_strategy=strategy)
    for spec in (inject or []):
        world.schedule_injection(**spec)
    world.run()
    return world.metrics


def _propagation_scenarios():
    from knowledge import Claim
    WARN_DAY, LIE_DAY = 82, 66
    return [
        ("PROP_QUIET", "idle", []),
        ("PROP_TRUE_WARNING", "idle", [dict(
            day=WARN_DAY, target="hub",
            claim=Claim(Resource.WOOD, 0.85, True, "warning:winter_wood", WARN_DAY),
            authority=0.9, by_player=True)]),
        ("PROP_FALSE_RUMOUR", "idle", [dict(
            day=LIE_DAY, target="random",
            claim=Claim(Resource.FOOD, 0.8, False, "rumour:food_panic", LIE_DAY),
            authority=0.6)]),
    ]


def _named_scenarios():
    """The data-defined world archetypes (DESIGN.md "scenarios are DATA"). Each
    runs headlessly straight from its scenario name -- no config surgery. Additive:
    they add new golden rows (their own resource/phase-keyed metrics) and leave
    frostpine's rows untouched. This anchors tidewater/guildhall/emberforge so any
    future refactor that changes their numbers is caught too."""
    return ["tidewater", "guildhall", "plaguewatch", "emberforge", "dustveil", "fallowmere"]


def _run_named(name: str):
    import scenario as _scen
    world = _scen.make_world(name, player_strategy="idle")
    world.run()
    return world.metrics


def collect() -> dict:
    """Run every scenario and return {name: summary_dict} with rounded floats."""
    cfg = Config()
    out: dict = {}
    for name, strat, acct, pop in _economy_scenarios(cfg):
        out[name] = _round(_run_economy(cfg, strat, acct, pop).summary())
    for name, strat, inject in _propagation_scenarios():
        out[name] = _round(_run_propagation(cfg, strat, inject).summary())
    for name, strat, mutate in _need_scenarios():
        out[name] = _round(_run_need(cfg, strat, mutate).summary())
    for name in _named_scenarios():
        out[f"SCENARIO_{name.upper()}"] = _round(_run_named(name).summary())
    return out


def _round(d: dict) -> dict:
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items()}


# --------------------------------------------------------------------------
# capture / check
# --------------------------------------------------------------------------
def capture() -> None:
    data = collect()
    with open(GOLDEN, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    n = sum(len(v) for v in data.values())
    print(f"captured {len(data)} scenarios / {n} metrics -> {GOLDEN}")


def check() -> int:
    if not os.path.exists(GOLDEN):
        print("no golden.json -- run `python regression.py --capture` first")
        return 1
    with open(GOLDEN) as f:
        golden = json.load(f)
    current = collect()
    failures = []
    for name in sorted(set(golden) | set(current)):
        if name not in current:
            failures.append(f"  {name}: scenario missing from current run")
            continue
        if name not in golden:
            failures.append(f"  {name}: new scenario not in golden (re-capture?)")
            continue
        g, c = golden[name], current[name]
        for k in sorted(set(g) | set(c)):
            gv, cv = g.get(k), c.get(k)
            if isinstance(gv, (int, float)) and isinstance(cv, (int, float)):
                if abs(gv - cv) > TOL:
                    failures.append(f"  {name}.{k}: golden={gv} current={cv} (Δ={cv - gv:+.6g})")
            elif gv != cv:
                failures.append(f"  {name}.{k}: golden={gv!r} current={cv!r}")

    if failures:
        print(f"REGRESSION FAILED -- {len(failures)} field(s) differ:")
        print("\n".join(failures))
        return 1
    total = sum(len(v) for v in current.values())
    print(f"REGRESSION OK -- {len(current)} scenarios, {total} metrics all match golden.")
    return 0


def main(argv) -> int:
    if "--capture" in argv:
        capture()
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
