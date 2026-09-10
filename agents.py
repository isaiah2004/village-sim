"""
Economic agents: Villagers (AI) and the Player.

Post-redesign contract:
  * Villagers are PURE LOCAL ACTORS. They do not see the AIC's bounties; they
    react only to what they can observe (their own reserves, market prices,
    their own and neighbours' shortages -> a `perceived_scarcity` belief).
  * The Player has a privileged information channel: it CAN see the AIC's
    posted bounties. This models the isekai information edge.
  * Crisis is real: when belief-driven panic raises reservation prices, the
    poorest villagers get priced out and suffer unmet need. The AIC observes
    this; it does not silently fix it.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from config import Config, Resource, Season


def _consumables(ctx: "Ctx"):
    """The consumable resource ids this scenario tracks (frostpine: wood, food)."""
    return ctx.consumables or (Resource.WOOD, Resource.FOOD)


def _scenario_ids(cfg):
    """(all resource ids, consumable ids) for cfg's scenario, or the frostpine
    enum defaults if no scenario is attached (agents built outside a World)."""
    sc = getattr(cfg, "scenario", None)
    if sc is None:
        return ([Resource.WOOD, Resource.FOOD, Resource.TOOL, Resource.WOODLOT],
                [Resource.WOOD, Resource.FOOD])
    return (list(sc.resource_ids()), list(sc.consumable_ids()))


def _need_ids(cfg, archetype: str) -> list:
    """The resources THIS archetype consumes daily (its needs). A NeedSpec with
    consumer="" is universal (every agent); one scoped to an archetype attaches
    only to that archetype. No scenario attached -> the frostpine defaults, where
    both needs are universal, so every agent needs wood + food (byte-identical)."""
    sc = getattr(cfg, "scenario", None)
    if sc is None:
        return [Resource.WOOD, Resource.FOOD]
    return [ns.resource for ns in sc.needs
            if ns.consumer == "" or ns.consumer == archetype]


# ----- decisions the agent hands back to the World to execute -----
@dataclass
class GatherAction:
    resource: Resource


@dataclass
class CraftToolAction:
    pass


@dataclass
class BuildWoodlotAction:
    """Establish a woodlot: a persistent capital good that yields wood each day."""
    pass


@dataclass
class InterventionAction:
    """Perform a pre-authored world-change from the intervention library (Layer 3),
    identified by key. Preconditions and effects live in interventions.py; the
    world applies it deterministically. Player-driven only."""
    key: str


@dataclass
class AcceptDealAction:
    """Conclude a negotiated loan-financed deal (Layer 3). The world hard-gates it,
    records the loan, credits the principal, and applies the intervention effect.
    Player-driven only."""
    key: str
    principal: float
    interest: float
    term_days: int
    merchant_id: str


@dataclass
class Asset:
    """An owned, persistent capital good (not a consumable holding).

    Most assets are the scenario's capital good (frostpine's woodlot), run by the
    world from `scenario.capital` by matching `kind`. An asset MAY instead carry
    its OWN production spec (`output_resource`/`output_per_level`, optional
    upkeep) -- an intervention-founded producer like an `open_trade_route`'s
    trade route -- which the world runs generically without a scenario.capital
    entry. `None` output_resource means "a scenario capital good", the historical
    shape (so frostpine assets are byte-identical)."""
    kind: str            # "woodlot"
    lot_id: int          # its lineage lot, so realized-effect credit can flow through it
    built_tick: int
    level: int = 1       # upgradable; output and upkeep scale with level
    output_resource: str | None = None   # self-carried producer spec (else scenario.capital)
    output_per_level: float = 0.0
    upkeep_resource: str | None = None
    upkeep_per_level: float = 0.0


@dataclass
class Loan:
    """A negotiated debt: the merchant lent `principal` at `interest` (total
    fraction over the term); the borrower repays `balance` in equal daily
    installments over `term_days`. Deterministic sim state -- the LLM merchant
    only negotiates the numbers; the sim enforces repayment and default."""
    lender_id: str
    principal: float
    interest: float          # total interest as a fraction of principal
    term_days: int
    struck_day: int
    balance: float           # remaining to repay; starts at principal*(1+interest)
    defaulted: bool = False

    @property
    def per_day(self) -> float:
        return round(self.principal * (1.0 + self.interest) / max(self.term_days, 1), 6)


@dataclass
class Order:
    agent_id: str
    resource: Resource
    side: str            # "buy" | "sell"
    qty: float
    price: float         # reservation price (max for buy, min for sell)


@dataclass
class Ctx:
    """Per-tick view of the world handed to agents for decision making."""
    cfg: Config
    day: int
    season: Season
    wood_need: float                    # compat alias: needs["wood"] (frostpine)
    food_need: float                    # compat alias: needs["food"] (frostpine)
    ref_price: dict                     # Resource -> reference market price
    # DESIGN.md: resources are data. `needs` is the per-agent daily consumption of
    # each consumable this day (base_consume x the active driver's phase); the agent
    # economic loops iterate `consumables`, so they work for any scenario's goods.
    needs: dict = field(default_factory=dict)         # resource id -> units/day
    consumables: tuple = ()                            # consumable resource ids
    yield_mult: dict = field(default_factory=dict)     # resource id -> today's gather-yield multiplier (driver)
    # Player-only privileged channels from the AIC. Villagers see empty dicts.
    bounty: dict = field(default_factory=dict)        # internal payout rate (used by strategies, not shown in UI)
    fair_price: dict = field(default_factory=dict)    # AIC's fair-value estimate (shown to player as guidance)


class Agent:
    is_player = False
    is_market_maker = False
    is_dependent = False
    is_institution = False        # an off-town buyer (war front, plague ward) -- not a resident
    archetype = "villager"        # the DATA name a NeedSpec.consumer can scope to

    def __init__(self, agent_id: str, cfg: Config, rng, produces=None, produce_target: float = 6.0):
        self.id = agent_id
        self.cfg = cfg
        self.rng = rng
        self.money = cfg.start_money
        # an optional TRADE GOOD this agent gathers for the market even though it
        # does not consume it (e.g. an adventurer's monster parts). Data-driven;
        # None -> the historical behaviour (gather only to cover own needs + a
        # profitable surplus). `produce_target` is how much to keep on hand to sell.
        self.produces = produces
        self.produce_target = produce_target
        # Resource buckets come from the scenario (DESIGN.md), so any world's goods
        # get holdings/skill/belief slots. The consumable order is stable, so the
        # per-consumable skill RNG draws happen in the same order -> byte-identical
        # for frostpine (wood then food).
        rids, cons = _scenario_ids(cfg)
        # the goods THIS agent consumes daily (its needs) -- scoped by archetype,
        # so a demand-side crisis good only burdens the participant who needs it.
        self.need_ids = set(_need_ids(cfg, type(self).archetype))
        # holdings[resource] = deque of [lot_id, qty_remaining], oldest first
        self.holdings: dict = {r: deque() for r in rids}
        self.stamina = cfg.stamina_per_day
        self.skill = {r: rng.uniform(0.85, 1.2) for r in cons}
        self.tool_durability_left = 0
        self.assets: list = []   # owned capital goods (woodlots, …)
        self.loans: list = []    # outstanding debts (Loan); empty unless loans_enabled
        # ---- belief: perceived scarcity per resource (0..1ish). Drives panic-
        # buying / reserve targets. Updated from observed events, not the AIC.
        self.perceived_scarcity: dict = {r: 0.0 for r in rids}
        # bookkeeping
        self.unmet_need = {r: 0.0 for r in cons}
        self.bonus_earned = 0.0

    # ---------- inventory helpers ----------
    def qty(self, r: Resource) -> float:
        # A resource the agent has no slot for is simply held in zero quantity;
        # tolerant lookup lets contract views ask about goods absent in a scenario.
        dq = self.holdings.get(r)
        return sum(item[1] for item in dq) if dq else 0.0

    def add_holding(self, lot_id: int, r: Resource, qty: float) -> None:
        self.holdings[r].append([lot_id, qty])

    def take(self, r: Resource, qty: float) -> list[tuple[int, float]]:
        """Remove up to `qty` FIFO; return [(lot_id, amount)] actually taken."""
        taken: list[tuple[int, float]] = []
        need = qty
        dq = self.holdings[r]
        while need > 1e-9 and dq:
            lot_id, have = dq[0]
            use = min(have, need)
            taken.append((lot_id, use))
            need -= use
            if use >= have - 1e-9:
                dq.popleft()
            else:
                dq[0][1] = have - use
        return taken

    @property
    def has_tool(self) -> bool:
        return self.tool_durability_left > 0

    # ---------- economic valuation ----------
    def daily_need(self, r, ctx: Ctx) -> float:
        if r not in self.need_ids:             # this agent doesn't consume r
            return 0.0
        if ctx.needs:
            return ctx.needs.get(r, 0.0)
        if r == Resource.WOOD:                 # legacy fallback (no scenario needs)
            return ctx.wood_need
        if r == Resource.FOOD:
            return ctx.food_need
        return 0.0


    def fear(self, r: Resource) -> float:
        """Clamped perceived-scarcity belief (0..1) for resource r."""
        return max(0.0, min(1.0, self.perceived_scarcity.get(r, 0.0)))

    def target_reserve(self, r: Resource, ctx: Ctx) -> float:
        base = self.daily_need(r, ctx) * self.cfg.reserve_buffer_days
        # Fear inflates the target reserve -> panic-buying / hoard-for-self.
        return base * (1.0 + (self.cfg.fear_buffer_mult - 1.0) * self.fear(r))

    def marginal_value(self, r: Resource, ctx: Ctx, reserve: float | None = None) -> float:
        """Decreasing marginal value, scaled up by fear (raises bid prices)."""
        intrinsic = self.cfg.intrinsic_value[r]
        if r == Resource.TOOL:
            return intrinsic
        reserve = self.qty(r) if reserve is None else reserve
        target = max(self.target_reserve(r, ctx), 1e-6)
        ratio = reserve / target
        if ratio < 1.0:
            base = intrinsic * (1.0 + 2.0 * (1.0 - ratio))
        else:
            base = intrinsic * max(0.25, 1.0 - 0.5 * (ratio - 1.0))
        # Fear amplifies what one is willing to pay -- the demand spike of panic.
        return base * (1.0 + (self.cfg.fear_price_mult - 1.0) * self.fear(r))

    def expected_gather_yield(self, r: Resource, ctx: Ctx) -> float:
        if ctx.yield_mult:
            mult = ctx.yield_mult.get(r, 1.0)
        else:
            mult = self.cfg.season_yield_mult[ctx.season]
        y = self.cfg.base_yield[r] * mult * self.skill[r]
        if self.has_tool:
            y *= (1.0 + self.cfg.tool_yield_bonus)
        return y

    # ---------- belief update ----------
    def update_belief(self, own_unmet: dict, village_unmet: dict,
                      rumour: dict | None = None, consumables: tuple = ()) -> None:
        """
        Fear rises with felt shortage (own > witnessed) and decays otherwise.

        `village_unmet` is the legacy village-wide witness ORACLE. With the
        knowledge layer active the World passes it as zero and supplies `rumour`
        instead: the scarcity this agent BELIEVES because gossip carried it here
        (0..1 per resource). Same downstream effect -- higher perceived_scarcity
        -> panic-buying + bigger reserve targets -- but sourced from information
        that actually had to travel, not an oracle.
        """
        rumour = rumour or {}
        for r in (consumables or (Resource.WOOD, Resource.FOOD)):
            personal = own_unmet.get(r, 0.0)
            witness = max(0.0, village_unmet.get(r, 0.0) - personal)
            delta = (self.cfg.fear_personal_gain * personal
                     + self.cfg.fear_witness_gain * witness
                     + self.cfg.rumour_fear_gain * rumour.get(r, 0.0)
                     - self.cfg.fear_decay)
            self.perceived_scarcity[r] = max(0.0, min(1.5,
                self.perceived_scarcity.get(r, 0.0) + delta))

    # ---------- consumption ----------
    def consume_daily(self, ctx: Ctx):
        """Burn the day's food + wood. Returns dict resource -> (consumed_lots, shortfall)."""
        result = {}
        for r in _consumables(ctx):
            need = self.daily_need(r, ctx)
            consumed = self.take(r, need)
            got = sum(q for _, q in consumed)
            shortfall = max(0.0, need - got)
            self.unmet_need[r] += shortfall
            result[r] = (consumed, shortfall)
        return result

    # ---------- production intents ----------
    def decide_actions(self, ctx: Ctx) -> list:
        actions = []
        stamina = self.stamina
        # Tool-crafting is a frostpine capital mechanic (a tool crafted from wood).
        # It only applies where the scenario actually has both a tool and wood.
        tools_available = Resource.TOOL in self.holdings and Resource.WOOD in self.holdings
        if (tools_available and not self.has_tool
                and self.qty(Resource.WOOD) >= self.target_reserve(Resource.WOOD, ctx) + self.cfg.tool_wood_cost
                and stamina >= self.cfg.effort_per_gather):
            actions.append(CraftToolAction())
            stamina -= self.cfg.effort_per_gather
        while stamina >= self.cfg.effort_per_gather:
            r = self._choose_gather(ctx)
            if r is None:
                break
            actions.append(GatherAction(r))
            stamina -= self.cfg.effort_per_gather
            self._pending = getattr(self, "_pending", {})
            self._pending[r] = self._pending.get(r, 0.0) + self.expected_gather_yield(r, ctx)
        self._pending = {}
        return actions

    def _projected_reserve(self, r: Resource) -> float:
        return self.qty(r) + getattr(self, "_pending", {}).get(r, 0.0)

    def _choose_gather(self, ctx: Ctx) -> Resource | None:
        """
        Villagers gather to cover their own reserves, then take a modest surplus
        only if it clears effort cost at CURRENT market prices. They DO NOT see
        the AIC's bounty -- they're not nudged by it.
        """
        # only gather goods this world actually lets you gather (base_yield > 0);
        # a "bought-in" good like tidewater's grain has base_yield 0 and is never
        # gathered. frostpine's wood and food are both gatherable -> unchanged.
        gatherable = [r for r in _consumables(ctx) if self.cfg.base_yield.get(r, 0.0) > 0]
        if not gatherable:
            return None
        cover = {}
        for r in gatherable:
            cover[r] = self._projected_reserve(r) / max(self.daily_need(r, ctx), 1e-6)
        worst = min(cover, key=lambda r: cover[r])
        if cover[worst] < self.cfg.reserve_buffer_days:
            return worst
        # produce the trade good for the market (a good gathered to SELL, not to
        # consume -- e.g. an adventurer's monster parts). Data-driven; None (the
        # historical default) skips this, so existing scenarios are byte-identical.
        if self.produces and self.produces in gatherable \
                and self._projected_reserve(self.produces) < self.produce_target:
            return self.produces
        best, best_profit = None, 0.0
        for r in gatherable:
            if self._projected_reserve(r) >= self.target_reserve(r, ctx) * self.cfg.surplus_gather_cap:
                continue
            unit_value = ctx.ref_price.get(r, 0.0)   # NO bounty term for villagers
            profit = unit_value * self.expected_gather_yield(r, ctx) - self.cfg.effort_cost
            if profit > best_profit:
                best, best_profit = r, profit
        return best

    # ---------- trading intents ----------
    def make_orders(self, ctx: Ctx) -> list[Order]:
        orders: list[Order] = []
        for r in _consumables(ctx):
            reserve = self.qty(r)
            target = self.target_reserve(r, ctx)
            if reserve < target:
                want = target - reserve
                bid = self.marginal_value(r, ctx, reserve)
                affordable = self.money / max(bid, 1e-6)
                qty = max(0.0, min(want, affordable))
                if qty > 1e-3:
                    orders.append(Order(self.id, r, "buy", qty, bid))
            elif reserve > target * self.cfg.surplus_sell_mult:
                surplus = reserve - target
                ask = max(self.marginal_value(r, ctx, reserve), self.cfg.intrinsic_value[r] * 0.6)
                orders.append(Order(self.id, r, "sell", surplus, ask))
        return orders


class Villager(Agent):
    pass


class Dependent(Villager):
    """
    A household that can do LIGHT work (garden food) but cannot chop wood -- the
    elderly, the infirm, specialists with no woodcraft. They subsist on food and
    sell a little surplus, but they must BUY their wood. That makes wood their
    specific vulnerability: in normal seasons they can afford it, but when winter
    makes wood scarce and dear, their food income can't keep them warm -- and they
    go cold first. This is why information and hoarding matter: the dependent is who
    a cornered market shuts out.
    """
    is_dependent = True
    archetype = "dependent"

    def __init__(self, agent_id, cfg, rng, money_mult: float = 1.2, produces="food", **kwargs):
        super().__init__(agent_id, cfg, rng)
        self.money = cfg.start_money * money_mult
        # the ONE good this dependent can make (data): frostpine gardeners produce
        # food but cannot cut wood; a tidewater net-mender produces nothing
        # (produces=None) and must buy the fish it needs.
        self.produces = produces

    def decide_actions(self, ctx):
        # produce only `self.produces` (never the crisis good); buy the rest.
        if self.produces is None:
            return []
        r = self.produces
        actions, stamina, pending = [], self.stamina, 0.0
        while stamina >= self.cfg.effort_per_gather:
            if self.qty(r) + pending >= self.target_reserve(r, ctx) * 1.5:
                break
            actions.append(GatherAction(r))
            pending += self.expected_gather_yield(r, ctx)
            stamina -= self.cfg.effort_per_gather
        return actions

    # make_orders is inherited: buys the crisis good to cover reserves, sells surplus.


class MarketMaker(Agent):
    """
    The "market" itself, embodied as an always-present trading counterparty.

    Posts a buy order at ref_price * (1 - spread) and a sell order at
    ref_price * (1 + spread) every day -- so there's ALWAYS someone you can
    sell to (at a small discount) and ALWAYS someone you can buy from (at a
    small premium), regardless of whether any villager happens to be trading
    that day. This is what a real village trading post does.

    Has effectively unlimited money. Its WOOD/FOOD inventory grows and
    shrinks ORGANICALLY (it doesn't magically produce) -- it starts with
    modest stock, accumulates as villagers/the player sell to it, and depletes
    as they buy from it. So it can run out during winter, preserving the
    underlying crisis dynamics.

    Excluded from villager counts, hoarding surveillance, and AIC bounty
    payouts (its inventory provenance is "market", which the accountant
    treats the same as "nature": no one earns credit for sourcing through it).
    """
    is_market_maker = True
    archetype = "market_maker"

    def __init__(self, agent_id: str, cfg: Config, rng,
                 spread: float = 0.05,
                 target_inventory: float = 20.0,
                 daily_volume: float = 5.0,
                 **kwargs):
        super().__init__(agent_id, cfg, rng)
        self.money = 1_000_000.0
        self.daily_stamina = 0.0
        self.stamina = 0.0
        self.spread = spread
        # The maker ALWAYS bids and asks. As its stock grows past `target`,
        # its bid drops toward the floor (discouraging more selling). As stock
        # falls toward 0, its ask grows above market (rationing what's left).
        # This is how real dealers manage inventory through pricing -- and it
        # means the player can always find SOMEONE to trade with, even if at a
        # price they don't love.
        self.target_inventory = target_inventory
        self.daily_volume = daily_volume

    def decide_actions(self, ctx):
        return []

    def consume_daily(self, ctx):
        return {r: ([], 0.0) for r in _consumables(ctx)}

    def update_belief(self, *args, **kwargs):
        pass

    def make_orders(self, ctx) -> list[Order]:
        orders = []
        for r in _consumables(ctx):
            ref = ctx.ref_price.get(r, self.cfg.intrinsic_value[r])
            intrinsic = self.cfg.intrinsic_value[r]
            floor = intrinsic * self.cfg.price_floor_mult
            stock = self.qty(r)
            # Bid: starts at ref*(1-spread) when empty, drops toward floor as
            # inventory grows above target. Past 2x target, bid is at the floor.
            excess = max(0.0, stock - self.target_inventory) / self.target_inventory
            bid_discount = self.spread + 0.5 * min(1.0, excess)
            bid_price = max(floor, ref * (1.0 - bid_discount))
            orders.append(Order(self.id, r, "buy", self.daily_volume, bid_price))
            # Ask: starts at ref*(1+spread) when well-stocked, rises as stock
            # falls below target. Below half-target, ask climbs sharply.
            if stock > 0.1:
                scarcity = max(0.0, self.target_inventory - stock) / self.target_inventory
                ask_premium = self.spread + 0.6 * min(1.0, scarcity)
                ask_price = ref * (1.0 + ask_premium)
                sell_qty = min(stock, self.daily_volume)
                orders.append(Order(self.id, r, "sell", sell_qty, ask_price))
        return orders


class Merchant(Agent):
    """
    DEMO of the modularity. A Merchant doesn't gather: they buy low and sell
    high. Plug them into the world via SpawnSpec(Merchant, count). Nothing in
    market.py / accountant.py / world.py / lineage.py needs to know they exist
    -- the existing systems treat them as just another agent.
    """
    archetype = "merchant"

    def __init__(self, agent_id, cfg, rng, capital_mult: float = 4.0):
        super().__init__(agent_id, cfg, rng)
        self.money = cfg.start_money * capital_mult
        self.stamina = 0.0                     # merchants don't gather
        # leaner reserves than villagers (they live off margins, not stockpiles)
        self._reserve_mult = 1.5

    def target_reserve(self, r, ctx):
        base = self.daily_need(r, ctx) * self._reserve_mult
        return base * (1.0 + (self.cfg.fear_buffer_mult - 1.0) * self.fear(r))

    def decide_actions(self, ctx):
        return []

    def make_orders(self, ctx) -> list[Order]:
        orders = []
        for r in _consumables(ctx):
            ref = ctx.ref_price.get(r, self.cfg.intrinsic_value[r])
            stock = self.qty(r)
            target = self.target_reserve(r, ctx)
            # cover subsistence first
            if stock < target:
                bid = self.marginal_value(r, ctx, stock)
                qty = min(target - stock, self.money / max(bid, 1e-6))
                if qty > 1e-3:
                    orders.append(Order(self.id, r, "buy", qty, bid))
            # buy speculatively when below ref price; resell above it
            buy_below = ref * 0.85
            sell_above = ref * 1.15
            if stock > target:
                orders.append(Order(self.id, r, "sell",
                                    stock - target, sell_above))
            # also try a small speculative bid at buy_below regardless
            spec_qty = min(self.money * 0.05 / max(buy_below, 1e-6), 5.0)
            if spec_qty > 0.1:
                orders.append(Order(self.id, r, "buy", spec_qty, buy_below))
        return orders


class InstitutionBuyer(Agent):
    """
    An off-town INSTITUTIONAL BUYER -- a demand-side crisis embodied as a
    participant (DESIGN.md's guildhall as a demand event). A war quartermaster or
    a plague apothecary that enters the market during a MOBILIZATION WINDOW and
    pays a PREMIUM for one good. It is pure infrastructure; which good, how big a
    premium, and how much it can absorb are DATA (kwargs). The window itself is
    DATA too: the buyer's need for `demand_good` is a demand-scoped NeedSpec whose
    per-phase requirement (the driver's consume_mult) is high only during the
    event and zero otherwise -- so the buyer is active exactly when the world's
    driver says the event is on.

    It does not gather or reside in the town (excluded from village welfare and
    hoard surveillance). It buys the good on the open market and CONSUMES it to
    meet its need, which fires realized-effect contribution up the lineage to the
    adventurers/players who supplied it -- the index rewarding those who serve the
    front. Its 'yes' to a price never overrides the market; it just bids.
    """
    is_institution = True
    archetype = "buyer"

    def __init__(self, agent_id, cfg, rng, demand_good: str = "",
                 premium: float = 1.6, capacity: float = 24.0, **kwargs):
        super().__init__(agent_id, cfg, rng)
        self.money = 1_000_000.0               # an institution, not a household
        self.stamina = 0.0                     # does not gather
        self.demand_good = demand_good
        self.premium = premium                 # price it will pay, as a multiple of ref
        self.capacity = capacity               # max units it bids for per active day

    def decide_actions(self, ctx):
        return []

    def make_orders(self, ctx) -> list[Order]:
        # only in the market during its event window: the window is exactly the
        # phases where its (demand-scoped) need for the good is non-zero. It bids
        # for what it will consume today (up to `capacity`) -- it does not stockpile,
        # so its own holdings never mask the town's real supply/scarcity.
        need = self.daily_need(self.demand_good, ctx)
        if need <= 1e-9 or not self.demand_good:
            return []
        want = max(0.0, min(self.capacity, need) - self.qty(self.demand_good))
        if want <= 1e-9:
            return []
        ref = ctx.ref_price.get(self.demand_good, self.cfg.intrinsic_value.get(self.demand_good, 1.0))
        price = ref * self.premium
        return [Order(self.id, self.demand_good, "buy", want, price)]


# =====================================================================
# Player strategies (pluggable)
# =====================================================================
# Each Strategy is a small object that decides what the player gathers
# and trades each tick. Adding a new player archetype = subclass Strategy,
# implement decide_actions / make_orders, register in STRATEGIES.
# Strategies are composable: they can fall back to villager-like behaviour
# by calling Agent.decide_actions(player, ctx) / Agent.make_orders.

class Strategy:
    """Base interface for a player strategy."""
    name: str = "base"
    daily_stamina_mult: float = 3.0   # multiplier on cfg.stamina_per_day

    def decide_actions(self, ag, ctx: Ctx) -> list:
        """Default behaviour: act like a villager would."""
        return Agent.decide_actions(ag, ctx)

    def make_orders(self, ag, ctx: Ctx) -> list[Order]:
        return Agent.make_orders(ag, ctx)


class IdleStrategy(Strategy):
    """Withdraws from the economy entirely. Control baseline."""
    name = "idle"
    daily_stamina_mult = 0.0
    def decide_actions(self, ag, ctx): return []
    def make_orders(self, ag, ctx):    return []


class IgnoreStrategy(Strategy):
    """Lives in the village like a villager. Ignores the AIC channel."""
    name = "ignore"
    daily_stamina_mult = 1.0
    # default Strategy methods already do villager-like behaviour


class ResponsiveStrategy(Strategy):
    """
    A simulated "good player". Reads the AIC's published FAIR PRICE and
    compares it to the current market: when wood's fair value is >15% above
    intrinsic, that's the AIC saying scarcity is coming -- gather and supply.
    Same signal a human player sees in the UI.
    """
    name = "responsive"
    daily_stamina_mult = 3.0

    def decide_actions(self, ag, ctx):
        intrinsic = ag.cfg.intrinsic_value[Resource.WOOD]
        fair = ctx.fair_price.get(Resource.WOOD, intrinsic)
        if fair > intrinsic * 1.15:
            actions = []
            stamina = ag.stamina
            food_deficit = ag.target_reserve(Resource.FOOD, ctx) - ag.qty(Resource.FOOD)
            while stamina >= ag.cfg.effort_per_gather:
                if food_deficit > 1e-3:
                    actions.append(GatherAction(Resource.FOOD))
                    food_deficit -= ag.expected_gather_yield(Resource.FOOD, ctx)
                else:
                    actions.append(GatherAction(Resource.WOOD))
                stamina -= ag.cfg.effort_per_gather
            return actions
        return Agent.decide_actions(ag, ctx)

    def make_orders(self, ag, ctx):
        orders = []
        for r in _consumables(ctx):
            reserve, target = ag.qty(r), ag.target_reserve(r, ctx)
            if reserve > target:
                ask = max(ag.cfg.intrinsic_value[r] * 0.7, ag.marginal_value(r, ctx, reserve))
                orders.append(Order(ag.id, r, "sell", reserve - target, ask))
            elif reserve < target:
                bid = ag.marginal_value(r, ctx, reserve)
                qty = min(target - reserve, ag.money / max(bid, 1e-6))
                if qty > 1e-3:
                    orders.append(Order(ag.id, r, "buy", qty, bid))
        return orders


class HoarderStrategy(Strategy):
    """Corners wood. Should be detected and penalised by the surveillance layer."""
    name = "hoarder"
    daily_stamina_mult = 3.0

    def decide_actions(self, ag, ctx):
        actions = []
        stamina = ag.stamina
        food_deficit = ag.target_reserve(Resource.FOOD, ctx) - ag.qty(Resource.FOOD)
        while stamina >= ag.cfg.effort_per_gather:
            if food_deficit > 1e-3:
                actions.append(GatherAction(Resource.FOOD))
                food_deficit -= ag.expected_gather_yield(Resource.FOOD, ctx)
            else:
                actions.append(GatherAction(Resource.WOOD))
            stamina -= ag.cfg.effort_per_gather
        return actions

    def make_orders(self, ag, ctx):
        orders = []
        r = Resource.FOOD
        reserve, target = ag.qty(r), ag.target_reserve(r, ctx)
        if reserve > target * ag.cfg.surplus_sell_mult:
            ask = max(ag.marginal_value(r, ctx, reserve), ag.cfg.intrinsic_value[r] * 0.6)
            orders.append(Order(ag.id, r, "sell", reserve - target, ask))
        wood_reserve, wood_target = ag.qty(Resource.WOOD), ag.target_reserve(Resource.WOOD, ctx)
        wood_surplus = max(0.0, wood_reserve - wood_target)
        if ctx.season == Season.WINTER and wood_surplus > 0:
            slice_qty = wood_surplus * 0.10
            ask = ctx.ref_price[Resource.WOOD] * 2.5
            orders.append(Order(ag.id, Resource.WOOD, "sell", slice_qty, ask))
        elif ctx.season in (Season.SPRING, Season.SUMMER) and wood_surplus > 0:
            ask = ag.cfg.intrinsic_value[Resource.WOOD]
            orders.append(Order(ag.id, Resource.WOOD, "sell", wood_surplus, ask))
        return orders


class HumanStrategy(Strategy):
    """
    Strategy that takes its actions from an externally-set queue. The UI fills
    `planned_actions` and `planned_orders` each day; this strategy hands them
    to the world. It also TRUNCATES gather actions to the player's available
    stamina so the UI can over-queue without breaking the sim.
    """
    name = "human"
    daily_stamina_mult = 3.0

    def __init__(self):
        self.planned_actions: list = []
        self.planned_orders: list = []

    def decide_actions(self, ag, ctx):
        gathers = [a for a in self.planned_actions if isinstance(a, GatherAction)]
        n_allowed = int(ag.stamina // ag.cfg.effort_per_gather)
        used = gathers[:n_allowed]
        ag.stamina -= len(used) * ag.cfg.effort_per_gather
        self.planned_actions = []
        return used

    def make_orders(self, ag, ctx):
        orders = self.planned_orders[:]
        self.planned_orders = []
        return orders


# Registry: lookup by short name. Add new strategies here to make them
# selectable by string from config / scenarios.
STRATEGIES: dict = {
    s.name: s for s in (
        IdleStrategy, IgnoreStrategy, ResponsiveStrategy, HoarderStrategy, HumanStrategy
    )
}


class Player(Agent):
    """The human-player proxy. Behaviour is delegated to a `Strategy` object."""
    is_player = True
    archetype = "player"

    def __init__(self, agent_id: str, cfg: Config, rng, strategy="responsive"):
        super().__init__(agent_id, cfg, rng)
        # The player is a somewhat-better-than-average producer of every
        # consumable. frostpine's historical values (wood 1.3, food 1.2) are
        # preserved exactly; any other scenario's goods get a flat competent
        # skill, so this is generic -- no per-scenario branching.
        _, cons = _scenario_ids(cfg)
        _historical = {"wood": 1.3, "food": 1.2}
        self.skill = {r: _historical.get(r.value if hasattr(r, "value") else r, 1.25)
                      for r in cons}
        # accept either a registry name or an actual Strategy instance
        if isinstance(strategy, str):
            strat = STRATEGIES.get(strategy)
            if strat is None:
                raise ValueError(f"unknown player strategy: {strategy!r} "
                                 f"(known: {sorted(STRATEGIES)})")
            self.strategy = strat()
        else:
            self.strategy = strategy
        self.daily_stamina = cfg.stamina_per_day * self.strategy.daily_stamina_mult
        self.stamina = self.daily_stamina

    def decide_actions(self, ctx: Ctx) -> list:
        return self.strategy.decide_actions(self, ctx)

    def make_orders(self, ctx: Ctx) -> list[Order]:
        return self.strategy.make_orders(self, ctx)


# =====================================================================
# Population spawn registry
# =====================================================================
# A scenario declares its non-player population as a list of SpawnSpecs.
# Adding a new entity type to the world = define the agent class above
# and add a SpawnSpec; the World iterates the list, no further changes.

@dataclass
class SpawnSpec:
    cls: type
    count: int
    id_prefix: str = ""
    kwargs: dict = field(default_factory=dict)

    def make_id(self, i: int) -> str:
        prefix = self.id_prefix or self.cls.__name__[:3].lower()
        return f"{prefix}{i:02d}"


# ---------------------------------------------------------------------
# Archetype registry: scenario population is DATA (a PopSpec names an archetype
# by string). This maps those names to agent classes so scenario.build_population
# can turn PopSpec rows into SpawnSpecs with no per-scenario code.
# ---------------------------------------------------------------------
ARCHETYPES: dict = {
    "villager": Villager,
    "dependent": Dependent,
    "market_maker": MarketMaker,
    "merchant": Merchant,
    "buyer": InstitutionBuyer,
}
