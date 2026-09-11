"""
Headless smoke test for the web pixel body (game_pixel.py).

Not a rules test -- game_pixel is a pure View, and the brain is covered by the
other gates. This proves the BODY drives the brain end to end without error under
a headless SDL surface: it scripts movement + every interaction (gather at trees
and fields, build the woodlot, the market stall, the Accountant's board, talking to
an NPC, carrying the word, sleeping to end the day), renders a frame each step and
writes one with pygame.image.save, then plays a FULL frostpine year to the result
screen -- exercising the daily save-boundary serialize deep into winter (the path
that used to crash) and the fenced end-of-year 'tallying' beat.

It skips cleanly (exit 0) if pygame isn't installed, so the foundation gate stays
green on a sim-only environment.

Run: python test_pixel_smoke.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# a headless SDL surface, chosen before pygame is imported anywhere.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

try:
    import pygame
except Exception as exc:                       # pygame is a View-only dependency
    print(f"  pixel smoke SKIPPED -- pygame unavailable ({exc!r})")
    raise SystemExit(0)

from game_pixel import PixelGame, TILE, VIEW_W, VIEW_H


def _down(keys=frozenset()):
    return lambda k: k in keys


def _kd(key):
    return [pygame.event.Event(pygame.KEYDOWN, key=key)]


def _at(game, fixture, below=True):
    """Teleport the player adjacent to a fixture (the smoke test exercises the
    ACTION path, not the pathfinding -- movement itself is covered separately)."""
    game.px = fixture.px
    game.py = fixture.py + (TILE if below else -TILE)


def _first(game, kind):
    return next(f for f in game.fixtures if f.kind == kind)


def _render_ok(game) -> None:
    assert game.screen.get_size() == (VIEW_W, VIEW_H)


def main() -> int:
    g = PixelGame(headless=True)
    assert g.mode == "title"
    _render_ok(g)

    # title -> play
    g.tick(_kd(pygame.K_RETURN), _down())
    assert g.mode == "play", f"expected play, got {g.mode}"

    # exercise MOVEMENT: hold left, then down, for a few frames (no error, position moves)
    x0, y0 = g.px, g.py
    for _ in range(20):
        g.tick([], _down({pygame.K_a}))
    for _ in range(20):
        g.tick([], _down({pygame.K_s}))
    assert (g.px, g.py) != (x0, y0), "player did not move under held keys"

    tree = _first(g, "wood"); field = _first(g, "food")
    wl = _first(g, "woodlot"); stall = _first(g, "market"); board = _first(g, "board")

    start_day = g.s.day
    # a dozen scripted days: work within the stamina budget, touch every fixture
    for day in range(12):
        _at(g, field); g.tick(_kd(pygame.K_e), _down()); _render_ok(g)
        _at(g, tree);  g.tick(_kd(pygame.K_e), _down()); _render_ok(g)
        _at(g, wl);    g.tick(_kd(pygame.K_e), _down())         # build/upgrade woodlot
        # the market stall overlay: open, sell wood, buy food, close
        _at(g, stall); g.tick(_kd(pygame.K_e), _down()); assert g.mode == "stall"
        g.tick(_kd(pygame.K_1), _down()); g.tick(_kd(pygame.K_4), _down())
        g.tick(_kd(pygame.K_ESCAPE), _down()); assert g.mode == "play"
        # the Accountant's board overlay: open + close
        _at(g, board); g.tick(_kd(pygame.K_e), _down()); assert g.mode == "board"
        g.tick(_kd(pygame.K_e), _down()); assert g.mode == "play"
        # talk to an NPC (renders their real belief line)
        if g.npcs:
            aid, tx, ty = g.npcs[0]
            g.px, g.py = tx * TILE + TILE, ty * TILE
            g.tick(_kd(pygame.K_e), _down())
        # carry the word (a player warning -> an enum-keyed belief)
        g.tick(_kd(pygame.K_c), _down())
        # sleep at home to end the day
        g.px, g.py = 8 * TILE, 8 * TILE
        g.tick(_kd(pygame.K_RETURN), _down())
        while g.mode == "tallying":
            g.tick([], _down())
        _render_ok(g)
    assert g.s.day > start_day, "the day did not advance"

    # prove a frame is capturable with pygame.image.save (the co-brain's path)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "frame.png")
        pygame.image.save(g.screen, path)
        assert os.path.getsize(path) > 0, "pygame.image.save produced no bytes"

    # play the REST of the year: sleep each day until the game ends. This drives the
    # daily save-boundary serialize deep into winter (the fixed crash path) and the
    # fenced end-of-year counterfactual behind the 'tallying' beat.
    guard = 0
    while not g.s.ended and guard < g.s.cfg.total_days + 5:
        # eat so we reach the natural year end rather than starving on day 3
        _at(g, field); g.tick(_kd(pygame.K_e), _down())
        g.px, g.py = 8 * TILE, 8 * TILE
        g.tick(_kd(pygame.K_RETURN), _down())
        while g.mode == "tallying":
            g.tick([], _down())
        guard += 1
    assert g.s.ended, "the year never ended"
    assert g.mode == "ended", f"expected ended screen, got {g.mode}"
    assert (g.s.result or {}).get("contribution") is not None, "no result produced"
    g.draw(); _render_ok(g)                     # the result screen renders

    pygame.quit()
    print(f"  pixel smoke OK -- played a full frostpine year to the result screen "
          f"(day {g.s.day}), every interaction + overlay rendered headless, "
          f"image.save verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
