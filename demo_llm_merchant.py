"""
The LLM merchant AT THE EDGE -- a runnable negotiation (DESIGN.md's Layer-3
AI-agent negotiation).

This is the actual edge loop a body (pygame/terminal/UE5) runs BETWEEN turns: the
player proposes loan terms, a merchant judges them over the sim's knowledge-gated
`MerchantView`, and the struck terms are submitted back through the contract as an
`AcceptDeal` intent -- where the SIM is the hard gate. The LLM decides only whether
and on what terms the merchant deals; it never touches world truth.

    python demo_llm_merchant.py            # ScriptedMerchant (deterministic, offline)
    python demo_llm_merchant.py --live     # the real LLMMerchant (needs the SDK + creds)

Default is the deterministic merchant, so this file runs with no network and no
cost -- exactly what `check.py` relies on. `--live` swaps in `LLMMerchant`
(`claude-haiku-4-5`); if the SDK or credentials are absent it fails CLOSED (the
merchant "is closed for the day") rather than crashing. The sim's outcome is
identical in shape either way: a validated deal or a clean decline.
"""
from __future__ import annotations

import sys

import contract as C
import merchant as M
from config import Config
from simcore import SimCore


def _deal_world() -> SimCore:
    cfg = Config()
    cfg.years = 1.0
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    cfg.interventions_enabled = True
    cfg.loans_enabled = True
    core = SimCore(config=cfg, propagation=True)
    core.begin_turn()
    # a proven but cash-poor player: a track record that earns a merchant's ear,
    # no coin to found the mill outright -> a loan is the only way.
    core.world.by_id["PLAYER"].bonus_earned = 120.0     # "trusted" standing
    core.world.by_id["PLAYER"].money = 5.0
    return core


def _make_merchant(live: bool):
    if not live:
        return M.ScriptedMerchant(), "ScriptedMerchant (deterministic)"
    return M.LLMMerchant(), "LLMMerchant (claude-haiku-4-5, edge)"


def main(argv: list[str]) -> int:
    live = "--live" in argv
    core = _deal_world()
    merchant, label = _make_merchant(live)

    print("=" * 64)
    print(f"MERCHANT NEGOTIATION AT THE EDGE -- {label}")
    print("=" * 64)
    rep = core.reputation("PLAYER")
    print(f"You approach the merchant. Your standing: {rep.descriptor} ({rep.standing:.0f}).")

    opening = M.DealProposal(key="found_mill", principal=100.0, interest=0.10, term_days=60)
    print(f"You propose: borrow {opening.principal:.0f} at {opening.interest:.0%} "
          f"over {opening.term_days} days to found a mill.\n")

    # the player's edge-side policy: take a counter up to 30% interest, else walk.
    out = M.negotiate(merchant, M.make_view_builder(core), opening, M.accept_up_to(0.30))
    print(f'Merchant: "{out.line}"')
    print(f"[{out.rounds} round(s); {out.reason or 'struck'}]\n")

    if not out.struck:
        print("No deal today -- the mill stays unfounded. (The sim state is unchanged.)")
        return 0

    # the ONLY thing that enters the sim: the settled terms, as a contract intent.
    t = out.terms
    print(f"Struck: {t.principal:.0f} at {t.interest:.0%} over {t.term_days} days. "
          "Submitting AcceptDeal through the wall...")
    core.submit(C.AcceptDeal(t.key, t.principal, t.interest, t.term_days))
    core.commit_turn()

    resolved = [e for e in core.drain_events() if isinstance(e, C.DealResolved)]
    snap = core.snapshot()
    me = next(a for a in snap.agents if a.is_player)
    if resolved and resolved[0].struck:
        print(f"SIM honored it: mill founded (woodlot Lv{me.woodlot_level}), "
              f"{len(snap.loans)} loan recorded.")
    else:
        why = resolved[0].reason if resolved else "no event"
        print(f"SIM's hard gate REJECTED the deal ({why}) -- the merchant's 'yes' "
              "cannot override the rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
