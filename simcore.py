"""
SimCore -- the engine-agnostic reference facade (Phase 1).

Wraps the validated `World` behind the contract in `contract.py`. A game body
(the 2D fun-test, later Unreal) talks ONLY to this: submit intents, step, read a
snapshot, drain events, query. It never touches the engine internals -- which is
what keeps the contribution accounting honest (the "wall") and lets the same core
run under any renderer.

Turn loop (matches how a tick-based game drives it):

    core = SimCore(propagation=False)
    while not core.done:
        snap = core.begin_turn()          # publish the day, freeze context
        # ... a body reads `snap`, decides, and submits the player's intents ...
        core.submit(Gather(Resource.WOOD))
        core.commit_turn()                # apply intents + advance the world
        for ev in core.drain_events(): ...

`step()` is the convenience combination of begin_turn + commit_turn.

The player is driven by ContractStrategy: it does exactly what intents say and
nothing on its own. NPCs remain autonomous inside the World. Determinism is
inherited from the World (seeded); submitting the same intents in the same order
yields the same run.
"""
from __future__ import annotations

from agents import (AcceptDealAction, BuildWoodlotAction, CraftToolAction, GatherAction,
                    InterventionAction, Order, Strategy)
from config import Config, Resource
from world import World
import contract as C


def _rv(r):
    """Render a resource id as a plain string (tolerates str-enum or bare str)."""
    return r.value if hasattr(r, "value") else r


class ContractStrategy(Strategy):
    """Player strategy that acts purely from externally submitted intents."""
    name = "contract"
    daily_stamina_mult = 3.0

    def __init__(self) -> None:
        self.q_actions: list = []    # GatherAction / CraftToolAction, in order
        self.q_orders: list = []     # Order

    def decide_actions(self, ag, ctx):
        # honour intents up to available stamina (a body may over-queue safely)
        allowed = int(ag.stamina // ag.cfg.effort_per_gather)
        used, rest, spent = [], [], 0
        for a in self.q_actions:
            if spent < allowed:
                used.append(a)
                spent += 1
            else:
                rest.append(a)
        ag.stamina -= spent * ag.cfg.effort_per_gather
        self.q_actions = []          # unused intents are dropped at end of turn
        return used

    def make_orders(self, ag, ctx):
        o = self.q_orders[:]
        self.q_orders = []
        return o


class SimCore:
    def __init__(self, config: Config | None = None, seed: int | None = None,
                 propagation: bool = False, population: list | None = None):
        cfg = config or Config()
        if seed is not None:
            cfg.seed = seed
        cfg.propagation_enabled = propagation
        self._strategy = ContractStrategy()
        # remembered so a save can rebuild the exact world shell before overlay
        self._population = population
        self._propagation = propagation
        self.world = World(cfg, player_strategy=self._strategy, population=population)
        self.cfg = self.world.cfg
        self._day = 0
        self._total = self.cfg.total_days
        self._events: list = []
        self._in_turn = False
        self._prev_bonus: dict = {}
        self._prev_penalty = 0.0

    # ---------------- lifecycle ----------------
    @property
    def done(self) -> bool:
        return self._day >= self._total

    @property
    def day(self) -> int:
        return self._day

    def begin_turn(self) -> C.Snapshot:
        """Publish the day (AIC bounty + frozen context) and return a snapshot."""
        if self.done:
            return self.snapshot()
        self.world.begin_day(self._day)
        self._in_turn = True
        return self.snapshot()

    def commit_turn(self) -> None:
        """Apply queued intents and advance the world one day; collect events."""
        if not self._in_turn:
            self.begin_turn()
        self._prev_bonus = {a.id: a.bonus_earned for a in self.world.agents}
        self._prev_penalty = self.world.accountant.state.total_penalty
        self.world.execute_day()
        self._collect_events()
        self._day += 1
        self._in_turn = False

    def step(self) -> None:
        self.begin_turn()
        self.commit_turn()

    # ---------------- intents ----------------
    def submit(self, intent, agent_id: str = "PLAYER") -> None:
        """Queue an intent for the player (the only externally-controlled agent for now)."""
        if isinstance(intent, C.Gather):
            self._strategy.q_actions.append(GatherAction(intent.resource))
        elif isinstance(intent, C.CraftTool):
            self._strategy.q_actions.append(CraftToolAction())
        elif isinstance(intent, C.BuildWoodlot):
            self._strategy.q_actions.append(BuildWoodlotAction())
        elif isinstance(intent, C.Perform):
            self._strategy.q_actions.append(InterventionAction(intent.key))
        elif isinstance(intent, C.AcceptDeal):
            self._strategy.q_actions.append(AcceptDealAction(
                intent.key, intent.principal, intent.interest, intent.term_days,
                intent.merchant_id))
        elif isinstance(intent, C.Trade):
            self._strategy.q_orders.append(
                Order(agent_id, intent.resource, intent.side, intent.qty, intent.price))
        elif isinstance(intent, C.Speak):
            if self.world.prop is None:
                raise RuntimeError("Speak intent requires propagation=True")
            from knowledge import Claim
            self.world.schedule_injection(
                day=self._day, target=agent_id,
                claim=Claim(intent.resource, intent.magnitude, intent.truth,
                            intent.root_id, self._day),
                authority=intent.authority, by_player=True)
        else:
            raise TypeError(f"unknown intent: {intent!r}")

    # ---------------- events ----------------
    def drain_events(self) -> list:
        ev, self._events = self._events, []
        return ev

    def _collect_events(self) -> None:
        w = self.world
        r_all = (Resource.WOOD, Resource.FOOD)
        self._events.append(C.DayAdvanced(self._day, self.cfg.season_for_day(self._day).value))
        # production this day (from lineage lots stamped with this tick)
        for lot in w.lineage.lots.values():
            if lot.tick == self._day and lot.producer_id not in ("nature", "market"):
                self._events.append(C.Produced(lot.producer_id, lot.resource, lot.qty_produced))
        # trades cleared
        for r in r_all:
            cl = w.last_clearings.get(r)
            if cl is not None and cl.volume > 1e-9:
                self._events.append(C.TradeCleared(r, cl.price, cl.volume, len(cl.trades)))
        # what the PLAYER actually bought/sold (the order may only partly clear)
        for r, d in getattr(w, "_settled", {}).get("PLAYER", {}).items():
            if d["sold"] > 1e-6:
                self._events.append(C.Settled(r, "sell", round(d["sold"], 3), round(d["sold_val"], 3)))
            if d["bought"] > 1e-6:
                self._events.append(C.Settled(r, "buy", round(d["bought"], 3), round(d["bought_val"], 3)))
        # realized-effect contribution paid (per-agent bonus delta)
        for a in w.agents:
            delta = a.bonus_earned - self._prev_bonus.get(a.id, 0.0)
            if delta > 1e-9:
                self._events.append(C.ContributionPaid(a.id, round(delta, 6)))
        # the felt "why" behind each payout: who was served, at what rate
        for (pid, cid, ckind, res, amt, rate, seas) in getattr(
                w.accountant.state, "contrib_events", ()):
            if amt > 1e-6:
                self._events.append(C.ContributionDetail(
                    pid, cid, ckind, res, round(amt, 6), round(rate, 4), seas))
        # shortages felt this day
        for aid, unmet in getattr(w, "_per_agent_unmet", {}).items():
            for r in r_all:
                if unmet.get(r, 0.0) > 1e-6:
                    self._events.append(C.Shortage(aid, r, round(unmet[r], 6)))
        # hoard surveillance
        for aid, stock in w.accountant.state.hoard_flags.items():
            self._events.append(C.HoardFlagged(aid, stock))
        fee = w.accountant.state.total_penalty - self._prev_penalty
        if fee > 1e-9:
            self._events.append(C.HoldingFee(round(fee, 6)))
        # capital goods established this day
        for a in w.agents:
            for asset in getattr(a, "assets", []):
                if asset.built_tick == self._day:
                    self._events.append(C.AssetBuilt(a.id, asset.kind))
        # interventions attempted this day (Layer 3) -- accepted or rejected
        for (aid, key, accepted, spent, target, reason) in getattr(w, "_interventions_today", ()):
            self._events.append(C.InterventionPerformed(
                aid, key, accepted, round(spent, 4), target, reason))
        # negotiated deals resolved this day (Layer 3) at the sim's hard gate
        for (aid, mid, key, struck, principal, interest, term, reason) in getattr(w, "_deals_today", ()):
            self._events.append(C.DealResolved(
                aid, mid, key, struck, round(principal, 4), round(interest, 4), term, reason))
        # loan servicing this day (repayment / pay-off / default)
        for (aid, lid, event, payment, balance) in getattr(w, "_loan_events", ()):
            self._events.append(C.LoanUpdated(aid, lid, event, round(payment, 4), round(balance, 4)))
        # knowledge network readout
        if w.prop is not None:
            vids = {a.id for a in w.agents if not a.is_player and not a.is_market_maker}
            for r in r_all:
                self._events.append(C.BeliefState(
                    r, round(w.prop.aware_fraction(r, vids), 6),
                    round(w.prop.avg_scarcity(r, vids), 6),
                    w.prop.distinct_roots(r, vids)))

    # ---------------- snapshot ----------------
    def _kind(self, a) -> str:
        if a.is_player:
            return "player"
        if a.is_market_maker:
            return "market_maker"
        if getattr(a, "is_dependent", False):
            return "dependent"
        if type(a).__name__ == "Merchant":
            return "merchant"
        return "villager"

    def snapshot(self) -> C.Snapshot:
        w = self.world
        sc = w.scenario
        rids = list(w.resource_ids)
        cons = list(w.consumable_ids)
        agents = []
        for a in w.agents:
            wl = next((x for x in getattr(a, "assets", []) if x.kind == "woodlot"), None)
            agents.append(C.AgentView(
                id=a.id, kind=self._kind(a), money=round(a.money, 4),
                wood=round(a.qty(Resource.WOOD), 4), food=round(a.qty(Resource.FOOD), 4),
                tool=round(a.qty(Resource.TOOL), 4), stamina=round(a.stamina, 4),
                fear_wood=round(a.fear(Resource.WOOD), 4), fear_food=round(a.fear(Resource.FOOD), 4),
                is_player=a.is_player, contribution_earned=round(a.bonus_earned, 4),
                woodlots=1 if wl else 0,
                woodlot_level=wl.level if wl else 0,
                woodlot_output=round(self.cfg.woodlot_wood_output * wl.level, 3) if wl else 0.0,
                holdings={_rv(r): round(a.qty(r), 4) for r in rids},
                fears={_rv(r): round(a.fear(r), 4) for r in cons},
            ))

        st = w.accountant.state
        markets = []
        for r in cons:                              # per-consumable, driven by scenario data
            cl = w.last_clearings.get(r)
            markets.append(C.MarketView(
                resource=r, ref_price=round(w.ref_price[r], 4),
                fair_price=round(st.fair_price.get(r, 0.0), 4),
                last_clear_price=round(cl.price, 4) if cl else 0.0,
                last_volume=round(cl.volume, 4) if cl else 0.0,
                bounty=round(st.bounty.get(r, 0.0), 4),
            ))

        problems = [
            C.ProblemView(ps.problem.key, ps.problem.kind, ps.problem.location,
                          ps.problem.subject, ps.severity)
            for ps in getattr(w, "problems", [])
        ]

        loans = []
        for a in w.agents:
            for ln in getattr(a, "loans", []):
                loans.append(C.LoanView(
                    agent_id=a.id, lender_id=ln.lender_id, principal=round(ln.principal, 4),
                    interest=round(ln.interest, 4), balance=round(ln.balance, 4),
                    term_days=ln.term_days, struck_day=ln.struck_day,
                    per_day=round(ln.per_day, 4), defaulted=ln.defaulted))

        vu = getattr(w, "village_unmet", {Resource.WOOD: 0.0, Resource.FOOD: 0.0})
        return C.Snapshot(
            day=self._day, season=w.driver.phase_name(self._day),
            agents=agents, markets=markets, problems=problems, loans=loans,
            village_unmet_wood=round(vu.get(Resource.WOOD, 0.0), 4),
            village_unmet_food=round(vu.get(Resource.FOOD, 0.0), 4),
            shortage_agents=getattr(w, "day_short_agents", 0),
            total_contribution_paid=round(st.total_paid, 4),
            total_penalty=round(st.total_penalty, 4),
            done=self.done,
            scenario=sc.name, primary_resource=_rv(sc.primary_resource),
            consumables=tuple(_rv(r) for r in cons),
            village_unmet={_rv(r): round(vu.get(r, 0.0), 4) for r in cons},
        )

    # ---------------- queries ----------------
    def score(self, agent_id: str = "PLAYER") -> float:
        """Realized contribution credited to an agent so far."""
        a = self.world.by_id.get(agent_id)
        return round(a.bonus_earned, 6) if a else 0.0

    def belief(self, agent_id: str, resource: Resource) -> tuple[float, float]:
        """(value, confidence) an agent holds about a resource's scarcity."""
        if self.world.prop is not None:
            b = self.world.prop.belief(agent_id, resource)
            return round(b.value, 6), round(b.confidence, 6)
        a = self.world.by_id.get(agent_id)
        return (round(a.fear(resource), 6), 1.0) if a else (0.0, 0.0)

    def market(self, resource: Resource) -> C.MarketView:
        return next(m for m in self.snapshot().markets if m.resource == resource)

    def problems(self) -> list:
        """The world's live problem board (Layer 1): typed, located, severity-ranked
        problems the player could resolve. Read-only; sorted worst-first."""
        return sorted(self.snapshot().problems, key=lambda p: -p.severity)

    def standing(self, agent_id: str = "PLAYER") -> float:
        """The agent's reputation/standing that gates interventions (Layer 3):
        realized contribution to date -- their track record of deeds."""
        import interventions
        a = self.world.by_id.get(agent_id)
        return interventions.standing(a, self.world) if a else 0.0

    def reputation(self, agent_id: str = "PLAYER") -> C.ReputationSummary:
        """The agent's standing plus a plain-language band, for merchant negotiation
        (Layer 3). Today standing = realized contribution; the descriptor is what a
        merchant prompt uses instead of the raw number."""
        import interventions
        a = self.world.by_id.get(agent_id)
        s = interventions.standing(a, self.world) if a else 0.0
        d = ("unproven" if s < 40 else "known" if s < 200
             else "trusted" if s < 600 else "renowned")
        return C.ReputationSummary(standing=round(s, 4), descriptor=d)

    def merchant_view(self, key: str, principal: float, interest: float, term_days: int,
                      merchant_id: str = "mk00", agent_id: str = "PLAYER") -> C.MerchantView:
        """The knowledge-gated projection a merchant reasons over for a proposal
        (Layer 3): public reference prices, the merchant's own capital, the season,
        public facts, and the counterparty's reputation -- never the AIC fair value
        or hidden truth. This is what the (Scripted or LLM) merchant judges."""
        w = self.world
        sc = w.scenario
        m = w.by_id.get(merchant_id)
        ref = {_rv(r): round(w.ref_price[r], 4) for r in w.consumable_ids}
        season = w.driver.phase_name(self._day)
        crisis = sc.crisis_phase
        dtw = w.driver.days_until_phase(self._day, crisis)
        facts = (f"{crisis} is near",) if (season != crisis and dtw <= 25) else ()
        return C.MerchantView(
            merchant_id=merchant_id,
            merchant_capital=round(m.money, 2) if m else 0.0,
            ref_prices=ref, season=season, reputation=self.reputation(agent_id),
            public_facts=facts, key=key, principal=round(principal, 4),
            interest=round(interest, 4), term_days=term_days)

    def interventions(self, agent_id: str = "PLAYER") -> list:
        """The pre-authored action library as an agent sees it now: each entry is
        (key, title, targets, capital_cost, min_standing, can_perform, reason) --
        what a body renders as the player's action menu, greying out the locked
        ones with the reason they're locked."""
        import interventions as I
        w = self.world
        a = w.by_id.get(agent_id)
        out = []
        for iv in w.interventions.values():
            accepted, reason = (False, "no such agent") if a is None else I.evaluate(w, a, iv)
            out.append((iv.key, iv.title, iv.targets, iv.capital_cost,
                        iv.min_standing, accepted, reason))
        return out

    def welfare(self) -> dict:
        return self.world.metrics.summary()

    # ---------------- persistence ----------------
    def serialize(self) -> dict:
        """Capture full state as a JSON-safe dict. Call at a day boundary
        (between commit_turn and the next begin_turn)."""
        import persistence
        return persistence.serialize_core(self)

    def load(self, data: dict) -> None:
        """Rebuild this core in place from a dict produced by serialize()."""
        import persistence
        persistence.deserialize_core(self, data)

    @classmethod
    def from_save(cls, data: dict) -> "SimCore":
        """Construct a SimCore directly from a save dict."""
        core = cls.__new__(cls)
        core.load(data)
        return core
