"""
Layer 3 tests -- merchant negotiation (DESIGN.md's AI-agent negotiation).

Proves the negotiation layer and its two guarantees -- deterministic core, and a
fail-closed LLM edge that never fabricates a deal:

  1. SCRIPTED        -- the deterministic merchant's rules: unproven -> declined;
     underpriced -> counter; fair -> accept; merchant broke -> declined.
  2. ROUNDS          -- negotiate() settles within the cap (<= 3 evaluations),
     across accept / counter-accept / counter-walk / decline / exhaustion.
  3. FAIL-CLOSED     -- a merchant that errors or is unavailable yields "closed
     for the day", never a strike. The real LLMMerchant with no SDK/client present
     fails closed too.
  4. LLM-ADAPTER     -- LLMMerchant with a STUB client parses a structured accept /
     counter / decline; a raising stub fails closed. No real API call.
  5. END-TO-END      -- a struck negotiation, submitted as AcceptDeal, is honored
     by the sim's hard gate (DealResolved struck); a walk strikes nothing.
  6. DETERMINISM.

Only ScriptedMerchant is exercised against the sim; the LLM path is stubbed. No
network, no cost. Dependency-free.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import contract as C
import merchant as M
from config import Config
from simcore import SimCore


# ---- helpers -------------------------------------------------------------
def _view(descriptor="known", standing=100.0, capital=1_000_000.0,
          key="found_mill", principal=100.0, interest=0.15, term=60):
    return C.MerchantView(
        merchant_id="mk00", merchant_capital=capital,
        ref_prices={"wood": 5.0, "food": 6.0}, season="autumn",
        reputation=C.ReputationSummary(standing=standing, descriptor=descriptor),
        public_facts=("winter is near",), key=key, principal=principal,
        interest=interest, term_days=term)


def _stub_client(decision: dict):
    """A fake Anthropic client returning one tool_use block carrying `decision`."""
    block = SimpleNamespace(type="tool_use", name="submit_decision", input=decision)
    resp = SimpleNamespace(content=[block])
    messages = SimpleNamespace(create=lambda **kw: resp)
    return SimpleNamespace(messages=messages)


def _raising_client():
    def boom(**kw):
        raise RuntimeError("network down")
    return SimpleNamespace(messages=SimpleNamespace(create=boom))


# ---- tests ---------------------------------------------------------------
def test_scripted() -> list:
    fails = []
    m = M.ScriptedMerchant()
    if not m.judge(_view(descriptor="unproven", standing=0.0)).line or \
            m.judge(_view(descriptor="unproven", standing=0.0)).accepted:
        fails.append("scripted: unproven borrower should be declined")
    # known band asks 0.25: an underpriced 0.15 offer -> counter at 0.25
    d = m.judge(_view(descriptor="known", interest=0.15))
    if d.accepted or d.counter is None or abs(d.counter.interest - 0.25) > 1e-9:
        fails.append(f"scripted: expected a 0.25 counter, got {d}")
    # a fair offer at/above the ask -> accept
    if not m.judge(_view(descriptor="known", interest=0.25)).accepted:
        fails.append("scripted: a fair offer should be accepted")
    # renowned gets the best rate
    if not m.judge(_view(descriptor="renowned", interest=0.10)).accepted:
        fails.append("scripted: renowned should be accepted at the low rate")
    # merchant without capital declines
    if m.judge(_view(capital=10.0, principal=100.0)).accepted:
        fails.append("scripted: a broke merchant should decline")
    return fails


def test_rounds() -> list:
    fails = []
    m = M.ScriptedMerchant()

    def make_view(p):
        return _view(descriptor="known", interest=p.interest, principal=p.principal,
                     key=p.key, term=p.term_days)

    opening = M.DealProposal("found_mill", 100.0, 0.15, 60)
    # accept the counter (0.25) since it's within ceiling -> struck in round 1
    out = M.negotiate(m, make_view, opening, M.accept_up_to(0.30))
    if not (out.struck and abs(out.terms.interest - 0.25) < 1e-9 and out.rounds <= 3):
        fails.append(f"rounds: counter-accept should strike at 0.25, got {out}")
    # ceiling below the counter -> walk, no strike
    out = M.negotiate(m, make_view, opening, M.accept_up_to(0.10))
    if out.struck or out.reason != "walked away":
        fails.append(f"rounds: below-ceiling counter should walk, got {out}")
    # a fair opening -> immediate accept
    out = M.negotiate(m, make_view, M.DealProposal("found_mill", 100.0, 0.25, 60),
                      M.accept_up_to(0.30))
    if not (out.struck and out.rounds == 1):
        fails.append(f"rounds: fair opening should strike in round 1, got {out}")
    # never exceeds the cap: a re-proposing policy that never accepts stops at 3
    calls = {"n": 0}
    def counting_merchant_view(p):
        calls["n"] += 1
        return make_view(p)
    def re_propose(r, mine, counter):
        return M.DealProposal(mine.key, mine.principal, 0.15, mine.term_days)  # never meets ask
    out = M.negotiate(m, counting_merchant_view, opening, re_propose, max_rounds=3)
    if calls["n"] > 3 or out.struck:
        fails.append(f"rounds: exceeded the 3-round cap ({calls['n']} evals) or wrongly struck")
    return fails


def test_fail_closed() -> list:
    fails = []
    class Boom:
        def judge(self, view):
            raise RuntimeError("merchant fainted")
    out = M.negotiate(Boom(), lambda p: _view(), M.DealProposal("found_mill", 100, 0.2, 60),
                      M.accept_up_to(0.3))
    if out.struck or "closed" not in out.line.lower():
        fails.append(f"fail-closed: erroring merchant should close, got {out}")
    # a merchant that returns closed=True
    class Closed:
        def judge(self, view):
            return M.MerchantDecision(False, None, "Closed for the day.", closed=True)
    out = M.negotiate(Closed(), lambda p: _view(), M.DealProposal("found_mill", 100, 0.2, 60),
                      M.accept_up_to(0.3))
    if out.struck:
        fails.append("fail-closed: a closed merchant must not strike")
    # the real LLMMerchant with no SDK/client available fails closed (never raises)
    d = M.LLMMerchant(client=None).judge(_view())
    if d.accepted or not d.closed:
        fails.append(f"fail-closed: LLMMerchant with no client should be closed, got {d}")
    return fails


def test_llm_adapter() -> list:
    fails = []
    accept = M.LLMMerchant(client=_stub_client(
        {"accepted": True, "counter_interest": None, "line": "Done."})).judge(_view())
    if not (accept.accepted and not accept.closed):
        fails.append(f"llm-adapter: stub accept not parsed, got {accept}")
    counter = M.LLMMerchant(client=_stub_client(
        {"accepted": False, "counter_interest": 0.2, "line": "Not so fast."})).judge(_view())
    if counter.accepted or counter.counter is None or abs(counter.counter.interest - 0.2) > 1e-9:
        fails.append(f"llm-adapter: stub counter not parsed, got {counter}")
    decline = M.LLMMerchant(client=_stub_client(
        {"accepted": False, "counter_interest": None, "line": "No."})).judge(_view())
    if decline.accepted or decline.counter is not None or decline.closed:
        fails.append(f"llm-adapter: stub decline not parsed, got {decline}")
    boom = M.LLMMerchant(client=_raising_client()).judge(_view())
    if boom.accepted or not boom.closed:
        fails.append(f"llm-adapter: raising client should fail closed, got {boom}")
    return fails


def _deal_cfg() -> Config:
    cfg = Config(); cfg.years = 1.0
    cfg.capital_goods_enabled = True
    cfg.reward_at_fair_value = True
    cfg.interventions_enabled = True
    cfg.loans_enabled = True
    return cfg


def test_end_to_end() -> list:
    """A struck negotiation, submitted as AcceptDeal, is honored by the sim."""
    fails = []
    core = SimCore(config=_deal_cfg(), propagation=True)
    core.begin_turn()
    core.world.by_id["PLAYER"].bonus_earned = 100.0     # "trusted" standing
    core.world.by_id["PLAYER"].money = 5.0              # broke -> needs the loan

    out = M.negotiate(M.ScriptedMerchant(), M.make_view_builder(core),
                      M.DealProposal("found_mill", 100.0, 0.10, 60), M.accept_up_to(0.30))
    if not out.struck:
        fails.append(f"end-to-end: negotiation should strike, got {out}")
        return fails
    t = out.terms
    core.submit(C.AcceptDeal(t.key, t.principal, t.interest, t.term_days))
    core.commit_turn()
    resolved = [e for e in core.drain_events() if isinstance(e, C.DealResolved)]
    if not resolved or not resolved[0].struck:
        fails.append(f"end-to-end: sim did not honor the struck deal, got {resolved}")
    me = next(a for a in core.snapshot().agents if a.is_player)
    if me.woodlot_level < 1:
        fails.append("end-to-end: the funded mill was not founded")
    if not core.snapshot().loans:
        fails.append("end-to-end: no loan was recorded")
    return fails


def test_determinism() -> list:
    fails = []
    def run():
        core = SimCore(config=_deal_cfg(), propagation=True)
        core.begin_turn()
        core.world.by_id["PLAYER"].bonus_earned = 100.0
        out = M.negotiate(M.ScriptedMerchant(), M.make_view_builder(core),
                          M.DealProposal("found_mill", 100.0, 0.10, 60), M.accept_up_to(0.30))
        return out
    a, b = run(), run()
    if a != b:
        fails.append("determinism: two identical negotiations diverged")
    return fails


def main() -> int:
    all_fails = []
    tests = (("SCRIPTED", test_scripted), ("ROUNDS", test_rounds),
             ("FAIL-CLOSED", test_fail_closed), ("LLM-ADAPTER", test_llm_adapter),
             ("END-TO-END", test_end_to_end), ("DETERMINISM", test_determinism))
    for name, fn in tests:
        fails = fn()
        print(f"[{'ok' if not fails else 'FAIL'}] {name}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails
    if all_fails:
        print(f"\nMERCHANT TESTS FAILED ({len(all_fails)})")
        return 1
    print("\nMERCHANT TESTS OK -- negotiation settles within the round cap, the LLM edge\n"
          "is fail-closed and stubbed (no network), and a struck deal is honored by the\n"
          "sim's hard gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
