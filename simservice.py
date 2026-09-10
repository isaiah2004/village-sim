"""
Sim-as-a-service -- drive SimCore across a JSON boundary (the UE5-readiness seam).

A UE5 client (or any out-of-process body) cannot import the Python sim; it speaks
the contract over a wire. `SimService` is that wire endpoint: it owns one SimCore
and answers plain-dict requests with plain-dict responses, using `contract_json`
for the Intent/Event/Snapshot shapes and `persistence` for save/load. Everything
in and out is JSON-safe, so the transport (HTTP, a socket, UE5's HTTP module) is
someone else's detail -- this is the whole server side of the boundary.

Request envelope: {"op": "<name>", ...}
  * {"op": "snapshot"}                       -> {"snapshot": {...}}
  * {"op": "submit", "intents": [ {..}, .. ]} -> {"ok": true, "queued": n}
  * {"op": "step"}                            -> {"snapshot": {...}, "events": [ {..} ], "done": bool}
  * {"op": "save"}                            -> {"save": {...}}          (full JSON save blob)
  * {"op": "load", "save": {...}}             -> {"snapshot": {...}}      (resume from a blob)
  * {"op": "schema"}                          -> {"schema": {...}}        (the wire shapes)

`handle(request)` never raises on a bad request -- it returns {"error": "..."} so a
remote client gets a clean protocol error, not a dropped connection. Determinism is
preserved: the same JSON intents in the same order reproduce an in-process run.
"""
from __future__ import annotations

import contract_json as CJ
import scenario as scen
from simcore import SimCore


class SimService:
    def __init__(self, scenario_name: str = "frostpine", propagation: bool = False,
                 interventions: bool = False):
        cfg = scen.make_config(scenario_name)
        if interventions:
            cfg.interventions_enabled = True
        self.core = SimCore(config=cfg, propagation=propagation,
                            population=scen.build_population(scen.get_scenario(scenario_name)))
        # The core is kept at a DAY BOUNDARY between requests (never mid-turn), so
        # a `save` is always clean and byte-identical to load: `step` begins and
        # commits a day transiently, then returns to the boundary.

    # ---------------- the wire endpoint ----------------
    def handle(self, request: dict) -> dict:
        """Answer one JSON-safe request with a JSON-safe response. Protocol errors
        come back as {"error": ...}; they never raise across the boundary."""
        try:
            op = (request or {}).get("op")
            if op == "snapshot":
                return {"snapshot": CJ.snapshot_to_json(self.core.snapshot())}
            if op == "submit":
                intents = request.get("intents", [])
                for d in intents:
                    self.core.submit(CJ.intent_from_json(d))
                return {"ok": True, "queued": len(intents)}
            if op == "step":
                if self.core.done:
                    return {"snapshot": CJ.snapshot_to_json(self.core.snapshot()),
                            "events": [], "done": True}
                self.core.begin_turn()      # publish the day (applies queued intents on commit)
                self.core.commit_turn()     # execute + advance -> back to a boundary
                events = [CJ.event_to_json(e) for e in self.core.drain_events()]
                return {"snapshot": CJ.snapshot_to_json(self.core.snapshot()),
                        "events": events, "done": self.core.done}
            if op == "save":                # always at a boundary -> clean save
                return {"save": self.core.serialize()}
            if op == "load":
                self.core = SimCore.from_save(request["save"])
                return {"snapshot": CJ.snapshot_to_json(self.core.snapshot())}
            if op == "schema":
                return {"schema": CJ.schema()}
            return {"error": f"unknown op {op!r}"}
        except Exception as e:  # noqa: BLE001 -- a wire endpoint must not drop the connection
            return {"error": f"{type(e).__name__}: {e}"}
