"""
The World: the simulation clock and orchestrator.

Each day, in order:
  1. Accountant publishes its bounty (player-only channel) and resets daily budget.
  2. Production phase. Tool-boosted gathering wires the tool into the lineage
     of the wood it helped produce.
  3. Market phase. Belief-driven (fear-amplified) reservation prices drive
     demand; the call auction clears.
  4. Consumption phase. Wood/food deplete; unmet need is recorded.
  5. Belief update. Villagers' perceived_scarcity rises with own + witnessed
     unmet need, decays otherwise. (This is the seam for knowledge-gated
     beliefs later.)
  6. Surveillance + holding-fee for flagged hoarders.
  7. Metrics.

CRITICAL DESIGN POINT (post-redesign):
  Only the PLAYER receives the AIC's bounty in its Ctx. Villagers' Ctx carries
  an empty bounty -- they are not nudged by the AIC. The crisis is solved (or
  not) by player agency reacting to the bounty; the AIC just measures and pays.
"""
from __future__ import annotations

import random

from accountant import Accountant
from agents import (Asset, BuildWoodlotAction, Ctx, CraftToolAction, GatherAction,
                    InterventionAction, MarketMaker, Player, SpawnSpec, Villager)
from config import Config, Resource, Season
from knowledge import Claim, PropagationEngine, SocialGraph
from lineage import LineageGraph
from market import CallMarket
from metrics import Metrics
import interventions
import problems

_ZERO_UNMET = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}


class World:
    def __init__(
        self,
        cfg: Config,
        player_strategy: str = "responsive",
        population: list | None = None,
    ):
        """
        Construct the world.

          cfg              -- tunable parameters
          player_strategy  -- registered strategy name (or Strategy instance)
          population       -- list[SpawnSpec] of NPCs to create. Defaults to
                              `cfg.n_villagers` villagers if omitted, so all
                              existing scenarios keep working.
        """
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.lineage = LineageGraph()
        self.market = CallMarket()
        self.accountant = Accountant(cfg)
        self.metrics = Metrics(cfg)
        # Layer 1: the world's problem board (typed, located, severity-tracked).
        # Observational -- refreshed from world-state each day, mutates nothing.
        self.problems = problems.build_board(cfg)
        # Layer 3: the pre-authored intervention library (data). Never applied
        # unless a body submits a Perform intent AND cfg.interventions_enabled.
        self.interventions = {iv.key: iv for iv in interventions.build_library(cfg)}
        self._interventions_today: list = []      # this day's attempts, for events
        self.day = 0
        self.ref_price = {r: cfg.intrinsic_value[r] for r in Resource}

        # ----- spawn NPCs from the population registry -----
        # Default population: villagers + one Market Maker (the trading post)
        # so there's always a counterparty for trades. Scenarios can override.
        pop_spec = population if population is not None else [
            SpawnSpec(Villager, cfg.n_villagers, id_prefix="v"),
            SpawnSpec(MarketMaker, 1, id_prefix="mk"),
        ]
        self.agents: list = []
        for spec in pop_spec:
            for i in range(spec.count):
                self.agents.append(spec.cls(spec.make_id(i), cfg, self.rng, **spec.kwargs))

        # ----- the human-player proxy (always present; 'idle' = no engagement) -----
        self.player = Player("PLAYER", cfg, self.rng, strategy=player_strategy)
        self.agents.append(self.player)

        self.by_id = {a.id: a for a in self.agents}
        self.tool_lot_of: dict[str, int] = {}

        # ----- knowledge propagation layer (Stage 3; off by default) -----
        # When enabled, the village-wide "witness" oracle is replaced by beliefs
        # that travel through a social graph. Built with the world rng so runs
        # stay reproducible; NONE of this touches the rng when disabled, so all
        # legacy scenarios remain byte-identical.
        self.prop: PropagationEngine | None = None
        self.scheduled_injections: dict[int, list] = {}
        self.info_acts: list = []            # player-sourced info acts, for scoring
        self.rumour_avg = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}
        if cfg.propagation_enabled:
            # dedicated RNG so gossip shuffles never perturb the economic stream
            self.prop_rng = random.Random(cfg.seed ^ 0x5F3759DF)
            ordinary = [a.id for a in self.agents if not a.is_market_maker]
            hubs = [a.id for a in self.agents if a.is_market_maker]
            graph = SocialGraph(cfg, [a.id for a in self.agents], hubs, self.prop_rng)
            self.prop = PropagationEngine(cfg, graph, self.prop_rng)
        self._active_ids = {a.id for a in self.agents}

        # initialized empty so UI can read on day 0 before first market clearing
        self.last_orders: dict = {r: [] for r in Resource}
        self.last_clearings: dict = {r: None for r in Resource}
        self._player_money_at_day_start: float = self.player.money
        self._player_bonus_at_day_start: float = 0.0

        self._seed_initial_reserves()

    def _seed_initial_reserves(self) -> None:
        """Give everyone a few days of starting reserves.

        Villagers / player / merchants: a few days of basic supplies (provenance "nature").
        Market makers: a larger trading-post inventory (provenance "market") so
        they can act as a liquidity buffer from day 1.
        """
        for ag in self.agents:
            if ag.is_market_maker:
                for r, qty in ((Resource.WOOD, 10.0), (Resource.FOOD, 10.0)):
                    lot = self.lineage.new_lot(r, "market", -1, "gather", qty)
                    ag.add_holding(lot.id, r, qty)
                continue
            for r in (Resource.WOOD, Resource.FOOD):
                need = self.cfg.wood_per_day[Season.SPRING] if r == Resource.WOOD else self.cfg.food_per_day
                qty = need * self.cfg.reserve_buffer_days
                lot = self.lineage.new_lot(r, "nature", -1, "gather", qty)
                ag.add_holding(lot.id, r, qty)

    # ---------- main loop ----------
    def run(self) -> Metrics:
        for day in range(self.cfg.total_days):
            self.day = day
            self.step(day)
        return self.metrics

    def step(self, day: int) -> None:
        """Run a full day. Equivalent to begin_day(day) + execute_day()."""
        self.begin_day(day)
        self.execute_day()

    def begin_day(self, day: int) -> None:
        """
        Publish today's bounty and freeze today's context. This is what the UI
        calls before showing the player their situation, so the AIC's posted
        bounty is visible before the player makes decisions.
        """
        self.day = day
        season = self.cfg.season_for_day(day)
        # Refresh stamina for every agent NOW (not during production phase), so
        # the UI shows the correct stamina BEFORE the player plans actions.
        for ag in self.agents:
            if ag.is_player:
                ag.stamina = getattr(ag, "daily_stamina", self.cfg.stamina_per_day)
            else:
                ag.stamina = self.cfg.stamina_per_day
            # dependents draw a small stipend (their non-wood livelihood)
            if ag.is_dependent:
                ag.money += self.cfg.dependent_stipend
        # Snapshot player wealth/bonus for per-day delta reporting.
        self._player_money_at_day_start = self.player.money
        self._player_bonus_at_day_start = self.player.bonus_earned
        self.accountant.start_day(day, self.agents)
        # Villagers see no bounty (empty dict). Only the player gets the AIC channel.
        # Villagers see no AIC channels -- they react only to market price + fear.
        self._villager_ctx = Ctx(
            cfg=self.cfg,
            day=day,
            season=season,
            wood_need=self.cfg.wood_per_day[season],
            food_need=self.cfg.food_per_day,
            ref_price=dict(self.ref_price),
            bounty={},
            fair_price={},
        )
        # Player has the AIC's fair-value channel (the isekai information edge)
        # and the internal bounty rate for legacy strategies that still read it.
        self._player_ctx = Ctx(
            cfg=self.cfg,
            day=day,
            season=season,
            wood_need=self.cfg.wood_per_day[season],
            food_need=self.cfg.food_per_day,
            ref_price=dict(self.ref_price),
            bounty=dict(self.accountant.state.bounty),
            fair_price=dict(self.accountant.state.fair_price),
        )
        # Layer 1: refresh the problem board from the day's world-state (the
        # accountant's scarcity signal is now fresh). Pure read -- no sim effect.
        problems.refresh(self.problems, self)
        self._interventions_today = []       # reset the day's intervention attempts

    def execute_day(self) -> None:
        """Run today's production -> market -> consumption -> belief -> surveillance."""
        self._production_phase()
        self._market_phase()
        self._consumption_phase()
        self._belief_update_phase()
        self.accountant.observe_sales(self._wood_sales_today)
        self.accountant.update_surveillance(self.agents, self.ref_price[Resource.WOOD],
                                            self.day_unmet[Resource.WOOD])
        self.accountant.charge_holding_fees(self.agents)
        self.metrics.record(self, self._villager_ctx)

    def _ctx_for(self, ag):
        return self._player_ctx if ag.is_player else self._villager_ctx

    # ---------- phases ----------
    def _production_phase(self) -> None:
        # Note: stamina was refreshed in begin_day. Don't reset here -- that
        # would erase any decrements a Strategy made in decide_actions.
        produced = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}
        for ag in self.agents:
            ctx = self._ctx_for(ag)
            for action in ag.decide_actions(ctx):
                if isinstance(action, GatherAction):
                    produced[action.resource] += self._do_gather(ag, action.resource, ctx)
                elif isinstance(action, CraftToolAction):
                    self._do_craft_tool(ag, ctx)
                elif isinstance(action, BuildWoodlotAction):
                    self._do_build_woodlot(ag, ctx)
                elif isinstance(action, InterventionAction):
                    self._do_intervention(ag, action.key, ctx)
        # capital goods run AFTER labour: each woodlot yields wood (fed by upkeep food).
        if self.cfg.capital_goods_enabled:
            produced[Resource.WOOD] += self._run_woodlots()
        for r, q in produced.items():
            self.accountant.observe_production(r, q)

    def _do_build_woodlot(self, ag, ctx: Ctx) -> None:
        """
        Establish (level 1) or UPGRADE a woodlot. Building to level L costs
        `woodlot_wood_cost * L` wood; each level adds `woodlot_wood_output` to the
        daily yield. Provenance is the wood spent, rooted at the woodlot lot so
        realized-effect credit flows to the builder.
        """
        wl = next((a for a in ag.assets if a.kind == "woodlot"), None)
        cur = wl.level if wl else 0
        if cur >= self.cfg.woodlot_max_level:
            return
        cost = self.cfg.woodlot_wood_cost * (cur + 1)
        consumed = ag.take(Resource.WOOD, cost)
        got = sum(q for _, q in consumed)
        if got < cost - 1e-6:
            if got > 0:   # not enough after all -> refund what we took
                lot = self.lineage.new_lot(Resource.WOOD, ag.id, ctx.day, "gather", got)
                ag.add_holding(lot.id, Resource.WOOD, got)
            return
        total = sum(q for _, q in consumed) or 1.0
        parents = [(lid, q / total) for lid, q in consumed]
        if wl is None:
            lot = self.lineage.new_lot(Resource.WOODLOT, ag.id, ctx.day, "build", 1.0, parents=parents)
            ag.assets.append(Asset(kind="woodlot", lot_id=lot.id, built_tick=ctx.day, level=1))
        else:
            wl.level = cur + 1   # upgrade: yield scales; output stays rooted at its lot

    def _do_intervention(self, ag, key: str, ctx: Ctx) -> None:
        """Attempt a pre-authored world-change (Layer 3). Preconditions and the
        authored effect live in interventions.py; the world just dispatches and
        records the attempt so a body can react. No-op unless enabled + accepted."""
        iv = self.interventions.get(key)
        if iv is None:
            self._interventions_today.append((ag.id, key, False, 0.0, "", "unknown intervention"))
            return
        accepted, spent, reason = interventions.perform(self, ag, iv, ctx.day)
        self._interventions_today.append((ag.id, key, accepted, spent, iv.targets, reason))

    def _run_woodlots(self) -> float:
        """
        Each woodlot yields `output * level` wood, provenance rooted at the woodlot
        lot (so realized effect credits its builder). Workers eat `upkeep * level`
        food/day; with no food the woodlot idles. Output lands in the owner's stock.
        """
        total = 0.0
        for ag in self.agents:
            for asset in ag.assets:
                if asset.kind != "woodlot":
                    continue
                upkeep = self.cfg.woodlot_upkeep_food * asset.level
                fed = sum(q for _, q in ag.take(Resource.FOOD, upkeep))
                if fed < upkeep - 1e-6:
                    if fed > 0:   # refund partial food; the woodlot idles
                        lot = self.lineage.new_lot(Resource.FOOD, ag.id, self.day, "gather", fed)
                        ag.add_holding(lot.id, Resource.FOOD, fed)
                    continue
                out = self.cfg.woodlot_wood_output * asset.level
                lot = self.lineage.new_lot(Resource.WOOD, ag.id, self.day, "woodlot", out,
                                           parents=[(asset.lot_id, 1.0)])
                ag.add_holding(lot.id, Resource.WOOD, out)
                total += out
        return total

    def _do_gather(self, ag, r: Resource, ctx: Ctx) -> float:
        base = self.cfg.base_yield[r] * self.cfg.season_yield_mult[ctx.season] * ag.skill[r]
        # A summer food blight (flag-gated OFF by default) cuts food gather yield
        # during its season -- the second-crisis lever. Wood is untouched; only
        # food produced in the blight season shrinks, so a food shortfall builds
        # exactly when winter-wood prep also wants attention.
        if (r == Resource.FOOD and self.cfg.food_blight_enabled
                and ctx.season == self.cfg.food_blight_season):
            base *= self.cfg.food_blight_yield_mult
        parents = []
        if ag.has_tool:
            total = base * (1.0 + self.cfg.tool_yield_bonus)
            extra = total - base
            parents = [(self.tool_lot_of[ag.id], extra / total)]   # tool enabled `extra/total`
            ag.tool_durability_left -= 1
            if ag.tool_durability_left <= 0:
                self.tool_lot_of.pop(ag.id, None)
            yield_qty = total
        else:
            yield_qty = base
        lot = self.lineage.new_lot(r, ag.id, ctx.day, "gather", yield_qty, parents=parents)
        ag.add_holding(lot.id, r, yield_qty)
        return yield_qty

    def _do_craft_tool(self, ag, ctx: Ctx) -> None:
        consumed = ag.take(Resource.WOOD, self.cfg.tool_wood_cost)
        got = sum(q for _, q in consumed)
        if got < self.cfg.tool_wood_cost - 1e-6:
            # not enough after all; put it back as a fresh lot and bail
            if got > 0:
                lot = self.lineage.new_lot(Resource.WOOD, ag.id, ctx.day, "gather", got)
                ag.add_holding(lot.id, Resource.WOOD, got)
            return
        total = sum(q for _, q in consumed) or 1.0
        parents = [(lid, q / total) for lid, q in consumed]   # wood is 100% of the tool's material
        tool_lot = self.lineage.new_lot(Resource.TOOL, ag.id, ctx.day, "craft", 1.0, parents=parents)
        self.tool_lot_of[ag.id] = tool_lot.id
        ag.tool_durability_left = self.cfg.tool_durability

    def _market_phase(self) -> None:
        self._wood_sales_today = {a.id: 0.0 for a in self.agents}
        # per-agent settled trades this day, for truthful buy/sell feedback:
        # _settled[agent_id][resource] = {'sold','sold_val','bought','bought_val'}
        self._settled: dict = {}
        # snapshot of today's order book + clearings so the UI can explain
        # why the player's orders did or didn't clear.
        self.last_orders: dict = {r: [] for r in Resource}
        self.last_clearings: dict = {r: None for r in Resource}
        orders = []
        for ag in self.agents:
            orders.extend(ag.make_orders(self._ctx_for(ag)))
        # Honest wood sell offers: sell orders at <= 1.5x current ref price.
        # (Fake offers at unreachable prices don't count -- prevents the
        # "post ask at 25 to look like a seller" exploit.)
        honest_price_cap = self.ref_price[Resource.WOOD] * 1.5
        honest_offers = {a.id: 0.0 for a in self.agents}
        for o in orders:
            if (o.resource == Resource.WOOD and o.side == "sell"
                    and o.price <= honest_price_cap):
                honest_offers[o.agent_id] += o.qty
        self.accountant.observe_honest_offers(honest_offers)
        for r in (Resource.WOOD, Resource.FOOD):
            res_orders = [o for o in orders if o.resource == r]
            self.last_orders[r] = res_orders
            demand = sum(o.qty for o in res_orders if o.side == "buy")
            supply = sum(o.qty for o in res_orders if o.side == "sell")
            clearing = self.market.clear(r, res_orders)
            self.last_clearings[r] = clearing
            if clearing.volume > 1e-9:
                self._settle(clearing)
                a = self.cfg.price_smoothing
                self.ref_price[r] = (1 - a) * self.ref_price[r] + a * clearing.price
            # excess-demand / excess-supply drift (works even when nothing clears):
            # a glut pushes price down, scarcity pushes it up -> chokes overproduction.
            imbalance = (demand - supply) / (demand + supply + 1e-6)
            self.ref_price[r] *= (1.0 + self.cfg.price_imbalance_k * imbalance)
            lo = self.cfg.intrinsic_value[r] * self.cfg.price_floor_mult
            hi = self.cfg.intrinsic_value[r] * self.cfg.price_cap_mult
            self.ref_price[r] = max(lo, min(hi, self.ref_price[r]))

    def _settle(self, clearing) -> None:
        for t in clearing.trades:
            buyer, seller = self.by_id[t.buyer_id], self.by_id[t.seller_id]
            cost = t.qty * t.price
            if buyer.money < cost - 1e-6:
                # clamp to what the buyer can actually afford
                t_qty = buyer.money / max(t.price, 1e-6)
            else:
                t_qty = t.qty
            if t_qty <= 1e-6:
                continue
            moved = seller.take(t.resource, t_qty)
            actually = sum(q for _, q in moved)
            for lot_id, q in moved:
                buyer.add_holding(lot_id, t.resource, q)
            pay = actually * t.price
            buyer.money -= pay
            seller.money += pay
            if t.resource == Resource.WOOD:
                self._wood_sales_today[t.seller_id] = (
                    self._wood_sales_today.get(t.seller_id, 0.0) + actually
                )
            sd = self._settled.setdefault(t.seller_id, {}).setdefault(
                t.resource, {"sold": 0.0, "sold_val": 0.0, "bought": 0.0, "bought_val": 0.0})
            sd["sold"] += actually; sd["sold_val"] += pay
            bd = self._settled.setdefault(t.buyer_id, {}).setdefault(
                t.resource, {"sold": 0.0, "sold_val": 0.0, "bought": 0.0, "bought_val": 0.0})
            bd["bought"] += actually; bd["bought_val"] += pay

    def _consumption_phase(self) -> None:
        self.day_unmet = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}
        self.day_short_agents = 0
        self.village_unmet = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}  # villagers only
        self._per_agent_unmet = {}
        for ag in self.agents:
            ctx = self._ctx_for(ag)
            result = ag.consume_daily(ctx)
            short_today = False
            own_unmet = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}
            for r in (Resource.WOOD, Resource.FOOD):
                _, shortfall = result[r]
                own_unmet[r] = shortfall
                self.day_unmet[r] += shortfall
                if not ag.is_player and not ag.is_market_maker:
                    self.village_unmet[r] += shortfall
                if shortfall > 1e-6:
                    short_today = True
            self._per_agent_unmet[ag.id] = own_unmet
            if short_today:
                self.day_short_agents += 1
            # A resource consumed to meet a registered need = realized stabilising
            # effect -> pay its producers up the lineage. Driven by the need
            # registry, so this is identical for wood, food, or any future need --
            # no per-resource code. (Today only wood is a rewarded need by default.)
            for need in self.accountant.rewarded_needs():
                consumed_lots, _ = result[need.resource]
                self.accountant.reward_consumption(
                    need.resource, ag.id, consumed_lots, ctx.season, self.lineage, self.by_id
                )

    # ---------- knowledge propagation API ----------
    def schedule_injection(self, day: int, target: str, claim: Claim,
                           authority: float = 1.0, by_player: bool = False) -> None:
        """
        Queue a claim to be injected into `target` (an agent id, or "random"/
        "hub") on `day`. `by_player` marks it as the player's information act so
        the AIC can later score it as contribution or disinformation.
        """
        self.scheduled_injections.setdefault(day, []).append(
            (target, claim, authority, by_player))

    def _resolve_target(self, target: str) -> str:
        if target == "hub":
            hubs = [a.id for a in self.agents if a.is_market_maker]
            return hubs[0] if hubs else self.agents[0].id
        if target == "random":
            villagers = [a.id for a in self.agents
                         if not a.is_player and not a.is_market_maker]
            return self.prop_rng.choice(villagers)
        return target

    def _belief_update_phase(self) -> None:
        """
        Update villagers' perceived_scarcity.

        Legacy path (propagation OFF): fear rises from felt shortage + the
        village-wide unmet ORACLE -- every villager reads the whole village's
        pain instantly. Kept byte-identical so validated scenarios don't move.

        Propagation path (ON): the oracle is gone. A villager's non-personal
        fear comes only from what GOSSIP has carried to them. Two ways a belief
        enters the network:
          * a personally-felt shortage -> a first-hand, INDEPENDENT witness
            (its own root), so many hungry villagers corroborate into strong,
            credible belief;
          * a scheduled injection (an event, a source, or the PLAYER's claim) ->
            which may be objectively TRUE or FALSE.
        The engine then spreads, attenuates, and decays those beliefs.
        """
        if self.prop is None:
            for ag in self.agents:
                if ag.is_player or ag.is_market_maker:
                    continue
                ag.update_belief(self._per_agent_unmet.get(ag.id, {}), self.village_unmet)
            return

        # 1. real personal shortage = a first-hand independent witness of scarcity
        for ag in self.agents:
            if ag.is_player or ag.is_market_maker:
                continue
            own = self._per_agent_unmet.get(ag.id, {})
            for r in (Resource.WOOD, Resource.FOOD):
                felt = own.get(r, 0.0)
                if felt > 1e-3:
                    mag = min(1.0, felt / max(self.cfg.wood_per_day[self.cfg.season_for_day(self.day)]
                                             if r == Resource.WOOD else self.cfg.food_per_day, 1e-6))
                    self.prop.inject(ag.id, Claim(r, mag, True, f"witness:{ag.id}:{r.value}", self.day),
                                     authority=1.0, day=self.day)

        # 2. scheduled injections (events / sources / player claims) for today
        for target, claim, authority, by_player in self.scheduled_injections.get(self.day, ()):  # noqa: E501
            aid = self._resolve_target(target)
            self.prop.inject(aid, claim, authority=authority, day=self.day)
            if by_player:
                self.info_acts.append((self.day, claim))

        # 3. spread one hop, then decay stale beliefs
        self.prop.step(self.day, self._active_ids)
        self.prop.decay()

        # 4. beliefs -> behaviour: feed each villager's GOSSIPED scarcity into fear
        #    (the oracle witness term is passed as zero -- it no longer exists)
        for ag in self.agents:
            if ag.is_player or ag.is_market_maker:
                continue
            rumour = {r: self.prop.scarcity(ag.id, r) for r in (Resource.WOOD, Resource.FOOD)}
            ag.update_belief(self._per_agent_unmet.get(ag.id, {}), _ZERO_UNMET, rumour=rumour)

        villagers = [a for a in self.agents if not a.is_player and not a.is_market_maker]
        vids = {a.id for a in villagers}
        for r in (Resource.WOOD, Resource.FOOD):
            self.rumour_avg[r] = self.prop.avg_scarcity(r, vids)
