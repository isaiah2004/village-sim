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
from needs import Need, build_registry


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
    # The forecast scarcity ratio (0..1) per resource -- the same signal that sets
    # fair value. Exposed so Layer 1's problem model can read a scarcity problem's
    # severity from the index's OWN measure. Observational; recomputed each day.
    scarcity: dict = field(default_factory=dict)
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
        # The registry of needs the index prices/rewards -- DATA, assembled from
        # config. All pricing and payout below is driven by this list, with no
        # per-resource branching, so a new need is a registry row, not new code.
        self.needs: list[Need] = build_registry(cfg)
        _sc = getattr(cfg, "scenario", None)
        _rids = list(_sc.resource_ids()) if _sc is not None else list(Resource)
        _cons = _sc.consumable_ids() if _sc is not None else [Resource.WOOD, Resource.FOOD]
        self.state = AccountantState(
            bounty={r: 0.0 for r in _rids},
            fair_price={r: cfg.intrinsic_value.get(r, 0.0) for r in _rids},
        )
        # rolling estimate of daily production per resource (observed only)
        self._prod_ema = {
            r: cfg.n_villagers * cfg.base_yield.get(r, 0.0) * 0.4 for r in _cons
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
            _rids = list(self.cfg.scenario.resource_ids())
            self.state.bounty = {r: 0.0 for r in _rids}
            self.state.fair_price = {r: self.cfg.intrinsic_value.get(r, 0.0) for r in _rids}
            self.state.scarcity = {r: 0.0 for r in _rids}
            return
        driver = self.cfg.scenario.driver           # yield modulation is data (DESIGN.md)
        # Price every registered need uniformly -- the need carries its own
        # requirement (severity source), so there is no per-resource logic here.
        for need in self.needs:
            r = need.resource
            reserves = sum(ag.qty(r) for ag in agents)
            # count only the agents who actually hold this need: a universal need
            # is every agent (frostpine, byte-identical); a demand-scoped need is
            # just its consumers (e.g. one war quartermaster), so scarcity isn't
            # inflated as if the whole town needed the good.
            n = sum(1 for ag in agents if r in getattr(ag, "need_ids", ()))
            projected_consumption = self._projected_consumption(need, day, n)
            # The AIC's view of capacity is pessimistic so it doesn't behave as
            # a perfect oracle: it under-estimates how much villagers can produce.
            today_mult = driver.yield_mult(day, r)
            base_capacity = (self._prod_ema[r] / max(today_mult, 1e-6)) * self.cfg.accountant_pessimism
            projected_production = sum(
                base_capacity * driver.yield_mult(d, r)
                for d in range(day, day + self.cfg.accountant_horizon)
            )
            deficit = projected_consumption - (reserves + projected_production)
            ratio = max(0.0, min(1.0, deficit / max(projected_consumption, 1e-6)))
            self.state.predicted_deficit[r] = deficit
            self.state.scarcity[r] = ratio       # Layer 1 reads this as problem severity
            self.state.bounty[r] = round(self.cfg.accountant_bounty_max * ratio, 3)
            # Fair value: intrinsic, lifted by scarcity. Player compares this
            # to the actual market price to spot under/over-valued goods.
            #   no scarcity  -> fair == intrinsic
            #   full scarcity -> fair == 3 x intrinsic
            self.state.fair_price[r] = round(
                self.cfg.intrinsic_value[r] * (1.0 + 2.0 * ratio), 2
            )

    def rewarded_needs(self) -> list[Need]:
        """The needs whose met demand pays realized-effect contribution."""
        return [need for need in self.needs if need.rewarded]

    def _projected_consumption(self, need: Need, day: int, n_agents: int) -> float:
        return sum(n_agents * need.daily_requirement(self.cfg, d)
                   for d in range(day, day + self.cfg.accountant_horizon))

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
                    (producer_id, consumer_id, consumer_kind, resource, amount, rate,
                     season.value if hasattr(season, "value") else season))

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
        Flag agents who hold a large stockpile of the crisis good while the
        village is in scarcity AND who are not actively releasing it to the
        market. We look at SALES (external release) rather than total stock
        change, so an agent can't hide a hoard by burning some of it themselves.
        The policed good is the scenario's primary resource (frostpine: wood).
        """
        primary = self.cfg.scenario.primary_resource
        scarce = (wood_price > self.cfg.intrinsic_value[primary] * self.cfg.scarcity_price_mult
                  or unmet_wood > 1e-6)
        self.state.hoard_flags = {}
        if not scarce:
            return
        for ag in agents:
            # market makers and off-town institutions are SUPPOSED to hold/absorb
            # inventory -- don't flag them
            if ag.is_market_maker or getattr(ag, "is_institution", False):
                continue
            stock = ag.qty(primary)
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
        primary = self.cfg.scenario.primary_resource
        for ag in agents:
            if ag.id not in self.state.hoard_flags:
                continue
            excess = ag.qty(primary) - self.cfg.hoard_stock_threshold
            if excess > 0:
                fee = min(ag.money, excess * self.cfg.hoard_fee_rate)
                ag.money -= fee
                self.state.total_penalty += fee
