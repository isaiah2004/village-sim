"""
NPC dialogue tests -- the village speaks its own belief.

Proves the belief-driven dialogue stub (session.villager_line / worried_voices)
is a faithful RENDER of what an agent actually believes, read straight through
the SimCore contract (SimCore.belief()), not an independent script:

  1. OBLIVIOUS -- before any word of winter reaches them, villagers hold no
     belief, so every line is the oblivious register (system tag).
  2. BELIEF-DRIVEN -- once the player warns and the claim propagates, the SAME
     agents' lines shift register, and the shift tracks their real belief: an
     agent whose SimCore.belief() confidence has risen no longer speaks the
     oblivious line.
  3. ORDER -- worried_voices ranks speakers by real belief pressure (value x
     confidence) read from the contract, most-worried first.
  4. DEPENDENTS -- a dependent who believes says, in words, the thing that makes
     them go cold first: they cannot fell their own wood.
  5. READ-ONLY -- asking the village to speak changes no world state.

Dependency-free; exit 0 = all pass. The game body renders these lines; this
test drives the rules layer headlessly so the foundation guards the feature.
"""
from __future__ import annotations

import sys

from config import Resource
from session import GameSession

OBLIVIOUS_TAG = "system"


def _villagers(s):
    return [a for a in s.snap.agents if not a.is_player and a.kind != "market_maker"]


def _play_and_warn(warn_days, days) -> GameSession:
    """Deterministic run: gather food to stay alive, speak the winter warning on
    the given days, advance `days` days (or until the game ends)."""
    s = GameSession()
    warn = set(warn_days)
    while not s.ended and s.day < days:
        while s.stamina_left() > 0:
            me = s.me()
            if me.food < 4.0:
                s.gather(Resource.FOOD)
            elif s.day in warn and s.can_warn():
                s.warn()
            else:
                s.gather(Resource.WOOD)
        s.end_day()
    return s


def test_oblivious() -> list:
    fails = []
    s = GameSession()                      # day 0, no word has spread yet
    for a in _villagers(s):
        value, confidence = s.core.belief(a.id, Resource.WOOD)
        line, tag = s.villager_line(a.id)
        if confidence >= 0.05 and value >= 0.05:
            continue                       # a belief exists; register may differ
        if tag != OBLIVIOUS_TAG:
            fails.append(f"oblivious: {a.id} holds no belief "
                         f"(v={value:.2f},c={confidence:.2f}) but tag={tag!r}")
        if not line:
            fails.append(f"oblivious: {a.id} produced an empty line")
    return fails


def test_belief_driven() -> list:
    """The line must follow the belief. Compare the SAME agents oblivious vs.
    after the warning has propagated; anyone whose belief actually rose must no
    longer be speaking the oblivious register."""
    fails = []
    before = GameSession()
    base = {a.id: before.core.belief(a.id, Resource.WOOD) for a in _villagers(before)}

    after = _play_and_warn(warn_days=(4, 5, 6), days=30)
    moved = 0
    for a in _villagers(after):
        value, confidence = after.core.belief(a.id, Resource.WOOD)
        _line, tag = after.villager_line(a.id)
        rose = confidence - base.get(a.id, (0.0, 0.0))[1] > 0.1
        if rose and confidence >= 0.05 and value >= 0.05:
            moved += 1
            if tag == OBLIVIOUS_TAG:
                fails.append(f"belief-driven: {a.id} belief rose to "
                             f"(v={value:.2f},c={confidence:.2f}) but still speaks oblivious")
    if moved == 0:
        fails.append("belief-driven: the warning moved no villager's belief -- "
                     "cannot prove the line tracks belief")
    return fails


def test_order() -> list:
    fails = []
    s = _play_and_warn(warn_days=(4, 5, 6), days=30)
    voices = s.worried_voices(3)
    if len(voices) < 2:
        fails.append(f"order: expected several voices, got {len(voices)}")
        return fails
    pressures = []
    for aid, line, _tag in voices:
        value, confidence = s.core.belief(aid, Resource.WOOD)
        pressures.append(value * confidence)
        if not line:
            fails.append(f"order: {aid} produced an empty line")
    if pressures != sorted(pressures, reverse=True):
        fails.append(f"order: worried_voices not sorted by belief pressure: {pressures}")
    return fails


def test_dependents() -> list:
    fails = []
    s = _play_and_warn(warn_days=(4, 5, 6), days=30)
    deps = [a for a in s.snap.agents if a.kind == "dependent"]
    if not deps:
        fails.append("dependents: no dependent households in the population")
    believing = 0
    for a in deps:
        _value, confidence = s.core.belief(a.id, Resource.WOOD)
        line, _tag = s.villager_line(a.id)
        if confidence >= 0.35:
            believing += 1
            if "fell my own" not in line:
                fails.append(f"dependents: believing {a.id} omits the can't-cut clause: {line!r}")
    if believing == 0:
        fails.append("dependents: no dependent came to believe -- cannot check their line")
    return fails


def test_read_only() -> list:
    """Listening changes nothing: same belief and same snapshot day before/after
    generating every villager's line."""
    fails = []
    s = _play_and_warn(warn_days=(4, 5, 6), days=20)
    day_before = s.day
    belief_before = {a.id: s.core.belief(a.id, Resource.WOOD) for a in _villagers(s)}
    _ = [s.villager_line(a.id) for a in _villagers(s)]
    _ = s.worried_voices(5)
    for a in _villagers(s):
        if s.core.belief(a.id, Resource.WOOD) != belief_before[a.id]:
            fails.append(f"read-only: speaking changed {a.id}'s belief")
    if s.day != day_before:
        fails.append("read-only: speaking advanced the day")
    return fails


def main() -> int:
    all_fails = []
    tests = (("OBLIVIOUS", test_oblivious), ("BELIEF-DRIVEN", test_belief_driven),
             ("ORDER", test_order), ("DEPENDENTS", test_dependents),
             ("READ-ONLY", test_read_only))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nDIALOGUE TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nDIALOGUE TESTS OK -- villager lines render real belief, read through\n"
          "the SimCore contract, and asking the village to speak changes nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
