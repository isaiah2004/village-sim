"""
Full-fidelity save/load for SimCore (the dedicated Phase-1 persistence task).

A save is a plain, JSON-safe dict: the rng states, the lineage DAG, every
agent's holdings/beliefs/assets, the accountant ledger, the knowledge network,
and enough construction info (config + population spec) to rebuild the world
shell before overlaying that state back onto it. Because every cross-object link
in this sim is an *id* (integer lot ids, string agent ids) rather than a Python
reference, nothing needs pointer-fixup on load -- the ids just resolve again.

Contract:
  * A save is taken at a DAY BOUNDARY (between commit_turn and the next
    begin_turn). Transient within-day scratch (the day's contexts, the order
    book, partial settlements) is intentionally NOT saved -- it is recomputed
    on the next step. So `load` always lands on a clean boundary.
  * Round-trip fidelity is verified behaviourally: a loaded core, fed the same
    intents, evolves byte-identically to the original (see test_persistence.py).
  * The blob carries CONTRACT_VERSION and SAVE_FORMAT_VERSION; load refuses a
    save whose contract MAJOR differs from the running one.
"""
from __future__ import annotations

from collections import deque
from dataclasses import fields as dc_fields

import agents as A
from agents import Asset, SpawnSpec
from config import Config, Resource, Season
from contract import CONTRACT_VERSION
from knowledge import Belief, Claim
from lineage import Lot
from market import Clearing
from world import World

_ZERO = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}

SAVE_FORMAT_VERSION = 1

# Agent classes that a population spec can name (Player is created by the World
# itself, not via the spec).
_AGENT_CLASSES = {c.__name__: c for c in (A.Villager, A.Dependent, A.MarketMaker, A.Merchant)}

_RES_VALUES = {r.value for r in Resource}
_SEASON_VALUES = {s.value for s in Season}


# ---------------------------------------------------------------- enum helpers
def _res_keyed(d: dict) -> dict:
    """{Resource: v} -> {str: v}"""
    return {k.value: v for k, v in d.items()}


def _res_unkey(d: dict) -> dict:
    """{str: v} -> {Resource: v}"""
    return {Resource(k): v for k, v in d.items()}


def _cfg_key_back(k):
    if isinstance(k, str):
        if k in _RES_VALUES:
            return Resource(k)
        if k in _SEASON_VALUES:
            return Season(k)
    return k


# ---------------------------------------------------------------------- config
def enc_config(cfg: Config) -> dict:
    out = {}
    for f in dc_fields(cfg):
        v = getattr(cfg, f.name)
        if isinstance(v, dict):
            out[f.name] = {(k.value if isinstance(k, (Resource, Season)) else k): vv
                           for k, vv in v.items()}
        else:
            out[f.name] = v
    return out


def dec_config(d: dict) -> Config:
    cfg = Config()
    for name, v in d.items():
        if not hasattr(cfg, name):
            continue                       # tolerate an older/newer field gracefully
        cur = getattr(cfg, name)
        if isinstance(cur, dict) and isinstance(v, dict):
            setattr(cfg, name, {_cfg_key_back(k): vv for k, vv in v.items()})
        else:
            setattr(cfg, name, v)
    return cfg


# ------------------------------------------------------------------ population
def enc_population(pop: list | None) -> list | None:
    if pop is None:
        return None
    return [{"cls": s.cls.__name__, "count": s.count,
             "id_prefix": s.id_prefix, "kwargs": dict(s.kwargs)} for s in pop]


def dec_population(data: list | None) -> list | None:
    if data is None:
        return None
    out = []
    for s in data:
        cls = _AGENT_CLASSES.get(s["cls"])
        if cls is None:
            raise ValueError(f"save names an unknown agent class: {s['cls']!r}")
        out.append(SpawnSpec(cls, s["count"], s.get("id_prefix", ""), dict(s.get("kwargs", {}))))
    return out


# ----------------------------------------------------------------------- claim
def _enc_claim(c: Claim) -> list:
    return [c.resource.value, c.magnitude, c.objective_truth, c.root_id, c.origin_day]


def _dec_claim(x: list) -> Claim:
    return Claim(Resource(x[0]), x[1], x[2], x[3], x[4])


# --------------------------------------------------------------------- lineage
def enc_lineage(lin) -> dict:
    return {
        "next_id": lin._next_id,
        "lots": [[l.id, l.resource.value, l.producer_id, l.tick, l.kind,
                  [[pid, w] for pid, w in l.parents], l.qty_produced, l.credit_paid]
                 for l in lin.lots.values()],
    }


def dec_lineage(lin, d: dict) -> None:
    lin.lots = {}
    for lid, res, pid, tick, kind, parents, qty, credit in d["lots"]:
        lin.lots[lid] = Lot(lid, Resource(res), pid, tick, kind,
                            [(p, w) for p, w in parents], qty, credit)
    lin._next_id = d["next_id"]


# ------------------------------------------------------------------ accountant
def enc_accountant(ac) -> dict:
    s = ac.state
    return {
        "bounty": _res_keyed(s.bounty),
        "fair_price": _res_keyed(s.fair_price),
        "predicted_deficit": _res_keyed(s.predicted_deficit),
        "paid_today": s.paid_today,
        "total_paid": s.total_paid,
        "total_penalty": s.total_penalty,
        "hoard_flags": dict(s.hoard_flags),
        "prod_ema": _res_keyed(ac._prod_ema),
        "sales_ema": dict(ac._sales_ema),
        "honest_offer_ema": dict(ac._honest_offer_ema),
    }


def dec_accountant(ac, d: dict) -> None:
    s = ac.state
    s.bounty = _res_unkey(d["bounty"])
    s.fair_price = _res_unkey(d["fair_price"])
    s.predicted_deficit = _res_unkey(d["predicted_deficit"])
    s.paid_today = d["paid_today"]
    s.total_paid = d["total_paid"]
    s.total_penalty = d["total_penalty"]
    s.hoard_flags = dict(d["hoard_flags"])
    ac._prod_ema = _res_unkey(d["prod_ema"])
    ac._sales_ema = dict(d["sales_ema"])
    ac._honest_offer_ema = dict(d["honest_offer_ema"])


# ----------------------------------------------------------------------- agent
def enc_agent(a) -> dict:
    return {
        "id": a.id,
        "money": a.money,
        "stamina": a.stamina,
        "holdings": {r.value: [[lid, q] for lid, q in a.holdings[r]] for r in a.holdings},
        "skill": {r.value: v for r, v in a.skill.items()},
        "tool_durability_left": a.tool_durability_left,
        "assets": [[x.kind, x.lot_id, x.built_tick, x.level] for x in a.assets],
        "perceived_scarcity": {r.value: v for r, v in a.perceived_scarcity.items()},
        "unmet_need": {r.value: v for r, v in a.unmet_need.items()},
        "bonus_earned": a.bonus_earned,
        "daily_stamina": getattr(a, "daily_stamina", None),
    }


def dec_agent(a, d: dict) -> None:
    a.money = d["money"]
    a.stamina = d["stamina"]
    a.holdings = {Resource(r): deque([lid, q] for lid, q in items)
                  for r, items in d["holdings"].items()}
    for r in Resource:                    # keep every resource slot present
        a.holdings.setdefault(r, deque())
    a.skill = {Resource(r): v for r, v in d["skill"].items()}
    a.tool_durability_left = d["tool_durability_left"]
    a.assets = [Asset(kind, lid, bt, lvl) for kind, lid, bt, lvl in d["assets"]]
    a.perceived_scarcity = {Resource(r): v for r, v in d["perceived_scarcity"].items()}
    a.unmet_need = {Resource(r): v for r, v in d["unmet_need"].items()}
    a.bonus_earned = d["bonus_earned"]
    if d.get("daily_stamina") is not None:
        a.daily_stamina = d["daily_stamina"]


# ------------------------------------------------------------------- knowledge
def enc_prop(prop) -> dict:
    return {
        "transmissions_today": prop.transmissions_today,
        "adj": {aid: sorted(ns) for aid, ns in prop.graph.adj.items()},
        "beliefs": {
            aid: {r.value: [b.value, b.confidence, sorted(b.roots), b.last_heard, b.generation]
                  for r, b in by.items()}
            for aid, by in prop.beliefs.items()
        },
    }


def dec_prop(prop, d: dict) -> None:
    prop.transmissions_today = d["transmissions_today"]
    prop.graph.adj = {aid: set(ns) for aid, ns in d["adj"].items()}
    prop.beliefs = {}
    for aid, by in d["beliefs"].items():
        prop.beliefs[aid] = {
            Resource(r): Belief(val, conf, set(roots), lh, gen)
            for r, (val, conf, roots, lh, gen) in by.items()
        }


# ----------------------------------------------------------------------- rng
def enc_rng(rng) -> list:
    version, internal, gauss = rng.getstate()
    return [version, list(internal), gauss]


def dec_rng(rng, data: list) -> None:
    version, internal, gauss = data
    rng.setstate((version, tuple(internal), gauss))


# ================================================================= top level
def serialize_core(core) -> dict:
    """Capture a SimCore as a JSON-safe dict (call at a day boundary)."""
    w = core.world
    blob = {
        "save_format_version": SAVE_FORMAT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "config": enc_config(core.cfg),
        "population": enc_population(getattr(core, "_population", None)),
        "propagation": w.prop is not None,
        "core": {
            "day": core._day,
            "total": core._total,
            "prev_bonus": dict(core._prev_bonus),
            "prev_penalty": core._prev_penalty,
        },
        "world": {
            "day": w.day,
            "ref_price": _res_keyed(w.ref_price),
            "rng": enc_rng(w.rng),
            "tool_lot_of": dict(w.tool_lot_of),
            "rumour_avg": _res_keyed(w.rumour_avg),
            "active_ids": sorted(w._active_ids),
            "player_money_at_day_start": w._player_money_at_day_start,
            "player_bonus_at_day_start": w._player_bonus_at_day_start,
            "scheduled_injections": {
                str(day): [[t, _enc_claim(c), auth, byp] for (t, c, auth, byp) in items]
                for day, items in w.scheduled_injections.items()
            },
            "info_acts": [[day, _enc_claim(c)] for day, c in w.info_acts],
            # within-day results snapshot() exposes, so a loaded screen shows the
            # same numbers as the saved one (they're recomputed on the next step).
            "village_unmet": _res_keyed(getattr(w, "village_unmet", dict(_ZERO))),
            "day_unmet": _res_keyed(getattr(w, "day_unmet", dict(_ZERO))),
            "day_short_agents": getattr(w, "day_short_agents", 0),
            "per_agent_unmet": {aid: _res_keyed(um)
                                for aid, um in getattr(w, "_per_agent_unmet", {}).items()},
            "last_clearings": {
                r.value: ([w.last_clearings[r].price, w.last_clearings[r].volume]
                          if w.last_clearings.get(r) else None)
                for r in Resource
            },
        },
        "lineage": enc_lineage(w.lineage),
        "accountant": enc_accountant(w.accountant),
        "agents": {a.id: enc_agent(a) for a in w.agents},
        "metrics": {"days": list(w.metrics.days), "series": {k: list(v) for k, v in w.metrics.series.items()}},
    }
    if w.prop is not None:
        blob["prop"] = enc_prop(w.prop)
        blob["world"]["prop_rng"] = enc_rng(w.prop_rng)
    return blob


def deserialize_core(core, data: dict) -> None:
    """Rebuild `core` in place from a save dict (mutates core)."""
    save_major = str(data.get("contract_version", "0")).split(".")[0]
    run_major = CONTRACT_VERSION.split(".")[0]
    if save_major != run_major:
        raise ValueError(
            f"incompatible save: contract v{data.get('contract_version')} "
            f"vs running v{CONTRACT_VERSION} (major differs)")

    # --- rebuild the world shell exactly as it was first constructed ---
    from simcore import ContractStrategy
    cfg = dec_config(data["config"])
    cfg.propagation_enabled = bool(data["propagation"])
    population = dec_population(data["population"])
    core.cfg = cfg
    core._population = population
    core._propagation = cfg.propagation_enabled
    core._strategy = ContractStrategy()
    core.world = World(cfg, player_strategy=core._strategy, population=population)
    w = core.world

    # --- overlay dynamic state back onto that shell ---
    wd = data["world"]
    w.day = wd["day"]
    w.ref_price = _res_unkey(wd["ref_price"])
    dec_rng(w.rng, wd["rng"])
    w.tool_lot_of = dict(wd["tool_lot_of"])
    w.rumour_avg = _res_unkey(wd["rumour_avg"])
    w._active_ids = set(wd["active_ids"])
    w._player_money_at_day_start = wd["player_money_at_day_start"]
    w._player_bonus_at_day_start = wd["player_bonus_at_day_start"]
    w.scheduled_injections = {
        int(day): [(t, _dec_claim(c), auth, byp) for (t, c, auth, byp) in items]
        for day, items in wd["scheduled_injections"].items()
    }
    w.info_acts = [(day, _dec_claim(c)) for day, c in wd["info_acts"]]
    w.village_unmet = _res_unkey(wd.get("village_unmet", _res_keyed(_ZERO)))
    w.day_unmet = _res_unkey(wd.get("day_unmet", _res_keyed(_ZERO)))
    w.day_short_agents = wd.get("day_short_agents", 0)
    w._per_agent_unmet = {aid: _res_unkey(um)
                          for aid, um in wd.get("per_agent_unmet", {}).items()}
    w.last_clearings = {}
    for r in Resource:
        v = wd.get("last_clearings", {}).get(r.value)
        w.last_clearings[r] = Clearing(r, v[0], v[1], []) if v else None

    dec_lineage(w.lineage, data["lineage"])
    dec_accountant(w.accountant, data["accountant"])
    for a in w.agents:
        ad = data["agents"].get(a.id)
        if ad is not None:
            dec_agent(a, ad)

    if w.prop is not None and "prop" in data:
        dec_rng(w.prop_rng, data["world"]["prop_rng"])
        dec_prop(w.prop, data["prop"])

    m = data["metrics"]
    w.metrics.days = list(m["days"])
    w.metrics.series = {k: list(v) for k, v in m["series"].items()}

    # --- restore the facade's own counters; land on a clean day boundary ---
    c = data["core"]
    core._day = c["day"]
    core._total = c["total"]
    core._prev_bonus = dict(c["prev_bonus"])
    core._prev_penalty = c["prev_penalty"]
    core._in_turn = False
    core._events = []
