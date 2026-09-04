"""
The AI Accountant (AIC) -- OBSERVER, not planner.

Role contract:
  * MEASURE: tracks production, reserves, prices, flows, and welfare. Records
    everything; modifies nothing about how villagers behave.
  * PRICE OPPORTUNITY: forecasts shortages and publishes a per-unit BOUNTY
    representing the marginal stabilizing value of a unit of the scarce resource.
    The bounty is a PUBLIC POSTING on a channel only the human player can read --
    villagers do not see it and are not nudged by it.
  * PAY CONTRIBUTION: pays out the bounty only when the resource does REALIZED
    stabilising work (is consumed to meet a village need). Credit flows backward
    through the resource-lineage DAG with per-hop attenuation, so foundational
    producers (gathered wood, crafted tools) earn proportional credit.
  * POLICE EXPLOITATION: flags agents holding a large stock that is NOT shrinking
    while the market is scarce (price-spike or active unmet need), and levies a
    holding fee on the cornered excess. Flagged agents receive no bounty.

The AIC's bounty is NOT a subsidy the village relies on. If the player ignores
it, the village suffers. The AIC just tells the truth about marginal value.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import Config, Resource, Season
from lineage import LineageGraph


@dataclass
class AccountantState:
    # Bounty: internal per-unit rate the AIC pays when a resource does realized
    # stabilising work. NOT shown to the player as an explicit number anymore --
    # players see it only as "AIC paid you $X for stabilisation" in the log.
    bounty: dict = field(default_factory=dict)
    # Fair value: the AIC's estimate of what each good SHOULD cost given the
    # forecast (intrinsic, scarcity, season). This IS shown to the player --
    # they compare it to the actual market price to spot opportunities.
    fair_price: dict = field(default_factory=dict)
    predicted_deficit: dict = field(default_factory=dict)
    paid_today: float = 0.0
    total_paid: float = 0.0
    total_penalty: float = 0.0
    hoard_flags: dict = field(default_factory=dict)
    # per-day realized-effect detail: (producer_id, consumer_id, consumer_kind,
    # resource, amount, rate, season) -- the "who did my resource help, and why
    # was it worth this" ledger. Transient: cleared each start_day, observed only.
    contrib_events: list = field(default_factory=list)


class Accountant:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = AccountantState(
            bounty={r: 0.0 for r in Resource},
            fair_price={r: cfg.intrinsic_value[r] for r in Resource},
        )
        # rolling estimate of daily production per resource (observed only)
        self._prod_ema = {
            Resource.WOOD: cfg.n_villagers * cfg.base_yield[Resource.WOOD] * 0.4,
            Resource.FOOD: cfg.n_villagers * cfg.base_yield[Resource.FOOD] * 0.4,
        }
        # surveillance: track wood SALES (cleared) and HONEST OFFERS (sell orders
        # at reasonable prices). A genuine supplier shows at least one; a hoarder
        # shows neither during scarcity.
        self._sales_ema: dict[str, float] = {}
        self._honest_offer_ema: dict[str, float] = {}

    # ---------- observation ----------
    def observe_production(self, resource: Resource, qty: float) -> None:
        if resource in self._prod_ema:
            a = 0.2
            self._prod_ema[resource] = (1 - a) * self._prod_ema[resource] + a * qty

    # ---------- daily bounty publish ----------
    def start_day(self, day: int, agents: list) -> None:
        """
        Compute the published bounty for the day. This DOES NOT affect village
        behaviour -- it's a posting on the player's privileged channel. The
        bounty is the AIC's best estimate of the marginal stabilising value of
        one more unit of the resource right now.
        """
        self.state.paid_today = 0.0
        self.state.contrib_events = []
        if not self.cfg.accountant_enabled:
            self.state.bounty = {r: 0.0 for r in Resource}
            self.state.fair_price = {r: self.cfg.intrinsic_value[r] for r in Resource}
            return
        n = len(agents)
        today_mult = self.cfg.season_yield_mult[self.cfg.season_for_day(day)]
        for r in (Resource.WOOD, Resource.FOOD):
            reserves = sum(ag.qty(r) for ag in agents)
            projected_consumption = self._projected_consumption(r, day, n)
            # The AIC's view of capacity is pessimistic so it doesn't behave as
            # a perfect oracle: it under-estimates how much villagers can produce.
            base_capacity = (self._prod_ema[r] / max(today_mult, 1e-6)) * self.cfg.accountant_pessimism
            projected_production = sum(
                base_capacity * self.cfg.season_yield_mult[self.cfg.season_for_day(d)]
                for d in range(day, day + self.cfg.accountant_horizon)
            )
            deficit = projected_consumption - (reserves + projected_production)
            ratio = max(0.0, min(1.0, deficit / max(projected_consumption, 1e-6)))
            self.state.predicted_deficit[r] = deficit
            self.state.bounty[r] = round(self.cfg.accountant_bounty_max * ratio, 3)
            # Fair value: intrinsic, lifted by scarcity. Player compares this
            # to the actual market price to spot under/over-valued goods.
            #   no scarcity  -> fair == intrinsic
            #   full scarcity -> fair == 3 x intrinsic
            self.state.fair_price[r] = round(
                self.cfg.intrinsic_value[r] * (1.0 + 2.0 * ratio), 2
            )

    def _projected_consumption(self, resource: Resource, day: int, n_agents: int) -> float:
        total = 0.0
        for d in range(day, day + self.cfg.accountant_horizon):
            season = self.cfg.season_for_day(d)
            if resource == Resource.WOOD:
                total += n_agents * self.cfg.wood_per_day[season]
            elif resource == Resource.FOOD:
                total += n_agents * self.cfg.food_per_day
        return total

    # ---------- realized-effect payout ----------
    def reward_consumption(
        self,
        resource: Resource,
        consumer_id: str,
        consumed_lots: list[tuple[int, float]],
        season: Season,
        lineage: LineageGraph,
        agents_by_id: dict,
    ) -> float:
        """
        A unit of `resource` was just consumed to meet `consumer_id`'s need.
        Pay the published bounty up the lineage to its producers -- BUT only
        when the producer is NOT the consumer. Subsistence-on-self does not
        count as contribution: contribution means "served someone else's need."
        Hoarders are also excluded.
        """
        if self.cfg.reward_at_fair_value:
            # price the met need at its fair value: floors at intrinsic, rises with
            # scarcity -> solving a crisis is rewarded, not zeroed out.
            rate = self.state.fair_price.get(resource, self.cfg.intrinsic_value[resource])
        else:
            rate = self.state.bounty.get(resource, 0.0)
        if rate <= 1e-6:
            return 0.0
        paid_here = 0.0

        consumer = agents_by_id.get(consumer_id)
        if consumer is None:
            consumer_kind = "unknown"
        elif getattr(consumer, "is_player", False):
            consumer_kind = "player"
        elif getattr(consumer, "is_market_maker", False):
            consumer_kind = "market_maker"
        elif getattr(consumer, "is_dependent", False):
            consumer_kind = "dependent"
        else:
            consumer_kind = "villager"

        def pay(producer_id: str, amount: float, lot) -> None:
            nonlocal paid_here
            if producer_id == consumer_id:
                return                       # subsistence on self -> no bounty
            if producer_id in ("nature", "market"):
                return                       # starting reserves / market-sourced
            if producer_id in self.state.hoard_flags:
                return
            ag = agents_by_id.get(producer_id)
            if ag is not None and amount > 0:
                ag.money += amount
                ag.bonus_earned += amount
                paid_here += amount
                # record the felt "why": this producer met THIS consumer's need
                self.state.contrib_events.append(
                    (producer_id, consumer_id, consumer_kind, resource,
                     amount, rate, season.value))

        for lot_id, qty in consumed_lots:
            budget_left = self.cfg.accountant_budget_per_day - self.state.paid_today
            if budget_left <= 1e-6:
                break
            value = min(rate * qty, budget_left)
            lineage.propagate_credit(lot_id, value, self.cfg.accountant_lambda, pay)
            self.state.paid_today += value
        self.state.total_paid += paid_here
        return paid_here

    # ---------- anti-exploitation backstop ----------
    def observe_sales(self, wood_sales_by_agent: dict) -> None:
        a = 0.3
        for agent_id, qty in wood_sales_by_agent.items():
            self._sales_ema[agent_id] = (1 - a) * self._sales_ema.get(agent_id, 0.0) + a * qty

    def observe_honest_offers(self, honest_offer_by_agent: dict) -> None:
        """Record wood sell orders posted at <= 1.5x current reference price."""
        a = 0.3
        for agent_id, qty in honest_offer_by_agent.items():
            self._honest_offer_ema[agent_id] = (
                (1 - a) * self._honest_offer_ema.get(agent_id, 0.0) + a * qty
            )

    def update_surveillance(self, agents: list, wood_price: float, unmet_wood: float = 0.0) -> None:
        """
        Flag agents who hold a large wood stockpile while the village is in
        scarcity AND who are not actively releasing it to the market. We look
        at SALES (external release) rather than total stock change, so an
        agent can't hide a hoard by burning some of it themselves.
        """
        scarce = (wood_price > self.cfg.intrinsic_value[Resource.WOOD] * self.cfg.scarcity_price_mult
                  or unmet_wood > 1e-6)
        self.state.hoard_flags = {}
        if not scarce:
            return
        for ag in agents:
            # market makers are SUPPOSED to hold inventory -- don't flag them
            if ag.is_market_maker:
                continue
            stock = ag.qty(Resource.WOOD)
            if stock <= self.cfg.hoard_stock_threshold:
                continue
            sales = self._sales_ema.get(ag.id, 0.0)
            honest_offer = self._honest_offer_ema.get(ag.id, 0.0)
            # Flag only if NEITHER honest offers NOR clearing sales are present.
            # 30% honest-offer-to-stock or 2% actual sales is enough to count as
            # genuinely trying to supply.
            offering = honest_offer > stock * 0.3
            selling = sales > stock * 0.02
            if not (offering or selling):
                self.state.hoard_flags[ag.id] = round(stock, 1)

    def charge_holding_fees(self, agents: list) -> None:
        if not self.state.hoard_flags:
            return
        for ag in agents:
            if ag.id not in self.state.hoard_flags:
                continue
            excess = ag.qty(Resource.WOOD) - self.cfg.hoard_stock_threshold
            if excess > 0:
                fee = min(ag.money, excess * self.cfg.hoard_fee_rate)
                ag.money -= fee
                self.state.total_penalty += fee
