"""
Sim-as-a-service tests -- the JSON contract boundary (UE5-readiness seam).

Proves a body can drive the exact same sim over a JSON wire, losslessly and
deterministically:

  1. SCHEMA        -- the service publishes the wire shapes (contract version,
     intent/event/snapshot field lists) a client generates its DTOs from.
  2. JSON-SAFE     -- an Intent round-trips dict<->object; a Snapshot and Events
     serialize with the stdlib json module (no custom encoder), for every world.
  3. DETERMINISM   -- driving a scenario ENTIRELY through JSON strings (client ->
     wire -> service) reaches the byte-identical welfare of an in-process SimCore
     fed the same intents. The boundary changes nothing.
  4. SAVE/LOAD OVER WIRE -- a save taken over the wire, loaded into a fresh
     service, resumes to the same state (re-save is byte-identical).
  5. ROBUST        -- a malformed request (bad op, unknown intent) returns
     {"error": ...}, never raises across the boundary.

Dependency-free (stdlib json only); exit 0 = all pass.
"""
from __future__ import annotations

import json
import sys

import contract as C
import contract_json as CJ
import scenario as scen
from simcore import SimCore
from simservice import SimService


def _json_ok(obj) -> bool:
    try:
        json.loads(json.dumps(obj))
        return True
    except (TypeError, ValueError):
        return False


def test_schema() -> list:
    fails = []
    s = SimService("frostpine").handle({"op": "schema"}).get("schema", {})
    if s.get("contract_version") != C.CONTRACT_VERSION:
        fails.append("schema: contract_version missing/mismatched")
    if "gather" not in s.get("intents", {}):
        fails.append("schema: 'gather' intent shape missing")
    if not s.get("intents") or not s.get("events") or not s.get("snapshot"):
        fails.append("schema: missing intent/event/snapshot shapes")
    return fails


def test_json_safe() -> list:
    fails = []
    # intent round-trip
    for intent in (C.Gather("wood"), C.Trade("fish", "sell", 3.0, 4.0),
                   C.Perform("found_mill"), C.BuildWoodlot()):
        d = CJ.intent_to_json(intent)
        if not _json_ok(d):
            fails.append(f"json-safe: intent {intent} not json-serializable")
        back = CJ.intent_from_json(json.loads(json.dumps(d)))
        if type(back) is not type(intent):
            fails.append(f"json-safe: intent {intent} did not round-trip type")
    # snapshot + events json-serializable for every world
    for name in scen.scenario_names():
        svc = SimService(name, interventions=True)
        resp = svc.handle({"op": "step"})
        if not _json_ok(resp.get("snapshot")):
            fails.append(f"json-safe: {name} snapshot not json-serializable")
        if not _json_ok(resp.get("events")):
            fails.append(f"json-safe: {name} events not json-serializable")
    return fails


def test_determinism_across_boundary() -> list:
    """A run driven purely through JSON strings == an in-process run with the same
    intents (same seed). The wire is lossless."""
    fails = []
    for name in scen.scenario_names():
        prim = scen.get_scenario(name).primary_resource
        prim = prim.value if hasattr(prim, "value") else prim

        # (a) in-process
        core = SimCore(config=scen.make_config(name),
                       population=scen.build_population(scen.get_scenario(name)))
        while not core.done:
            core.begin_turn()
            core.submit(C.Gather(prim))
            core.commit_turn()
        direct = core.welfare()

        # (b) over the JSON wire
        svc = SimService(name)
        done = False
        while not done:
            svc.handle(json.loads(json.dumps({"op": "submit",
                        "intents": [{"type": "gather", "resource": prim}]})))
            resp = json.loads(json.dumps(svc.handle({"op": "step"})))
            done = resp["done"]
        wired = svc.core.welfare()

        if direct != wired:
            diff = {k: (direct.get(k), wired.get(k)) for k in set(direct) | set(wired)
                    if direct.get(k) != wired.get(k)}
            fails.append(f"{name}: JSON-driven run diverged from in-process: {diff}")
    return fails


def test_save_load_over_wire() -> list:
    fails = []
    svc = SimService("guildhall")
    for _ in range(40):
        svc.handle({"op": "step"})
    blob = json.loads(json.dumps(svc.handle({"op": "save"})["save"]))
    fresh = SimService("guildhall")
    fresh.handle({"op": "load", "save": blob})
    blob2 = fresh.handle({"op": "save"})["save"]
    if blob != json.loads(json.dumps(blob2)):
        fails.append("save/load over wire: resumed state re-saves differently")
    return fails


def test_layer3_over_wire() -> list:
    """The whole Layer-3 loop drives over JSON: read the intervention menu and
    reputation, then Perform an intervention as a submitted intent, and an
    InterventionPerformed event comes back over the wire."""
    fails = []
    svc = SimService("frostpine", flags={
        "interventions_enabled": True, "capital_goods_enabled": True,
        "reward_at_fair_value": True})
    # menu + reputation reads are well-formed JSON
    menu = svc.handle({"op": "interventions"}).get("interventions")
    if not menu or not all("can_perform" in e and "reason" in e for e in menu):
        fails.append("layer3-wire: intervention menu malformed")
    if not _json_ok(menu):
        fails.append("layer3-wire: intervention menu not json-serializable")
    rep = svc.handle({"op": "reputation"}).get("reputation")
    if not rep or "standing" not in rep or "descriptor" not in rep:
        fails.append("layer3-wire: reputation read malformed")
    # qualify the player (test-side setup), then Perform over the wire
    svc.core.world.by_id["PLAYER"].bonus_earned = 300.0
    svc.core.world.by_id["PLAYER"].money = 500.0
    # advance to a day with a live scarcity/capital problem so the deed can land
    for _ in range(120):
        r = json.loads(json.dumps(svc.handle({"op": "interventions"})))
        if any(e["can_perform"] for e in r["interventions"]):
            break
        svc.handle({"op": "step"})
    ready = [e["key"] for e in svc.handle({"op": "interventions"})["interventions"]
             if e["can_perform"]]
    if not ready:
        fails.append("layer3-wire: no intervention ever became performable")
        return fails
    svc.handle(json.loads(json.dumps(
        {"op": "submit", "intents": [{"type": "perform", "key": ready[0]}]})))
    resp = json.loads(json.dumps(svc.handle({"op": "step"})))
    perf = [e for e in resp["events"] if e["type"] == "InterventionPerformed"]
    if not perf:
        fails.append("layer3-wire: no InterventionPerformed event came back over the wire")
    elif not perf[0]["accepted"]:
        fails.append(f"layer3-wire: performed intervention rejected: {perf[0]['reason']}")
    return fails


def test_robust() -> list:
    fails = []
    svc = SimService("frostpine")
    for bad in ({"op": "nonsense"}, {"op": "submit", "intents": [{"type": "zzz"}]}, {}):
        resp = svc.handle(bad)
        if "error" not in resp:
            fails.append(f"robust: bad request {bad} should return an error, got {resp}")
    return fails


def main() -> int:
    all_fails = []
    tests = (("SCHEMA", test_schema), ("JSON-SAFE", test_json_safe),
             ("DETERMINISM", test_determinism_across_boundary),
             ("SAVE/LOAD-WIRE", test_save_load_over_wire),
             ("LAYER3-WIRE", test_layer3_over_wire), ("ROBUST", test_robust))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nSERVICE TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nSERVICE OK -- the contract drives across a JSON boundary losslessly and\n"
          "deterministically; a UE5/web client speaks these shapes and nothing else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
