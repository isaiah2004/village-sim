"""
Dev script: render ONE representative mid-run frame per registered scenario to a
PNG, so the pygame body (game.py) can be reviewed for layout on EVERY world without
a human sitting at each one. This is how the co-brain screenshots the generic body.

It drives the real game headlessly -- SDL_VIDEODRIVER=dummy, no window -- advances
each world with the body's own universal auto-policy until it reaches the crisis
phase (the busiest, most crowded frame: shortages, prices, interventions all live),
then writes the frame with pygame.image.save.

    python shoot_scenarios.py                 # all registered scenarios -> shots/
    python shoot_scenarios.py tidewater dust  # only the named ones
    python shoot_scenarios.py --out /tmp/x    # a different output dir

Nothing here touches the sim, the rules, the contract, or the golden master: it
only reads the same universal fields game.py renders. shots/ is gitignored.
"""
from __future__ import annotations

import os
import sys

# choose the dummy video driver BEFORE pygame is imported anywhere.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402  (must follow the env setup above)

import scenario as scen  # noqa: E402
from game import Game  # noqa: E402

MAX_DAYS = 120          # a hard cap so a world that never enters its crisis still shoots


def shoot_one(name: str, out_dir: str) -> str:
    """Advance one world to a representative frame and save it. Returns the path."""
    g = Game(scenario=name, headless=True)
    w = g.world
    crisis = w.sc.crisis_phase
    guard = 0
    # advance with the body's universal policy until the crisis phase (the frame
    # where the most is happening) or the day cap, whichever comes first.
    while (not w.done) and w.season != crisis and guard < MAX_DAYS:
        w.auto_day(); guard += 1
    if g.state != "ended" and w.done:
        g.state = "ended"
    g.draw()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.png")
    pygame.image.save(g.screen, path)
    return path


def shoot_menu(out_dir: str) -> str:
    """Render the start-menu (scenario picker) frame, so the picker can be reviewed
    too, not just the worlds."""
    g = Game(scenario=None)              # menu state
    g.draw()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "_menu.png")
    pygame.image.save(g.screen, path)
    return path


def main(argv: list[str]) -> int:
    out_dir = "shots"
    if "--out" in argv:
        i = argv.index("--out")
        out_dir = argv[i + 1] if i + 1 < len(argv) else out_dir
        argv = argv[:i] + argv[i + 2:]
    known = scen.scenario_names()
    picks = [a for a in argv if not a.startswith("-")]
    for p in picks:
        if p not in known:
            print(f"unknown scenario {p!r}; known: {known}")
            return 1
    names = picks or known
    if not picks:                        # a full run also shoots the picker
        try:
            print(f"[{'menu':12}] -> {shoot_menu(out_dir)}")
        except Exception as exc:
            print(f"[{'menu':12}] FAILED: {exc!r}")
    for name in names:
        try:
            path = shoot_one(name, out_dir)
            print(f"[{name:12}] -> {path}")
        except Exception as exc:                      # keep shooting the rest
            print(f"[{name:12}] FAILED: {exc!r}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
