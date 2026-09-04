"""
Knowledge Propagation (Stage 3).

The economy already models belief -> behaviour -> world (a villager's
`perceived_scarcity` inflates their reservation price and reserve target, which
moves the market). What it LACKED was a believable *source* for that belief:
today the "witness" signal is a village-wide unmet aggregate -- an oracle every
villager reads instantly and perfectly.

This module replaces that oracle with INFORMATION THAT HAS TO TRAVEL. A scarcity
claim is injected into one agent and spreads across a social graph with:

  * delay          -- it reaches distant villagers days later (or never),
  * fidelity loss   -- confidence attenuates per hop; magnitude drifts (rumours
                       grow scarier in the retelling),
  * echo caps       -- 100 people repeating ONE source is not 100 witnesses;
                       confidence only climbs freely when INDEPENDENT roots agree,
  * objective/belief split -- the world knows the truth; villagers hold beliefs.
                       A FALSE claim can still spread and change behaviour, and
                       that behaviour can make the false claim come true.

Design contract (mirrors the AIC and the LLM wall):
  * This layer is DETERMINISTIC simulation. No LLM is in the loop. It runs for
    every agent every tick, cheaply. (An LLM, later, only renders a villager's
    held belief into words when the player talks to them -- never here.)
  * It never touches objective world state. It moves BELIEFS. Reality is changed
    only downstream, through the ordinary economic behaviour those beliefs drive.

A per-agent belief is a tiny fixed record -- value, confidence, and the SET OF
ROOTS it has independently heard from (not a lineage tree). Echo-vs-corroboration
is decided by counting distinct roots, which keeps per-agent state O(1) and the
whole thing scalable to thousands of agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import Config, Resource


@dataclass
class Claim:
    """A proposition about the scarcity of a resource, as it enters the world."""
    resource: Resource
    magnitude: float          # claimed severity of the shortage, 0..1
    objective_truth: bool     # is it actually true in the sim? (the world knows; NPCs don't)
    root_id: str              # identity of the ORIGINATING source/event (for echo detection)
    origin_day: int


@dataclass
class Belief:
    """One agent's held belief about one resource's scarcity."""
    value: float = 0.0                     # believed magnitude, 0..1
    confidence: float = 0.0                # 0..1
    roots: set = field(default_factory=set)  # distinct origin ids heard from
    last_heard: int = -1
    generation: int = 0                    # hops from the source (0 = original witness)

    def pressure(self) -> float:
        """How strongly this belief demands retelling / drives behaviour."""
        return self.value * self.confidence


class SocialGraph:
    """
    Who can talk to whom. Undirected adjacency keyed by agent id.

    Built once: each villager gets ~`social_degree` random acquaintances; hub
    agents (the market maker = the tavern/trading post) additionally connect to
    many villagers, so information flows through them fast -- a hub's importance
    comes from its NETWORK POSITION, not any special intelligence.
    """
    def __init__(self, cfg: Config, agent_ids: list[str], hub_ids: list[str], rng):
        self.adj: dict[str, set] = {aid: set() for aid in agent_ids}
        ordinary = [a for a in agent_ids if a not in hub_ids]
        # sparse random mesh among ordinary agents
        for aid in ordinary:
            others = [o for o in ordinary if o != aid]
            rng.shuffle(others)
            for o in others[:cfg.social_degree]:
                self._link(aid, o)
        # hubs reach broadly
        for hid in hub_ids:
            targets = [o for o in ordinary]
            rng.shuffle(targets)
            for o in targets[:cfg.hub_degree]:
                self._link(hid, o)

    def _link(self, a: str, b: str) -> None:
        if a in self.adj and b in self.adj:
            self.adj[a].add(b)
            self.adj[b].add(a)

    def neighbours(self, aid: str) -> list[str]:
        # sorted for determinism: set iteration order varies per process, which
        # would make even a seeded shuffle non-reproducible.
        return sorted(self.adj.get(aid, ()))


class PropagationEngine:
    """
    Holds every agent's beliefs and moves information across the social graph.

    beliefs[agent_id][resource] -> Belief
    """
    def __init__(self, cfg: Config, graph: SocialGraph, rng):
        self.cfg = cfg
        self.graph = graph
        self.rng = rng
        self.beliefs: dict[str, dict] = {}
        self.transmissions_today = 0   # for observability / demo narration

    # ---------- belief access ----------
    def belief(self, aid: str, r: Resource) -> Belief:
        return self.beliefs.setdefault(aid, {}).get(r, Belief())

    def scarcity(self, aid: str, r: Resource) -> float:
        """The scarcity pressure this agent currently believes -> feeds fear."""
        b = self.beliefs.get(aid, {}).get(r)
        return b.pressure() if b else 0.0

    # ---------- injection ----------
    def inject(self, aid: str, claim: Claim, authority: float = 1.0, day: int = 0) -> None:
        """
        Seed a claim directly into one agent (an event they witnessed, or a
        source -- the King, refugees, or the PLAYER -- telling them). The origin
        agent becomes a confident first-hand holder.
        """
        b = self.beliefs.setdefault(aid, {}).setdefault(claim.resource, Belief())
        self._absorb(b, claim.magnitude, authority, claim.root_id, day, generation=0)

    # ---------- the belief-update rule (the keystone) ----------
    def _absorb(self, b: Belief, in_value: float, in_conf: float,
                root: str, day: int, generation: int) -> None:
        """
        Update belief `b` from an incoming claim.

          gain moves confidence UP toward certainty, weighted by how much of the
          claim's credibility is new. A NEW independent root corroborates fully;
          a REPEAT of an already-heard root barely moves the needle (echo cap) --
          this is what stops popularity from masquerading as truth.

          value is pulled toward the claim in proportion to that same gain.

        Objective truth is NEVER referenced here. This only shapes belief.
        """
        new_root = root not in b.roots
        corrob = self.cfg.corroboration_factor if new_root else self.cfg.echo_factor
        gain = in_conf * corrob * (1.0 - b.confidence)
        if gain <= 1e-9 and not new_root:
            b.roots.add(root)
            return
        b.confidence = min(1.0, b.confidence + gain)
        b.value = max(0.0, min(1.0, b.value + gain * (in_value - b.value)))
        b.roots.add(root)
        b.last_heard = day
        b.generation = generation if b.generation == 0 else min(b.generation, generation)

    # ---------- daily propagation ----------
    def step(self, day: int, active_ids: set) -> None:
        """
        One tick of gossip. Every agent holding a belief above the retelling
        threshold spends a transmission budget on random neighbours. Higher-
        pressure beliefs are told first (information prioritisation), so urgent
        news out-competes small talk for scarce communication opportunities.
        """
        self.transmissions_today = 0
        # snapshot senders first so within-day spread doesn't cascade instantly
        senders = []
        for aid, by_res in self.beliefs.items():
            if aid not in active_ids:
                continue
            for r, b in by_res.items():
                if b.pressure() >= self.cfg.transmit_threshold:
                    senders.append((b.pressure(), aid, r, b))
        senders.sort(reverse=True, key=lambda t: t[0])

        pending: list[tuple[str, Resource, float, float, str, int]] = []
        for _p, aid, r, b in senders:
            neigh = [n for n in self.graph.neighbours(aid) if n in active_ids]
            if not neigh:
                continue
            self.rng.shuffle(neigh)
            for target in neigh[:self.cfg.transmit_budget]:
                # fidelity loss on the wire: confidence attenuates by the channel
                # only (source credibility was already discounted at injection),
                # and the claimed magnitude drifts UP a touch (fear grows in the
                # retelling). Because a repeat of the SAME root is echo-capped at
                # the receiver, a single rumour saturates at "plausible", while
                # many INDEPENDENT roots (real witnesses) climb toward certainty.
                out_conf = b.confidence * self.cfg.channel_fidelity
                out_value = min(1.0, b.value + self.cfg.rumour_exaggeration)
                # pick a deterministic root to carry (min); set order varies per process
                carried = min(b.roots) if b.roots else aid
                pending.append((target, r, out_value, out_conf,
                                carried, b.generation + 1))
                self.transmissions_today += 1

        for target, r, v, c, root, gen in pending:
            tb = self.beliefs.setdefault(target, {}).setdefault(r, Belief())
            self._absorb(tb, v, c, root, day, gen)

    # ---------- decay ----------
    def decay(self) -> None:
        """Stale information loses grip: confidence bleeds off unless refreshed."""
        d = self.cfg.fear_decay
        for by_res in self.beliefs.values():
            for b in by_res.values():
                b.confidence = max(0.0, b.confidence - d)

    # ---------- observability ----------
    def aware_fraction(self, r: Resource, active_ids: set, thresh: float = 0.05) -> float:
        """Fraction of active agents who now hold any real belief about r."""
        if not active_ids:
            return 0.0
        n = sum(1 for aid in active_ids if self.scarcity(aid, r) >= thresh)
        return n / len(active_ids)

    def avg_scarcity(self, r: Resource, active_ids: set) -> float:
        if not active_ids:
            return 0.0
        return sum(self.scarcity(aid, r) for aid in active_ids) / len(active_ids)

    def distinct_roots(self, r: Resource, active_ids: set) -> int:
        roots = set()
        for aid in active_ids:
            b = self.beliefs.get(aid, {}).get(r)
            if b:
                roots |= b.roots
        return len(roots)
