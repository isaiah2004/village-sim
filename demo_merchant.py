"""
Layer 3 demo -- the merchant negotiation loop (DESIGN.md's mill), end to end.

The whole loop, deterministic (ScriptedMerchant, no LLM, no cost):

    prove yourself (the index credits your deeds -> standing) -> negotiate a loan
    with the merchant (he counters; you accept within your ceiling) -> the sim
    strikes the deal, funds and founds the mill (Layer 1's capital-gap problem
    falls) -> you repay principal+interest over the term.

Swap ScriptedMerchant for LLMMerchant (merchant.py, edge-only) and the merchant
reasons in-character instead; everything downstream is identical, because only
the settled terms enter the sim.

    python demo_merchant.py
"""
from __future__ import annotations

import sys

import contract as C
import merchant as M
from config import Config, Resource
from simcore import SimCore


def _cfg() -> Config:
    cfg = Config(); cfg.years = 2.0
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    cfg.interventions_enabled = True
    cfg.loans_enabled = True
    return cfg


def _supply_wood(core, snap):
    me = next(a for a in snap.agents if a.is_player)
    for _ in range(int(me.stamina)):
        core.submit(C.Gather(Resource.WOOD))
    wm = next(m for m in snap.markets if m.resource == Resource.WOOD)
    if me.wood > 4:
        core.submit(C.Trade(Resource.WOOD, "sell", me.wood - 3, wm.ref_price * 0.95))


def main() -> int:
    core = SimCore(config=_cfg(), propagation=True)
    print("=" * 70)
    print("THE MERCHANT NEGOTIATION LOOP -- fund a mill with a loan (two years)")
    print("=" * 70)

    # --- phase 1: prove yourself until the merchant will deal -------------
    founded_day = None
    negotiated = None
    balance_at = {}
    while not core.done:
        snap = core.begin_turn()
        rep = core.reputation()
        if founded_day is None and rep.descriptor in ("trusted", "renowned"):
            # --- phase 2: negotiate a loan-funded mill --------------------
            opening = M.DealProposal("found_mill", principal=100.0, interest=0.05, term_days=60)
            outcome = M.negotiate(M.ScriptedMerchant(), M.make_view_builder(core),
                                  opening, M.accept_up_to(0.20))
            print(f"\nDay {core.day}: you are '{rep.descriptor}' (standing {rep.standing:.0f}).")
            print(f'  You: "Lend me {opening.principal:.0f} at {opening.interest:.0%} '
                  f'to found a mill."')
            print(f'  Merchant: "{outcome.line}"')
            if outcome.struck:
                t = outcome.terms
                print(f"  -> STRUCK in {outcome.rounds} round(s): "
                      f"{t.principal:.0f} at {t.interest:.0%} over {t.term_days} days.")
                core.submit(C.AcceptDeal(t.key, t.principal, t.interest, t.term_days))
                negotiated = t
                founded_day = core.day
            else:
                print(f"  -> no deal ({outcome.reason}); keep proving yourself.")
        else:
            _supply_wood(core, snap)          # keep earning -- before and after the deal
        core.commit_turn()
        for ev in core.drain_events():
            if isinstance(ev, C.DealResolved) and ev.struck:
                me = next(a for a in core.snapshot().agents if a.is_player)
                print(f"  sim honored the deal: mill founded (woodlot L{me.woodlot_level}), "
                      f"loan recorded.")
        if founded_day is not None and core.day in (founded_day + 30, founded_day + 60, founded_day + 90):
            ln = next((l for l in core.snapshot().loans if l.agent_id == "PLAYER"), None)
            if ln:
                balance_at[core.day - founded_day] = ln.balance

    # --- phase 3: the aftermath ------------------------------------------
    fin = core.snapshot()
    me = next(a for a in fin.agents if a.is_player)
    gap = next((p.severity for p in fin.problems if p.key == "capital_gap:wood"), None)
    ln = next((l for l in fin.loans if l.agent_id == "PLAYER"), None)
    print("\n" + "-" * 70)
    if negotiated:
        owed = negotiated.principal * (1 + negotiated.interest)
        print(f"  loan: borrowed {negotiated.principal:.0f}, owed {owed:.0f} at "
              f"{negotiated.interest:.0%}; " +
              ("repaid in full." if (ln is None or ln.balance <= 1e-6) and not (ln and ln.defaulted)
               else f"balance {ln.balance:.0f}" + (" (DEFAULTED)" if ln and ln.defaulted else "")))
        for days, bal in sorted(balance_at.items()):
            print(f"    +{days:>3}d after founding: balance {bal:.0f}")
    print(f"  mill: woodlot level {me.woodlot_level}; "
          f"village capital-gap:wood severity now {gap:.2f} (ceiling without capital is 1.00).")
    print("-" * 70)
    print("\nreading: you turned a track record into credit, the merchant into a lender,")
    print("and a loan into infrastructure the index rewards and the village keeps. The")
    print("LLM merchant (merchant.LLMMerchant) drops into the same negotiate() call at the")
    print("edge; the sim hard-gate, the loan, and the effect are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
