"""
Contract conformance test (Phase-1 freeze gate).

Guards the frozen v1 contract from silent drift in either direction:
  * the SIM must accept every declared intent and emit only declared events,
    with snapshots shaped exactly as the contract says;
  * a BODY (game.py now, Unreal later) must reference only names the contract
    still exports -- a renamed/removed symbol here fails the build, not at runtime
    in front of a player.

Run: python test_contract.py   (also picked up by `python -m pytest`).
"""
from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import contract as C
from config import Config, Resource
from simcore import SimCore


def _core() -> SimCore:
    cfg = Config()
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    # propagation ON so Speak is legal and BeliefState events are exercised
    return SimCore(cfg, seed=7, propagation=True)


def test_version_present():
    assert isinstance(C.CONTRACT_VERSION, str) and C.CONTRACT_VERSION
    major = C.CONTRACT_VERSION.split(".")[0]
    assert major.isdigit(), "version must start with an integer major"
    print(f"  contract version {C.CONTRACT_VERSION}")


def test_every_intent_type_is_accepted():
    """SimCore.submit() must accept one of each declared intent without error."""
    core = _core()
    core.begin_turn()
    samples = {
        C.Gather: C.Gather(Resource.WOOD),
        C.CraftTool: C.CraftTool(),
        C.BuildWoodlot: C.BuildWoodlot(),
        C.Trade: C.Trade(Resource.WOOD, "sell", 1.0, 5.0),
        C.Speak: C.Speak(Resource.WOOD, 0.8, True, "test_root", authority=0.6),
        C.Perform: C.Perform("found_mill"),
    }
    assert set(samples) == set(C.INTENT_TYPES), \
        "test does not cover every declared intent type"
    for t, intent in samples.items():
        core.submit(intent)          # must not raise
    core.commit_turn()
    print(f"  accepted all {len(samples)} intent types")


def test_unknown_intent_is_rejected():
    core = _core()
    core.begin_turn()
    try:
        core.submit(object())
    except TypeError:
        print("  unknown intent correctly rejected")
        return
    raise AssertionError("submit() accepted an intent outside the contract")


def test_emitted_events_are_all_declared():
    """Every event drained from a live run must be a declared Event type."""
    core = _core()
    seen = set()
    core.begin_turn()
    core.submit(C.Gather(Resource.WOOD))
    core.submit(C.BuildWoodlot())
    core.submit(C.Speak(Resource.WOOD, 0.9, True, "player_warning", authority=0.85))
    core.commit_turn()
    for _ in range(40):                      # run a while to surface rarer events
        if core.done:
            break
        core.begin_turn()
        core.submit(C.Gather(Resource.WOOD))
        core.submit(C.Trade(Resource.WOOD, "sell", 2.0, 4.0))
        core.commit_turn()
        for ev in core.drain_events():
            assert isinstance(ev, C.EVENT_TYPES), \
                f"undeclared event escaped the contract: {type(ev).__name__}"
            seen.add(type(ev).__name__)
    # sanity: the run should have produced a spread of event kinds, not just one
    assert {"DayAdvanced", "Produced"} <= seen, f"suspiciously few event kinds: {seen}"
    print(f"  observed {len(seen)} event kinds, all declared: {sorted(seen)}")


def test_snapshot_shape():
    """snapshot() returns the declared dataclasses with the declared fields."""
    core = _core()
    snap = core.begin_turn()
    assert isinstance(snap, C.Snapshot) and is_dataclass(snap)
    assert snap.agents and snap.markets, "snapshot should carry agents and markets"

    def field_names(dc) -> set:
        return {f.name for f in fields(dc)}

    for a in snap.agents:
        assert isinstance(a, C.AgentView)
        assert field_names(a) == field_names(C.AgentView)
    for m in snap.markets:
        assert isinstance(m, C.MarketView)
        assert field_names(m) == field_names(C.MarketView)
    # every declared market resource is represented
    assert {m.resource for m in snap.markets} == {Resource.WOOD, Resource.FOOD}
    # Layer 1 (v1.2, additive): the world-state problem board is carried and shaped
    assert snap.problems, "snapshot should carry the problem board"
    for p in snap.problems:
        assert isinstance(p, C.ProblemView)
        assert field_names(p) == field_names(C.ProblemView)
        assert 0.0 <= p.severity <= 1.0, "problem severity must be normalised 0..1"
    print(f"  snapshot: {len(snap.agents)} agents, {len(snap.markets)} markets, "
          f"{len(snap.problems)} problems, shapes match")


def test_body_references_resolve():
    """Every `C.<Name>` a body uses must still exist in the frozen contract.

    Static guard: catches a body left pointing at a renamed/removed symbol before
    a player ever hits it. Scans the shipped bodies next to this sim.
    """
    here = Path(__file__).parent
    bodies = [p for p in (here / "session.py", here / "game.py") if p.exists()]
    assert bodies, "expected at least session.py/game.py to scan"
    ref = re.compile(r"\bC\.([A-Za-z_][A-Za-z0-9_]*)")
    missing = {}
    for body in bodies:
        names = set(ref.findall(body.read_text(encoding="utf-8")))
        gone = sorted(n for n in names if not hasattr(C, n))
        if gone:
            missing[body.name] = gone
    assert not missing, f"body references not in the contract: {missing}"
    scanned = {b.name for b in bodies}
    print(f"  body references all resolve ({', '.join(sorted(scanned))})")


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"contract conformance -- {len(tests)} checks")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print(f"\nOK: contract v{C.CONTRACT_VERSION} conformance passed ({len(tests)} checks)")


if __name__ == "__main__":
    run_all()
