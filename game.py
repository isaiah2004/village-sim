"""
Say the Word -- pygame VIEW (one of potentially many bodies).

This file is PURE PRESENTATION. It owns the window, the fonts, the colour skin,
the layout, and how input maps to intent -- and nothing else. All game rules live
in GameSession (session.py); all simulation lives in SimCore behind the contract.

    SimCore (sim)  <-  GameSession (rules)  <-  THIS View (skin)

Swapping the skin -- e.g. a top-down pixel game with walking characters instead of
this click-sim -- means writing a new View against the same GameSession API
(read its state, call its action methods) and touching neither the rules nor the
sim. This View reaches the world only through `self.s` (the session); it never
imports the sim engine, and it maps SEMANTIC news tags to colour here, so a
different body can map them to sprites or sounds instead.

    pip install pygame
    python game.py
"""
from __future__ import annotations

import math
import sys

try:
    import pygame
except ImportError:
    print("pygame is not installed. Run:  pip install pygame")
    sys.exit(1)

from config import Resource, Season
from session import GameSession

# ---- the skin: this View's palette. All look-and-feel lives here. ----
BG      = (14, 19, 25);  SURFACE = (22, 28, 37);  SURF2 = (29, 37, 48)
INK     = (231, 235, 241); MUTE = (131, 144, 160)
EMBER   = (232, 106, 58);  EMBERD = (194, 74, 22)
STEEL   = (109, 138, 166); GREEN = (90, 167, 124)
CRIMSON = (224, 87, 79);   BELIEF = (155, 139, 200); LINE = (40, 49, 61)

# semantic news tag -> colour. A pixel-art body would map these tags to icons or
# sound cues instead; the session never dictates colour.
TAG_COLORS = {
    "system": MUTE, "contribution": EMBER, "sold": GREEN, "bought": STEEL,
    "unsold": MUTE, "cold": CRIMSON, "dependent_cold": CRIMSON, "word": BELIEF,
    "hint": STEEL, "asset": GREEN, "starving": CRIMSON, "food_low": CRIMSON,
}


class Button:
    def __init__(self, rect, key, hint="", label=""):
        self.rect = rect; self.key = key; self.hint = hint; self.label = label


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Say the Word")
        self.W, self.H = 1000, 660
        self.MINW, self.MINH = 860, 580
        self.screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.f_h1 = pygame.font.SysFont("georgia,serif", 30, bold=True)
        self.f_h2 = pygame.font.SysFont("georgia,serif", 20, bold=True)
        self.f = pygame.font.SysFont("segoeui,arial", 16)
        self.f_sm = pygame.font.SysFont("segoeui,arial", 14)
        self.f_xs = pygame.font.SysFont("segoeui,arial", 12)
        self.mono = pygame.font.SysFont("consolas,monospace", 15)
        self.mono_sm = pygame.font.SysFont("consolas,monospace", 12)
        self.s = GameSession()          # the rules; this View only reads/drives it
        self.intro = True               # a View-only splash before the first turn
        self.toast = ("", 0)            # (text, frames-left) transient status line
        self._relayout()

    # ---------------- convenience passthroughs to the session ----------------
    def me(self): return self.s.me()
    def market(self, r): return self.s.market(r)

    # ---------------- layout ----------------
    def _relayout(self):
        W, H = self.W, self.H; pad = 14; R = pygame.Rect
        self.lay = {}
        self.lay["top"] = R(pad, 10, W - 2 * pad, 60)
        bar_h = 92
        self.lay["bar"] = R(pad, H - bar_h, W - 2 * pad, bar_h - pad)
        y0 = self.lay["top"].bottom + 10
        y1 = self.lay["bar"].top - 10
        split = int(W * 0.585)
        self.lay["village"] = R(pad, y0, split - pad, y1 - y0)
        rx = split + 8; rw = W - pad - rx; ch = y1 - y0
        acc_h = int(ch * 0.50); stand_h = int(ch * 0.20)
        self.lay["acc"] = R(rx, y0, rw, acc_h)
        self.lay["stand"] = R(rx, y0 + acc_h + 8, rw, stand_h)
        self.lay["log"] = R(rx, y0 + acc_h + stand_h + 16, rw, ch - acc_h - stand_h - 16)
        # bottom action buttons
        bar = self.lay["bar"]
        keys = [(pygame.K_q, "Q"), (pygame.K_w, "W"), (pygame.K_e, "E"),
                (pygame.K_d, "D"), (pygame.K_f, "F"), (pygame.K_RETURN, "Enter")]
        n = len(keys); gap = 8; bw = (bar.w - (n - 1) * gap) / n
        by = bar.y + 26; bh = bar.h - 30
        self.buttons = [Button(R(int(bar.x + i * (bw + gap)), by, int(bw), bh), k, h)
                        for i, (k, h) in enumerate(keys)]
        # trade buttons inside the accountant panel (sell/buy per resource)
        acc = self.lay["acc"]; self.trades = []
        yy = acc.y + 50
        for r in (Resource.WOOD, Resource.FOOD):
            bx = acc.right - 128
            self.trades.append((R(bx, yy + 20, 58, 24), r, "sell"))
            self.trades.append((R(bx + 64, yy + 20, 58, 24), r, "buy"))
            yy += int((acc.h - 60) / 2)

    # ---------------- input -> intent ----------------
    def act(self, key):
        s = self.s
        if self.intro:
            self.intro = False; return
        if s.phase == "ended":
            if key == pygame.K_r:
                s.new_game()
            return
        if key == pygame.K_q:      s.gather(Resource.WOOD)
        elif key == pygame.K_w:    s.gather(Resource.FOOD)
        elif key == pygame.K_e:    s.build_woodlot()
        elif key == pygame.K_d:    s.warn()
        elif key == pygame.K_f:    s.fast_forward()
        elif key == pygame.K_s:    self._save()
        elif key == pygame.K_l:    self._load()
        elif key == pygame.K_RETURN: s.end_day()

    def _save(self):
        path = self.s.save_to_file()
        self._toast(f"Saved  ·  day {self.s.day}")

    def _load(self):
        self._toast(f"Loaded  ·  day {self.s.day}" if self.s.load_from_file()
                    else "No save found")

    def _toast(self, text):
        self.toast = (text, 150)        # ~2.5s at 60fps

    # ---------------- loop ----------------
    def run(self):
        while True:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit(); return
                elif e.type == pygame.VIDEORESIZE:
                    self.W = max(self.MINW, e.w); self.H = max(self.MINH, e.h)
                    self.screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
                    self._relayout()
                elif e.type == pygame.KEYDOWN:
                    self.act(e.key)
                elif e.type == pygame.MOUSEBUTTONDOWN:
                    if self.intro:
                        self.intro = False
                    elif self.s.phase == "ended":
                        if self.restart_rect.collidepoint(e.pos):
                            self.s.new_game()
                    else:
                        for b in self.buttons:
                            if b.rect.collidepoint(e.pos): self.act(b.key)
                        for rect, r, side in self.trades:
                            if rect.collidepoint(e.pos): self.s.trade(r, side)
            self.draw(); self.clock.tick(60)

    # ---------------- render ----------------
    def draw(self):
        self.screen.fill(BG)
        self._draw_topbar(); self._draw_village(); self._draw_side()
        self._draw_actionbar(); self._draw_log()
        if self.intro: self._overlay_intro()
        elif self.s.phase == "ended": self._overlay_over()
        self._draw_toast()
        pygame.display.flip()

    def _draw_toast(self):
        text, frames = self.toast
        if frames <= 0 or not text:
            return
        self.toast = (text, frames - 1)
        pad = 10
        w = self.f_sm.size(text)[0] + pad * 2
        box = pygame.Rect((self.W - w) // 2, 74, w, 30)
        pygame.draw.rect(self.screen, SURF2, box, border_radius=8)
        pygame.draw.rect(self.screen, GREEN, box, width=1, border_radius=8)
        self._text(text, self.f_sm, INK, box.centerx, box.y + 7, center=True)

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
            self._text(label, self.f_sm, BG, rect.centerx, rect.y + 7, center=True)
            if hint: self._text(hint, self.mono_sm, BG, rect.centerx, rect.y + 26, center=True)
            return
        fill = SURF2 if enabled else (20, 24, 30)
        if hot and enabled: fill = (38, 48, 60)
        pygame.draw.rect(self.screen, fill, rect, border_radius=8)
        pygame.draw.rect(self.screen, EMBER if hot and enabled else LINE, rect, width=1, border_radius=8)
        c = INK if enabled else (70, 78, 90)
        self._text(label, self.f_sm, c, rect.centerx, rect.y + 7, center=True)
        if hint: self._text(hint, self.mono_sm, MUTE if enabled else (60, 66, 78), rect.centerx, rect.y + 26, center=True)

    def _draw_topbar(self):
        me = self.me(); top = self.lay["top"]; self._panel(top)
        season = self.s.season.upper()
        dtw = self.s.cfg.days_until_season(self.s.day, Season.WINTER)
        self._text(f"Day {self.s.day}", self.f_h2, INK, top.x + 14, top.y + 8)
        self._text(season, self.f_sm, CRIMSON if season == "WINTER" else STEEL, top.x + 14, top.y + 34)
        self._text(f"Winter in {dtw}d" if season != "WINTER" else "WINTER -- wood is life",
                   self.mono, EMBER if (season != "WINTER" and dtw < 20) or season == "WINTER" else MUTE,
                   top.x + 116, top.y + 20)
        food_col = CRIMSON if me.food < 2 else GREEN
        stats = [("MONEY", f"{me.money:.0f}", INK), ("WOOD", f"{me.wood:.0f}", EMBER),
                 ("FOOD", f"{me.food:.0f}", food_col),
                 ("STAMINA", f"{self.s.stamina_left()}/{int(round(me.stamina))}", STEEL),
                 ("SCORE", f"{me.contribution_earned:.0f}", EMBER)]
        cw = min(104, (top.right - 300) / 5)
        x = top.right - 14 - len(stats) * cw
        for label, val, c in stats:
            self._text(label, self.mono_sm, MUTE, x, top.y + 10)
            self._text(val, self.f_h2, c, x, top.y + 26)
            x += cw

    def _draw_village(self):
        v = self.lay["village"]; self._panel(v)
        self._text("THE VILLAGE", self.mono_sm, MUTE, v.x + 16, v.y + 10)
        if self.s.warn_ever:
            self._text(f"word of winter: {self.s.wood_awareness*100:.0f}% expect it"
                       + (f"  ({self.s.wood_roots} sources)" if self.s.wood_roots else ""),
                       self.f_xs, BELIEF, v.right - 16, v.y + 12, right=True)
        cx, cy = v.centerx, v.centery + 6; Rr = min(v.w, v.h) * 0.37
        others = [a for a in self.s.snap.agents if a.kind != "market_maker" and not a.is_player]
        spots = []                       # (agent, x, y, rad) for hover hit-testing
        for i, a in enumerate(others):
            ang = (i / max(len(others), 1)) * math.tau - math.pi / 2
            spots.append(self._draw_agent(a, cx + math.cos(ang) * Rr, cy + math.sin(ang) * Rr))
        spots.append(self._draw_agent(self.me(), cx, cy))
        # hover a villager to hear their mind: the bubble text is that agent's
        # real belief, rendered by the session through the SimCore contract.
        if not self.intro and self.s.phase == "playing":
            mx, my = pygame.mouse.get_pos()
            for a, ax, ay, rad in spots:
                if a.is_player:
                    continue
                if (mx - ax) ** 2 + (my - ay) ** 2 <= (rad + 6) ** 2:
                    line, tag = self.s.villager_line(a.id)
                    self._draw_speech(ax, ay - rad - 6, line, TAG_COLORS.get(tag, INK), v)
                    break

    def _draw_agent(self, a, x, y):
        cold = a.id in self.s.cold_today
        if a.is_player: col, rad = EMBER, 26
        elif cold: col, rad = CRIMSON, 17
        elif a.fear_wood > 0.5: col, rad = BELIEF, 15
        else: col, rad = GREEN, 15
        if a.kind == "dependent":
            pygame.draw.circle(self.screen, CRIMSON if cold else MUTE, (int(x), int(y)), rad + 6, width=2)
        pygame.draw.circle(self.screen, col, (int(x), int(y)), rad)
        pygame.draw.circle(self.screen, BG, (int(x), int(y)), rad, width=2)
        if a.is_player:
            self._text("YOU", self.mono_sm, BG, int(x), int(y) - 8, center=True)
            self._text(f"{a.wood:.0f}w {a.food:.0f}f", self.mono_sm, INK, int(x), int(y) + 30, center=True)
        return a, int(x), int(y), rad

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

    def _draw_speech(self, ax, ay, text, color, bounds):
        """A small speech bubble above an agent, clamped inside the village panel."""
        font = self.f_xs; maxw = min(230, bounds.w - 24)
        lines = self._wrap(text, font, maxw)
        lh = font.get_height() + 2
        w = max(font.size(ln)[0] for ln in lines) + 16
        h = lh * len(lines) + 12
        x = int(max(bounds.x + 6, min(ax - w // 2, bounds.right - w - 6)))
        y = int(max(bounds.y + 6, ay - h - 6))
        box = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.screen, SURF2, box, border_radius=8)
        pygame.draw.rect(self.screen, color, box, width=1, border_radius=8)
        for i, ln in enumerate(lines):
            self._text(ln, font, INK, x + 8, y + 6 + i * lh)

    def _draw_side(self):
        me = self.me(); acc = self.lay["acc"]; self._panel(acc)
        self._text("THE AI ACCOUNTANT", self.mono_sm, EMBER, acc.x + 14, acc.y + 10)
        self._text("fair value -- what only you can see", self.f_xs, MUTE, acc.x + 14, acc.y + 28)
        y = acc.y + 50
        step = int((acc.h - 60) / 2)
        for r in (Resource.WOOD, Resource.FOOD):
            m = self.market(r)
            self._text((r.value if hasattr(r,'value') else r).upper(), self.f_h2, INK, acc.x + 14, y)
            self._text(f"market {m.ref_price:5.1f}", self.mono, MUTE, acc.x + 14, y + 26)
            self._text(f"fair   {m.fair_price:5.1f}", self.mono, EMBER, acc.x + 14, y + 44)
            if m.ref_price < m.fair_price * 0.85:
                self._text("UNDERVALUED - gather & supply", self.f_xs, GREEN, acc.x + 14, y + 64)
            elif m.ref_price > m.fair_price * 1.15:
                self._text("OVERPRICED - sell into it", self.f_xs, EMBER, acc.x + 14, y + 64)
            else:
                self._text("fairly priced", self.f_xs, MUTE, acc.x + 14, y + 64)
            y += step
        for rect, r, side in self.trades:
            can = (side == "buy") or self.s.can_sell(r)
            self._btn(rect, side.title(), "", enabled=can)
        # standing + woodlot readout
        st = self.lay["stand"]; self._panel(st)
        self._text("YOUR STANDING", self.mono_sm, MUTE, st.x + 14, st.y + 8)
        self._text(f"{me.contribution_earned:.0f}", self.f_h1, EMBER, st.x + 14, st.y + 24)
        kept = len(self.s.impact)
        self._text("contribution" + (f"  ·  kept {kept} warm" if kept else ""),
                   self.f_sm, MUTE if not kept else GREEN, st.x + 14, st.y + 62)
        if me.woodlot_level > 0:
            upkeep = self.s.cfg.woodlot_upkeep_food * me.woodlot_level
            self._text(f"Woodlot  Lv {me.woodlot_level}/{self.s.cfg.woodlot_max_level}", self.f_sm, GREEN, st.x + 120, st.y + 20)
            self._text(f"+{me.woodlot_output:.1f} wood/day", self.mono_sm, GREEN, st.x + 120, st.y + 42)
            self._text(f"eats {upkeep:.1f} food/day", self.mono_sm, MUTE, st.x + 120, st.y + 58)
        else:
            self._text("no woodlot yet", self.f_sm, MUTE, st.x + 120, st.y + 30)

    def _draw_actionbar(self):
        me = self.me(); winter = self.s.season == "winter"
        lvl = me.woodlot_level; maxl = self.s.cfg.woodlot_max_level
        wl_label = "Build Woodlot" if lvl == 0 else (f"Upgrade Wd L{lvl+1}" if lvl < maxl else "Woodlot MAX")
        wl_hint = f"E · {self.s.wl_cost(lvl):.0f}w" if lvl < maxl else "E"
        defs = [
            ("Gather Wood", "Q", self.s.can_gather()),
            ("Gather Food", "W", self.s.can_gather()),
            (wl_label, wl_hint, self.s.can_build_woodlot()),
            ("Warn Winter", "D", self.s.can_warn()),
            ("Fast > Winter", "F", self.s.can_fast_forward()),
        ]
        for b, (label, hint, en) in zip(self.buttons[:5], defs):
            self._btn(b.rect, label, hint, enabled=en)
        self._btn(self.buttons[5].rect, "End Day", "Enter", accent=True)
        q = ", ".join(self.s.queued) if self.s.queued else "nothing yet"
        self._text("PLANNED: " + q, self.f_xs, MUTE if not self.s.queued else INK,
                   self.lay["bar"].x + 2, self.lay["bar"].y + 4)
        self._text("S save · L load", self.f_xs, MUTE,
                   self.lay["bar"].right - 2, self.lay["bar"].y + 4, right=True)

    def _clip(self, s, font, maxw):
        if font.size(s)[0] <= maxw:
            return s
        while s and font.size(s + "...")[0] > maxw:
            s = s[:-1]
        return s + "..."

    def _draw_log(self):
        lg = self.lay["log"]; self._panel(lg)
        self._text("THE DAY'S NEWS", self.mono_sm, MUTE, lg.x + 14, lg.y + 8)
        yy = lg.y + 30; maxl = max(1, (lg.h - 34) // 20); avail = lg.w - 28
        for t, tag in self.s.news[-maxl:]:
            c = TAG_COLORS.get(tag, INK)
            self._text(self._clip("- " + t, self.f_xs, avail), self.f_xs, c, lg.x + 14, yy); yy += 20

    # ---------------- overlays ----------------
    def _dim(self):
        s = pygame.Surface((self.W, self.H), pygame.SRCALPHA); s.fill((10, 13, 18, 238))
        self.screen.blit(s, (0, 0))

    def _overlay_intro(self):
        self._dim(); cx = self.W // 2
        self._text("Say the Word", self.f_h1, EMBER, cx, 64, center=True)
        for i, (ln, c) in enumerate([
            ("You are a villager, but you carry a modern mind: you alone can read", INK),
            ("the Accountant's FAIR VALUE for every good. The village cannot.", INK),
            ("", INK),
            ("Winter is coming and wood grows scarce. Three households garden food", INK),
            ("but cannot chop wood -- they buy it, and they go cold first. And you", INK),
            ("must eat: run out of food for three days and you starve.", INK),
            ("", INK),
            ("Gather, build & upgrade a woodlot (passive wood), trade into scarcity,", INK),
            ("or spend a day carrying word of winter so the village prepares. Your", INK),
            ("score is the worth of the need you meet -- most for those who can't cut wood.", INK),
            ("", INK),
            ("Q wood  W food  E woodlot  D warn  F fast-forward  Enter end day", STEEL),
            ("Sell / Buy in the Accountant panel.  S save · L load · hover a villager to hear them.", STEEL),
        ]):
            self._text(ln, self.f, c, cx, 124 + i * 26, center=True)
        self._text("click or press any key to begin", self.mono, MUTE, cx, 124 + 13 * 26, center=True)

    def _overlay_over(self):
        self._dim(); cx = self.W // 2
        res = self.s.result or {}
        contrib = res.get("contribution", 0.0)
        wu = res.get("winter_unmet", 0.0)
        base = res.get("baseline_unmet", wu)
        saved = res.get("saved", 0.0)
        reason = res.get("reason", "")
        y = 130
        self._text("The year has turned." if not reason else "You did not survive it.",
                   self.f_h1, EMBER if not reason else CRIMSON, cx, y, center=True); y += 56
        if reason:
            self._text(reason, self.f, INK, cx, y, center=True); y += 40
        self._text(f"Contribution earned:   {contrib:.0f}", self.f_h2, INK, cx, y, center=True); y += 40
        verdict = ("The village came through warm." if wu < 8 else
                   "The village suffered the winter." if wu < 25 else "Many froze. The winter was cruel.")
        vcol = GREEN if wu < 8 else (EMBER if wu < 25 else CRIMSON)
        self._text(verdict, self.f_h2, vcol, cx, y, center=True); y += 48
        # impact diagnostic: what if you had never been here?
        self._text("WHAT IF YOU HADN'T BEEN HERE?", self.mono_sm, MUTE, cx, y, center=True); y += 24
        self._text(f"Without you, the village would have lost  {base:.0f}  to winter.",
                   self.f, MUTE, cx, y, center=True); y += 26
        self._text(f"You brought it to  {wu:.0f}   ({'-' if saved>=0 else '+'}{abs(saved):.0f} suffering).",
                   self.f, GREEN if saved > 1 else STEEL, cx, y, center=True); y += 44
        # the WARNING lever's measured, isolated effect (your words on their own)
        if res.get("warned"):
            we = res.get("warning_effect", 0.0)
            self._text("YOUR WARNING", self.mono_sm, MUTE, cx, y, center=True); y += 24
            if we > 1:
                self._text(f"On its own, your word would have spared the village {we:.0f} winter suffering.",
                           self.f, BELIEF, cx, y, center=True); y += 26
            else:
                self._text("Your word reached them, though supply held either way this year.",
                           self.f, MUTE, cx, y, center=True); y += 26
            y += 12
        # who you actually kept warm across the year -- the realized-effect story
        if res.get("kept_warm"):
            self._text("WHO YOU KEPT WARM", self.mono_sm, MUTE, cx, y, center=True); y += 24
            self._text(f"Your wood met {res['kept_warm']} villager(s)' need {res['times']} times this year.",
                       self.f, INK, cx, y, center=True); y += 26
            if res.get("dependents"):
                self._text(f"{res['dependents']} were dependent households who cannot cut their own wood.",
                           self.f, EMBER, cx, y, center=True); y += 26
            y += 14
        self.restart_rect = pygame.Rect(cx - 90, y, 180, 44)
        self._btn(self.restart_rect, "Play Again  [R]", "", accent=True)


if __name__ == "__main__":
    import sys
    # This pygame body renders the AUTHORED frostpine game (its winter/wood UI is
    # bespoke). Selecting any OTHER registered world is supported through the
    # scenario-agnostic body in view_play.py, which drives the same SimCore
    # contract -- so `game.py --scenario <name>` hands off to it rather than
    # forcing a frostpine-shaped UI onto a world it doesn't fit.
    if "--scenario" in sys.argv:
        i = sys.argv.index("--scenario")
        _name = sys.argv[i + 1] if i + 1 < len(sys.argv) else "frostpine"
        if _name != "frostpine":
            import view_play
            raise SystemExit(view_play.play(_name))
    Game().run()
