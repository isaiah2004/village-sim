"""
A SCENARIO-AGNOSTIC playable body -- pick ANY registered world and play it, all
through the SimCore contract. Nothing here knows wood from fish from iron: it reads
the snapshot's generic fields (scenario / consumables / primary_resource /
village_unmet, MarketView, AgentView.holdings, problems, interventions) and maps
typed commands to contract intents. This is the "a 2D wrapper can actually test any
scenario" bar met at the terminal: one body, every world, zero per-scenario code.

    python view_play.py                     # pick a scenario, then play it
    python view_play.py tidewater           # play a named scenario
    python view_play.py --demo              # scripted auto-run over EVERY scenario (CI-safe)
    python view_play.py tidewater --demo    # scripted auto-run of one scenario

Commands (interactive): 'g <good>' gather, 'b <good> [qty]' buy, 's <good> [qty]'
sell, 'build' establish/upgrade capital, 'do <key>' perform an intervention from
your own capital, 'deal <key>' negotiate a loan (a deterministic merchant) to fund
one, 'warn <good>' speak a scarcity claim, [enter] end the day, 'f' fast-forward a
day, 'x' quit. It talks only to SimCore -- the frostpine game (game.py /
view_text.py) is untouched; this is a separate body proving the skin is swappable
per world, now driving the whole Layer-3 loop (reputation-gated interventions +
loan financing) on ANY scenario.
"""
from __future__ import annotations

import sys

import contract as C
import scenario as scen
from simcore import SimCore


# --------------------------------------------------------------------- build
def _core(name: str, propagation: bool = True) -> SimCore:
    cfg = scen.make_config(name)
    cfg.interventions_enabled = True         # let a player attempt Layer-3 actions
    cfg.capital_goods_enabled = True         # ...including founding capital goods
    cfg.loans_enabled = True                 # ...financed by a negotiated loan
    cfg.reward_at_fair_value = True          # crises pay fair value, so deeds are worth doing
    cfg.reputation_propagation = True        # standing = how far word of your deeds has reached
    return SimCore(config=cfg, propagation=propagation,
                   population=scen.build_population(scen.get_scenario(name)))


def _rv(r):
    return r.value if hasattr(r, "value") else r


# -------------------------------------------------------------------- render
def dashboard(core: SimCore) -> str:
    snap = core.snapshot()
    me = next(a for a in snap.agents if a.is_player)
    lines = [
        "=" * 66,
        f"{snap.scenario}   day {snap.day}   phase: {snap.season}   "
        f"crisis good: {snap.primary_resource}",
        f"you:  money {me.money:>6.0f}   stamina {me.stamina:>4.1f}   "
        f"score {me.contribution_earned:>6.1f} contribution",
    ]
    # holdings of every good you carry (generic)
    held = "  ".join(f"{g} {me.holdings.get(g, 0.0):.0f}" for g in snap.consumables)
    lines.append(f"  hold: {held}")
    lines.append("  market:")
    for m in snap.markets:
        rid = _rv(m.resource)
        lines.append(f"    {rid:<12} price {m.ref_price:6.2f}  fair {m.fair_price:6.2f}"
                     f"  village-unmet {snap.village_unmet.get(rid, 0.0):6.1f}")
    # Layer 1: worst live problems
    probs = core.problems()[:3]
    if probs:
        lines.append("  problems: " + ", ".join(
            f"{p.key}={p.severity:.2f}" for p in probs))
    # Layer 3: what you could do right now (unlocked ones)
    ivs = [(k, reason, ok) for (k, title, tgt, cost, ms, ok, reason) in core.interventions()]
    ready = [k for k, reason, ok in ivs if ok]
    if ivs:
        if ready:
            lines.append("  interventions ready: " + ", ".join(ready))
        else:
            lines.append("  interventions: " + "; ".join(f"{k} (locked: {reason})"
                                                          for k, reason, ok in ivs[:2]))
    # Layer 3 financing: your standing (how far word of your deeds has reached) and
    # any loans you owe. Standing gates both interventions and a merchant's terms.
    rep = core.reputation("PLAYER")
    lines.append(f"  standing: {rep.descriptor} ({rep.standing:.0f})")
    if snap.loans:
        lines.append("  loans: " + ", ".join(
            f"{l.balance:.0f} owed to {l.lender_id}" for l in snap.loans))
    return "\n".join(lines)


def negotiate_deal(core: SimCore, key: str, ceiling: float = 0.30) -> str:
    """Negotiate a loan (deterministic ScriptedMerchant) to fund intervention `key`,
    then submit it as an AcceptDeal -- the sim is the hard gate. Layer 3's financing
    loop, driven from the generic body through the contract. Returns a status line."""
    import merchant as M
    row = next((iv for iv in core.interventions() if iv[0] == key), None)
    if row is None:
        return f"no such intervention {key!r}"
    principal = row[3]                                   # the intervention's capital cost
    opening = M.DealProposal(key, principal, 0.10, 60)
    out = M.negotiate(M.ScriptedMerchant(), M.make_view_builder(core),
                      opening, M.accept_up_to(ceiling))
    if not out.struck:
        return f'merchant: "{out.line}"  (no deal: {out.reason})'
    t = out.terms
    core.submit(C.AcceptDeal(t.key, t.principal, t.interest, t.term_days))
    return (f'merchant: "{out.line}"  -> borrow {t.principal:.0f} at {t.interest:.0%} '
            f"to fund {key} (submitted; applied on end-of-day at the sim's hard gate)")


# ------------------------------------------------------------------ commands
def _price_for(core: SimCore, good: str, side: str) -> float:
    m = next((m for m in core.snapshot().markets if _rv(m.resource) == good), None)
    ref = m.ref_price if m else 1.0
    return ref * (1.15 if side == "buy" else 0.85)     # cross the spread so it clears


def apply(core: SimCore, cmd: str) -> bool:
    """Map a typed command to contract intents. Returns False to quit."""
    parts = cmd.strip().split()
    if not parts:
        core.commit_turn(); core.begin_turn(); return True     # [enter] = end day
    verb, args = parts[0].lower(), parts[1:]
    goods = set(core.snapshot().consumables)
    if verb in ("x", "quit"):
        return False
    if verb == "f":
        core.commit_turn(); core.begin_turn(); return True
    if verb == "g" and args and args[0] in goods:
        core.submit(C.Gather(args[0]))
    elif verb in ("b", "s") and args and args[0] in goods:
        good = args[0]
        qty = float(args[1]) if len(args) > 1 else 4.0
        side = "buy" if verb == "b" else "sell"
        core.submit(C.Trade(good, side, qty, _price_for(core, good, side)))
    elif verb == "build":
        core.submit(C.BuildWoodlot())
    elif verb == "do" and args:
        core.submit(C.Perform(args[0]))
    elif verb == "deal" and args:
        print("  " + negotiate_deal(core, args[0],
                                    float(args[1]) if len(args) > 1 else 0.30))
    elif verb == "warn" and args and args[0] in goods:
        try:
            core.submit(C.Speak(args[0], 0.85, True, "player:warning", 0.9))
        except RuntimeError:
            print("  (this world has no propagation network to speak into)")
    else:
        print(f"  ? unknown or bad command: {cmd!r}")
    return True


# ---------------------------------------------------------------------- play
def play(name: str) -> None:
    core = _core(name)
    core.begin_turn()
    print(f"Playing '{name}'. Commands: g <good> / b|s <good> [qty] / build / "
          "do <key> / deal <key> / warn <good> / [enter] end day / f / x quit")
    while not core.done:
        print("\n" + dashboard(core))
        try:
            cmd = input("> ")
        except (EOFError, KeyboardInterrupt):
            print(); return
        if not apply(core, cmd):
            print("goodbye."); return
    print("\n" + dashboard(core))
    print("\nThe year has turned.")


# ---------------------------------------------------------------------- demo
def demo_one(name: str) -> dict:
    """Scripted, no-input playthrough of one scenario through the contract: each
    day the player gathers the crisis good (and, where it can, founds capital),
    proving the body drives this world end to end. Returns the welfare summary."""
    core = _core(name)
    while not core.done:
        snap = core.begin_turn()
        me = next(a for a in snap.agents if a.is_player)
        prim = snap.primary_resource
        # a simple, universal policy: work the crisis good; invest in capital when
        # the scenario has it and we can; sell a little of what we pile up.
        if C.Gather is not None:
            core.submit(C.Gather(prim))
            for g in snap.consumables:
                if g != prim:
                    core.submit(C.Gather(g))
        core.submit(C.BuildWoodlot())            # no-op unless the world has capital + means
        if me.holdings.get(prim, 0.0) > 6.0:
            core.submit(C.Trade(prim, "sell", 4.0, _price_for(core, prim, "sell")))
        core.commit_turn()
    return core.welfare()


def demo(names: list[str]) -> int:
    for name in names:
        w = demo_one(name)
        prim = scen.get_scenario(name).primary_resource
        prim = _rv(prim)
        paid = w.get("total_reward_paid", 0.0)
        unmet = w.get(f"village_unmet_{prim}", 0.0)
        print(f"[{name:12}] ran full year via contract -- crisis good {prim}: "
              f"village-unmet {unmet:8.1f}, contribution paid {paid:8.1f}")
    return 0


# ---------------------------------------------------------------------- main
def main(argv: list[str]) -> int:
    is_demo = "--demo" in argv
    names = [a for a in argv if not a.startswith("-")]
    known = scen.scenario_names()
    for n in names:
        if n not in known:
            print(f"unknown scenario {n!r}; known: {known}")
            return 1
    if is_demo:
        return demo(names or known)
    if not names:
        print(f"scenarios: {', '.join(known)}")
        try:
            name = input("pick one > ").strip() or known[0]
        except (EOFError, KeyboardInterrupt):
            return 0
        if name not in known:
            print(f"unknown scenario {name!r}"); return 1
    else:
        name = names[0]
    play(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
