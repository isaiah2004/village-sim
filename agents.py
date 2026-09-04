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
class Asset:
    """An owned, persistent capital good (not a consumable holding)."""
    kind: str            # "woodlot"
    lot_id: int          # its lineage lot, so realized-effect credit can flow through it
    built_tick: int
    level: int = 1       # upgradable; output and upkeep scale with level


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
    wood_need: float                    # current-season wood consumption / day
    food_need: float
    ref_price: dict                     # Resource -> reference market price
    # Player-only privileged channels from the AIC. Villagers see empty dicts.
    bounty: dict = field(default_factory=dict)        # internal payout rate (used by strategies, not shown in UI)
    fair_price: dict = field(default_factory=dict)    # AIC's fair-value estimate (shown to player as guidance)


class Agent:
    is_player = False
    is_market_maker = False
    is_dependent = False

    def __init__(self, agent_id: str, cfg: Config, rng):
        self.id = agent_id
        self.cfg = cfg
        self.rng = rng
        self.money = cfg.start_money
        # holdings[resource] = deque of [lot_id, qty_remaining], oldest first
        self.holdings: dict[Resource, deque] = {r: deque() for r in Resource}
        self.stamina = cfg.stamina_per_day
        self.skill = {
            Resource.WOOD: rng.uniform(0.85, 1.2),
            Resource.FOOD: rng.uniform(0.85, 1.2),
        }
        self.tool_durability_left = 0
        self.assets: list = []   # owned capital goods (woodlots, …)
        # ---- belief: perceived scarcity per resource (0..1ish). Drives panic-
        # buying / reserve targets. Updated from observed events, not the AIC.
        self.perceived_scarcity: dict[Resource, float] = {r: 0.0 for r in Resource}
        # bookkeeping
        self.unmet_need = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}
        self.bonus_earned = 0.0

    # ---------- inventory helpers ----------
    def qty(self, r: Resource) -> float:
        return sum(item[1] for item in self.holdings[r])

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
    def daily_need(self, r: Resource, ctx: Ctx) -> float:
        if r == Resource.WOOD:
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
        y = self.cfg.base_yield[r] * self.cfg.season_yield_mult[ctx.season] * self.skill[r]
        if self.has_tool:
            y *= (1.0 + self.cfg.tool_yield_bonus)
        return y

    # ---------- belief update ----------
    def update_belief(self, own_unmet: dict, village_unmet: dict,
                      rumour: dict | None = None) -> None:
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
        for r in (Resource.WOOD, Resource.FOOD):
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
        for r in (Resource.WOOD, Resource.FOOD):
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
        if (not self.has_tool
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
        cover = {}
        for r in (Resource.WOOD, Resource.FOOD):
            cover[r] = self._projected_reserve(r) / max(self.daily_need(r, ctx), 1e-6)
        worst = min(cover, key=lambda r: cover[r])
        if cover[worst] < self.cfg.reserve_buffer_days:
            return worst
        best, best_profit = None, 0.0
        for r in (Resource.WOOD, Resource.FOOD):
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
        for r in (Resource.WOOD, Resource.FOOD):
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

    def __init__(self, agent_id, cfg, rng, money_mult: float = 1.2, **kwargs):
        super().__init__(agent_id, cfg, rng)
        self.money = cfg.start_money * money_mult

    def decide_actions(self, ctx):
        # garden food only (never wood); a little surplus to sell for wood money
        actions, stamina, pending = [], self.stamina, 0.0
        while stamina >= self.cfg.effort_per_gather:
            if self.qty(Resource.FOOD) + pending >= self.target_reserve(Resource.FOOD, ctx) * 1.5:
                break
            actions.append(GatherAction(Resource.FOOD))
            pending += self.expected_gather_yield(Resource.FOOD, ctx)
            stamina -= self.cfg.effort_per_gather
        return actions

    # make_orders is inherited: buys wood to cover reserves, sells food surplus.


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
        return {Resource.WOOD: ([], 0.0), Resource.FOOD: ([], 0.0)}

    def update_belief(self, *args, **kwargs):
        pass

    def make_orders(self, ctx) -> list[Order]:
        orders = []
        for r in (Resource.WOOD, Resource.FOOD):
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
        for r in (Resource.WOOD, Resource.FOOD):
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
        for r in (Resource.WOOD, Resource.FOOD):
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

    def __init__(self, agent_id: str, cfg: Config, rng, strategy="responsive"):
        super().__init__(agent_id, cfg, rng)
        self.skill = {Resource.WOOD: 1.3, Resource.FOOD: 1.2}
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
