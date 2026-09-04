"""
GameSession -- the engine-agnostic RULES of the Contribution game.

The middle layer of "one brain, many bodies":

    SimCore (the simulation)  <-  GameSession (this game's rules)  <-  a View

GameSession talks to the world ONLY through the SimCore contract, and it renders
NOTHING -- no pygame, no colours, no pixels. It owns the day/turn flow, the action
economy (stamina), win/lose, the realized-effect impact ledger, the counterfactual
"what if you weren't here" baseline, and a SEMANTIC news feed: each line carries a
tag naming its MEANING ('contribution', 'cold', 'word', ...), never a colour, so a
View maps tags to colour -- or a pixel-art body maps them to sprites and sounds.

Any presentation drives the SAME session: call its action methods when the player
acts (click a button, or walk a character up to the woodlot and press A), read its
state to draw the world. Swapping the whole skin -- click-sim today, a top-down
Pokemon-style tile game tomorrow -- means writing a new View against this API and
changing nothing here or in the sim.

Interaction-model-agnostic on purpose: the session exposes intent ("gather wood",
"warn", "trade") and guards ("can I build a woodlot right now?"), not input. How
the player expresses that intent -- a keypress, a mouse click, a character walking
onto a tile -- is the View's business.
"""
from __future__ import annotations

import contract as C
from agents import Dependent, MarketMaker, SpawnSpec, Villager
from config import Config, Resource


def make_config() -> Config:
    cfg = Config()
    cfg.years = 1.0
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    return cfg


def default_population(cfg: Config):
    # a deeper-pocketed trading post so selling clears more per day (game feel;
    # the validated scenarios keep the default shallow market)
    return [SpawnSpec(Villager, 8, id_prefix="v"),
            SpawnSpec(Dependent, 3, id_prefix="d"),
            SpawnSpec(MarketMaker, 1, id_prefix="mk",
                      kwargs={"daily_volume": 16.0, "target_inventory": 40.0})]


# The vocabulary of news tags a View must know how to present. Documented here so
# a new body has one place to look. (A View may style any subset; unknown tags
# should fall back to a neutral style.)
NEWS_TAGS = (
    "system", "contribution", "sold", "bought", "unsold", "cold",
    "dependent_cold", "word", "hint", "asset", "starving", "food_low",
)


class GameSession:
    HOARD_HINT_WOOD = 45.0        # stockpile that triggers the "bank it" hint
    STARVE_DAYS = 3               # days without food before you die

    def __init__(self, config_factory=make_config, population_factory=default_population):
        self._mk_cfg = config_factory
        self._mk_pop = population_factory
        self.new_game()

    # ------------------------------------------------------------------ lifecycle
    def new_game(self) -> None:
        self.cfg = self._mk_cfg()
        self.core = SimCoreFactory(self.cfg, self._mk_pop)
        self.stamina_used = 0
        self.queued: list[str] = []
        self.news: list[tuple[str, str]] = []      # (text, semantic tag)
        self.cold_today: set[str] = set()
        self.warned_today = False
        self.warn_ever = False
        self.starving = 0
        self.warn_days: list[int] = []      # exact days you spoke the warning
        self.pending_sell: dict = {}
        # realized-effect ledger: consumer_id -> {times,total,kind} -- WHO your
        # wood actually kept warm across the year (the felt score).
        self.impact: dict = {}
        self.wood_awareness = 0.0
        self.wood_roots = 0
        self._aware_bucket = 0
        self.hoard_hinted = False
        self.phase = "playing"                      # 'playing' | 'ended'
        self.over_reason = ""
        self.result: dict | None = None
        self._boundary: dict = {}                   # last clean-boundary save
        self._log("A new year begins. Winter is far off -- but only you can see it coming.", "system")
        self._enter_day()

    def _enter_day(self) -> None:
        """Stash a clean-boundary save, THEN begin the day for the UI. The save
        must be captured here -- between commit_turn and begin_turn -- because
        begin_day applies per-day effects (stamina refresh, the dependent
        stipend) that would double-apply if a mid-turn save were reloaded and
        begin_day ran again. Capturing pre-begin makes save/load round-trip
        byte-identical (see test_save_load_game.py)."""
        self._boundary = self._make_boundary()
        self.snap = self.core.begin_turn()

    # --------------------------------------------------------------------- reads
    def me(self):
        return next(a for a in self.snap.agents if a.is_player)

    def market(self, r: Resource):
        return next(m for m in self.snap.markets if m.resource == r)

    # --------------------------------------------------------------- npc voices
    # The village speaks its own belief. A villager's line is derived ONLY from
    # what they actually believe about the winter -- read straight through the
    # contract via SimCore.belief() -- so the words a body shows are the same
    # scarcity signal that drives their panic-buying underneath. This is a pure
    # read: rendering belief, never changing it. A line carries a semantic tag
    # (never a colour), so a View skins it -- text bubble, sprite barks, audio.
    def villager_line(self, agent_id: str) -> tuple[str, str]:
        """(spoken_text, semantic_tag) for one agent, reflecting their real
        belief about the coming winter (wood scarcity). Confidence sets the
        register -- rumour heard once vs. conviction independently corroborated;
        magnitude sets how dire. Dependents add that they cannot cut their own
        wood, the reason they go cold first. Cold-today colours the tag."""
        view = next((a for a in self.snap.agents if a.id == agent_id), None)
        kind = view.kind if view is not None else "villager"
        dependent = kind == "dependent"
        cold = agent_id in self.cold_today
        # THE read through the wall: this agent's held belief about wood.
        value, confidence = self.core.belief(agent_id, Resource.WOOD)

        if confidence < 0.05 or value < 0.05:
            line = ("Winter? A long way off yet. The woodshed can wait."
                    if not dependent else
                    "Wood's dear, but there's time. Someone will have it to sell.")
            tag = "system"
        elif confidence < 0.35:
            line = "There's a rumour the winter'll come hard. Talk, most likely."
            tag = "hint"
        elif confidence < 0.60:
            line = ("Folk say the cold comes early. I've begun laying wood by, "
                    "just in case.")
            tag = "word"
        elif value < 0.55:
            line = "The winter's coming and it'll bite. I'm cutting all the wood I can."
            tag = "word"
        else:
            line = ("A cruel winter's nearly on us -- I cut wood every hour I have "
                    "and it's still not enough.")
            tag = "word"

        if dependent and confidence >= 0.35:
            line += " And I can't fell my own -- I must buy, and pray there's wood to sell."
        if cold:
            line = "I'm cold. " + line
            tag = "dependent_cold" if dependent else "cold"
        return line, tag

    def worried_voices(self, n: int = 2) -> list[tuple[str, str, str]]:
        """The n most-worried non-player, non-market voices, as
        (agent_id, spoken_text, tag), sorted by belief pressure (value x
        confidence). What the village would say if you stopped to listen."""
        speakers = []
        for a in self.snap.agents:
            if a.is_player or a.kind == "market_maker":
                continue
            value, confidence = self.core.belief(a.id, Resource.WOOD)
            line, tag = self.villager_line(a.id)
            speakers.append((value * confidence, a.id, line, tag))
        speakers.sort(key=lambda t: -t[0])
        return [(aid, line, tag) for _, aid, line, tag in speakers[:n]]

    @property
    def day(self) -> int:
        return self.core.day

    @property
    def season(self) -> str:
        return self.snap.season

    @property
    def ended(self) -> bool:
        return self.phase == "ended"

    def stamina_left(self) -> int:
        return int(round(self.me().stamina)) - self.stamina_used

    def wl_cost(self, level: int) -> float:
        return self.cfg.woodlot_wood_cost * (level + 1)

    def _log(self, text: str, tag: str = "system") -> None:
        self.news.append((text, tag))
        self.news = self.news[-8:]

    # --------------------------------------------------------------- persistence
    # A save is the whole GAME, not just the sim: the sim state goes through the
    # contract (SimCore.serialize/load -- the wall holds), and the session layer
    # adds its own game state (the news feed, the impact ledger, warning history,
    # win/lose). Both are captured at a clean day boundary by _enter_day, so a
    # reload lands exactly where the save was taken and continues byte-identically.
    SAVE_FORMAT = 1
    DEFAULT_SAVE_PATH = "savegame.save.json"

    def _session_state(self) -> dict:
        """JSON-safe snapshot of the session's own (non-sim) game state."""
        return {
            "news": [list(item) for item in self.news],
            "cold_today": sorted(self.cold_today),
            "warned_today": self.warned_today,
            "warn_ever": self.warn_ever,
            "starving": self.starving,
            "warn_days": list(self.warn_days),
            "impact": {k: dict(v) for k, v in self.impact.items()},
            "wood_awareness": self.wood_awareness,
            "wood_roots": self.wood_roots,
            "aware_bucket": self._aware_bucket,
            "hoard_hinted": self.hoard_hinted,
            "phase": self.phase,
            "over_reason": self.over_reason,
            "result": self.result,
        }

    def _restore_session(self, s: dict) -> None:
        self.news = [tuple(item) for item in s["news"]]
        self.cold_today = set(s["cold_today"])
        self.warned_today = s.get("warned_today", False)
        self.warn_ever = s["warn_ever"]
        self.starving = s["starving"]
        self.warn_days = list(s["warn_days"])
        self.impact = {k: dict(v) for k, v in s["impact"].items()}
        self.wood_awareness = s["wood_awareness"]
        self.wood_roots = s["wood_roots"]
        self._aware_bucket = s["aware_bucket"]
        self.hoard_hinted = s["hoard_hinted"]
        self.phase = s["phase"]
        self.over_reason = s["over_reason"]
        self.result = s["result"]

    def _make_boundary(self) -> dict:
        """A save taken at THIS day boundary: sim (through the wall) + session."""
        return {"sim": self.core.serialize(), "session": self._session_state()}

    def save(self) -> dict:
        """A JSON-safe save of the whole game at the current day boundary."""
        return {"game_save_format": self.SAVE_FORMAT, **self._boundary}

    def load(self, blob: dict) -> None:
        """Restore a game produced by save(). Rebuilds the sim via the contract
        (SimCore.from_save) and re-enters the saved day exactly as _enter_day
        does, so play continues identically from here."""
        fmt = blob.get("game_save_format")
        if fmt != self.SAVE_FORMAT:
            raise ValueError(f"incompatible game save format {fmt!r} "
                             f"(this build reads {self.SAVE_FORMAT})")
        from simcore import SimCore
        self.core = SimCore.from_save(blob["sim"])     # contract-level restore
        self.cfg = self.core.cfg
        self._restore_session(blob["session"])
        self.stamina_used = 0                          # transients reset to day-start
        self.queued = []
        self.pending_sell = {}
        self._boundary = {"sim": blob["sim"], "session": blob["session"]}
        self.snap = self.core.begin_turn()

    def save_to_file(self, path: str | None = None) -> str:
        import json
        path = path or self.DEFAULT_SAVE_PATH
        with open(path, "w") as f:
            json.dump(self.save(), f)
        return path

    def load_from_file(self, path: str | None = None) -> bool:
        """Load if the save file exists; return False (touching nothing) if not."""
        import json, os
        path = path or self.DEFAULT_SAVE_PATH
        if not os.path.exists(path):
            return False
        with open(path) as f:
            self.load(json.load(f))
        return True

    # ------------------------------------------------------------------- guards
    def can_act(self) -> bool:
        return self.phase == "playing"

    def can_gather(self) -> bool:
        return self.can_act() and self.stamina_left() > 0

    def can_build_woodlot(self) -> bool:
        me = self.me()
        return (self.can_act() and self.stamina_left() > 0
                and me.woodlot_level < self.cfg.woodlot_max_level
                and me.wood >= self.wl_cost(me.woodlot_level))

    def can_warn(self) -> bool:
        return self.can_act() and not self.warned_today and self.stamina_left() > 0

    def can_fast_forward(self) -> bool:
        return self.can_act() and self.season != "winter"

    def can_sell(self, r: Resource) -> bool:
        me = self.me()
        held = me.wood if r == Resource.WOOD else me.food
        keep = 2.5 if r == Resource.WOOD else 3.5
        return self.can_act() and held > keep

    # ------------------------------------------------------------------ actions
    # Each returns True if the intent was accepted. A View calls these; it need
    # not pre-check guards (they re-check), but the guards let it grey out UI.
    def gather(self, r: Resource) -> bool:
        if not self.can_gather():
            return False
        self.core.submit(C.Gather(r)); self.stamina_used += 1
        self.queued.append(f"gather {r.value}")
        return True

    def build_woodlot(self) -> bool:
        if not self.can_build_woodlot():
            return False
        me = self.me()
        self.core.submit(C.BuildWoodlot()); self.stamina_used += 1
        self.queued.append("woodlot" if me.woodlot_level == 0 else "upgrade woodlot")
        return True

    def warn(self) -> bool:
        if not self.can_warn():
            return False
        # spend the day carrying the word instead of gathering: a real choice
        self.core.submit(C.Speak(Resource.WOOD, 0.85, True, "player_warning", authority=0.85))
        self.warned_today = True; self.warn_ever = True; self.stamina_used += 1
        self.warn_days.append(self.day)
        self.queued.append("warn of winter")
        return True

    def trade(self, r: Resource, side: str) -> bool:
        if not self.can_act():
            return False
        me = self.me(); px = self.market(r).ref_price
        if side == "sell":
            keep = 2.0 if r == Resource.WOOD else 3.0
            qty = (me.wood if r == Resource.WOOD else me.food) - keep
            if qty <= 0.5:
                return False
            self.core.submit(C.Trade(r, "sell", qty, px * 0.95))
            self.queued.append(f"sell {qty:.0f} {r.value}")
            self.pending_sell[r] = self.pending_sell.get(r, 0.0) + qty
            return True
        self.core.submit(C.Trade(r, "buy", 3.0, px * 1.15))
        self.queued.append(f"buy 3 {r.value}")
        return True

    def fast_forward(self) -> None:
        if not self.can_fast_forward():
            return
        guard = 0
        while (self.phase == "playing" and not self.core.done
               and self.season != "winter" and guard < 200):
            # auto-subsist: gather enough food to feed yourself AND the woodlot
            for _ in range(min(3, self.stamina_left())):
                self.core.submit(C.Gather(Resource.FOOD)); self.stamina_used += 1
            self.end_day(); guard += 1

    def end_day(self) -> None:
        if self.phase != "playing":
            return
        self.core.commit_turn()
        self._process_events(self.core.drain_events())
        self.stamina_used = 0; self.queued = []; self.pending_sell = {}
        self.warned_today = False
        if self.starving >= self.STARVE_DAYS:
            self._end("You starved. Even the one who could see the winter must eat.")
        elif self.core.done:
            self._end("")
        else:
            self._enter_day()
            me = self.me()
            if me.food < 2.0:
                self._log("Food is running low -- gather or buy food.", "food_low")
            # reframe over-gathering: a big stockpile isn't waste, it's banked for winter
            if self.season != "winter" and me.wood > self.HOARD_HINT_WOOD and not self.hoard_hinted:
                self._log("You're sitting on a lot of wood. Good -- in winter it's worth "
                          "far more, and those who can't cut their own will need it. Hold it.", "hint")
                self.hoard_hinted = True

    # ---------------------------------------------------------- end / counterfactual
    def _end(self, reason: str) -> None:
        self.over_reason = reason
        self.phase = "ended"
        base = self._ghost_winter_unmet()                 # you were never here
        wu = self.core.welfare().get("winter_village_unmet_wood", 0.0)
        # isolate the WARNING lever: what your words alone were worth, with no
        # resource actions on either side -- a clean, measured marginal effect.
        warning_effect = 0.0
        if self.warn_days:
            warn_only = self._ghost_winter_unmet(self.warn_days)
            warning_effect = base - warn_only
        self.result = {
            "contribution": self.core.score("PLAYER"),
            "winter_unmet": wu,
            "baseline_unmet": base,
            "saved": base - wu,
            "kept_warm": len(self.impact),
            "times": sum(r["times"] for r in self.impact.values()),
            "dependents": sum(1 for r in self.impact.values() if r["kind"] == "dependent"),
            "warned": bool(self.warn_days),
            "warning_effect": warning_effect,
            "survived": not reason,
            "reason": reason,
        }

    def _ghost_winter_unmet(self, warn_days=()) -> float:
        """Run a parallel SimCore in which the player takes NO resource actions,
        speaking the winter warning only on `warn_days`. With warn_days empty this
        is 'you were never here'; with your actual warning days it isolates what
        your information alone did. Pure-contract -- no reach into the engine."""
        warn_days = set(warn_days)
        cfg = self._mk_cfg()
        ghost = SimCoreFactory(cfg, self._mk_pop)
        while not ghost.done:
            if ghost.day in warn_days:
                ghost.begin_turn()
                ghost.submit(C.Speak(Resource.WOOD, 0.85, True, "player_warning", authority=0.85))
                ghost.commit_turn()
            else:
                ghost.step()
        return ghost.welfare().get("winter_village_unmet_wood", 0.0)

    # --------------------------------------------------------------- event digest
    @staticmethod
    def _who(kind: str) -> str:
        return {"dependent": "a dependent household", "villager": "a neighbour",
                "market_maker": "the trading post", "player": "yourself"}.get(kind, "someone")

    def _process_events(self, events) -> None:
        self.cold_today = set(); earned = 0.0; cold = set(); starved = False
        sold: dict = {}
        detail: dict = {}          # consumer_id -> [amount, kind, season, rate]
        for ev in events:
            if isinstance(ev, C.ContributionPaid) and ev.agent_id == "PLAYER":
                earned += ev.amount
            elif isinstance(ev, C.ContributionDetail) and ev.producer_id == "PLAYER":
                d = detail.setdefault(ev.consumer_id, [0.0, ev.consumer_kind, ev.season, ev.rate])
                d[0] += ev.amount; d[3] = max(d[3], ev.rate)
                rec = self.impact.setdefault(ev.consumer_id, {"total": 0.0, "times": 0, "kind": ev.consumer_kind})
                rec["total"] += ev.amount; rec["times"] += 1; rec["kind"] = ev.consumer_kind
            elif isinstance(ev, C.BeliefState) and ev.resource == Resource.WOOD:
                self.wood_awareness = ev.awareness; self.wood_roots = ev.distinct_roots
            elif isinstance(ev, C.Shortage) and ev.resource == Resource.WOOD:
                self.cold_today.add(ev.agent_id)
                if ev.agent_id != "PLAYER":
                    cold.add(ev.agent_id)
            elif isinstance(ev, C.Shortage) and ev.resource == Resource.FOOD and ev.agent_id == "PLAYER":
                starved = True
            elif isinstance(ev, C.AssetBuilt) and ev.agent_id == "PLAYER":
                self._log("Your woodlot is established -- it yields wood every day now.", "asset")
            elif isinstance(ev, C.Settled):
                if ev.side == "sell":
                    sold[ev.resource] = sold.get(ev.resource, 0.0) + ev.qty
                    self._log(f"Sold {ev.qty:.0f} {ev.resource.value} for {ev.value:.0f}g "
                              f"(@ {ev.value/max(ev.qty,1e-6):.1f}).", "sold")
                else:
                    self._log(f"Bought {ev.qty:.0f} {ev.resource.value} for {ev.value:.0f}g.", "bought")
        # tell the player when a sell order did NOT clear (and why)
        for r, req in self.pending_sell.items():
            unsold = req - sold.get(r, 0.0)
            if unsold > 0.5:
                self._log(f"{unsold:.0f} {r.value} didn't sell -- no buyers (it isn't scarce now).", "unsold")
        self.starving = self.starving + 1 if starved else 0
        if starved:
            self._log(f"You have no food -- STARVING ({self.starving}/{self.STARVE_DAYS} days).", "starving")
        # the FELT contribution: name who you kept warm and why it was worth it
        if detail:
            items = sorted(detail.items(), key=lambda kv: -kv[1][0])
            total = sum(v[0] for _, v in items)
            _, (amt, kind, seas, rate) = items[0]
            extra = f" (+{len(items)-1})" if len(items) > 1 else ""
            self._log(f"+{total:.0f} kept {self._who(kind)}{extra} warm -- {seas} fair {rate:.0f}/u.", "contribution")
        elif earned > 0.05:
            self._log(f"+{earned:.0f} contribution -- your wood met a need.", "contribution")
        # word of winter spreading: milestone lines as awareness climbs
        if self.warn_ever:
            bucket = int(self.wood_awareness * 4)      # quarters
            if bucket > self._aware_bucket and self.wood_awareness > 0.05:
                self._aware_bucket = bucket
                self._log(f"Word spreads -- {self.wood_awareness*100:.0f}% now expect a hard winter.", "word")
        deps = {c for c in cold if c.startswith("d")}
        if deps:
            self._log(f"{len(deps)} dependent household(s) went cold.", "dependent_cold")
        elif cold:
            self._log(f"{len(cold)} villager(s) went cold.", "cold")


def SimCoreFactory(cfg: Config, mk_pop):
    """Build a propagation-enabled SimCore for `cfg` with its population. Kept as
    a tiny factory so both the live game and the counterfactual build identically."""
    from simcore import SimCore
    return SimCore(config=cfg, propagation=True, population=mk_pop(cfg))
