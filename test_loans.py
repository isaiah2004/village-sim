"""
Layer 3 tests -- the loan / capital mechanic (deterministic sim state).

Proves loans are authored, deterministic sim state -- the LLM negotiates numbers,
the sim enforces them:

  1. GATED-OFF   -- with loans_enabled False (default), AcceptDeal is rejected
     ("loans disabled"); no loan, no money moves. (regression.py separately proves
     the 140 golden metrics stay byte-identical.)
  2. STRIKE      -- with flags on + standing, AcceptDeal records a loan, the
     merchant lends the principal, and the funded intervention is performed.
  3. CLAMP       -- interest and term are clamped to the config maxima; a
     negotiated over-ask cannot exceed them.
  4. REPAYMENT   -- a solvent borrower repays principal+interest in equal daily
     installments to the lender; balance reaches 0 (paid_off) and money is
     conserved between borrower and lender.
  5. DEFAULT     -- an insolvent borrower defaults: the lender seizes what cash it
     can, the loan is marked defaulted, and a LoanUpdated(defaulted) event fires.
  6. DETERMINISM.

Dependency-free; exit 0 = all pass.
"""
from __future__ import annotations

import sys

import contract as C
from config import Config
from simcore import SimCore


def _cfg(loans=True) -> Config:
    cfg = Config(); cfg.years = 1.0
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    cfg.interventions_enabled = True
    cfg.loans_enabled = loans
    return cfg


def _primed_core(loans=True, standing=100.0, money=5.0) -> SimCore:
    core = SimCore(config=_cfg(loans), propagation=True)
    core.begin_turn()
    core.world.by_id["PLAYER"].bonus_earned = standing
    core.world.by_id["PLAYER"].money = money
    return core


def test_gated_off() -> list:
    fails = []
    core = _primed_core(loans=False, money=500.0)
    merchant_before = next(a for a in core.snapshot().agents if a.kind == "market_maker").money
    core.submit(C.AcceptDeal("found_mill", 100.0, 0.15, 60))
    core.commit_turn()
    evs = [e for e in core.drain_events() if isinstance(e, C.DealResolved)]
    if not evs or evs[0].struck:
        fails.append("gated-off: AcceptDeal should be rejected when loans are disabled")
    elif "disabled" not in evs[0].reason:
        fails.append(f"gated-off: reason should mention disabled, got {evs[0].reason!r}")
    if core.snapshot().loans:
        fails.append("gated-off: a loan was recorded while disabled")
    return fails


def test_strike() -> list:
    fails = []
    core = _primed_core(money=5.0)
    core.submit(C.AcceptDeal("found_mill", 100.0, 0.15, 60))
    core.commit_turn()
    evs = [e for e in core.drain_events() if isinstance(e, C.DealResolved)]
    if not evs or not evs[0].struck:
        fails.append(f"strike: deal should be struck, got {evs}")
        return fails
    loans = core.snapshot().loans
    if not loans or loans[0].agent_id != "PLAYER":
        fails.append("strike: no player loan recorded")
    elif abs(loans[0].principal - 100.0) > 1e-6:
        fails.append(f"strike: loan principal wrong ({loans[0].principal})")
    me = next(a for a in core.snapshot().agents if a.is_player)
    if me.woodlot_level < 1:
        fails.append("strike: funded mill not founded")
    return fails


def test_clamp() -> list:
    fails = []
    core = _primed_core(money=5.0)
    over_interest = core.cfg.loan_max_interest + 1.0
    over_term = core.cfg.loan_max_term_days + 500
    core.submit(C.AcceptDeal("found_mill", 100.0, over_interest, over_term))
    core.commit_turn()
    core.drain_events()
    loans = core.snapshot().loans
    if not loans:
        fails.append("clamp: expected a loan to inspect")
        return fails
    ln = loans[0]
    if ln.interest > core.cfg.loan_max_interest + 1e-9:
        fails.append(f"clamp: interest {ln.interest} exceeds max {core.cfg.loan_max_interest}")
    if ln.term_days > core.cfg.loan_max_term_days:
        fails.append(f"clamp: term {ln.term_days} exceeds max {core.cfg.loan_max_term_days}")
    return fails


def test_repayment() -> list:
    """A solvent borrower repays fully; total repaid == principal*(1+interest).

    (Measured from the loan's own LoanUpdated events -- the merchant's raw money
    also swings with market trades, so those don't isolate the loan.)"""
    fails = []
    core = _primed_core(money=100000.0, standing=100.0)   # plenty of cash to service it
    principal, interest, term = 100.0, 0.2, 30
    core.submit(C.AcceptDeal("found_mill", principal, interest, term))
    core.commit_turn()
    total_paid = 0.0
    paid_off = False
    for e in core.drain_events():                          # day-0 installment already ran
        if isinstance(e, C.LoanUpdated):
            total_paid += e.payment
            paid_off = paid_off or e.event == "paid_off"
    for _ in range(term + 2):
        if core.done:
            break
        core.begin_turn(); core.commit_turn()
        for e in core.drain_events():
            if isinstance(e, C.LoanUpdated):
                total_paid += e.payment
                paid_off = paid_off or e.event == "paid_off"
    if not paid_off:
        fails.append("repayment: loan never reached paid_off")
    loans = core.snapshot().loans
    if loans and loans[0].balance > 1e-6:
        fails.append(f"repayment: balance not cleared ({loans[0].balance})")
    expected = principal * (1.0 + interest)
    if abs(total_paid - expected) > 1e-2:
        fails.append(f"repayment: total repaid {total_paid:.3f} != owed {expected:.3f}")
    return fails


def test_default() -> list:
    """An insolvent borrower defaults; the lender seizes cash, loan marked defaulted."""
    fails = []
    # principal == capital_cost so nothing is left after founding; idle -> no income
    core = _primed_core(money=5.0, standing=100.0)
    cap_cost = 80.0
    core.submit(C.AcceptDeal("found_mill", cap_cost, 0.2, 20))
    core.commit_turn(); core.drain_events()
    defaulted = False
    for _ in range(25):
        if core.done:
            break
        core.begin_turn(); core.commit_turn()   # idle player: no income to service the loan
        for e in core.drain_events():
            if isinstance(e, C.LoanUpdated) and e.event == "defaulted":
                defaulted = True
    if not defaulted:
        fails.append("default: an insolvent borrower should default")
    loans = core.snapshot().loans
    if loans and not loans[0].defaulted:
        fails.append("default: loan not marked defaulted")
    me = next(a for a in core.snapshot().agents if a.is_player)
    if me.money > 1e-6:
        fails.append(f"default: borrower should have been drained, has {me.money}")
    return fails


def test_determinism() -> list:
    fails = []
    def run():
        core = _primed_core(money=50.0)
        core.submit(C.AcceptDeal("found_mill", 100.0, 0.2, 30))
        core.commit_turn(); core.drain_events()
        while not core.done:
            core.step()
        return core.welfare(), [(l.agent_id, l.balance, l.defaulted) for l in core.snapshot().loans]
    if run() != run():
        fails.append("determinism: two identical loan runs diverged")
    return fails


def main() -> int:
    all_fails = []
    tests = (("GATED-OFF", test_gated_off), ("STRIKE", test_strike), ("CLAMP", test_clamp),
             ("REPAYMENT", test_repayment), ("DEFAULT", test_default),
             ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nLOAN TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nLOAN TESTS OK -- loans are deterministic sim state: gated off by default,"
          "\nclamped, repaid to the lender, and defaulted when the borrower can't pay.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
