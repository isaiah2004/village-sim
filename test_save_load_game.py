"""
Save/load fidelity for a whole GAME (GameSession), not just the sim core.

test_persistence.py already proves SimCore round-trips byte-identically. This
guards the BODY-level feature (AGENTS.md Track A #4): a game saved mid-run and
reloaded -- through JSON, into a fresh GameSession -- must continue
byte-identically, session layer (news feed, impact ledger, warning history,
win/lose) included. The subtlety it pins down: the save is taken at a clean day
boundary (before begin_turn), so begin_day's per-day effects -- the dependent
stipend especially -- are applied exactly once on reload, never twice.

Proves:
  1. ROUND-TRIP  -- save at day 40, JSON-cycle it, load into a new session, and
     play both to year's end with the same script: identical result, welfare,
     every agent's holdings, every villager's belief, news, and impact.
  2. RESUME-POINT -- the loaded game resumes on the saved day, mid-phase state
     intact (not restarted, not advanced).
  3. FILE   -- save_to_file / load_from_file round-trips through disk, and
     load_from_file returns False (touching nothing) when no save exists.
  4. FORMAT -- an unknown save format is refused, not silently misread.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

from config import Resource
from session import GameSession

SAVE_DAY = 40


def _script_step(s: GameSession) -> None:
    """A deterministic player whose choices depend only on session state, so two
    sessions in the same state evolve identically."""
    while s.stamina_left() > 0:
        me = s.me()
        if me.food < 4.0:
            s.gather(Resource.FOOD)
        elif s.day % 7 == 0 and s.can_warn():
            s.warn()
        elif s.can_build_woodlot():
            s.build_woodlot()
        else:
            s.gather(Resource.WOOD)
    s.trade(Resource.WOOD, "sell")
    s.end_day()


def _play_to(s: GameSession, day: int) -> None:
    while not s.ended and s.day < day:
        _script_step(s)


def _play_out(s: GameSession) -> None:
    while not s.ended:
        _script_step(s)


def _fingerprint(s: GameSession) -> dict:
    """Everything a player would see or the sim would carry forward."""
    return {
        "day": s.day,
        "phase": s.phase,
        "result": s.result,
        "welfare": s.core.welfare(),
        "news": list(s.news),
        "impact": {k: dict(v) for k, v in s.impact.items()},
        "agents": {a.id: (round(a.money, 6), round(a.wood, 6), round(a.food, 6),
                          round(a.contribution_earned, 6), round(a.stamina, 6))
                   for a in s.snap.agents},
        "beliefs": {a.id: (s.core.belief(a.id, Resource.WOOD),
                           s.core.belief(a.id, Resource.FOOD))
                    for a in s.snap.agents},
    }


def test_round_trip() -> list:
    fails = []
    live = GameSession()
    _play_to(live, SAVE_DAY)
    blob = json.loads(json.dumps(live.save()))     # simulate a save file on disk

    reloaded = GameSession()
    reloaded.load(blob)

    # both play the identical script to the end of the year
    _play_out(live)
    _play_out(reloaded)

    fa, fb = _fingerprint(live), _fingerprint(reloaded)
    for key in fa:
        if fa[key] != fb[key]:
            fails.append(f"round-trip diverged on {key!r}: live={fa[key]} reloaded={fb[key]}")
    return fails


def test_resume_point() -> list:
    fails = []
    live = GameSession()
    _play_to(live, SAVE_DAY)
    saved_day = live.day
    saved_impact = {k: dict(v) for k, v in live.impact.items()}
    blob = json.loads(json.dumps(live.save()))

    reloaded = GameSession()
    reloaded.load(blob)
    if reloaded.day != saved_day:
        fails.append(f"resume-point: loaded on day {reloaded.day}, saved on {saved_day}")
    if reloaded.phase != "playing":
        fails.append(f"resume-point: loaded phase {reloaded.phase!r}, expected 'playing'")
    if {k: dict(v) for k, v in reloaded.impact.items()} != saved_impact:
        fails.append("resume-point: impact ledger not restored")
    if reloaded.stamina_used != 0 or reloaded.queued:
        fails.append("resume-point: per-day transients not reset to day-start")
    return fails


def test_file_round_trip() -> list:
    fails = []
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "game.save.json")

    empty = GameSession()
    if empty.load_from_file(path) is not False:
        fails.append("file: load_from_file should return False when no save exists")

    live = GameSession()
    _play_to(live, SAVE_DAY)
    live.save_to_file(path)
    if not os.path.exists(path):
        fails.append("file: save_to_file did not write the file")

    reloaded = GameSession()
    if reloaded.load_from_file(path) is not True:
        fails.append("file: load_from_file should return True on success")

    _play_out(live)
    _play_out(reloaded)
    if _fingerprint(live) != _fingerprint(reloaded):
        fails.append("file: disk round-trip did not continue identically")

    os.remove(path)
    os.rmdir(tmpdir)
    return fails


def test_format_guard() -> list:
    fails = []
    live = GameSession()
    _play_to(live, 5)
    blob = live.save()
    blob["game_save_format"] = 999            # a save this build cannot read
    try:
        GameSession().load(blob)
        fails.append("format: an unknown save format was not refused")
    except ValueError:
        pass
    return fails


def main() -> int:
    all_fails = []
    tests = (("ROUND-TRIP", test_round_trip), ("RESUME-POINT", test_resume_point),
             ("FILE", test_file_round_trip), ("FORMAT", test_format_guard))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nGAME SAVE/LOAD TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nGAME SAVE/LOAD TESTS OK -- a whole game round-trips through JSON and\n"
          "disk and continues byte-identically, session layer included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
