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
from agents import (AcceptDealAction, Asset, BuildWoodlotAction, Ctx, CraftToolAction,
                    GatherAction, InterventionAction, Loan, MarketMaker, Order, Player,
                    SpawnSpec, Villager, is_resident)
from config import Config, Resource, Season
from knowledge import Claim, PropagationEngine, SocialGraph
from lineage import LineageGraph
from market import CallMarket
from metrics import Metrics
from reputation import ReputationNetwork as _Reputation
import interventions
import problems

_ZERO_UNMET = {Resource.WOOD: 0.0, Resource.FOOD: 0.0}

# the guild's price-support purchases (MarketSpec.model == 'guild') settle to this
# reserved buyer id: the goods are EXPORTED (removed from circulation), never held
# by any agent, so the guild floors producer income without hoarding supply.
GUILD_SINK_ID = "__guild_sink__"


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
        # DESIGN.md: scenarios are DATA. Attach the live Scenario (from cfg if
        # make_config set it, else by name) BEFORE anything reads its axes, and
        # expose the driver + resource sets the mechanics iterate. A bare Config()
        # resolves to "frostpine" -> the historical baseline, byte-identical.
        import scenario as _scen
        self.scenario = getattr(cfg, "scenario", None) or _scen.get_scenario(
            getattr(cfg, "scenario_name", "frostpine"))
        cfg.scenario = self.scenario
        self.driver = self.scenario.driver
        self.resource_ids = tuple(self.scenario.resource_ids())
        self.consumable_ids = tuple(self.scenario.consumable_ids())
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
        self._deals_today: list = []              # this day's AcceptDeal outcomes
        self._loan_events: list = []              # this day's loan repayments/defaults
        self.day = 0
        self.ref_price = {r: cfg.intrinsic_value.get(r, 0.0) for r in self.resource_ids}

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
        self.rumour_avg = {r: 0.0 for r in self.consumable_ids}
        if cfg.propagation_enabled:
            # dedicated RNG so gossip shuffles never perturb the economic stream
            self.prop_rng = random.Random(cfg.seed ^ 0x5F3759DF)
            ordinary = [a.id for a in self.agents if not a.is_market_maker]
            hubs = [a.id for a in self.agents if a.is_market_maker]
            graph = SocialGraph(cfg, [a.id for a in self.agents], hubs, self.prop_rng)
            self.prop = PropagationEngine(cfg, graph, self.prop_rng)
        self._active_ids = {a.id for a in self.agents}

        # ----- reputation propagation (Layer 3; off by default) -----
        # Deeds spread through the SAME kind of social graph as scarcity news, but
        # on a DEDICATED rng and graph so the economic/gossip streams stay
        # byte-identical. Standing then = realized contribution x how far word of
        # the agent's deeds has reached (reputation.py). Untouched when the flag is
        # off, so every existing scenario is unchanged.
        self.reputation = None
        if cfg.reputation_propagation:
            self.rep_rng = random.Random(cfg.seed ^ 0x2545F491)
            hubs = [a.id for a in self.agents if a.is_market_maker]
            rep_graph = SocialGraph(cfg, [a.id for a in self.agents], hubs, self.rep_rng)
            self.reputation = _Reputation(cfg, rep_graph, self.rep_rng)

        # initialized empty so UI can read on day 0 before first market clearing
        self.last_orders: dict = {r: [] for r in self.resource_ids}
        self.last_clearings: dict = {r: None for r in self.resource_ids}
        self._player_money_at_day_start: float = self.player.money
        self._player_bonus_at_day_start: float = 0.0

        self._seed_initial_reserves()

    def resident_ids(self) -> set:
        """The townspeople 'the village' is measured over (villagers + dependents):
        not the player, the market maker, or an off-town institution. Used as the
        denominator for reputation reach -- how far word has reached the town."""
        return {a.id for a in self.agents if is_resident(a)}

    def _seed_initial_reserves(self) -> None:
        """Give everyone a few days of starting reserves.

        Villagers / player / merchants: a few days of basic supplies (provenance "nature").
        Market makers: a larger trading-post inventory (provenance "market") so
        they can act as a liquidity buffer from day 1.
        """
        for ag in self.agents:
            if ag.is_market_maker:
                for r in self.consumable_ids:
                    qty = 10.0
                    lot = self.lineage.new_lot(r, "market", -1, "gather", qty)
                    ag.add_holding(lot.id, r, qty)
                continue
            for r in self.consumable_ids:
                rspec = self.scenario.resource(r)
                need = rspec.base_consume * self.driver.consume_mult(0, r)
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
        # The active driver's phase drives time, needs, and gather yields (DESIGN.md
        # "Drivers"). For frostpine the phase name is the season and these values
        # reproduce the historical season tables exactly (byte-identical).
        season = self.driver.phase_name(day)
        needs = {r: self.scenario.resource(r).base_consume * self.driver.consume_mult(day, r)
                 for r in self.consumable_ids}
        ymult = {r: self.driver.yield_mult(day, r) for r in self.resource_ids}
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
            wood_need=needs.get(Resource.WOOD, 0.0),
            food_need=needs.get(Resource.FOOD, 0.0),
            ref_price=dict(self.ref_price),
            needs=needs, consumables=self.consumable_ids, yield_mult=ymult,
            bounty={},
            fair_price={},
        )
        # Player has the AIC's fair-value channel (the isekai information edge)
        # and the internal bounty rate for legacy strategies that still read it.
        self._player_ctx = Ctx(
            cfg=self.cfg,
            day=day,
            season=season,
            wood_need=needs.get(Resource.WOOD, 0.0),
            food_need=needs.get(Resource.FOOD, 0.0),
            ref_price=dict(self.ref_price),
            needs=needs, consumables=self.consumable_ids, yield_mult=ymult,
            bounty=dict(self.accountant.state.bounty),
            fair_price=dict(self.accountant.state.fair_price),
        )
        # Layer 1: refresh the problem board from the day's world-state (the
        # accountant's scarcity signal is now fresh). Pure read -- no sim effect.
        problems.refresh(self.problems, self)
        self._interventions_today = []       # reset the day's intervention attempts
        self._deals_today = []               # reset the day's deal outcomes
        self._loan_events = []               # reset the day's loan repayments/defaults

    def execute_day(self) -> None:
        """Run today's production -> market -> consumption -> belief -> surveillance."""
        self._production_phase()
        self._market_phase()
        self._consumption_phase()
        self._belief_update_phase()
        self.accountant.observe_sales(self._wood_sales_today)
        _primary = self.scenario.primary_resource
        self.accountant.update_surveillance(self.agents, self.ref_price[_primary],
                                            self.day_unmet.get(_primary, 0.0))
        self.accountant.charge_holding_fees(self.agents)
        self._loan_phase()
        self._reputation_phase()
        self.metrics.record(self, self._villager_ctx)

    def _reputation_phase(self) -> None:
        """Deeds spread (Layer 3). Each agent's realized contribution to date is
        refreshed as a first-hand deed fact at their own node, then word travels
        one hop through the reputation graph and stale word decays. No-op unless
        reputation propagation is enabled -> golden byte-identical."""
        if self.reputation is None:
            return
        for ag in self.agents:
            if ag.is_market_maker or getattr(ag, "is_institution", False):
                continue                       # the market/institutions don't build personal repute
            self.reputation.record_deed(ag.id, getattr(ag, "bonus_earned", 0.0), self.day)
        self.reputation.step(self.day, self._active_ids)
        self.reputation.decay()

    def _ctx_for(self, ag):
        return self._player_ctx if ag.is_player else self._villager_ctx

    # ---------- phases ----------
    def _production_phase(self) -> None:
        # Note: stamina was refreshed in begin_day. Don't reset here -- that
        # would erase any decrements a Strategy made in decide_actions.
        produced = {r: 0.0 for r in self.consumable_ids}
        for ag in self.agents:
            ctx = self._ctx_for(ag)
            for action in ag.decide_actions(ctx):
                if isinstance(action, GatherAction):
                    produced[action.resource] = produced.get(action.resource, 0.0) \
                        + self._do_gather(ag, action.resource, ctx)
                elif isinstance(action, CraftToolAction):
                    self._do_craft_tool(ag, ctx)
                elif isinstance(action, BuildWoodlotAction):
                    self._do_build_woodlot(ag, ctx)
                elif isinstance(action, InterventionAction):
                    self._do_intervention(ag, action.key, ctx)
                elif isinstance(action, AcceptDealAction):
                    self._do_accept_deal(ag, action, ctx)
        # capital goods run AFTER labour: each capital good yields its output
        # resource (frostpine's woodlot -> wood, fed by upkeep food). Outputs are
        # data (scenario.capital) or an intervention-founded producer's own spec
        # (an open_trade_route trade route), so this is not wood-specific and works
        # even in worlds with no scenario.capital of their own.
        if self.cfg.capital_goods_enabled:
            for out_res, q in self._run_woodlots().items():
                produced[out_res] = produced.get(out_res, 0.0) + q
        for r, q in produced.items():
            self.accountant.observe_production(r, q)

    def _capital_spec(self, kind: str | None = None):
        """The scenario's capital-good DATA (CapitalSpec). Defaults to the primary
        capital good; `kind` selects a specific one. frostpine's is the woodlot;
        emberforge's is the forge -- same generic machinery, different values."""
        caps = self.scenario.capital
        if not caps:
            return None
        if kind is None:
            return caps[0]
        return next((c for c in caps if c.kind == kind), None)

    def _do_build_woodlot(self, ag, ctx: Ctx) -> None:
        """
        Establish (level 1) or UPGRADE the scenario's capital good. Building to
        level L costs `build_cost * L` of the build resource; each level adds
        `output_per_level` to the daily yield. All values are DATA (CapitalSpec),
        so this is generic -- frostpine's woodlot (wood-built, wood-yielding) and
        emberforge's forge are the same code. Provenance is the resource spent,
        rooted at the asset lot so realized-effect credit flows to the builder.
        """
        spec = self._capital_spec()
        if spec is None:
            return
        wl = next((a for a in ag.assets if a.kind == spec.kind), None)
        cur = wl.level if wl else 0
        if cur >= spec.max_level:
            return
        cost = spec.build_cost * (cur + 1)
        consumed = ag.take(spec.build_cost_resource, cost)
        got = sum(q for _, q in consumed)
        if got < cost - 1e-6:
            if got > 0:   # not enough after all -> refund what we took
                lot = self.lineage.new_lot(spec.build_cost_resource, ag.id, ctx.day, "gather", got)
                ag.add_holding(lot.id, spec.build_cost_resource, got)
            return
        total = sum(q for _, q in consumed) or 1.0
        parents = [(lid, q / total) for lid, q in consumed]
        if wl is None:
            lot = self.lineage.new_lot(spec.kind, ag.id, ctx.day, "build", 1.0, parents=parents)
            ag.assets.append(Asset(kind=spec.kind, lot_id=lot.id, built_tick=ctx.day, level=1))
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

    def _do_accept_deal(self, ag, action, ctx: Ctx) -> None:
        """Conclude a negotiated loan-financed deal (Layer 3), the HARD gate. Terms
        arrive already negotiated (edge-side); the sim clamps them, re-checks the
        intervention's preconditions and the merchant's capital, records the loan,
        credits the principal, and applies the authored effect -- or rejects with a
        reason. A negotiated 'yes' can never override a failed precondition here."""
        key, mid = action.key, action.merchant_id
        principal = max(0.0, float(action.principal))
        interest = max(0.0, min(float(action.interest), self.cfg.loan_max_interest))   # clamp
        term = max(1, min(int(action.term_days), self.cfg.loan_max_term_days))         # clamp

        def reject(reason):
            self._deals_today.append((ag.id, mid, key, False, 0.0, 0.0, 0, reason))

        if not self.cfg.interventions_enabled:
            return reject("interventions disabled")
        if not self.cfg.loans_enabled:
            return reject("loans disabled")
        iv = self.interventions.get(key)
        if iv is None:
            return reject("unknown intervention")
        merchant = self.by_id.get(mid)
        if merchant is None or not merchant.is_market_maker:
            return reject("no such merchant")
        if merchant.money < principal:
            return reject("merchant lacks capital")
        # non-capital preconditions still hold; the loan supplies the capital.
        ok, reason = interventions.evaluate(self, ag, iv, extra_capital=principal)
        if not ok:
            return reject(reason)
        # strike: the merchant lends, the borrower records the debt, the effect fires.
        merchant.money -= principal
        ag.money += principal
        loan = Loan(mid, principal, interest, term, ctx.day, balance=round(principal * (1.0 + interest), 6))
        ag.loans.append(loan)
        accepted, _spent, r2 = interventions.perform(self, ag, iv, ctx.day)
        if not accepted:                       # unwind if the effect somehow fails
            ag.money -= principal
            merchant.money += principal
            ag.loans.pop()
            return reject(r2 or "intervention failed")
        self._deals_today.append((ag.id, mid, key, True, principal, interest, term, ""))

    def _loan_phase(self) -> None:
        """Deterministic daily loan servicing (Layer 3). Each active loan takes an
        equal installment; a borrower who cannot pay defaults (the lender seizes
        what cash it can toward the balance, and the loan is marked defaulted -- a
        black mark the reputation model will later propagate). No-op when disabled,
        so validated scenarios stay byte-identical."""
        if not self.cfg.loans_enabled:
            return
        for ag in self.agents:
            for loan in ag.loans:
                if loan.defaulted or loan.balance <= 1e-9:
                    continue
                pay = min(loan.per_day, loan.balance)
                lender = self.by_id.get(loan.lender_id)
                if ag.money + 1e-9 >= pay:
                    ag.money -= pay
                    loan.balance = round(loan.balance - pay, 6)
                    if lender is not None:
                        lender.money += pay
                    kind = "paid_off" if loan.balance <= 1e-9 else "repaid"
                    self._loan_events.append((ag.id, loan.lender_id, kind, round(pay, 6), loan.balance))
                else:
                    seized = max(0.0, ag.money)          # can't make the installment -> default
                    ag.money -= seized
                    if lender is not None:
                        lender.money += seized
                    loan.balance = round(max(0.0, loan.balance - seized), 6)
                    loan.defaulted = True
                    self._loan_events.append((ag.id, loan.lender_id, "defaulted", round(seized, 6), loan.balance))
                    # a default is a DEED too -- a bad one. Word of it spreads through
                    # the reputation network and discounts the defaulter's standing
                    # (DESIGN.md's "a reputation hit that propagates"). No-op unless
                    # reputation propagation is on -> golden-safe.
                    if self.reputation is not None:
                        self.reputation.record_default(ag.id, self.day)

    def _run_woodlots(self) -> dict:
        """
        Run every capital good the scenario defines. Each asset yields
        `output_per_level * level` of its output resource, provenance rooted at the
        asset lot (so realized effect credits its builder). Its workers eat
        `upkeep_per_level * level` of the upkeep resource per day; with no upkeep
        the asset idles. Output lands in the owner's stock. All values are DATA
        (CapitalSpec) -- frostpine's woodlot (food -> wood) and emberforge's forge
        are the same loop. Returns {output_resource: total produced}.
        """
        totals: dict = {}
        cap_kinds = {s.kind for s in self.scenario.capital}
        for spec in self.scenario.capital:
            for ag in self.agents:
                for asset in ag.assets:
                    if asset.kind != spec.kind:
                        continue
                    self._run_one_asset(
                        ag, asset, spec.output_resource, spec.output_per_level,
                        spec.upkeep_resource, spec.upkeep_per_level, spec.kind, totals)
        # intervention-founded producers that carry their OWN spec (e.g. an
        # open_trade_route trade route) -- run generically, no scenario.capital row.
        for ag in self.agents:
            for asset in ag.assets:
                if asset.kind in cap_kinds or not getattr(asset, "output_resource", None):
                    continue
                self._run_one_asset(
                    ag, asset, asset.output_resource, asset.output_per_level,
                    asset.upkeep_resource, asset.upkeep_per_level, asset.kind, totals)
        return totals

    def _run_one_asset(self, ag, asset, out_res, out_per_level, up_res, up_per_level,
                       kind: str, totals: dict) -> None:
        """Run one producing asset: eat upkeep (if any), yield output rooted at the
        asset lot so realized-effect credit flows to its owner."""
        if up_res and up_per_level:
            upkeep = up_per_level * asset.level
            fed = sum(q for _, q in ag.take(up_res, upkeep))
            if fed < upkeep - 1e-6:
                if fed > 0:   # refund partial upkeep; the asset idles
                    lot = self.lineage.new_lot(up_res, ag.id, self.day, "gather", fed)
                    ag.add_holding(lot.id, up_res, fed)
                return
        out = out_per_level * asset.level
        lot = self.lineage.new_lot(out_res, ag.id, self.day, kind, out,
                                   parents=[(asset.lot_id, 1.0)])
        ag.add_holding(lot.id, out_res, out)
        totals[out_res] = totals.get(out_res, 0.0) + out

    def _do_gather(self, ag, r: Resource, ctx: Ctx) -> float:
        mult = ctx.yield_mult.get(r, 1.0) if ctx.yield_mult else self.cfg.season_yield_mult[ctx.season]
        base = self.cfg.base_yield[r] * mult * ag.skill[r]
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
        self.last_orders: dict = {r: [] for r in self.resource_ids}
        self.last_clearings: dict = {r: None for r in self.resource_ids}
        orders = []
        for ag in self.agents:
            orders.extend(ag.make_orders(self._ctx_for(ag)))
        orders.extend(self._guild_support_orders())     # guild market model (data-selected)
        # Honest wood sell offers: sell orders at <= 1.5x current ref price.
        # (Fake offers at unreachable prices don't count -- prevents the
        # "post ask at 25 to look like a seller" exploit.)
        primary = self.scenario.primary_resource        # anti-hoard watches the crisis good
        honest_price_cap = self.ref_price[primary] * 1.5
        honest_offers = {a.id: 0.0 for a in self.agents}
        for o in orders:
            if (o.resource == primary and o.side == "sell"
                    and o.price <= honest_price_cap):
                honest_offers[o.agent_id] += o.qty
        self.accountant.observe_honest_offers(honest_offers)
        for r in self.consumable_ids:
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

    def _guild_support_orders(self) -> list:
        """The guild market model (MarketSpec.model == 'guild') as DATA: the guild
        hall posts a standing SUPPORT BID at a capped floor `price` for up to
        `quota` units of the covered good. It clears through the ORDINARY auction,
        so it only wins supply when the market price is at/below the floor (a
        peacetime glut) and steps aside whenever real demand lifts the price above
        it (the war window). Whatever it buys is EXPORTED (see GUILD_SINK_ID in
        _settle) -- the guild is a buyer of last resort shipping goods away, NOT a
        reseller whose stockpile would mask the town's true supply. No-op for
        call_auction scenarios; a data-selected participant, not a scenario branch."""
        spec = self.scenario.market
        if spec.model != "guild":
            return []
        p = spec.params
        resource = p.get("resource", self.scenario.primary_resource)
        quota = float(p.get("quota", 0.0))
        price = float(p.get("price", self.cfg.intrinsic_value.get(resource, 0.0)))
        if quota <= 1e-9 or price <= 1e-9:
            return []
        return [Order(GUILD_SINK_ID, resource, "buy", quota, price)]

    def _settle(self, clearing) -> None:
        for t in clearing.trades:
            if t.buyer_id == GUILD_SINK_ID:
                # guild price-support: pay the seller at the floor and EXPORT the
                # goods (they leave the economy -- no buyer holds them). This is
                # what stops the support from masking the town's real supply.
                seller = self.by_id[t.seller_id]
                moved = seller.take(t.resource, t.qty)
                actually = sum(q for _, q in moved)
                if actually <= 1e-6:
                    continue
                pay = actually * t.price
                seller.money += pay
                if t.resource == self.scenario.primary_resource:
                    self._wood_sales_today[t.seller_id] = (
                        self._wood_sales_today.get(t.seller_id, 0.0) + actually)
                sd = self._settled.setdefault(t.seller_id, {}).setdefault(
                    t.resource, {"sold": 0.0, "sold_val": 0.0, "bought": 0.0, "bought_val": 0.0})
                sd["sold"] += actually; sd["sold_val"] += pay
                continue
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
            if t.resource == self.scenario.primary_resource:
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
        self.day_unmet = {r: 0.0 for r in self.consumable_ids}
        self.day_short_agents = 0
        self.village_unmet = {r: 0.0 for r in self.consumable_ids}  # villagers only
        self._per_agent_unmet = {}
        for ag in self.agents:
            ctx = self._ctx_for(ag)
            result = ag.consume_daily(ctx)
            short_today = False
            own_unmet = {r: 0.0 for r in self.consumable_ids}
            for r in self.consumable_ids:
                _, shortfall = result[r]
                own_unmet[r] = shortfall
                self.day_unmet[r] += shortfall
                if is_resident(ag):
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
            villagers = [a.id for a in self.agents if is_resident(a)]
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
                ag.update_belief(self._per_agent_unmet.get(ag.id, {}), self.village_unmet, consumables=self.consumable_ids)
            return

        # 1. real personal shortage = a first-hand independent witness of scarcity
        for ag in self.agents:
            if ag.is_player or ag.is_market_maker:
                continue
            own = self._per_agent_unmet.get(ag.id, {})
            for r in self.consumable_ids:
                felt = own.get(r, 0.0)
                if felt > 1e-3:
                    need_r = self._villager_ctx.needs.get(r, 1.0)
                    mag = min(1.0, felt / max(need_r, 1e-6))
                    rid = r.value if hasattr(r, "value") else r
                    self.prop.inject(ag.id, Claim(r, mag, True, f"witness:{ag.id}:{rid}", self.day),
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
            rumour = {r: self.prop.scarcity(ag.id, r) for r in self.consumable_ids}
            ag.update_belief(self._per_agent_unmet.get(ag.id, {}), _ZERO_UNMET, rumour=rumour, consumables=self.consumable_ids)

        villagers = [a for a in self.agents if is_resident(a)]
        vids = {a.id for a in villagers}
        for r in self.consumable_ids:
            self.rumour_avg[r] = self.prop.avg_scarcity(r, vids)
