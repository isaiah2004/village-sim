"""
Reputation = DEEDS PROPAGATED (DESIGN.md's Layer-3 reputation model).

Standing used to be read straight off an agent's realized contribution. That is
the deterministic first cut; the full model is that a player's notable DEEDS
become facts that travel the SAME social graph as scarcity rumours -- with delay,
per-hop fidelity loss, and echo caps -- and it is that PROPAGATED standing (how
far word of you has actually reached) that gates interventions and a merchant's
yes/no. A newcomer who did a great deed nobody has heard of yet is still unproven;
as word spreads, doors open.

This reuses the knowledge-propagation engine unchanged, keyed by the SUBJECT
agent's id instead of a resource: injecting a deed at the doer's own node and
letting it spread. It runs on its OWN rng, so it never perturbs the economic
propagation stream -- the scarcity golden stays byte-identical. It moves only
belief; it never touches world truth (an agent's actual `bonus_earned` is real,
the reputation just says how widely it is known).

`standing = bonus_earned * reach`, where reach in [0,1] is the fraction of the
village that has heard of the agent's deeds. With reputation propagation OFF there
is no network and callers fall back to raw `bonus_earned` (reach == 1), so every
existing scenario is unchanged.
"""
from __future__ import annotations

from config import Config
from knowledge import Claim, PropagationEngine, SocialGraph


class ReputationNetwork:
    """Spreads deed-facts about agents across the social graph and reports how far
    word of each agent has reached. A thin wrapper over PropagationEngine keyed by
    subject-agent-id, with its own rng."""

    def __init__(self, cfg: Config, graph: SocialGraph, rng):
        self.cfg = cfg
        self.engine = PropagationEngine(cfg, graph, rng)

    def record_deed(self, agent_id: str, cumulative_contribution: float, day: int) -> None:
        """Refresh the agent's own first-hand deed fact (root = the agent, since a
        deed has one true origin). Magnitude is the contribution normalized against
        `reputation_deed_scale`, so a bigger benefactor is a stronger story."""
        if cumulative_contribution <= 1e-9:
            return
        magnitude = min(1.0, cumulative_contribution / max(self.cfg.reputation_deed_scale, 1e-6))
        claim = Claim(resource=agent_id, magnitude=magnitude,
                      objective_truth=True, root_id=agent_id, origin_day=day)
        self.engine.inject(agent_id, claim, authority=1.0, day=day)

    def record_default(self, agent_id: str, day: int) -> None:
        """Word of a loan DEFAULT -- a bad deed. It spreads the same way as good
        deeds (its own subject key `default:<id>`) and discounts the defaulter's
        standing via `disrepute` below (DESIGN.md's 'a reputation hit that
        propagates'). Originates at the defaulter's node, magnitude 1.0."""
        key = f"default:{agent_id}"
        claim = Claim(resource=key, magnitude=1.0, objective_truth=True,
                      root_id=key, origin_day=day)
        self.engine.inject(agent_id, claim, authority=1.0, day=day)

    def step(self, day: int, active_ids: set) -> None:
        self.engine.step(day, active_ids)

    def decay(self) -> None:
        self.engine.decay()

    def reach(self, agent_id: str, active_ids) -> float:
        """Fraction of OTHER active agents who have heard of this agent's deeds."""
        return self._heard_fraction(agent_id, agent_id, active_ids)

    def disrepute(self, agent_id: str, active_ids) -> float:
        """Fraction of OTHER active agents who have heard this agent DEFAULTED.
        Zero unless a default was recorded; rises as word of it spreads."""
        return self._heard_fraction(f"default:{agent_id}", agent_id, active_ids)

    def _heard_fraction(self, subject: str, exclude_id: str, active_ids) -> float:
        others = [a for a in active_ids if a != exclude_id]
        if not others:
            return 0.0
        thr = self.cfg.reputation_aware_threshold
        heard = sum(1 for h in others if self.engine.scarcity(h, subject) >= thr)
        return heard / len(others)
