"""
Say the Word -- pygame VIEW (one of potentially many bodies), now SCENARIO-AGNOSTIC.

This file is PURE PRESENTATION. It owns the window, the fonts, the colour skin,
the layout, and how input maps to intent -- and nothing else. All simulation lives
in SimCore behind the contract; this body reads ONLY the contract's universal
(v1.5) fields, so it renders ANY registered world -- frostpine, tidewater,
guildhall, plaguewatch, emberforge, dustveil, fallowmere, or a scenario added
later -- with zero per-scenario code. It is the graphical twin of view_play.py:
one skin, every world.

    SimCore (sim)  <-  THIS View (skin, driving the contract directly)

Nothing here knows wood from fish from steel, or winter from a war levy. It reads
the snapshot's generic fields (scenario / season / primary_resource / consumables /
village_unmet, AgentView.holdings & .fears, MarketView, ProblemView, the
intervention library, reputation, loans) and maps clicks/keys to contract intents
(Gather / Trade / BuildWoodlot / Perform / Speak / AcceptDeal). The layout adapts
to N goods, whichever market model, and whichever mix of archetypes a world spawns.
Semantic news tags map to colour HERE, so a different body maps them to sprites.

    pip install pygame
    python game.py                 # a start menu: pick any registered world
    python game.py tidewater       # jump straight into a named world

Headless-capturable: it runs under SDL_VIDEODRIVER=dummy and every frame can be
written with pygame.image.save (see shoot_scenarios.py). Determinism and the sim
are untouched -- this is a View.
"""
from __future__ import annotations

import math
import sys

try:
    import pygame
except ImportError:
    print("pygame is not installed. Run:  pip install pygame")
    sys.exit(1)

import contract as C
import scenario as scen
from simcore import SimCore

# ---- the skin: this View's palette. All look-and-feel lives here. ----
BG      = (14, 19, 25);  SURFACE = (22, 28, 37);  SURF2 = (29, 37, 48)
INK     = (231, 235, 241); MUTE = (131, 144, 160)
EMBER   = (232, 106, 58);  EMBERD = (194, 74, 22)
STEEL   = (109, 138, 166); GREEN = (90, 167, 124)
CRIMSON = (224, 87, 79);   BELIEF = (155, 139, 200); LINE = (40, 49, 61)
GOLD    = (211, 178, 98)

# semantic news tag -> colour. A pixel-art body would map these tags to icons or
# sound cues instead; the sim never dictates colour. These tags cover the generic
# contract events this body narrates for every world.
TAG_COLORS = {
    "system": MUTE, "contribution": EMBER, "sold": GREEN, "bought": STEEL,
    "unsold": MUTE, "cold": CRIMSON, "dependent_cold": CRIMSON, "word": BELIEF,
    "hint": STEEL, "asset": GREEN, "starving": CRIMSON, "food_low": CRIMSON,
    "shortage": CRIMSON, "intervention": GOLD, "deal": GOLD, "loan": STEEL,
}

# agent kind -> a base colour, so a body paints any archetype mix a world spawns
# (villager / dependent / market_maker / merchant / institution / player).
KIND_COLORS = {
    "player": EMBER, "villager": GREEN, "dependent": MUTE, "market_maker": STEEL,
    "merchant": GOLD, "institution": BELIEF,
}


def _rv(r):
    """Resource id as a display string (tolerant of enum or string)."""
    return r.value if hasattr(r, "value") else r


# =====================================================================
# The model this View drives: a SimCore for one scenario, read ONLY through
# the universal contract fields, plus a semantic news feed built from generic
# events. No frostpine knowledge -- the scenario supplies its own labels.
# =====================================================================
class World:
    NEWS_MAX = 9

    def __init__(self, name: str):
        self.name = name
        self.sc = scen.get_scenario(name)
        self.core = self._build(name)
        self.news: list[tuple[str, str]] = []
        self.queued: list[str] = []
        self.has_prop = self.core.world.prop is not None
        self._log(f"{name}: {self.primary} is the crisis good; "
                  f"peak stress in the '{self.sc.crisis_phase}' phase.", "system")
        self.snap = self.core.begin_turn()

    @staticmethod
    def _build(name: str) -> SimCore:
        # the same full-featured build view_play.py uses, so the graphical body and
        # the terminal body drive an identical world: Layer-3 on, reputation
        # propagating, crises paying fair value.
        cfg = scen.make_config(name)
        cfg.interventions_enabled = True
        cfg.capital_goods_enabled = True
        cfg.loans_enabled = True
        cfg.reward_at_fair_value = True
        cfg.reputation_propagation = True
        return SimCore(config=cfg, propagation=True,
                       population=scen.build_population(scen.get_scenario(name)))

    # ---- universal reads (labels the world exposes about itself) ----
    @property
    def day(self) -> int: return self.snap.day
    @property
    def season(self) -> str: return self.snap.season
    @property
    def primary(self) -> str: return _rv(self.sc.primary_resource)
    @property
    def consumables(self) -> list: return list(self.snap.consumables)
    @property
    def done(self) -> bool: return self.core.done
    @property
    def has_capital(self) -> bool: return bool(self.sc.capital)

    def capital_label(self) -> str:
        if not self.sc.capital:
            return "Found capital"
        return f"Found {self.sc.capital[0].kind}"

    def days_to_crisis(self) -> int:
        try:
            return self.sc.driver.days_until_phase(self.day, self.sc.crisis_phase)
        except Exception:
            return -1

    def me(self):
        return next(a for a in self.snap.agents if a.is_player)

    def market(self, good: str):
        return next((m for m in self.snap.markets if _rv(m.resource) == good), None)

    def reputation(self):
        return self.core.reputation("PLAYER")

    def problems(self, n: int = 4) -> list:
        return self.core.problems()[:n]

    def interventions(self) -> list:
        # (key, title, targets, cost, min_standing, can_perform, reason)
        return self.core.interventions()

    def loans(self) -> list:
        return [l for l in self.snap.loans if l.agent_id == "PLAYER"]

    def _log(self, text: str, tag: str = "system") -> None:
        if self.news and self.news[-1][0] == text:     # collapse consecutive repeats
            return
        self.news.append((text, tag))
        self.news = self.news[-self.NEWS_MAX:]

    # ---- input -> intent (the only way this body touches the world) ----
    def gather(self, good: str) -> None:
        self.core.submit(C.Gather(good)); self.queued.append(f"gather {good}")

    def build(self) -> None:
        self.core.submit(C.BuildWoodlot()); self.queued.append(self.capital_label().lower())

    def trade(self, good: str, side: str, qty: float = 4.0) -> None:
        m = self.market(good)
        ref = m.ref_price if m else 1.0
        px = ref * (1.15 if side == "buy" else 0.85)   # cross the spread so it clears
        self.core.submit(C.Trade(good, side, qty, px))
        self.queued.append(f"{side} {qty:.0f} {good}")

    def warn(self) -> bool:
        if not self.has_prop:
            self._log("This world has no rumour network to speak into.", "hint")
            return False
        self.core.submit(C.Speak(self.primary, 0.85, True, "player:warning", 0.85))
        self.queued.append(f"warn of {self.primary}")
        return True

    def perform_ready(self, silent: bool = False) -> bool:
        """Perform the first intervention whose preconditions are all met."""
        row = next((iv for iv in self.interventions() if iv[5]), None)
        if row is None:
            if not silent:
                self._log("No intervention is unlocked yet (need standing/capital/a live problem).", "hint")
            return False
        self.core.submit(C.Perform(row[0])); self.queued.append(f"perform {row[0]}")
        return True

    def fund_first(self) -> bool:
        """Negotiate a loan (deterministic merchant, at the edge) to fund the
        cheapest intervention that only lacks capital, then submit it as an
        AcceptDeal -- the sim is the hard gate. Layer-3 financing, generic."""
        import merchant as M
        rows = [iv for iv in self.interventions()
                if (not iv[5]) and iv[6].startswith("needs capital")]
        rows.sort(key=lambda iv: iv[3])
        if not rows:
            self._log("Nothing to finance right now (no capital-gated action is otherwise ready).", "hint")
            return False
        key, principal = rows[0][0], rows[0][3]
        opening = M.DealProposal(key, principal, 0.10, 60)
        out = M.negotiate(M.ScriptedMerchant(), M.make_view_builder(self.core),
                          opening, M.accept_up_to(0.30))
        if not out.struck:
            self._log(f'Merchant declined: {out.reason}.', "deal")
            return False
        t = out.terms
        self.core.submit(C.AcceptDeal(t.key, t.principal, t.interest, t.term_days))
        self.queued.append(f"deal {key}")
        self._log(f'Merchant: borrow {t.principal:.0f} at {t.interest:.0%} to fund {key}.', "deal")
        return True

    # ---- turn flow ----
    def end_day(self) -> None:
        if self.done:
            return
        self.core.commit_turn()
        self._digest(self.core.drain_events())
        self.queued = []
        if not self.done:
            self.snap = self.core.begin_turn()
        else:
            self.snap = self.core.snapshot()

    def auto_day(self) -> None:
        """A simple, universal policy for one day: work the crisis good and each
        other consumable, invest in capital where the world has it, perform any
        unlocked intervention. Used by the fast-forward button and the headless
        screenshot script to reach a representative mid-run state."""
        if self.done:
            return
        self.core.submit(C.Gather(self.primary))
        for g in self.consumables:
            if g != self.primary:
                self.core.submit(C.Gather(g))
        if self.has_capital:
            self.core.submit(C.BuildWoodlot())
        self.perform_ready(silent=True)
        me = self.me()
        if me.holdings.get(self.primary, 0.0) > 6.0:
            self.trade(self.primary, "sell", 4.0)
        self.end_day()

    def _digest(self, events) -> None:
        """Fold the day's generic contract events into the semantic news feed.
        Every branch reads only contract event fields -- no scenario knowledge."""
        earned = 0.0
        sold: dict = {}
        cold: set[str] = set()
        for ev in events:
            if isinstance(ev, C.ContributionPaid) and ev.agent_id == "PLAYER":
                earned += ev.amount
            elif isinstance(ev, C.Settled):
                r = _rv(ev.resource)
                if ev.side == "sell":
                    sold[r] = sold.get(r, 0.0) + ev.qty
                    self._log(f"Sold {ev.qty:.0f} {r} for {ev.value:.0f}g.", "sold")
                else:
                    self._log(f"Bought {ev.qty:.0f} {r} for {ev.value:.0f}g.", "bought")
            elif isinstance(ev, C.Shortage) and ev.agent_id != "PLAYER":
                cold.add(ev.agent_id)
            elif isinstance(ev, C.AssetBuilt) and ev.agent_id == "PLAYER":
                self._log(f"Your {ev.kind} is established -- it yields every day now.", "asset")
            elif isinstance(ev, C.InterventionPerformed) and ev.agent_id == "PLAYER":
                if ev.accepted:
                    self._log(f"You performed '{ev.key}' ({ev.capital_spent:.0f}g) against {ev.target}.", "intervention")
                elif ev.reason:
                    self._log(f"'{ev.key}' blocked: {ev.reason}.", "hint")
            elif isinstance(ev, C.DealResolved) and ev.agent_id == "PLAYER":
                if ev.struck:
                    self._log(f"Deal struck: borrowed {ev.principal:.0f} to fund '{ev.key}'.", "deal")
                elif ev.reason:
                    self._log(f"Deal fell through: {ev.reason}.", "hint")
            elif isinstance(ev, C.LoanUpdated) and ev.agent_id == "PLAYER":
                if ev.event == "paid_off":
                    self._log(f"Loan to {ev.lender_id} paid off.", "loan")
                elif ev.event == "defaulted":
                    self._log(f"You DEFAULTED on {ev.lender_id} -- word will spread.", "starving")
        if earned > 0.05:
            self._log(f"+{earned:.0f} contribution -- your supply met a real need.", "contribution")
        if cold:
            deps = sum(1 for c in cold if c.startswith("d"))
            if deps:
                self._log(f"{deps} dependent household(s) went short today.", "dependent_cold")
            else:
                self._log(f"{len(cold)} agent(s) went short today.", "cold")


# =====================================================================
# The pygame View: window, skin, layout, input mapping. Scenario-agnostic.
# =====================================================================
class Button:
    def __init__(self, rect, cb, label="", hint="", enabled=True, accent=False):
        self.rect = rect; self.cb = cb; self.label = label
        self.hint = hint; self.enabled = enabled; self.accent = accent


class Game:
    def __init__(self, scenario: str | None = None, headless: bool = False):
        pygame.init()
        pygame.display.set_caption("Say the Word")
        self.W, self.H = 1060, 700
        self.MINW, self.MINH = 900, 600
        flags = pygame.RESIZABLE if not headless else 0
        self.screen = pygame.display.set_mode((self.W, self.H), flags)
        self.headless = headless
        self.clock = pygame.time.Clock()
        self.f_h1 = pygame.font.SysFont("georgia,serif", 30, bold=True)
        self.f_h2 = pygame.font.SysFont("georgia,serif", 20, bold=True)
        self.f = pygame.font.SysFont("segoeui,arial", 16)
        self.f_sm = pygame.font.SysFont("segoeui,arial", 14)
        self.f_xs = pygame.font.SysFont("segoeui,arial", 12)
        self.mono = pygame.font.SysFont("consolas,monospace", 15)
        self.mono_sm = pygame.font.SysFont("consolas,monospace", 12)
        self.names = scen.scenario_names()
        self.world: World | None = None
        self.toast = ("", 0)
        self.buttons: list[Button] = []
        self.menu_buttons: list[Button] = []
        if scenario is not None:
            self.state = "playing"
            self._start(scenario)
        else:
            self.state = "menu"
            self._relayout()

    # ------------------------------------------------------------ lifecycle
    def _start(self, name: str) -> None:
        self.world = World(name)
        self.state = "playing"
        self._relayout()

    def _toast(self, text: str) -> None:
        self.toast = (text, 150)

    # ------------------------------------------------------------ layout
    def _relayout(self) -> None:
        R = pygame.Rect
        if self.state == "menu":
            self._layout_menu()
            return
        W, H, pad = self.W, self.H, 14
        self.lay = {}
        self.lay["top"] = R(pad, 10, W - 2 * pad, 66)
        bar_h = 104
        self.lay["bar"] = R(pad, H - bar_h, W - 2 * pad, bar_h - pad)
        y0 = self.lay["top"].bottom + 10
        y1 = self.lay["bar"].top - 10
        split = int(W * 0.56)
        self.lay["village"] = R(pad, y0, split - pad, y1 - y0)
        rx = split + 8; rw = W - pad - rx; ch = y1 - y0
        mkt_h = int(ch * 0.44); side_h = int(ch * 0.26)
        self.lay["market"] = R(rx, y0, rw, mkt_h)
        self.lay["side"] = R(rx, y0 + mkt_h + 8, rw, side_h)
        self.lay["log"] = R(rx, y0 + mkt_h + side_h + 16, rw, ch - mkt_h - side_h - 16)
        self._build_buttons()

    def _layout_menu(self) -> None:
        R = pygame.Rect
        n = len(self.names)
        cols = 2 if n > 4 else 1
        rows = math.ceil(n / cols)
        bw, bh, gap = 340, 52, 14
        total_w = cols * bw + (cols - 1) * gap
        x0 = (self.W - total_w) // 2
        y0 = 210
        self.menu_buttons = []
        for i, nm in enumerate(self.names):
            c, r = i % cols, i // cols
            rect = R(x0 + c * (bw + gap), y0 + r * (bh + gap), bw, bh)
            self.menu_buttons.append(Button(rect, (lambda name=nm: self._start(name)),
                                            label=nm, hint=f"[{i+1}]"))
        _ = rows

    def _build_buttons(self) -> None:
        """Build the bottom action bar for the current world -- adaptive to N goods,
        the scenario's capital good, and whether it has a rumour network."""
        R = pygame.Rect; w = self.world; bar = self.lay["bar"]
        defs: list[tuple[str, str, callable, bool]] = []
        # one gather button per consumable good (label, hint, callback, enabled)
        for i, g in enumerate(w.consumables):
            defs.append((f"Gather {g[:11]}", f"[{i+1}]",
                         (lambda good=g: w.gather(good)), True))
        if w.has_capital:
            defs.append((w.capital_label(), "[b]", w.build, True))
        defs.append((f"Warn {w.primary[:8]}", "[w]", w.warn, w.has_prop))
        defs.append(("Perform", "[p]", w.perform_ready, True))
        defs.append(("Fund (deal)", "[f]", w.fund_first, True))
        defs.append(("Auto day", "[a]", w.auto_day, True))
        # lay them across the top row of the bar
        n = len(defs); gap = 6
        bw = (bar.w - (n - 1) * gap) / max(n, 1)
        by = bar.y + 4; bh = 40
        self.buttons = []
        for i, (label, hint, cb, en) in enumerate(defs):
            rect = R(int(bar.x + i * (bw + gap)), by, int(bw), bh)
            self.buttons.append(Button(rect, cb, label=label, hint=hint, enabled=en))
        # trade buttons live in the market panel (built there); end-day is drawn
        # as an accent button on the bar's second row.
        self.end_rect = R(bar.right - 150, bar.bottom - 34, 150, 30)

    # ------------------------------------------------------------ input
    def act_key(self, key) -> None:
        if self.state == "menu":
            for i, b in enumerate(self.menu_buttons):
                if key == getattr(pygame, f"K_{i+1}", None):
                    b.cb(); return
            return
        w = self.world
        if self.state == "ended":
            if key == pygame.K_m:
                self.state = "menu"; self._relayout()
            return
        # number keys gather the i-th consumable
        for i, g in enumerate(w.consumables):
            if key == getattr(pygame, f"K_{i+1}", None):
                w.gather(g); return
        if key == pygame.K_b and w.has_capital: w.build()
        elif key == pygame.K_w: w.warn()
        elif key == pygame.K_p: w.perform_ready()
        elif key == pygame.K_f: w.fund_first()
        elif key == pygame.K_a: w.auto_day()
        elif key == pygame.K_RETURN: self._do_end_day()
        elif key == pygame.K_ESCAPE:
            self.state = "menu"; self._relayout()

    def act_click(self, pos) -> None:
        if self.state == "menu":
            for b in self.menu_buttons:
                if b.rect.collidepoint(pos): b.cb(); return
            return
        if self.state == "ended":
            if getattr(self, "menu_rect", None) and self.menu_rect.collidepoint(pos):
                self.state = "menu"; self._relayout()
            return
        for b in self.buttons:
            if b.enabled and b.rect.collidepoint(pos): b.cb(); return
        if self.end_rect.collidepoint(pos): self._do_end_day(); return
        for rect, good, side in getattr(self, "trade_rects", []):
            if rect.collidepoint(pos): self.world.trade(good, side); return

    def _do_end_day(self) -> None:
        self.world.end_day()
        self._relayout()                    # goods/capital never change, but stay safe
        if self.world.done:
            self.state = "ended"

    # ------------------------------------------------------------ loop
    def run(self) -> None:
        while True:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit(); return
                elif e.type == pygame.VIDEORESIZE:
                    self.W = max(self.MINW, e.w); self.H = max(self.MINH, e.h)
                    self.screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
                    self._relayout()
                elif e.type == pygame.KEYDOWN:
                    self.act_key(e.key)
                elif e.type == pygame.MOUSEBUTTONDOWN:
                    self.act_click(e.pos)
            self.draw(); self.clock.tick(60)

    # ------------------------------------------------------------ draw primitives
    def _text(self, s, font, color, x, y, center=False, right=False):
        surf = font.render(s, True, color); r = surf.get_rect()
        if center: r.centerx = x
        elif right: r.right = x
        else: r.x = x
        r.y = y; self.screen.blit(surf, r); return r

    def _panel(self, rect, fill=SURFACE):
        pygame.draw.rect(self.screen, fill, rect, border_radius=12)
        pygame.draw.rect(self.screen, LINE, rect, width=1, border_radius=12)

    def _btn(self, rect, label, hint, enabled=True, accent=False):
        mx, my = pygame.mouse.get_pos(); hot = rect.collidepoint(mx, my)
        if accent:
            pygame.draw.rect(self.screen, EMBERD if hot else EMBER, rect, border_radius=8)
            self._text(label, self.f_sm, BG, rect.centerx, rect.centery - 8, center=True)
            if hint: self._text(hint, self.mono_sm, BG, rect.centerx, rect.centery + 6, center=True)
            return
        fill = SURF2 if enabled else (20, 24, 30)
        if hot and enabled: fill = (38, 48, 60)
        pygame.draw.rect(self.screen, fill, rect, border_radius=8)
        pygame.draw.rect(self.screen, EMBER if hot and enabled else LINE, rect, width=1, border_radius=8)
        c = INK if enabled else (70, 78, 90)
        self._text(self._clip(label, self.f_sm, rect.w - 8), self.f_sm, c,
                   rect.centerx, rect.y + 6, center=True)
        if hint:
            self._text(hint, self.mono_sm, MUTE if enabled else (60, 66, 78),
                       rect.centerx, rect.y + 24, center=True)

    def _clip(self, s, font, maxw):
        if font.size(s)[0] <= maxw:
            return s
        while s and font.size(s + "...")[0] > maxw:
            s = s[:-1]
        return s + "..."

    def _wrap(self, text, font, maxw):
        words, lines, cur = text.split(), [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if font.size(trial)[0] <= maxw or not cur:
                cur = trial
            else:
                lines.append(cur); cur = wd
        if cur:
            lines.append(cur)
        return lines

    def _bar(self, x, y, w, h, frac, color):
        frac = max(0.0, min(1.0, frac))
        pygame.draw.rect(self.screen, (20, 24, 30), (x, y, w, h), border_radius=4)
        if frac > 0:
            pygame.draw.rect(self.screen, color, (x, y, int(w * frac), h), border_radius=4)

    # ------------------------------------------------------------ draw
    def draw(self) -> None:
        self.screen.fill(BG)
        if self.state == "menu":
            self._draw_menu()
        else:
            self._draw_topbar(); self._draw_village(); self._draw_market()
            self._draw_side(); self._draw_log(); self._draw_actionbar()
            if self.state == "ended":
                self._overlay_over()
        self._draw_toast()
        pygame.display.flip()

    def _draw_toast(self) -> None:
        text, frames = self.toast
        if frames <= 0 or not text:
            return
        self.toast = (text, frames - 1)
        w = self.f_sm.size(text)[0] + 20
        box = pygame.Rect((self.W - w) // 2, 78, w, 30)
        pygame.draw.rect(self.screen, SURF2, box, border_radius=8)
        pygame.draw.rect(self.screen, GREEN, box, width=1, border_radius=8)
        self._text(text, self.f_sm, INK, box.centerx, box.y + 7, center=True)

    # ---- menu ----
    def _draw_menu(self) -> None:
        cx = self.W // 2
        self._text("Say the Word", self.f_h1, EMBER, cx, 84, center=True)
        self._text("one skin, every world -- pick a scenario to test",
                   self.f, MUTE, cx, 128, center=True)
        self._text("This body reads only the contract's universal fields, so it renders",
                   self.f_sm, MUTE, cx, 158, center=True)
        self._text("any registered world with no per-scenario code.",
                   self.f_sm, MUTE, cx, 178, center=True)
        for b in self.menu_buttons:
            self._btn(b.rect, b.label, b.hint, enabled=True)
        self._text("click a world, or press its number  ·  Esc returns here in-game",
                   self.mono_sm, MUTE, cx, self.H - 40, center=True)

    # ---- top bar ----
    def _draw_topbar(self) -> None:
        w = self.world; top = self.lay["top"]; self._panel(top)
        self._text(w.name.upper(), self.f_h2, INK, top.x + 14, top.y + 8)
        self._text(f"Day {w.day}  ·  phase: {w.season}", self.mono, MUTE, top.x + 14, top.y + 38)
        d2c = w.days_to_crisis()
        crisis_soon = (w.season == w.sc.crisis_phase) or (0 <= d2c < 20)
        crisis_txt = (f"{w.sc.crisis_phase.upper()} -- peak stress on {w.primary}"
                      if w.season == w.sc.crisis_phase
                      else f"{w.sc.crisis_phase} in {d2c}d" if d2c >= 0 else "")
        me = w.me()
        stats = [("MONEY", f"{me.money:.0f}", INK),
                 ("STAMINA", f"{me.stamina:.0f}", STEEL),
                 ("SCORE", f"{me.contribution_earned:.0f}", EMBER)]
        cw = 96; stats_x = top.right - 14 - len(stats) * cw
        col_x = top.x + 288
        self._text(self._clip(crisis_txt, self.mono, stats_x - col_x - 12), self.mono,
                   EMBER if crisis_soon else MUTE, col_x, top.y + 12)
        self._text(f"market: {w.sc.market.model}", self.mono_sm, MUTE, col_x, top.y + 40)
        x = stats_x
        for label, val, c in stats:
            self._text(label, self.mono_sm, MUTE, x, top.y + 10)
            self._text(val, self.f_h2, c, x, top.y + 26)
            x += cw

    # ---- village (agents + player holdings) ----
    def _draw_village(self) -> None:
        w = self.world; v = self.lay["village"]; self._panel(v)
        self._text("THE VILLAGE", self.mono_sm, MUTE, v.x + 16, v.y + 10)
        # player holdings chips, one per good -- adapts to N goods
        me = w.me()
        self._draw_holdings(v, me)
        cx, cy = v.centerx, v.centery + 22
        Rr = min(v.w, v.h) * 0.30
        others = [a for a in w.snap.agents
                  if not a.is_player and a.kind != "market_maker"]
        spots = []
        for i, a in enumerate(others):
            ang = (i / max(len(others), 1)) * math.tau - math.pi / 2
            spots.append(self._draw_agent(a, cx + math.cos(ang) * Rr, cy + math.sin(ang) * Rr, w))
        spots.append(self._draw_agent(me, cx, cy, w))
        # hover an agent to read its mind: its top perceived scarcity (fears dict),
        # straight from the contract -- the same signal driving its behaviour.
        if not self.headless:
            mx, my = pygame.mouse.get_pos()
            for a, ax, ay, rad in spots:
                if a.is_player:
                    continue
                if (mx - ax) ** 2 + (my - ay) ** 2 <= (rad + 6) ** 2:
                    self._draw_speech(ax, ay - rad - 6, self._mind(a), v)
                    break

    def _draw_holdings(self, v, me) -> None:
        w = self.world
        x = v.x + 16; y = v.bottom - 30
        self._text("YOU hold:", self.mono_sm, MUTE, x, y - 2)
        x += 78
        for g in w.consumables:
            q = me.holdings.get(g, 0.0)
            chip = f"{g[:11]} {q:.0f}"
            cw = self.mono_sm.size(chip)[0] + 14
            if x + cw > v.right - 12:
                break
            box = pygame.Rect(x, y - 4, cw, 20)
            pygame.draw.rect(self.screen, SURF2, box, border_radius=6)
            self._text(chip, self.mono_sm, INK, x + 7, y)
            x += cw + 6

    def _mind(self, a) -> tuple[str, str]:
        """A generic 'what's on this agent's mind' line: its worst perceived
        scarcity, from the universal fears dict. Returns (text, tag)."""
        fears = a.fears or {}
        if fears:
            good, val = max(fears.items(), key=lambda kv: kv[1])
        else:
            good, val = self.world.primary, 0.0
        who = {"dependent": "I can't produce my own -- ",
               "institution": "Our charter demands it -- ",
               "merchant": ""}.get(a.kind, "")
        if val < 0.1:
            return f"{who}{good}? No worry yet.", "system"
        if val < 0.4:
            return f"{who}talk is the {good} will run short.", "hint"
        if val < 0.7:
            return f"{who}I'm laying in {good} while I can.", "word"
        return f"{who}the {good} is nearly gone and it frightens me.", "cold"

    def _draw_agent(self, a, x, y, w):
        fears = a.fears or {}
        top_fear = max(fears.values(), default=0.0)
        base = KIND_COLORS.get(a.kind, GREEN)
        if a.is_player:
            col, rad = EMBER, 24
        elif top_fear > 0.6:
            col, rad = CRIMSON, 15
        elif top_fear > 0.35:
            col, rad = BELIEF, 15
        else:
            col, rad = base, 14
        # dependents / institutions get a ring so their special role reads at a glance
        if a.kind in ("dependent", "institution"):
            pygame.draw.circle(self.screen, base, (int(x), int(y)), rad + 6, width=2)
        pygame.draw.circle(self.screen, col, (int(x), int(y)), rad)
        pygame.draw.circle(self.screen, BG, (int(x), int(y)), rad, width=2)
        if a.is_player:
            self._text("YOU", self.mono_sm, BG, int(x), int(y) - 8, center=True)
        return a, int(x), int(y), rad

    def _draw_speech(self, ax, ay, mind, bounds) -> None:
        text, tag = mind
        color = TAG_COLORS.get(tag, INK)
        font = self.f_xs; maxw = min(230, bounds.w - 24)
        lines = self._wrap(text, font, maxw)
        lh = font.get_height() + 2
        ww = max(font.size(ln)[0] for ln in lines) + 16
        hh = lh * len(lines) + 12
        x = int(max(bounds.x + 6, min(ax - ww // 2, bounds.right - ww - 6)))
        y = int(max(bounds.y + 6, ay - hh - 6))
        box = pygame.Rect(x, y, ww, hh)
        pygame.draw.rect(self.screen, SURF2, box, border_radius=8)
        pygame.draw.rect(self.screen, color, box, width=1, border_radius=8)
        for i, ln in enumerate(lines):
            self._text(ln, font, INK, x + 8, y + 6 + i * lh)

    # ---- market panel (per-consumable, with trade buttons) ----
    def _draw_market(self) -> None:
        w = self.world; acc = self.lay["market"]; self._panel(acc)
        self._text("THE AI ACCOUNTANT", self.mono_sm, EMBER, acc.x + 14, acc.y + 10)
        self._text("fair value & unmet need -- what only you can see", self.f_xs, MUTE, acc.x + 14, acc.y + 28)
        goods = w.consumables
        top = acc.y + 50; avail_h = acc.bottom - top - 8
        step = avail_h / max(len(goods), 1)
        self.trade_rects = []
        for i, g in enumerate(goods):
            y = int(top + i * step)
            m = w.market(g)
            ref = m.ref_price if m else 0.0
            fair = m.fair_price if m else 0.0
            unmet = w.snap.village_unmet.get(g, 0.0)
            self._text(g.upper()[:14], self.f_h2 if step > 60 else self.f, INK, acc.x + 14, y)
            self._text(f"mkt {ref:5.1f}  fair {fair:5.1f}", self.mono, MUTE, acc.x + 14, y + 24)
            # valuation cue (generic: undervalued -> supply it; overpriced -> sell)
            if fair > 0 and ref < fair * 0.85:
                self._text("UNDERVALUED -- gather & supply", self.f_xs, GREEN, acc.x + 14, y + 44)
            elif fair > 0 and ref > fair * 1.15:
                self._text("OVERPRICED -- sell into it", self.f_xs, EMBER, acc.x + 14, y + 44)
            elif unmet > 0.5:
                self._text(f"village unmet {unmet:.0f}", self.f_xs, CRIMSON, acc.x + 14, y + 44)
            else:
                self._text("fairly priced", self.f_xs, MUTE, acc.x + 14, y + 44)
            # sell/buy buttons
            bx = acc.right - 128
            sr = pygame.Rect(bx, y + 6, 58, 24); br = pygame.Rect(bx + 64, y + 6, 58, 24)
            self._btn(sr, "Sell", "", enabled=True)
            self._btn(br, "Buy", "", enabled=True)
            self.trade_rects.append((sr, g, "sell"))
            self.trade_rects.append((br, g, "buy"))

    # ---- side panel: standing, problems, loans ----
    def _draw_side(self) -> None:
        w = self.world; st = self.lay["side"]; self._panel(st)
        rep = w.reputation()
        self._text("YOUR STANDING", self.mono_sm, MUTE, st.x + 14, st.y + 8)
        self._text(f"{rep.standing:.0f}", self.f_h2, EMBER, st.x + 14, st.y + 24)
        self._text(rep.descriptor, self.f_sm, GOLD, st.x + 60, st.y + 30)
        # problems (Layer 1): worst-first, with a severity bar
        self._text("LIVE PROBLEMS", self.mono_sm, MUTE, st.x + 14, st.y + 52)
        y = st.y + 70
        probs = w.problems(3)
        if not probs:
            self._text("none right now", self.f_xs, MUTE, st.x + 14, y)
        for p in probs:
            self._text(self._clip(p.key, self.f_xs, st.w - 90), self.f_xs, INK, st.x + 14, y)
            self._bar(st.right - 74, y + 2, 60, 8, p.severity, CRIMSON if p.severity > 0.5 else EMBER)
            y += 18
        # active loans (Layer 3 financing)
        loans = w.loans()
        if loans:
            self._text("LOANS", self.mono_sm, MUTE, st.x + 14, y + 2); y += 18
            for l in loans[:2]:
                self._text(self._clip(f"owe {l.balance:.0f} to {l.lender_id}", self.f_xs, st.w - 28),
                           self.f_xs, STEEL if not l.defaulted else CRIMSON, st.x + 14, y)
                y += 16

    # ---- news log ----
    def _draw_log(self) -> None:
        w = self.world; lg = self.lay["log"]; self._panel(lg)
        self._text("THE DAY'S NEWS", self.mono_sm, MUTE, lg.x + 14, lg.y + 8)
        yy = lg.y + 30; maxl = max(1, (lg.h - 34) // 20); avail = lg.w - 28
        for t, tag in w.news[-maxl:]:
            c = TAG_COLORS.get(tag, INK)
            self._text(self._clip("- " + t, self.f_xs, avail), self.f_xs, c, lg.x + 14, yy)
            yy += 20

    # ---- action bar ----
    def _draw_actionbar(self) -> None:
        w = self.world; bar = self.lay["bar"]
        for b in self.buttons:
            self._btn(b.rect, b.label, b.hint, enabled=b.enabled)
        # interventions readiness strip + planned actions
        ivs = w.interventions()
        ready = [iv[0] for iv in ivs if iv[5]]
        strip = ("ready: " + ", ".join(ready)) if ready else \
                ("interventions locked (build standing/capital)" if ivs else "")
        self._text(self._clip(strip, self.f_xs, bar.w - 320), self.f_xs,
                   GOLD if ready else MUTE, bar.x + 2, bar.bottom - 30)
        q = ", ".join(w.queued) if w.queued else "nothing yet"
        self._text(self._clip("PLANNED: " + q, self.f_xs, bar.w - 320), self.f_xs,
                   MUTE if not w.queued else INK, bar.x + 2, bar.bottom - 14)
        self._btn(self.end_rect, "End Day", "Enter", accent=True)

    # ---- end overlay ----
    def _overlay_over(self) -> None:
        s = pygame.Surface((self.W, self.H), pygame.SRCALPHA); s.fill((10, 13, 18, 238))
        self.screen.blit(s, (0, 0))
        w = self.world; cx = self.W // 2; y = 150
        self._text("The cycle has turned.", self.f_h1, EMBER, cx, y, center=True); y += 56
        self._text(f"{w.name}  ·  day {w.day}", self.f_h2, MUTE, cx, y, center=True); y += 48
        welfare = w.core.welfare()
        self._text(f"Contribution earned:   {w.core.score('PLAYER'):.0f}",
                   self.f_h2, INK, cx, y, center=True); y += 40
        prim = w.primary
        unmet = welfare.get(f"village_unmet_{prim}", 0.0)
        self._text(f"Village unmet {prim} across the run:  {unmet:.0f}",
                   self.f, STEEL, cx, y, center=True); y += 30
        paid = welfare.get("total_reward_paid", 0.0)
        self._text(f"Total contribution the index paid out:  {paid:.0f}",
                   self.f, MUTE, cx, y, center=True); y += 44
        self.menu_rect = pygame.Rect(cx - 100, y, 200, 44)
        self._btn(self.menu_rect, "Back to menu  [M]", "", accent=True)


if __name__ == "__main__":
    name = None
    for a in sys.argv[1:]:
        if not a.startswith("-"):
            name = a
    if name is not None and name not in scen.scenario_names():
        print(f"unknown scenario {name!r}; known: {scen.scenario_names()}")
        raise SystemExit(1)
    Game(scenario=name).run()
