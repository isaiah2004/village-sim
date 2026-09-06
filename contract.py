"""
The SimCore contract (Phase 1) -- the engine-agnostic interface every "body"
speaks: the 2D fun-test now, Unreal later. Nothing here imports a game engine or
a renderer; these are plain data.

Three families:
  * INTENTS   -- the ONLY way an external controller (the player, or any
                 game-driven agent) affects the world. Submitted, then applied on
                 the next step. NPCs are simulated internally and need no intents.
  * EVENTS    -- what happened during a step, for the presentation layer to react
                 to (a trade cleared, a belief shifted, a shortage bit).
  * SNAPSHOT  -- a read-only view of world state for rendering.

FROZEN -- v1 (2026-09-05). This schema is the Phase-1 foundation. Any change to a
field's name, type, or meaning is a BREAKING change: bump CONTRACT_VERSION and add
a migration note, don't edit silently. Additive-only changes (a new optional field
with a default, a wholly new Event type) keep the minor line compatible. The
conformance test (test_contract.py) fails if the sim or a body drifts from this.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

# Resource is part of the contract's vocabulary; re-exported so bodies import it
# from here, not from the engine internals.
from config import Resource, Season

# Wire/schema version. Major = breaking (fields moved/renamed/retyped); minor =
# additive-only. A serialized snapshot or save file should carry this so a loader
# can refuse or migrate an incompatible one.
#   1.0 (2026-09-05) frozen baseline.
#   1.1 (2026-09-05) additive: ContributionDetail event (the felt "why" behind a
#       ContributionPaid). Minor bump -- older bodies ignore the new type safely.
#   1.2 (2026-09-06) additive: ProblemView + Snapshot.problems -- Layer 1's
#       world-state problem board (typed, located, severity), read-only. Minor
#       bump; the field defaults to [] so older bodies are unaffected.
CONTRACT_VERSION = "1.2"

__all__ = [
    "CONTRACT_VERSION", "Resource", "Season",
    "Gather", "CraftTool", "BuildWoodlot", "Trade", "Speak", "Intent", "INTENT_TYPES",
    "DayAdvanced", "Produced", "TradeCleared", "Settled", "ContributionPaid",
    "ContributionDetail", "Shortage", "HoardFlagged", "HoldingFee", "AssetBuilt",
    "BeliefState", "Event", "EVENT_TYPES",
    "AgentView", "MarketView", "ProblemView", "Snapshot",
]


# ======================================================================
# INTENTS  (external control -> the world)
# ======================================================================
@dataclass
class Gather:
    """Spend an action gathering a resource."""
    resource: Resource


@dataclass
class CraftTool:
    """Turn wood into a tool (capital good that boosts gather yield)."""
    pass


@dataclass
class BuildWoodlot:
    """Invest wood to establish a woodlot: an owned asset that yields wood daily."""
    pass


@dataclass
class Trade:
    """Post a market order. side: 'buy' | 'sell'. price is the reservation price."""
    resource: Resource
    side: str
    qty: float
    price: float


@dataclass
class Speak:
    """
    Inject a claim into the knowledge network (the player as an information node).
    The claim originates at the speaking agent and spreads from their position in
    the social graph -- reach is emergent, not a parameter.
      magnitude 0..1 = claimed scarcity; truth = whether it's objectively true;
      authority 0..1 = how much the source is trusted; root_id = source identity
      (for echo-vs-corroboration).
    """
    resource: Resource
    magnitude: float
    truth: bool
    root_id: str
    authority: float = 0.6


# The closed set of intents a body may submit. This tuple IS the contract's
# surface for external control -- the conformance test asserts SimCore.submit()
# accepts every type in it and nothing outside it.
INTENT_TYPES = (Gather, CraftTool, BuildWoodlot, Trade, Speak)
Intent = Union[Gather, CraftTool, BuildWoodlot, Trade, Speak]


# ======================================================================
# EVENTS  (the world -> presentation)
# ======================================================================
@dataclass
class DayAdvanced:
    day: int
    season: str


@dataclass
class Produced:
    agent_id: str
    resource: Resource
    qty: float


@dataclass
class TradeCleared:
    resource: Resource
    price: float
    volume: float
    n_trades: int


@dataclass
class Settled:
    """How much an externally-controlled agent actually bought/sold this step
    (an order only clears against real counterparties -- this is the truth of it)."""
    resource: Resource
    side: str        # 'sell' | 'buy'
    qty: float
    value: float     # money that changed hands


@dataclass
class ContributionPaid:
    """Realized-effect payout credited to a contributor this step."""
    agent_id: str
    amount: float


@dataclass
class ContributionDetail:
    """The felt 'why' behind a ContributionPaid: whose need this producer's
    resource met, and at what price. One per (producer, consumer) credit flow, so
    a body can tell the player exactly who they kept warm and why it was worth
    what it was worth -- realized systemic effect made legible."""
    producer_id: str
    consumer_id: str
    consumer_kind: str     # 'villager' | 'dependent' | 'player' | ...
    resource: Resource
    amount: float          # credit paid to the producer for meeting this need
    rate: float            # per-unit fair value applied (high in deep winter)
    season: str


@dataclass
class Shortage:
    """An agent could not meet its daily need."""
    agent_id: str
    resource: Resource
    amount: float


@dataclass
class HoardFlagged:
    agent_id: str
    stock: float


@dataclass
class HoldingFee:
    """Anti-exploitation fee levied on cornered stock."""
    total: float


@dataclass
class AssetBuilt:
    """A capital good was established this step."""
    agent_id: str
    kind: str


@dataclass
class BeliefState:
    """Aggregate knowledge-network readout for a resource (propagation on)."""
    resource: Resource
    awareness: float          # fraction of villagers who hold any belief
    avg_belief: float         # mean value*confidence
    distinct_roots: int       # echo (1) vs corroboration (many)


# The closed set of events the world emits. The conformance test asserts every
# event drained from a live run is an instance of one of these.
EVENT_TYPES = (
    DayAdvanced, Produced, TradeCleared, Settled, ContributionPaid,
    ContributionDetail, Shortage, HoardFlagged, HoldingFee, AssetBuilt, BeliefState,
)
Event = Union[
    DayAdvanced, Produced, TradeCleared, Settled, ContributionPaid,
    ContributionDetail, Shortage, HoardFlagged, HoldingFee, AssetBuilt, BeliefState,
]


# ======================================================================
# SNAPSHOT  (read-only render state)
# ======================================================================
@dataclass
class AgentView:
    id: str
    kind: str                 # 'villager' | 'player' | 'merchant' | 'market_maker' | 'dependent'
    money: float
    wood: float
    food: float
    tool: float
    stamina: float
    fear_wood: float
    fear_food: float
    is_player: bool
    contribution_earned: float
    woodlots: int = 0            # owned capital goods of this kind
    woodlot_level: int = 0       # 0 = none; else current upgrade level
    woodlot_output: float = 0.0  # wood/day the woodlot yields at its level


@dataclass
class MarketView:
    resource: Resource
    ref_price: float          # current market price
    fair_price: float         # AIC's fair-value estimate (player's information edge)
    last_clear_price: float
    last_volume: float
    bounty: float             # internal realized-effect rate (usually not shown raw)


@dataclass
class ProblemView:
    """A world-state problem the player could resolve (Layer 1). Typed, located,
    with a severity (0..1) the sim tracks. This is 'what is the problem?' made
    legible -- the thing the index prices when the player drives it down and,
    later, the thing an intervention targets. Read-only render state."""
    key: str                  # stable identity, e.g. "scarcity:wood"
    kind: str                 # TYPE, e.g. "scarcity" | "capital_gap"
    location: str             # WHERE, e.g. "village"
    subject: str              # what it concerns, e.g. "wood"
    severity: float           # 0..1; 0 = resolved/absent, 1 = worst


@dataclass
class Snapshot:
    day: int
    season: str
    agents: list = field(default_factory=list)     # list[AgentView]
    markets: list = field(default_factory=list)    # list[MarketView]
    problems: list = field(default_factory=list)   # list[ProblemView] (Layer 1)
    village_unmet_wood: float = 0.0
    village_unmet_food: float = 0.0
    shortage_agents: int = 0
    total_contribution_paid: float = 0.0
    total_penalty: float = 0.0
    done: bool = False
