# Session progress notes

A running log of a long unattended build session: integrating the three task
branches onto `main`, then working the backlog. Newest entries appended at the end.

## Phase 1 — integrate #2 / #3 / #4 onto main (A → B → C)

Starting point: `main` at `b31e28e` (PR #1 merged, contract v1.5, golden 13 scenarios /
183 metrics, 15 check.py gates). The three branches were cut independently from this
commit, so B and C conflict with each other and with A on: `contract.py` (version note),
`golden.json`, `check.py` (gate list), `scenario.py`, `agents.py`, `world.py`,
`simcore.py`, `persistence.py`, and docs. Resolution policy: UNION — keep every additive
event/field, set `CONTRACT_VERSION` to cover all, include every new golden scenario
(baseline rows byte-identical), register every new gate, merge docs.

### Result — integrated cleanly, all three ✓

- **A (guildhall demand crisis)** merged first: fast-forward-style `--no-ff` merge,
  no conflicts (main was still at the branch base). check.py green, 16 gates.
- **B (reputation propagation)** merged second: one conflict, `check.py` gate list —
  resolved by UNION (kept both `demand events` and `reputation` gates). Everything
  else (contract.py, world.py, agents.py, simcore.py, golden.json) auto-merged: B
  added no golden rows (flag-gated off) and no contract fields, and its
  `is_institution` guards were already `getattr`-defensive so A's real flag slots in.
  check.py green, 17 gates.
- **C (LLM merchant edge)** merged third: auto-merged (ort) — AGENTS.md + the
  merchant doc reconciled automatically; merchant.py hardening, demo_llm_merchant.py,
  eval_llm_merchant.py added. No golden/contract change (LLM never in the sim).
  check.py green, 17 gates.

Post-integration state: contract v1.5 (no bump needed — A/B/C added no new fields;
A's only contract change was the additive `AgentView.kind` value "institution").
golden 14 scenarios / 197 metrics; frostpine + the PR-#1 baselines byte-identical.
Cross-cutting sanity: demo_scenarios (all 5 worlds), demo_llm_merchant (scripted),
demo_reputation all run. **check.py: FOUNDATION HOLDS, 17 gates.**
