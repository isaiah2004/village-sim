"""
Layer 3 -- the intervention library (DESIGN.md's "the real game", first piece).

How the player CHANGES the world: a curated library of pre-authored actions, each
gated by preconditions (capital, standing, enabling knowledge) and applying an
authored EFFECT to world-state. DESIGN.md's loop:

    change the world (here) -> the index prices it (Layer 2) -> the deed spreads as
    reputation (knowledge.py) -> reputation gates the next, bigger intervention.

This module is the load-bearing, deterministic spine of that loop. Two seams are
left explicit for later, per DESIGN.md's non-negotiables:

  * REPUTATION. `standing()` is a deterministic first cut -- realized contribution
    to date, i.e. your track record of deeds. The full model (deeds propagated
    through knowledge.py) plugs into the same precondition slot without changing
    callers.
  * NEGOTIATION. `evaluate()` is the deterministic "merchant" -- can you acquire
    the means and is it worth doing? An LLM merchant can later replace THIS
    function at the edge: propose terms, judge standing, answer yes/no -- while the
    sim still validates and applies. The LLM never mutates world-state or holds sim
    truth; the authored effect below is the only thing that changes the world.

Adding an intervention is data (a row in `build_library`) plus, if its world-change
is new, one authored effect. No per-intervention logic leaks into the sim's phases.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import Config, Resource


@dataclass(frozen=True)
class Intervention:
    """One pre-authored world-change, as data.

    key          -- stable identity, e.g. "found_mill".
    title        -- human-facing name for a body's action menu.
    targets      -- the problem key it addresses (Layer 1), e.g. "capital_gap:wood".
    capital_cost -- money required to acquire the means (the loan / capital outlay).
    min_standing -- reputation/standing required (your track record of deeds).
    requires     -- cfg flags that must be True (authored enabling knowledge, e.g.
                    the capital-goods system that runs the built asset).
    """
    key: str
    title: str
    targets: str
    capital_cost: float
    min_standing: float = 0.0
    requires: tuple = ()


# ------------------------------------------------------------------ effects
# Authored, deterministic world-changes keyed by intervention. Load-bearing sim
# code: this is the ONLY place an intervention touches world-state. Each effect is
# generic (it acts on the scenario's crisis good / capital good, never a literal
# resource) and is scored by the index: the goods it produces or injects are rooted
# in the founder's lineage, so realized-effect credit flows to them as those goods
# meet needs, and the world-state change lowers the Layer-1 problem it targets.
def _primary(world) -> str:
    return world.scenario.primary_resource


def _effect_found_mill(world, agent, day: int) -> None:
    """Establish/upgrade the scenario's CAPITAL good (frostpine's woodlot,
    emberforge's forge), financed by capital rather than the founder's labour. Its
    daily output is rooted at the asset lot, so credit flows to the founder."""
    from agents import Asset
    spec = world._capital_spec()
    if spec is None:
        return
    wl = next((a for a in agent.assets if a.kind == spec.kind), None)
    if wl is not None:
        if wl.level < spec.max_level:
            wl.level += 1
        return
    lot = world.lineage.new_lot(spec.kind, agent.id, day, "build", 1.0, parents=[])
    agent.assets.append(Asset(kind=spec.kind, lot_id=lot.id, built_tick=day, level=1))


def _effect_haul_relief(world, agent, day: int) -> None:
    """Haul in a one-time RELIEF SHIPMENT of the crisis good, rooted at the founder,
    into their own stock -- immediate supply they then sell/distribute, credited by
    the index as it meets needs. The early, cheap rung of the ladder."""
    r = _primary(world)
    qty = world.cfg.relief_shipment_qty
    lot = world.lineage.new_lot(r, agent.id, day, "haul", qty, parents=[])
    agent.add_holding(lot.id, r, qty)


def _effect_open_trade_route(world, agent, day: int) -> None:
    """Open a TRADE ROUTE: a persistent asset importing the crisis good every day,
    rooted at the founder. It carries its own producer spec, so the world runs it
    generically in the capital phase -- no scenario.capital entry needed. Upgrades
    an existing route a level."""
    from agents import Asset
    r = _primary(world)
    tr = next((a for a in agent.assets if a.kind == "trade_route"), None)
    if tr is not None:
        tr.level += 1
        return
    lot = world.lineage.new_lot("trade_route", agent.id, day, "build", 1.0, parents=[])
    agent.assets.append(Asset(kind="trade_route", lot_id=lot.id, built_tick=day, level=1,
                              output_resource=r, output_per_level=world.cfg.trade_route_output))


def _effect_hire_crew(world, agent, day: int) -> None:
    """Hire a CREW: a permanent boost to the founder's own output of the crisis
    good (they gather more each day; those lots root at them, so the index credits
    the extra supply). Labour, not infrastructure."""
    r = _primary(world)
    if r in agent.skill:
        agent.skill[r] *= world.cfg.crew_skill_mult


def _effect_endow_granary(world, agent, day: int) -> None:
    """Endow a communal GRANARY: a buffer of the crisis good placed with the market
    maker (rooted at the founder), so the town can buy through a spike; credited as
    villagers draw it down to meet needs."""
    r = _primary(world)
    mk = next((a for a in world.agents if a.is_market_maker), None)
    if mk is None:
        return
    qty = world.cfg.granary_qty
    lot = world.lineage.new_lot(r, agent.id, day, "granary", qty, parents=[])
    mk.add_holding(lot.id, r, qty)


EFFECTS = {
    "found_mill": _effect_found_mill,
    "haul_relief": _effect_haul_relief,
    "open_trade_route": _effect_open_trade_route,
    "hire_crew": _effect_hire_crew,
    "endow_granary": _effect_endow_granary,
}


def build_library(cfg: Config) -> list[Intervention]:
    """The pre-authored action library, as DATA -- a representative ladder of ways
    to change the world, each gated by capital AND a track record (min_standing) and
    each scored by the index. Rungs (rising standing): a cheap emergency shipment; a
    permanent labour boost; founding the scenario's capital good; a communal granary;
    a persistent trade route. All target the scenario's OWN crisis/capital problem,
    so a new world inherits the whole library with no new code."""
    sc = getattr(cfg, "scenario", None)
    prim = sc.primary_resource if sc else "wood"
    out_res = sc.capital[0].output_resource if (sc and sc.capital) else prim
    return [
        # emergency one-shot supply -- the early rung, low standing, no capital system needed
        Intervention("haul_relief", "Haul a relief shipment to the shortage",
                     targets=f"scarcity:{prim}", capital_cost=30.0, min_standing=15.0),
        # capital infrastructure -- founds/upgrades the scenario's capital good
        Intervention("found_mill", "Found a mill (income-generating infrastructure)",
                     targets=f"capital_gap:{out_res}", capital_cost=80.0, min_standing=40.0,
                     requires=("capital_goods_enabled",)),
        # labour -- a permanent boost to your own output of the crisis good
        Intervention("hire_crew", "Hire a crew (boost your own output)",
                     targets=f"scarcity:{prim}", capital_cost=60.0, min_standing=60.0),
        # a communal buffer with the market -- eases a price spike for everyone
        Intervention("endow_granary", "Endow a communal granary (a market buffer)",
                     targets=f"scarcity:{prim}", capital_cost=120.0, min_standing=90.0),
        # a persistent import channel -- the big infrastructure rung
        Intervention("open_trade_route", "Open a trade route (persistent imports)",
                     targets=f"scarcity:{prim}", capital_cost=150.0, min_standing=120.0,
                     requires=("capital_goods_enabled",)),
    ]


# ------------------------------------------------------------ standing / gate
def standing(agent, world=None) -> float:
    """Reputation that gates interventions and merchant deals: your track record of
    deeds, AS KNOWN. Base is realized contribution to date. When reputation
    propagation is on (DESIGN.md's full model, reputation.py), it is scaled by how
    far word of your deeds has actually reached the village -- a benefactor nobody
    has heard of is still unproven. With propagation off there is no network and
    reach is 1, so this is exactly the raw-contribution first cut (golden-safe)."""
    base = round(getattr(agent, "bonus_earned", 0.0), 6)
    rep = getattr(world, "reputation", None) if world is not None else None
    if rep is None or agent is None:
        return base
    reach = rep.reach(agent.id, world._active_ids)
    return round(base * reach, 6)


def _target_severity(world, problem_key: str) -> float:
    ps = next((p for p in getattr(world, "problems", []) if p.problem.key == problem_key), None)
    return ps.severity if ps else 0.0


def evaluate(world, agent, iv: Intervention, extra_capital: float = 0.0) -> tuple[bool, str]:
    """Deterministic 'can the player acquire the means, and is it worth doing?' --
    the stand-in for the merchant's yes/no. Returns (accepted, reason). An LLM
    merchant can later replace this at the edge; the sim still validates here.
    `extra_capital` lets a loan-financed deal (AcceptDeal) satisfy the capital
    precondition with borrowed money rather than the agent's own cash."""
    if not world.cfg.interventions_enabled:
        return False, "interventions disabled"
    for flag in iv.requires:
        if not getattr(world.cfg, flag, False):
            return False, f"requires {flag}"
    if _target_severity(world, iv.targets) <= 1e-6:
        return False, "no such problem to solve"          # only a real problem pays
    have = standing(agent, world)
    if have < iv.min_standing:
        return False, f"needs standing {iv.min_standing:.0f} (have {have:.0f})"
    if agent.money + extra_capital < iv.capital_cost:
        return False, f"needs capital {iv.capital_cost:.0f} (have {agent.money + extra_capital:.0f})"
    return True, ""


def perform(world, agent, iv: Intervention, day: int) -> tuple[bool, float, str]:
    """Check preconditions and, if met, spend the capital and apply the authored
    effect. Returns (accepted, capital_spent, reason). Deterministic."""
    ok, reason = evaluate(world, agent, iv)
    if not ok:
        return False, 0.0, reason
    agent.money -= iv.capital_cost
    EFFECTS[iv.key](world, agent, day)
    return True, iv.capital_cost, ""
