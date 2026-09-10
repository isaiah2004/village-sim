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
#   1.3 (2026-09-06) additive: Perform intent + InterventionPerformed event --
#       Layer 3's pre-authored world-changes. Minor bump; older bodies never
#       submit Perform and safely ignore the new event type.
#   1.4 (2026-09-10) additive: AcceptDeal intent; DealResolved + LoanUpdated
#       events; MerchantView/ReputationSummary reads; LoanView + Snapshot.loans --
#       Layer 3's merchant negotiation + loan financing. Minor bump; older bodies
#       never submit AcceptDeal, ignore the new events, and skip the new reads.
#   1.5 (2026-09-10) additive: universal (scenario-agnostic) read fields so a body
#       can render ANY world without knowing wood/food. AgentView.holdings/fears
#       (resource-id -> qty/fear dicts); Snapshot.scenario/primary_resource/
#       consumables/village_unmet (the generic mirror of village_unmet_wood/food).
#       The frostpine-named fields (wood, food, fear_wood, village_unmet_wood, ...)
#       are UNCHANGED and still populated for frostpine, so older bodies keep
#       working; a universal body reads the dicts instead. Minor bump.
CONTRACT_VERSION = "1.5"

__all__ = [
    "CONTRACT_VERSION", "Resource", "Season",
    "Gather", "CraftTool", "BuildWoodlot", "Trade", "Speak", "Perform", "AcceptDeal",
    "Intent", "INTENT_TYPES",
    "DayAdvanced", "Produced", "TradeCleared", "Settled", "ContributionPaid",
    "ContributionDetail", "Shortage", "HoardFlagged", "HoldingFee", "AssetBuilt",
    "BeliefState", "InterventionPerformed", "DealResolved", "LoanUpdated",
    "Event", "EVENT_TYPES",
    "AgentView", "MarketView", "ProblemView", "ReputationSummary", "MerchantView",
    "LoanView", "Snapshot",
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


@dataclass
class Perform:
    """Perform a pre-authored world-change from the intervention library (Layer 3),
    identified by `key` (e.g. "found_mill"). The world checks the intervention's
    preconditions (capital, standing, enabling knowledge) and, if met, applies its
    authored effect to world-state -- which the index then prices. A no-op if
    interventions are disabled or a precondition fails; the reason surfaces as an
    InterventionPerformed event with accepted=False."""
    key: str


@dataclass
class AcceptDeal:
    """Conclude a negotiated deal: take a loan of `principal` at `interest` (total
    fraction over the term) over `term_days` from `merchant_id`, to fund
    intervention `key`. A body submits this after a negotiation (deterministic
    ScriptedMerchant, or the edge LLMMerchant) has settled terms. The sim is the
    HARD gate: it re-checks the intervention's non-capital preconditions and the
    merchant's capital, clamps the terms, records the loan, credits the principal,
    and applies the authored effect -- or rejects with a reason. Either way it
    emits a DealResolved event. The LLM's 'yes' never overrides this."""
    key: str
    principal: float
    interest: float
    term_days: int
    merchant_id: str = "mk00"


# The closed set of intents a body may submit. This tuple IS the contract's
# surface for external control -- the conformance test asserts SimCore.submit()
# accepts every type in it and nothing outside it.
INTENT_TYPES = (Gather, CraftTool, BuildWoodlot, Trade, Speak, Perform, AcceptDeal)
Intent = Union[Gather, CraftTool, BuildWoodlot, Trade, Speak, Perform, AcceptDeal]


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


@dataclass
class InterventionPerformed:
    """A pre-authored world-change was attempted this step (Layer 3). accepted
    tells whether preconditions were met and the effect applied; on failure,
    `reason` says why (so a body can show 'need more capital/standing')."""
    agent_id: str
    key: str
    accepted: bool
    capital_spent: float      # money paid to perform it (0 if rejected)
    target: str               # the problem key it addresses, e.g. "capital_gap:wood"
    reason: str               # "" on success; else why it was rejected


@dataclass
class DealResolved:
    """Outcome of an AcceptDeal at the sim's hard gate. struck=True means the loan
    was recorded, the principal credited, and the intervention performed; else
    `reason` says why the deal fell through (the merchant's 'yes' cannot override
    a failed precondition)."""
    agent_id: str
    merchant_id: str
    key: str
    struck: bool
    principal: float
    interest: float
    term_days: int
    reason: str               # "" if struck; else why rejected


@dataclass
class LoanUpdated:
    """A loan's state changed this step: a scheduled repayment, a full pay-off, or
    a default (the borrower could not make the payment)."""
    agent_id: str
    lender_id: str
    event: str                # "repaid" | "paid_off" | "defaulted"
    payment: float            # money moved this step (0 on default)
    balance: float            # remaining balance after this step


# The closed set of events the world emits. The conformance test asserts every
# event drained from a live run is an instance of one of these.
EVENT_TYPES = (
    DayAdvanced, Produced, TradeCleared, Settled, ContributionPaid,
    ContributionDetail, Shortage, HoardFlagged, HoldingFee, AssetBuilt, BeliefState,
    InterventionPerformed, DealResolved, LoanUpdated,
)
Event = Union[
    DayAdvanced, Produced, TradeCleared, Settled, ContributionPaid,
    ContributionDetail, Shortage, HoardFlagged, HoldingFee, AssetBuilt, BeliefState,
    InterventionPerformed, DealResolved, LoanUpdated,
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
    # universal (scenario-agnostic) mirrors -- resource-id -> value for EVERY
    # resource in the world, so a body renders any scenario without wood/food
    # knowledge. The named fields above are the frostpine slices of these.
    holdings: dict = field(default_factory=dict)   # resource id -> qty held
    fears: dict = field(default_factory=dict)       # resource id -> perceived scarcity 0..1


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
class ReputationSummary:
    """What a merchant has come to know of an agent's track record -- the gate
    input for negotiation. `standing` is the numeric measure (today: realized
    contribution); `descriptor` is the plain-language band a prompt can use."""
    standing: float
    descriptor: str           # "unproven" | "known" | "trusted" | "renowned"


@dataclass
class MerchantView:
    """The deliberately PARTIAL projection a merchant reasons over (knowledge-
    gating by construction): public market prices, the merchant's own capital, the
    season, public facts, and the counterparty's reputation -- never the AIC fair
    value or any hidden world truth. Carries the proposal currently on the table."""
    merchant_id: str
    merchant_capital: float
    ref_prices: dict          # resource.value -> public reference price
    season: str
    reputation: ReputationSummary
    public_facts: tuple       # short public strings (e.g. "winter is near")
    # the proposal on the table this round:
    key: str
    principal: float
    interest: float
    term_days: int


@dataclass
class LoanView:
    """A borrower's outstanding loan (read-only render state)."""
    agent_id: str
    lender_id: str
    principal: float
    interest: float
    balance: float
    term_days: int
    struck_day: int
    per_day: float
    defaulted: bool


@dataclass
class Snapshot:
    day: int
    season: str
    agents: list = field(default_factory=list)     # list[AgentView]
    markets: list = field(default_factory=list)    # list[MarketView]
    problems: list = field(default_factory=list)   # list[ProblemView] (Layer 1)
    loans: list = field(default_factory=list)      # list[LoanView] (Layer 3 financing)
    village_unmet_wood: float = 0.0
    village_unmet_food: float = 0.0
    shortage_agents: int = 0
    total_contribution_paid: float = 0.0
    total_penalty: float = 0.0
    done: bool = False
    # universal (scenario-agnostic) identity + welfare, so a body can label and
    # render any world. village_unmet is the generic mirror of village_unmet_wood/
    # food (resource id -> unmet); consumables lists the goods that deplete daily.
    scenario: str = "frostpine"
    primary_resource: str = "wood"       # the crisis good (metrics/UI focus)
    consumables: tuple = ("wood", "food")
    village_unmet: dict = field(default_factory=dict)   # resource id -> village unmet
