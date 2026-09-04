"""
Persistence round-trip test (Phase-1 save/load gate).

The real fidelity check is behavioural, not structural: take a save, push it
through a JSON round-trip (proving it's wire-safe), load it into a FRESH core,
then drive the original and the reloaded core with identical intents for many
more days. If a single float of state were lost, the two would diverge. They
must stay byte-identical -- snapshots, events, and score, every day.

Run: python test_persistence.py
"""
from __future__ import annotations

import json
from dataclasses import asdict

import contract as C
from agents import Dependent, MarketMaker, SpawnSpec, Villager
from config import Config, Resource
from simcore import SimCore

WARM = 40      # days before saving
CONT = 30      # days to run both cores after the save


def _population(cfg):
    return [SpawnSpec(Villager, 8, id_prefix="v"),
            SpawnSpec(Dependent, 3, id_prefix="d"),
            SpawnSpec(MarketMaker, 1, id_prefix="mk",
                      kwargs=dict(spread=0.05, target_inventory=40.0, daily_volume=16.0))]


def _cfg(propagation: bool) -> Config:
    cfg = Config()
    cfg.years = 1.0
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    cfg.propagation_enabled = propagation
    return cfg


def _intents(day: int, propagation: bool) -> list:
    """A deterministic, varied intent script keyed purely on the day, so both
    cores receive identical inputs regardless of internal object identity."""
    out = [C.Gather(Resource.WOOD), C.Gather(Resource.FOOD)]
    if day % 5 == 0:
        out.append(C.BuildWoodlot())
    if day % 3 == 0:
        out.append(C.Trade(Resource.WOOD, "sell", 5.0, 4.0))
    if day % 4 == 0:
        out.append(C.Trade(Resource.FOOD, "buy", 3.0, 8.0))
    if propagation and day % 7 == 0:
        out.append(C.Speak(Resource.WOOD, 0.85, True, "player_warning", authority=0.85))
    return out


def _drive(core: SimCore, day: int, propagation: bool):
    core.begin_turn()
    for intent in _intents(day, propagation):
        core.submit(intent)
    core.commit_turn()
    return core.snapshot(), core.drain_events(), core.score("PLAYER")


def _events_key(events: list):
    return [(type(e).__name__, asdict(e)) for e in events]


def _run_case(propagation: bool) -> None:
    tag = "propagation ON" if propagation else "propagation OFF"
    a = SimCore(_cfg(propagation), seed=7, propagation=propagation, population=_population(_cfg(propagation)))
    for d in range(WARM):
        _drive(a, d, propagation)

    # save -> JSON text -> back (proves the blob is wire-safe) -> fresh core
    blob = a.serialize()
    wire = json.dumps(blob)                       # must not raise
    reloaded = json.loads(wire)
    b = SimCore.from_save(reloaded)

    # sanity: the two cores agree the instant after load, before stepping
    assert asdict(a.snapshot()) == asdict(b.snapshot()), f"[{tag}] snapshots differ right after load"
    assert a.day == b.day == WARM

    for d in range(WARM, WARM + CONT):
        sa, ea, sca = _drive(a, d, propagation)
        sb, eb, scb = _drive(b, d, propagation)
        assert asdict(sa) == asdict(sb), f"[{tag}] snapshot diverged on day {d}"
        assert _events_key(ea) == _events_key(eb), f"[{tag}] events diverged on day {d}"
        assert abs(sca - scb) < 1e-12, f"[{tag}] score diverged on day {d}: {sca} vs {scb}"

    assert a.welfare() == b.welfare(), f"[{tag}] final welfare differs"
    print(f"  [{tag}] identical for {CONT} days after reload; "
          f"final score={a.score('PLAYER'):.3f}, welfare wood-unmet="
          f"{a.welfare()['village_unmet_wood']:.2f}")


def test_roundtrip_propagation_on():
    _run_case(True)


def test_roundtrip_propagation_off():
    _run_case(False)


def test_incompatible_version_refused():
    a = SimCore(_cfg(True), seed=1, propagation=True, population=_population(_cfg(True)))
    a.step()
    blob = a.serialize()
    blob["contract_version"] = "999.0"
    try:
        SimCore.from_save(blob)
    except ValueError:
        print("  incompatible contract major correctly refused")
        return
    raise AssertionError("load accepted a save from an incompatible contract major")


def test_json_size_reasonable():
    a = SimCore(_cfg(True), seed=7, propagation=True, population=_population(_cfg(True)))
    for d in range(WARM):
        _drive(a, d, True)
    n = len(json.dumps(a.serialize()))
    print(f"  save blob after {WARM} days: {n/1024:.1f} KB")
    assert n < 5_000_000, "save blob unexpectedly large"


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"persistence round-trip -- {len(tests)} checks")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print("\nPERSISTENCE OK -- save/load round-trips byte-identical through JSON.")


if __name__ == "__main__":
    run_all()
