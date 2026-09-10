"""
Drive the sim across a JSON boundary -- the concrete UE5-readiness example.

Everything a UE5 (or web) client would do: send JSON requests to `SimService`, read
JSON responses, never touching a Python sim object. Here the "wire" is just
json.dumps/json.loads around every crossing, to make the boundary explicit -- swap
it for HTTP and the client is unchanged.

    python demo_service.py                # play frostpine across the boundary
    python demo_service.py tidewater

Prints the schema a client generates its DTOs from, drives a full year sending only
JSON, and shows a save/resume across the wire.
"""
from __future__ import annotations

import json
import sys

from simservice import SimService


def _wire(service: SimService, request: dict) -> dict:
    """Simulate the network hop: serialize the request to a JSON string, hand it to
    the service, serialize the response back. Only JSON ever crosses."""
    req = json.loads(json.dumps(request))          # client -> wire -> server
    resp = service.handle(req)
    return json.loads(json.dumps(resp))            # server -> wire -> client


def main(argv: list[str]) -> int:
    name = next((a for a in argv if not a.startswith("-")), "frostpine")
    service = SimService(name, interventions=True)

    schema = _wire(service, {"op": "schema"})["schema"]
    print(f"=== sim-as-a-service: {name} (contract v{schema['contract_version']}) ===")
    print(f"intents a client may send: {', '.join(sorted(schema['intents']))}")

    snap = _wire(service, {"op": "snapshot"})["snapshot"]
    prim = snap["primary_resource"]
    print(f"crisis good: {prim}   goods: {', '.join(snap['consumables'])}\n")

    saved = None
    day = 0
    while not snap.get("done"):
        # a trivial client policy: each day, send a JSON gather intent for the crisis good
        _wire(service, {"op": "submit", "intents": [{"type": "gather", "resource": prim}]})
        resp = _wire(service, {"op": "step"})
        snap = resp["snapshot"]
        if day == 90:                              # save mid-year, across the wire
            saved = _wire(service, {"op": "save"})["save"]
        day += 1

    me = next(a for a in snap["agents"] if a["is_player"])
    print(f"year complete ({day} days). player contribution: {me['contribution_earned']:.1f}")
    print(f"village unmet {prim}: {snap['village_unmet'].get(prim, 0.0):.1f}")

    if saved is not None:
        # resume the mid-year save in a FRESH service, over the wire
        fresh = SimService(name)
        rs = _wire(fresh, {"op": "load", "save": saved})["snapshot"]
        print(f"\nresumed a mid-year save over the wire at day {rs['day']} "
              f"(phase {rs['season']}).")
    print("\nNothing but JSON crossed the boundary -- a UE5 client drives the same sim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
