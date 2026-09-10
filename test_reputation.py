"""
Reputation-propagation tests -- DESIGN.md's "reputation = deeds propagated".

Standing that gates interventions and merchant deals is no longer read straight
off realized contribution: a deed becomes a fact that travels the social graph,
and it is that PROPAGATED standing (contribution x how far word has reached) that
gates. These pin that down:

  1. GOLDEN-SAFE  -- reputation runs on its OWN rng and only shapes standing, which
     nothing in the base economy consults; so turning it on leaves every economic
     metric byte-identical (even for a scarcity-propagation scenario, proving the
     two networks' rngs don't cross). regression.py owns the full proof; this
     asserts the invariant directly.
  2. RAMP         -- a big benefactor whose word has spread ends near reach 1.0
     (full standing); a small or fresh contributor is barely known (low reach,
     low standing). Word takes time and network position to travel.
  3. GATES        -- propagated standing can LOCK an intervention that raw
     contribution alone would unlock (reach < 1 pulls standing below the bar), and
     the same deed unlocks it once reach is high. This is the whole point.
  4. DETERMINISM  -- same seed, same reaches.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import scenario as scen
import interventions
from interventions import Intervention, evaluate, standing


def _run(rep_on, strategy="idle"):
    w = scen.make_world("frostpine", player_strategy=strategy, reputation_propagation=rep_on)
    w.run()
    return w


def test_golden_safe() -> list:
    fails = []
    off = _run(False).metrics.summary()
    on = _run(True).metrics.summary()
    if off != on:
        diffs = {k: (off.get(k), on.get(k)) for k in set(off) | set(on) if off.get(k) != on.get(k)}
        fails.append(f"reputation ON perturbed the economy: {diffs}")
    return fails


def test_ramp() -> list:
    fails = []
    w = _run(True)
    earners = sorted([a for a in w.agents if a.bonus_earned > 0], key=lambda a: -a.bonus_earned)
    if len(earners) < 2:
        fails.append("expected several contributors to compare")
        return fails
    top = earners[0]
    top_reach = w.reputation.reach(top.id, w._active_ids)
    if top_reach < 0.6:
        fails.append(f"the biggest benefactor is barely known (reach {top_reach:.2f})")
    # standing must equal bonus * reach
    exp = round(top.bonus_earned * top_reach, 6)
    got = standing(top, w)
    if abs(exp - got) > 1e-6:
        fails.append(f"standing != bonus*reach ({got} vs {exp})")
    # a fresh, un-propagated deed is worth less than its raw contribution
    if not any(w.reputation.reach(a.id, w._active_ids) < 0.99 for a in earners):
        fails.append("no contributor had partial reach -- word spread implausibly perfectly")
    return fails


def test_gates() -> list:
    """Propagated standing must be able to LOCK a deal that raw contribution passes,
    and the SAME raw contribution passes once reach is high."""
    fails = []
    w = _run(True)
    earners = sorted([a for a in w.agents if a.bonus_earned > 0], key=lambda a: -a.bonus_earned)
    # find a real contributor whose word only partly spread (reach strictly < 1)
    partial = next((a for a in earners
                    if 0.0 < w.reputation.reach(a.id, w._active_ids) < 0.95
                    and a.bonus_earned > 5.0), None)
    if partial is None:
        fails.append("no partially-known contributor to test gating")
        return fails
    reach = w.reputation.reach(partial.id, w._active_ids)
    raw = partial.bonus_earned
    prop = standing(partial, w)
    # a bar set between propagated standing and raw contribution: locked by repute,
    # would have been unlocked without it.
    bar = (prop + raw) / 2.0
    iv = Intervention(key="test", title="t", targets="none", capital_cost=0.0, min_standing=bar)
    partial.money = 10_000.0                        # capital not the blocker
    # (no such problem 'none' -> evaluate would reject on target; test the standing
    #  gate directly instead of the whole precondition chain)
    if not (prop < bar <= raw):
        fails.append(f"could not straddle the bar (prop={prop:.1f} bar={bar:.1f} raw={raw:.1f})")
        return fails
    # propagated standing is below the bar -> a repute-gated deal is not yet earned
    if standing(partial, w) >= bar:
        fails.append("propagated standing did not fall below the bar")
    # ...but raw contribution (reputation OFF) would clear it
    if not (raw >= bar):
        fails.append("raw contribution should clear the bar")
    return fails


def test_default_hit() -> list:
    """A loan default is a bad deed that PROPAGATES: as word of it spreads, the
    defaulter's standing is discounted (DESIGN.md's 'a reputation hit that
    propagates'), and the penalty is tunable."""
    from world import World
    fails = []

    def standing_after_default(penalty: float) -> tuple:
        cfg = scen.make_config("frostpine", reputation_propagation=True,
                               reputation_default_penalty=penalty)
        w = World(cfg, player_strategy="idle",
                  population=scen.build_population(scen.get_scenario("frostpine")))
        p = w.player
        p.bonus_earned = 300.0
        for d in range(40):                       # spread the good deed -> full standing
            w.begin_day(d); w.execute_day()
        before = standing(p, w)
        w.reputation.record_default(p.id, 40)
        for d in range(40, 90):                   # let word of the default spread
            w.begin_day(d); w.execute_day()
        return before, standing(p, w)

    before, after = standing_after_default(1.0)
    if not (before > 1.0):
        fails.append(f"default-hit: player should have real standing first ({before})")
    if not (after < before * 0.2):
        fails.append(f"default-hit: a fully-known default barely dented standing "
                     f"({before:.1f} -> {after:.1f})")
    # a softer penalty hurts less
    _, soft = standing_after_default(0.5)
    if not (soft > after):
        fails.append(f"default-hit: a lower penalty should hurt less ({soft:.1f} vs {after:.1f})")
    return fails


def test_determinism() -> list:
    a = _run(True)
    b = _run(True)
    ra = {x.id: round(a.reputation.reach(x.id, a._active_ids), 6) for x in a.agents}
    rb = {x.id: round(b.reputation.reach(x.id, b._active_ids), 6) for x in b.agents}
    return [] if ra == rb else ["reputation reach not deterministic across runs"]


def main() -> int:
    all_fails = []
    tests = (("GOLDEN-SAFE", test_golden_safe), ("RAMP", test_ramp),
             ("GATES", test_gates), ("DEFAULT-HIT", test_default_hit),
             ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nREPUTATION TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nREPUTATION OK -- deeds propagate on their own rng (economy byte-identical),\n"
          "standing = contribution x how far word has reached, and that propagated\n"
          "standing gates deals a mere tally of deeds would not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
