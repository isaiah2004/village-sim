"""
Layer 1 -- the world-state Problem model (DESIGN.md's frontier).

DESIGN.md: the world produces PROBLEMS; the index (Layer 2) prices whoever
resolves them; interventions (Layer 3) target them. This module is Layer 1's
first piece: a general, data-defined notion of a problem so "what was the
problem?" (question 2 of the four) is a first-class, queryable thing rather than
a hardcoded wood/winter special case.

A Problem is DATA: a stable identity, a TYPE (kind), a LOCATION, and a subject the
type's evaluator reads. Its SEVERITY (0..1) is not stored on the problem -- it is
READ from live world-state each day, so the simulation tracks and updates it as
the world moves. Severity is the seam Layer 2 already knows how to price and Layer
3 will target.

Two authored TYPES ship here to prove the model holds more than one shape of
problem: "scarcity" (a consumption good is short -- reuses the index's own scarcity
signal) and "capital_gap" (the village lacks income-generating infrastructure --
a non-consumption problem, the "missing mill" from DESIGN.md's worked example).
Adding a located INSTANCE is a row of data; adding a new TYPE is one evaluator.
This module reads world-state and mutates nothing -- it is observation, so it
never perturbs the validated economy.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import Config, Resource
from needs import build_registry


@dataclass(frozen=True)
class Problem:
    """One registered problem, as pure data.

    key      -- stable identity, e.g. "scarcity:wood", "capital_gap:wood".
    kind     -- the TYPE; selects the severity evaluator (authored, small set).
    location -- WHERE it is; "village" for now (Stage-2 knowledge adds regions).
    subject  -- what it concerns (e.g. a resource value); data the evaluator reads.
    """
    key: str
    kind: str
    location: str
    subject: str


@dataclass
class ProblemState:
    """A problem plus its current severity, updated from world-state each day."""
    problem: Problem
    severity: float = 0.0            # 0..1; 0 = resolved / absent, 1 = worst


# --- severity evaluators: one per TYPE (authored); instances above are pure data.
# Each reads world-state and returns a 0..1 severity. Pure reads -- no mutation.
def _severity_scarcity(world, subject: str) -> float:
    """A consumption good is short. Reuse the index's OWN scarcity signal (the
    accountant's forecast ratio) so the problem's severity is exactly what Layer 2
    already prices -- no second definition of 'how bad is it'."""
    return max(0.0, min(1.0, world.accountant.state.scarcity.get(subject, 0.0)))


def _severity_capital_gap(world, subject: str) -> float:
    """The village leans on hand-labour because it lacks income-generating
    infrastructure. Severity = the share of daily demand for `subject` NOT covered
    by owned capital that outputs it. 1 = no capital at all; 0 = capital alone
    could meet demand. A non-consumption problem -- the 'missing mill' shape.
    Demand and capital come from scenario DATA, so it works for any world."""
    day = world.day
    consumers = [a for a in world.agents if not a.is_market_maker]
    rspec = next((x for x in world.scenario.resources if x.id == subject), None)
    per = (rspec.base_consume if rspec else 0.0) * world.driver.consume_mult(day, subject)
    demand = len(consumers) * per
    if demand <= 1e-9:
        return 0.0
    out_per_level = next((c.output_per_level for c in getattr(world.scenario, "capital", ())
                          if c.output_resource == subject), 0.0)
    kinds = {c.kind for c in getattr(world.scenario, "capital", ()) if c.output_resource == subject}
    capacity = sum(out_per_level * asset.level
                   for a in world.agents for asset in getattr(a, "assets", [])
                   if asset.kind in kinds)
    return max(0.0, min(1.0, 1.0 - capacity / demand))


EVALUATORS = {
    "scarcity": _severity_scarcity,
    "capital_gap": _severity_capital_gap,
}


def default_problems(cfg: Config) -> list[Problem]:
    """The world's problem board as DATA: a scarcity problem per registered need
    (typed, located in the village), plus the village's capital-infrastructure gap.
    Adding a located problem is a row here; adding a new TYPE is one evaluator."""
    def _rid(r):
        return r.value if hasattr(r, "value") else r
    board = [Problem(f"scarcity:{_rid(need.resource)}", "scarcity", "village", _rid(need.resource))
             for need in build_registry(cfg)]
    # a capital-gap problem per capital good's output (frostpine: capital_gap:wood)
    for capspec in getattr(getattr(cfg, "scenario", None), "capital", ()):
        board.append(Problem(f"capital_gap:{capspec.output_resource}", "capital_gap",
                             "village", capspec.output_resource))
    if not getattr(cfg, "scenario", None):
        board.append(Problem("capital_gap:wood", "capital_gap", "village", "wood"))
    return board


def build_board(cfg: Config) -> list[ProblemState]:
    return [ProblemState(p) for p in default_problems(cfg)]


def refresh(board: list[ProblemState], world) -> None:
    """Update every problem's severity from current world-state -- the simulation
    tracking and updating its problems. Pure read; changes no sim quantity, so it
    is safe to run always-on without perturbing the validated economy."""
    for ps in board:
        ps.severity = round(EVALUATORS[ps.problem.kind](world, ps.problem.subject), 6)
