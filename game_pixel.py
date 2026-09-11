"""
Frostpine -- a top-down PIXEL-GAME body over the same brain, built pygbag-first so
it ships to the web (pygame -> WASM). It is the walk-around twin of view_play.py:
you move a character around the village and ACT by walking up to things, and every
action goes through GameSession -- this file adds NO game logic and never touches
the sim, the rules, the contract, or the golden master.

    SimCore (sim)  <-  GameSession (rules)  <-  THIS pixel View (skin)

Why pygbag-first (all non-negotiable for a browser build):
  * everything runs inside `async def main()` and ends with `asyncio.run(main())`;
  * the frame loop yields to the browser with `await asyncio.sleep(0)` every frame;
  * NO blocking calls in the loop -- no input(), no time.sleep, no threads, no
    sys.exit mid-loop, no synchronous file dialogs; assets are built at startup;
  * the one heavy thing the brain does -- GameSession._end runs two full "ghost"
    SimCores for the counterfactual -- is fenced behind a painted "tallying the
    year..." beat so the tab shows a frame before that (~1s in WASM) compute;
  * disk save/load is skipped in this body (the browser FS is virtual).

Art is self-made, in-code pixel sprites (flat-colour primitives on small surfaces)
-- CC0 by construction, no external fetch. Art isn't the point; the point is that a
neutral tester can play the tuned frostpine world from a link.

    pip install pygame           # then, locally:  python game_pixel.py
    pip install pygbag           # web build:       see DEPLOY-WEB.md
"""
from __future__ import annotations

import asyncio

import pygame

from config import Resource, Season
from session import GameSession

# --------------------------------------------------------------------- skin
TILE = 32
VIEW_W, VIEW_H = 928, 640          # viewport (camera window) in pixels

# palette (a cool dusk village; hard flat colours read as pixel art)
BG      = (18, 22, 30)
GRASS   = (58, 92, 66);  GRASS2 = (66, 104, 74);  PATH = (120, 104, 78)
INK     = (233, 237, 243); MUTE = (150, 162, 178); PANEL = (24, 30, 41, 232)
EMBER   = (232, 128, 66);  EMBERD = (196, 92, 34)
STEEL   = (120, 150, 180); GREEN = (110, 190, 140)
CRIMSON = (226, 96, 86);   BELIEF = (168, 150, 214); GOLD = (222, 190, 110)
WOOD_C  = (150, 104, 66);  LEAF = (74, 138, 92);   LEAF2 = (60, 118, 78)
SKY     = (44, 58, 80)

# semantic news tag -> colour (the body maps meaning to colour; the session never
# dictates it -- a pixel body could map these to sprites/sounds instead).
TAG_COLORS = {
    "system": MUTE, "contribution": EMBER, "sold": GREEN, "bought": STEEL,
    "unsold": MUTE, "cold": CRIMSON, "dependent_cold": CRIMSON, "word": BELIEF,
    "hint": STEEL, "asset": GREEN, "starving": CRIMSON, "food_low": CRIMSON,
}


def _rv(r):
    return r.value if hasattr(r, "value") else r


# ================================================================ sprites
# Self-made, in-code pixel sprites: each builds a small SRCALPHA surface with flat
# rectangles (a blocky, license-clean pixel look). No external assets, no fetch.
def _surf(w=TILE, h=TILE):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def _rect(s, c, x, y, w, h):
    pygame.draw.rect(s, c, (x, y, w, h))


def spr_tree() -> pygame.Surface:
    s = _surf()
    _rect(s, WOOD_C, 14, 20, 4, 10)
    _rect(s, LEAF2, 6, 6, 20, 16)
    _rect(s, LEAF, 8, 4, 16, 14)
    _rect(s, (92, 160, 110), 11, 6, 7, 6)
    return s


def spr_field() -> pygame.Surface:
    s = _surf()
    _rect(s, (86, 68, 44), 2, 6, 28, 22)
    for i in range(4):
        _rect(s, (150, 176, 92), 4 + i * 7, 8, 3, 18)
        _rect(s, GOLD, 4 + i * 7, 8, 3, 4)
    return s


def spr_woodlot(level: int) -> pygame.Surface:
    s = _surf()
    _rect(s, (70, 54, 38), 3, 22, 26, 7)          # plot bed
    if level <= 0:
        _rect(s, LEAF, 14, 14, 4, 10)             # a sapling
        _rect(s, LEAF, 11, 12, 10, 5)
        return s
    for i in range(min(level, 5)):                 # a growing stack of logs
        _rect(s, WOOD_C, 5 + i, 20 - i * 3, 22 - 2 * i, 3)
        _rect(s, (176, 126, 82), 5 + i, 20 - i * 3, 4, 3)
    return s


def spr_stall() -> pygame.Surface:
    s = _surf()
    _rect(s, (110, 82, 56), 4, 16, 24, 14)        # counter
    _rect(s, (150, 120, 84), 4, 14, 24, 3)
    for i in range(4):                             # striped awning
        _rect(s, EMBER if i % 2 else INK, 4 + i * 6, 6, 6, 8)
    _rect(s, (90, 66, 44), 5, 12, 2, 18); _rect(s, (90, 66, 44), 25, 12, 2, 18)
    return s


def spr_board() -> pygame.Surface:
    s = _surf()
    _rect(s, (86, 64, 42), 14, 16, 4, 14)         # post
    _rect(s, (60, 46, 30), 5, 5, 22, 15)          # frame
    _rect(s, (224, 214, 188), 7, 7, 18, 11)       # parchment
    _rect(s, STEEL, 9, 9, 14, 2); _rect(s, EMBER, 9, 13, 10, 2)
    return s


def spr_bed() -> pygame.Surface:
    s = _surf()
    _rect(s, (74, 58, 40), 4, 10, 24, 18)         # hut base
    _rect(s, CRIMSON, 2, 6, 28, 7)                # roof
    _rect(s, (40, 32, 24), 13, 18, 8, 10)         # door
    return s


def _person(body, hair, small=False) -> pygame.Surface:
    s = _surf()
    dy = 4 if small else 0
    _rect(s, (52, 40, 32), 12, 26 - dy, 8, 4)     # feet
    _rect(s, body, 10, 15 - dy, 12, 12)           # torso
    _rect(s, (226, 196, 166), 12, 8 - dy, 8, 8)   # head
    _rect(s, hair, 12, 6 - dy, 8, 4)              # hair
    return s


def spr_player() -> pygame.Surface:  return _person((80, 150, 210), (60, 44, 30))
def spr_villager() -> pygame.Surface: return _person((150, 120, 84), (44, 34, 24))
def spr_dependent() -> pygame.Surface: return _person((150, 130, 170), (70, 70, 80), small=True)


# ================================================================ the world map
# A hand-laid frostpine as a PLACE: a forest ring, a path, and the village
# fixtures you walk up to. Purely presentational -- positions are this body's, the
# meaning of each fixture is the session action it calls.
LEGEND = [
    "TTTTTTTTTTTTTTTTTTTTTTTTTTTTTT",
    "T............................T",
    "T...TT.......PP.......FFF.....T",
    "T...TT.......PP.......FFF.....T",
    "T............PP..............T",
    "T....N.......PP.......N......T",
    "T............PP..............T",
    "T..TT...bbb..PP.....FFF......T",
    "T..TT...bbb..PP.....FFF......T",
    "T............PP..............T",
    "T......N.....PP......N.......T",
    "T............PP..............T",
    "T...WW.......PP......ss......T",
    "T...WW.......PP......ss..nn..T",
    "T............PP..............T",
    "TTTTTTTTTTTTTTTTTTTTTTTTTTTTTT",
]
MAP_TW, MAP_TH = len(LEGEND[0]), len(LEGEND)
MAP_W, MAP_H = MAP_TW * TILE, MAP_TH * TILE


class Fixture:
    """One thing you can walk up to and act on. `kind` maps to a session action."""
    __slots__ = ("kind", "tx", "ty", "solid")

    def __init__(self, kind, tx, ty, solid=True):
        self.kind = kind; self.tx = tx; self.ty = ty; self.solid = solid

    @property
    def px(self): return self.tx * TILE + TILE // 2
    @property
    def py(self): return self.ty * TILE + TILE // 2


class PixelGame:
    SPEED = 3.0

    def __init__(self, headless: bool = False):
        pygame.init()
        pygame.display.set_caption("Frostpine")
        flags = 0
        self.screen = pygame.display.set_mode((VIEW_W, VIEW_H), flags)
        self.headless = headless
        self.clock = pygame.time.Clock()
        self.f_big = pygame.font.Font(None, 40)
        self.f_h = pygame.font.Font(None, 26)
        self.f = pygame.font.Font(None, 20)
        self.f_sm = pygame.font.Font(None, 17)
        self.running = True
        self.mode = "title"                 # title | play | stall | board | tallying | ended
        self.toast = ("", 0)
        self.bubble = None                  # (agent_id, frames_left)
        self._tally_frames = 0
        self._tally_final = False
        # the brain: this body only reads it and calls its action methods.
        self.s = GameSession()
        self.sprites = self._build_sprites()
        self._build_map()
        # ground texture, rendered once (a static Surface we blit with the camera)
        self.ground = self._build_ground()
        # place the player on the central path, near the bottom (home)
        self.px = 13 * TILE + TILE // 2
        self.py = 12 * TILE + TILE // 2

    # ---------------------------------------------------------- asset build
    def _build_sprites(self) -> dict:
        return {
            "tree": spr_tree(), "field": spr_field(), "stall": spr_stall(),
            "board": spr_board(), "bed": spr_bed(), "player": spr_player(),
            "villager": spr_villager(), "dependent": spr_dependent(),
        }

    def _build_map(self) -> None:
        self.fixtures: list[Fixture] = []
        self.solid: set[tuple[int, int]] = set()
        self.npc_slots: list[tuple[int, int]] = []
        for ty, row in enumerate(LEGEND):
            for tx, ch in enumerate(row):
                if ch == "T":
                    self.fixtures.append(Fixture("wood", tx, ty, solid=True))
                    self.solid.add((tx, ty))
                elif ch == "F":
                    self.fixtures.append(Fixture("food", tx, ty, solid=False))
                elif ch == "b":
                    self.fixtures.append(Fixture("woodlot", tx, ty, solid=False))
                elif ch == "s":
                    self.fixtures.append(Fixture("market", tx, ty, solid=True))
                    self.solid.add((tx, ty))
                elif ch == "n":
                    self.fixtures.append(Fixture("board", tx, ty, solid=True))
                    self.solid.add((tx, ty))
                elif ch == "N":
                    self.npc_slots.append((tx, ty))
        # map session NPCs (villagers + dependents, not the player/market maker) to
        # the N slots, so the people in the map ARE the people in the sim.
        npcs = [a for a in self.s.snap.agents
                if not a.is_player and a.kind != "market_maker"]
        self.npcs: list[tuple[str, int, int]] = []
        for i, a in enumerate(npcs):
            if i >= len(self.npc_slots):
                break
            tx, ty = self.npc_slots[i]
            self.npcs.append((a.id, tx, ty))
            self.solid.add((tx, ty))
        # the woodlot cluster (3x2 'b' tiles) is really one plot -- collapse to one
        # fixture so the hint/action fire once.
        self.fixtures = [f for f in self.fixtures if f.kind != "woodlot"] + \
            [Fixture("woodlot", 8, 7, solid=False)]

    def _build_ground(self) -> pygame.Surface:
        g = pygame.Surface((MAP_W, MAP_H))
        for ty in range(MAP_TH):
            for tx in range(MAP_TW):
                ch = LEGEND[ty][tx]
                base = PATH if ch == "P" else (GRASS2 if (tx + ty) % 2 else GRASS)
                _rect(g, base, tx * TILE, ty * TILE, TILE, TILE)
        return g

    # ---------------------------------------------------------- convenience
    def me(self):
        return self.s.me()

    def _toast(self, text: str) -> None:
        self.toast = (text, 150)

    # ---------------------------------------------------------- input
    def handle_event(self, e) -> None:
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type != pygame.KEYDOWN:
            return
        k = e.key
        if self.mode == "title":
            self.mode = "play"
            return
        if self.mode == "ended":
            if k in (pygame.K_r, pygame.K_RETURN):
                self.s.new_game(); self._build_map()
                self.px = 13 * TILE + TILE // 2; self.py = 12 * TILE + TILE // 2
                self.mode = "play"
            return
        if self.mode == "board":
            self.mode = "play"
            return
        if self.mode == "stall":
            self._stall_key(k)
            return
        if self.mode != "play":
            return
        # in play: action + warn + end-day
        if k in (pygame.K_e, pygame.K_SPACE):
            self._interact()
        elif k == pygame.K_c:          # "carry the word" -- warn of winter
            self._act(self.s.warn(), "You spend the day carrying word of winter.",
                      "Nothing to warn about right now.")
        elif k == pygame.K_RETURN:     # sleep to end the day, only when home at the bed
            if self._bed_here():
                self._try_end_day()
            else:
                self._toast("Head home to the hut, then press Enter to sleep.")

    def _stall_key(self, k) -> None:
        if k == pygame.K_1:
            self._act(self.s.trade(Resource.WOOD, "sell"), "Sold wood at the stall.", "No wood to spare.")
        elif k == pygame.K_2:
            self._act(self.s.trade(Resource.WOOD, "buy"), "Bought wood.", "Couldn't buy wood.")
        elif k == pygame.K_3:
            self._act(self.s.trade(Resource.FOOD, "sell"), "Sold food at the stall.", "No food to spare.")
        elif k == pygame.K_4:
            self._act(self.s.trade(Resource.FOOD, "buy"), "Bought food.", "Couldn't buy food.")
        elif k in (pygame.K_ESCAPE, pygame.K_e, pygame.K_SPACE):
            self.mode = "play"

    def _act(self, ok: bool, ok_msg: str, fail_msg: str) -> None:
        self._toast(ok_msg if ok else fail_msg)

    def _interact(self) -> None:
        f = self._nearest_fixture()
        if f is None:
            npc = self._nearest_npc()
            if npc is not None:
                self.bubble = (npc, 180)
            return
        if f.kind == "wood":
            self._act(self.s.gather(Resource.WOOD), "You chop wood (+stamina spent).",
                      "You're spent -- rest at home to end the day.")
        elif f.kind == "food":
            self._act(self.s.gather(Resource.FOOD), "You gather food.",
                      "You're spent -- rest at home to end the day.")
        elif f.kind == "woodlot":
            lvl = self.me().woodlot_level
            self._act(self.s.build_woodlot(),
                      "You raised your woodlot." if lvl else "You founded a woodlot.",
                      "Not enough wood/stamina for the woodlot.")
        elif f.kind == "market":
            self.mode = "stall"
        elif f.kind == "board":
            self.mode = "board"

    def _try_end_day(self) -> None:
        """End the day at the home/bed. The brain's GameSession._end runs two full
        ghost SimCores (the counterfactual) whenever the game ENDS -- at the natural
        year's end OR on a starvation death. Both are heavy, so fence either behind a
        painted beat: paint a frame first, run the compute next frame. A plain day is
        instant and ends immediately."""
        final_year = self.s.day >= self.s.cfg.total_days - 1
        may_starve = self.s.starving >= self.s.STARVE_DAYS - 1
        if final_year or may_starve:
            self._tally_final = final_year     # which message to show on the beat
            self.mode = "tallying"
            self._tally_frames = 2             # paint the beat for a couple of frames
        else:
            self.s.end_day()
            self._toast(f"You sleep. A new day -- {self.s.season}.")

    # ---------------------------------------------------------- proximity
    def _nearest_fixture(self):
        best, bestd = None, 1.6 * TILE
        for f in self.fixtures:
            d = ((f.px - self.px) ** 2 + (f.py - self.py) ** 2) ** 0.5
            if d < bestd:
                best, bestd = f, d
        return best

    def _nearest_npc(self):
        best, bestd = None, 1.6 * TILE
        for aid, tx, ty in self.npcs:
            cx, cy = tx * TILE + TILE // 2, ty * TILE + TILE // 2
            d = ((cx - self.px) ** 2 + (cy - self.py) ** 2) ** 0.5
            if d < bestd:
                best, bestd = aid, d
        return best

    def _bed_here(self):
        # the home/bed lives at the 'bbb' block; treat that region as the bed
        return 7 <= self.px / TILE <= 10 and 6.5 <= self.py / TILE <= 9

    # ---------------------------------------------------------- update
    def update(self, is_down) -> None:
        if self.mode == "tallying":
            self._tally_frames -= 1
            if self._tally_frames <= 0:
                self.s.end_day()               # the (fenced) heavy compute
                if self.s.ended:
                    self.mode = "ended"
                else:                          # survived a near-starvation day
                    self.mode = "play"
                    self._toast(f"You sleep. A new day -- {self.s.season}.")
            return
        if self.mode != "play":
            return
        if self.bubble is not None:
            aid, fr = self.bubble
            self.bubble = (aid, fr - 1) if fr > 1 else None
        dx = (is_down(pygame.K_d) or is_down(pygame.K_RIGHT)) - (is_down(pygame.K_a) or is_down(pygame.K_LEFT))
        dy = (is_down(pygame.K_s) or is_down(pygame.K_DOWN)) - (is_down(pygame.K_w) or is_down(pygame.K_UP))
        self._move(dx * self.SPEED, dy * self.SPEED)

    def _move(self, vx, vy) -> None:
        if vx:
            self.px = self._slide(self.px + vx, self.py, vx, 0)
        if vy:
            self.py = self._slide(self.px, self.py + vy, 0, vy)

    def _slide(self, nx, ny, vx, vy):
        r = 10                                  # player half-hitbox
        nx = max(TILE + r, min(nx, MAP_W - TILE - r))
        ny = max(TILE + r, min(ny, MAP_H - TILE - r))
        for cx, cy in ((nx - r, ny - r), (nx + r, ny - r), (nx - r, ny + r), (nx + r, ny + r)):
            if (int(cx // TILE), int(cy // TILE)) in self.solid:
                return self.px if vx else self.py
        return nx if vx else ny

    # ---------------------------------------------------------- camera + draw
    def _cam(self):
        cx = max(0, min(int(self.px - VIEW_W // 2), MAP_W - VIEW_W))
        cy = max(0, min(int(self.py - VIEW_H // 2), MAP_H - VIEW_H))
        return cx, cy

    def draw(self) -> None:
        self.screen.fill(BG)
        if self.mode == "title":
            self._draw_title(); return
        cx, cy = self._cam()
        self.screen.blit(self.ground, (-cx, -cy))
        # fixtures
        for f in self.fixtures:
            spr = self._fixture_sprite(f)
            if spr is not None:
                self.screen.blit(spr, (f.tx * TILE - cx, f.ty * TILE - cy))
        # NPCs (colour tint by their real belief/cold, read through the session)
        for aid, tx, ty in self.npcs:
            self._draw_npc(aid, tx * TILE - cx, ty * TILE - cy)
        # player
        self.screen.blit(self.sprites["player"], (int(self.px - TILE // 2 - cx),
                                                  int(self.py - TILE // 2 - cy)))
        # interaction hint
        self._draw_hint(cx, cy)
        # speech bubble
        if self.bubble is not None:
            self._draw_bubble(self.bubble[0], cx, cy)
        # HUD + overlays
        self._draw_hud()
        self._draw_ticker()
        if self.mode == "board":
            self._draw_board()
        elif self.mode == "stall":
            self._draw_stall()
        elif self.mode == "tallying":
            self._center_panel(
                ["Tallying the year...", "(measuring the winter you shaped)"]
                if self._tally_final else
                ["The day closes...", "(a hard reckoning)"])
        elif self.mode == "ended":
            self._draw_result()
        self._draw_toast()

    def _fixture_sprite(self, f):
        if f.kind == "wood":     return self.sprites["tree"]
        if f.kind == "food":     return self.sprites["field"]
        if f.kind == "market":   return self.sprites["stall"]
        if f.kind == "board":    return self.sprites["board"]
        if f.kind == "woodlot":  return spr_woodlot(self.me().woodlot_level)
        return None

    def _draw_npc(self, aid, x, y) -> None:
        view = next((a for a in self.s.snap.agents if a.id == aid), None)
        base = "dependent" if (view and view.kind == "dependent") else "villager"
        spr = self.sprites[base].copy()
        cold = aid in self.s.cold_today
        if cold:
            spr.fill(CRIMSON + (90,), special_flags=pygame.BLEND_RGBA_ADD)
        elif view and view.fear_wood > 0.5:
            spr.fill(BELIEF + (60,), special_flags=pygame.BLEND_RGBA_ADD)
        self.screen.blit(spr, (x, y))

    def _draw_hint(self, cx, cy) -> None:
        label = None
        f = self._nearest_fixture()
        if f is not None:
            label = {"wood": "[E] Chop wood", "food": "[E] Gather food",
                     "woodlot": "[E] Build / upgrade woodlot", "market": "[E] Market stall",
                     "board": "[E] Read the Accountant's board"}[f.kind]
            hx, hy = f.px - cx, f.ty * TILE - cy - 6
        else:
            npc = self._nearest_npc()
            if npc is not None:
                label = "[E] Speak with them"
                nx = next((tx for a, tx, ty in self.npcs if a == npc), 0)
                ny = next((ty for a, tx, ty in self.npcs if a == npc), 0)
                hx, hy = nx * TILE + TILE // 2 - cx, ny * TILE - cy - 6
        if self._bed_here():
            label = "[Enter] Sleep -- end the day"
            hx, hy = int(self.px - cx), int(self.py - TILE - cy)
        if label:
            self._tip(label, hx, hy)

    def _tip(self, text, x, y) -> None:
        surf = self.f_sm.render(text, True, INK)
        r = surf.get_rect(); r.centerx = x; r.bottom = y
        r.clamp_ip(self.screen.get_rect())
        bg = r.inflate(10, 6)
        s = pygame.Surface(bg.size, pygame.SRCALPHA); s.fill((16, 20, 28, 220))
        self.screen.blit(s, bg.topleft)
        pygame.draw.rect(self.screen, GOLD, bg, width=1, border_radius=4)
        self.screen.blit(surf, r)

    def _draw_bubble(self, aid, cx, cy) -> None:
        line, tag = self.s.villager_line(aid)
        nx = next((tx for a, tx, ty in self.npcs if a == aid), 0)
        ny = next((ty for a, tx, ty in self.npcs if a == aid), 0)
        color = TAG_COLORS.get(tag, INK)
        words = line.split(); lines = []; cur = ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if self.f_sm.size(t)[0] <= 240 or not cur:
                cur = t
            else:
                lines.append(cur); cur = wd
        if cur:
            lines.append(cur)
        lh = self.f_sm.get_height() + 2
        w = max(self.f_sm.size(ln)[0] for ln in lines) + 16
        h = lh * len(lines) + 10
        bx = int(nx * TILE + TILE // 2 - cx - w // 2)
        by = int(ny * TILE - cy - h - 8)
        box = pygame.Rect(bx, by, w, h); box.clamp_ip(self.screen.get_rect())
        s = pygame.Surface(box.size, pygame.SRCALPHA); s.fill((20, 26, 36, 235))
        self.screen.blit(s, box.topleft)
        pygame.draw.rect(self.screen, color, box, width=1, border_radius=6)
        for i, ln in enumerate(lines):
            self.screen.blit(self.f_sm.render(ln, True, INK), (box.x + 8, box.y + 5 + i * lh))

    # ---------------------------------------------------------- HUD
    def _text(self, s, font, color, x, y, center=False, right=False):
        surf = font.render(s, True, color); r = surf.get_rect()
        if center: r.centerx = x
        elif right: r.right = x
        else: r.x = x
        r.y = y; self.screen.blit(surf, r); return r

    def _draw_hud(self) -> None:
        me = self.me()
        bar = pygame.Rect(0, 0, VIEW_W, 40)
        s = pygame.Surface(bar.size, pygame.SRCALPHA); s.fill((16, 20, 28, 220))
        self.screen.blit(s, (0, 0))
        season = self.s.season
        dtw = self.s.cfg.days_until_season(self.s.day, Season.WINTER)
        seasonc = CRIMSON if season == "winter" else STEEL
        self._text(f"Day {self.s.day}", self.f_h, INK, 12, 9)
        self._text(season.upper(), self.f, seasonc, 96, 12)
        self._text("winter -- wood is life" if season == "winter"
                   else f"winter in {dtw}d", self.f_sm, EMBER if dtw < 20 or season == "winter" else MUTE,
                   170, 13)
        stats = [(f"wood {me.wood:.0f}", EMBER), (f"food {me.food:.0f}", GREEN if me.food >= 2 else CRIMSON),
                 (f"money {me.money:.0f}", INK), (f"stamina {self.s.stamina_left()}", STEEL),
                 (f"score {me.contribution_earned:.0f}", GOLD)]
        x = VIEW_W - 12
        for txt, c in reversed(stats):
            r = self._text(txt, self.f, c, x, 12, right=True)
            x = r.left - 16

    def _draw_ticker(self) -> None:
        news = self.s.news[-1] if self.s.news else None
        if not news:
            return
        text, tag = news
        bar = pygame.Rect(0, VIEW_H - 26, VIEW_W, 26)
        s = pygame.Surface(bar.size, pygame.SRCALPHA); s.fill((16, 20, 28, 220))
        self.screen.blit(s, bar.topleft)
        self._text("- " + text, self.f_sm, TAG_COLORS.get(tag, INK), 12, VIEW_H - 22)

    def _draw_toast(self) -> None:
        text, frames = self.toast
        if frames <= 0 or not text:
            return
        self.toast = (text, frames - 1)
        surf = self.f.render(text, True, INK)
        r = surf.get_rect(); r.centerx = VIEW_W // 2; r.y = 48
        bg = r.inflate(20, 10)
        s = pygame.Surface(bg.size, pygame.SRCALPHA); s.fill((20, 26, 36, 230))
        self.screen.blit(s, bg.topleft)
        pygame.draw.rect(self.screen, GREEN, bg, width=1, border_radius=6)
        self.screen.blit(surf, r)

    # ---------------------------------------------------------- overlays
    def _center_panel(self, lines, title_color=EMBER):
        s = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA); s.fill((10, 13, 18, 220))
        self.screen.blit(s, (0, 0))
        y = VIEW_H // 2 - len(lines) * 16
        for i, ln in enumerate(lines):
            font = self.f_h if i == 0 else self.f
            self._text(ln, font, title_color if i == 0 else INK, VIEW_W // 2, y, center=True)
            y += 34 if i == 0 else 26

    def _draw_board(self) -> None:
        # the AI Accountant's fair-value board -- the isekai edge: only you can read it.
        lines = ["THE ACCOUNTANT'S BOARD"]
        for r in (Resource.WOOD, Resource.FOOD):
            m = self.s.market(r)
            cue = ("UNDERVALUED -- supply it" if m.ref_price < m.fair_price * 0.85 else
                   "OVERPRICED -- sell into it" if m.ref_price > m.fair_price * 1.15 else
                   "fairly priced")
            lines.append(f"{_rv(r).upper():5}  market {m.ref_price:4.1f}   fair {m.fair_price:4.1f}   {cue}")
        lines.append("(press any key to step back)")
        self._center_panel(lines, GOLD)

    def _draw_stall(self) -> None:
        me = self.me()
        self._center_panel([
            "THE MARKET STALL",
            f"you carry: wood {me.wood:.0f}   food {me.food:.0f}   money {me.money:.0f}",
            "[1] sell wood     [2] buy wood",
            "[3] sell food     [4] buy food",
            "(Esc / E to step back)",
        ], GOLD)

    def _draw_result(self) -> None:
        res = self.s.result or {}
        wu = res.get("winter_unmet", 0.0); base = res.get("baseline_unmet", wu)
        saved = res.get("saved", 0.0)
        verdict = ("The village came through warm." if wu < 8 else
                   "The village suffered the winter." if wu < 25 else "Many froze. The winter was cruel.")
        lines = [
            "You did not survive it." if res.get("reason") else "The year has turned.",
            res.get("reason") or verdict,
            f"Contribution earned: {res.get('contribution', 0.0):.0f}",
            f"Without you, {base:.0f} winter-need would have gone unmet; you brought it to {wu:.0f}.",
        ]
        if res.get("kept_warm"):
            lines.append(f"Your wood met {res['kept_warm']} neighbour(s)' need {res.get('times', 0)} times.")
        if res.get("warned") and res.get("warning_effect", 0.0) > 1:
            lines.append(f"Your warning alone spared the village {res['warning_effect']:.0f} suffering.")
        lines.append("[R] play again")
        self._center_panel(lines, EMBER if not res.get("reason") else CRIMSON)

    def _draw_title(self) -> None:
        self.screen.fill(SKY)
        cx = VIEW_W // 2
        # a little scene
        self.screen.blit(pygame.transform.scale(self.sprites["player"], (96, 96)), (cx - 48, 150))
        self._text("FROSTPINE", self.f_big, INK, cx, 90, center=True)
        for i, ln in enumerate([
            "You carry a modern mind in a village that cannot see winter coming.",
            "Only you can read the Accountant's fair value. Walk the village:",
            "chop wood, tend fields, raise a woodlot, trade at the stall, carry",
            "the word of winter -- then sleep to end each day.",
            "",
            "Move: WASD / arrows      Act: E / Space      Warn: C      Sleep: Enter (at home)",
        ]):
            self._text(ln, self.f, INK if i < 4 else STEEL, cx, 270 + i * 26, center=True)
        self._text("press any key to begin", self.f_h, EMBER, cx, 470, center=True)

    # ---------------------------------------------------------- one frame (sync)
    def tick(self, events, is_down) -> None:
        """Process input, advance state, render one frame to self.screen. Pure sync
        so the headless smoke test can drive it without an event loop; the async
        main() wraps this with flip() + `await asyncio.sleep(0)`."""
        for e in events:
            self.handle_event(e)
        self.update(is_down)
        self.draw()


# ==================================================================== entry
async def main() -> None:
    game = PixelGame()
    while game.running:
        events = pygame.event.get()
        pressed = pygame.key.get_pressed()
        game.tick(events, lambda k: pressed[k])
        pygame.display.flip()
        game.clock.tick(60)
        await asyncio.sleep(0)           # hand the frame back to the browser
    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
