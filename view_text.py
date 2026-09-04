"""
A SECOND body -- a terminal view over the exact same GameSession.

This exists to prove the "one brain, many bodies" split is real: it renders with
plain text instead of pygame, takes typed commands instead of clicks, and shares
NOTHING with game.py -- yet drives the identical GameSession and SimCore. A future
top-down pixel game with walking characters is the same exercise at higher
fidelity: read the session's state, call its action methods, present it your way.

    python view_text.py            # play in the terminal
    python view_text.py --demo     # a scripted auto-run (no input; CI-safe)

Nothing here imports pygame or the sim engine. It talks only to the session.
"""
from __future__ import annotations

import sys

from config import Resource, Season
from session import GameSession

CMDS = """commands:  q gather wood   w gather food   e woodlot   d warn winter
           s sell wood   b buy food   f fast-forward   [enter] end day   x quit"""


def dashboard(s: GameSession) -> str:
    me = s.me()
    wood_m = s.market(Resource.WOOD); food_m = s.market(Resource.FOOD)
    dtw = s.cfg.days_until_season(s.day, Season.WINTER)
    when = "WINTER" if s.season == "winter" else f"{s.season}  (winter in {dtw}d)"
    wl = (f"woodlot Lv{me.woodlot_level} +{me.woodlot_output:.1f}w/day"
          if me.woodlot_level else "no woodlot")
    word = f"  word-of-winter {s.wood_awareness*100:.0f}%" if s.warn_ever else ""
    lines = [
        "=" * 64,
        f"Day {s.day}  {when}",
        f"you:  money {me.money:>5.0f}   wood {me.wood:>5.0f}   food {me.food:>4.0f}"
        f"   stamina {s.stamina_left()}/{int(round(me.stamina))}",
        f"score {me.contribution_earned:>5.0f} contribution   kept {len(s.impact)} warm   {wl}{word}",
        f"market  WOOD {wood_m.ref_price:4.1f} (fair {wood_m.fair_price:4.1f})"
        f"   FOOD {food_m.ref_price:4.1f} (fair {food_m.fair_price:4.1f})",
        "news:",
    ]
    for text, tag in s.news[-5:]:
        lines.append(f"   [{tag}] {text}")
    return "\n".join(lines)


def apply(s: GameSession, cmd: str) -> bool:
    """Map a typed command to a session intent. Returns False to quit."""
    cmd = cmd.strip().lower()
    if cmd in ("x", "quit"):
        return False
    if cmd == "q": s.gather(Resource.WOOD)
    elif cmd == "w": s.gather(Resource.FOOD)
    elif cmd == "e": s.build_woodlot()
    elif cmd == "d": s.warn()
    elif cmd == "s": s.trade(Resource.WOOD, "sell")
    elif cmd == "b": s.trade(Resource.FOOD, "buy")
    elif cmd == "f": s.fast_forward()
    elif cmd == "":  s.end_day()
    return True


def show_result(s: GameSession) -> None:
    r = s.result or {}
    print("=" * 64)
    print("YOU DID NOT SURVIVE." if not r.get("survived") else "THE YEAR HAS TURNED.")
    if r.get("reason"):
        print(f"  {r['reason']}")
    print(f"  contribution earned: {r.get('contribution', 0):.0f}")
    print(f"  village winter shortfall: {r.get('winter_unmet', 0):.0f}  "
          f"(without you: {r.get('baseline_unmet', 0):.0f}, "
          f"you saved {r.get('saved', 0):.0f})")
    if r.get("kept_warm"):
        print(f"  you met {r['kept_warm']} villager(s)' need {r['times']} times; "
              f"{r['dependents']} were dependent households.")
    if r.get("warned"):
        we = r.get("warning_effect", 0.0)
        if we > 1:
            print(f"  your warning alone would have spared the village {we:.0f} winter suffering.")
        else:
            print("  your warning reached them, though supply held either way this year.")
    print("=" * 64)


def play() -> None:
    s = GameSession()
    print("SAY THE WORD -- terminal body\n" + CMDS)
    while not s.ended:
        print("\n" + dashboard(s))
        try:
            cmd = input("> ")
        except (EOFError, KeyboardInterrupt):
            print(); return
        if not apply(s, cmd):
            print("goodbye."); return
    print("\n" + dashboard(s)); show_result(s)


def demo() -> None:
    """Scripted auto-run: a sensible player, no input -- proves the body drives a
    whole game headlessly through the session, exactly like the pygame smoke."""
    s = GameSession()
    while not s.ended:
        me = s.me()
        while s.stamina_left() > 0:
            me = s.me()
            if me.food < 4.0: s.gather(Resource.FOOD)
            elif s.can_build_woodlot(): s.build_woodlot()
            elif s.day in (8, 20) and s.can_warn(): s.warn()
            else: s.gather(Resource.WOOD)
        s.trade(Resource.WOOD, "sell")
        s.end_day()
    print(dashboard(s)); show_result(s)


if __name__ == "__main__":
    (demo if "--demo" in sys.argv else play)()
