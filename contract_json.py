"""
JSON wire format for the SimCore contract -- the UE5 / sim-as-a-service seam.

The contract (`contract.py`) is already plain data: Intents in, Events + a Snapshot
out. This module is the thin, lossless bridge between those Python dataclasses and
JSON, so a body in ANOTHER process or engine (a UE5 client, a web front-end) can
drive the exact same sim across a wire and nothing but JSON crosses the boundary.
It adds no behaviour and imports no engine internals -- it speaks only `contract`.

Three families, each with a stable JSON shape (see docs/contract-schema.md):
  * INTENT  -- {"type": "<name>", ...fields}  (external control -> the sim)
  * EVENT   -- {"type": "<Name>", ...fields}  (the sim -> the presentation)
  * SNAPSHOT-- the read-only world view, nested plain objects/arrays.

Determinism is preserved across the boundary: the same JSON intents in the same
order drive the same run as the in-process contract (proven in test_service.py).
"""
from __future__ import annotations

from dataclasses import asdict, fields

import contract as C


def _rv(r):
    return r.value if hasattr(r, "value") else r


# --------------------------------------------------------------- intents (in)
# type-tag -> (class, ordered field names). The tag is the lower-cased class name.
_INTENTS = {cls.__name__.lower(): (cls, [f.name for f in fields(cls)] if hasattr(cls, "__dataclass_fields__") else [])
            for cls in C.INTENT_TYPES}


def intent_to_json(intent) -> dict:
    """A contract Intent -> a JSON-safe dict tagged by type."""
    d = {"type": type(intent).__name__.lower()}
    for f in fields(intent):
        d[f.name] = _rv(getattr(intent, f.name))
    return d


def intent_from_json(d: dict):
    """A JSON dict {"type": ..., ...} -> the contract Intent. Raises on an unknown
    type or a missing required field, so a malformed wire message fails loudly
    rather than silently doing nothing."""
    if not isinstance(d, dict) or "type" not in d:
        raise ValueError(f"intent json missing 'type': {d!r}")
    tag = str(d["type"]).lower()
    if tag not in _INTENTS:
        raise ValueError(f"unknown intent type {d['type']!r}; known: {sorted(_INTENTS)}")
    cls, names = _INTENTS[tag]
    kwargs = {n: d[n] for n in names if n in d}
    return cls(**kwargs)


# --------------------------------------------------------------- events (out)
def event_to_json(ev) -> dict:
    """A contract Event -> a JSON-safe dict tagged by its class name."""
    out = {"type": type(ev).__name__}
    for f in fields(ev):
        out[f.name] = _rv(getattr(ev, f.name))
    return out


# ------------------------------------------------------------- snapshot (out)
def snapshot_to_json(snap: C.Snapshot) -> dict:
    """A Snapshot -> nested JSON-safe dict. str-enum resource ids serialize as
    their string value; the generic per-resource dicts are already string-keyed."""
    d = asdict(snap)
    # MarketView.resource may be a str-enum; normalise to a plain string.
    for m in d.get("markets", []):
        m["resource"] = _rv(m["resource"])
    return d


# --------------------------------------------------------- schema (for docs/UE5)
# A compact, machine-readable description of the wire shapes -- what a UE5 client
# generates its DTOs from. Field lists are derived from the dataclasses, so this
# can never drift from the actual contract.
def schema() -> dict:
    def shape(cls):
        return [f.name for f in fields(cls)]
    return {
        "contract_version": C.CONTRACT_VERSION,
        "intents": {cls.__name__.lower(): shape(cls) for cls in C.INTENT_TYPES},
        "events": {cls.__name__: shape(cls) for cls in C.EVENT_TYPES},
        "snapshot": shape(C.Snapshot),
        "views": {cls.__name__: shape(cls)
                  for cls in (C.AgentView, C.MarketView, C.ProblemView, C.LoanView)},
    }
