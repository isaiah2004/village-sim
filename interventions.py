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
# code: this is the ONLY place an intervention touches world-state.
def _effect_found_mill(world, agent, day: int) -> None:
    """Establish an income-generating mill -- a woodlot capital asset financed by
    CAPITAL rather than the founder's own labour and wood. It reuses the existing
    capital-goods machinery: `world._run_woodlots` yields wood from it every day,
    which lowers the capital-gap and wood-scarcity problems, and realized-effect
    credit flows back to the founder through the asset's lineage lot. An existing
    mill is upgraded a level instead (a bigger works)."""
    from agents import Asset
    wl = next((a for a in agent.assets if a.kind == "woodlot"), None)
    if wl is not None:
        if wl.level < world.cfg.woodlot_max_level:
            wl.level += 1
        return
    lot = world.lineage.new_lot(Resource.WOODLOT, agent.id, day, "build", 1.0, parents=[])
    agent.assets.append(Asset(kind="woodlot", lot_id=lot.id, built_tick=day, level=1))


EFFECTS = {
    "found_mill": _effect_found_mill,
}


def build_library(cfg: Config) -> list[Intervention]:
    """The pre-authored action library, as DATA. Grows by adding rows here (and one
    effect per genuinely new world-change). The first rung: found a mill, gated by
    capital AND a track record of contribution -- the deed-then-bigger-deed ladder."""
    return [
        Intervention(
            key="found_mill",
            title="Found a mill (income-generating infrastructure)",
            targets="capital_gap:wood",
            capital_cost=80.0,
            min_standing=40.0,
            requires=("capital_goods_enabled",),
        ),
    ]


# ------------------------------------------------------------ standing / gate
def standing(agent) -> float:
    """Reputation proxy: realized contribution to date -- your track record of
    deeds. DESIGN.md's full model is deeds propagated through knowledge.py; this is
    the deterministic first cut that plugs into the same precondition slot."""
    return round(getattr(agent, "bonus_earned", 0.0), 6)


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
    have = standing(agent)
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
