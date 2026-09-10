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

## Phase 2 — backlog

### Item 1 — scenario-agnostic playable View ✓ (branch: claude/playable-any-scenario)

Delivered a NEW generic playable body, `view_play.py`, that selects and plays ANY
registered world purely through the SimCore contract — it reads only the snapshot's
generic fields (scenario/consumables/primary_resource/village_unmet, MarketView,
AgentView.holdings, problems, interventions) and maps typed commands (gather / buy /
sell / build / do <key> / warn) to contract intents. `--demo` scripts a full-year
playthrough of every scenario; interactive mode is a per-day command loop.
`view_text.py --scenario <name>` and `game.py --scenario <name>` hand any non-frostpine
world to it.

FLAG / decision for the human: I did NOT rewrite the pygame `game.py` UI or the
frostpine `GameSession` to be generic. `GameSession` is the *authored frostpine game*
(win = survive winter, warn-winter, starvation, the counterfactual, villager lines
about wood/winter) — generalizing all of that is judgment-heavy authored-content work
and risks the game-save/load golden, and the pygame layout can't be visually verified
in this environment. The honest architecture is "many bodies over one contract," so the
scenario-agnostic playable View is a separate body (`view_play.py`); frostpine's
authored game stays byte-identical. If you'd rather the pygame body itself render every
world generically, that's a dedicated UI task for a session that can see the screen.

New gate `test_view_play.py` (plays-all / renders / commands-have-effect) → check.py
18 gates. golden.json UNCHANGED (this item is a new body + a `--scenario` launch arg;
no sim/contract change). check.py green.

### Item 2 — cross-scenario hardening ✓ (branch: claude/cross-scenario-hardening)

New gate `test_scenarios.py` asserts, for EVERY registered world: runs a full year
headless; the crisis actually fires (nonzero total unmet of the crisis good AND
nonzero contribution paid AND crisis-phase price > calm-phase price — no inert
worlds); save/load round-trips BYTE-IDENTICALLY (serialize→load→serialize equal);
and it drives through the SimCore contract with the generic snapshot reads present.

BUG FOUND & FIXED (exactly what this item is for): `persistence._AGENT_CLASSES` was a
hardcoded list missing Task A's `InstitutionBuyer`, so guildhall and plaguewatch
could not be loaded (save→load raised "unknown agent class"). Fixed by deriving the
map from `agents.ARCHETYPES`, so every spawnable archetype (and any future one)
round-trips with no per-class edit. All 5 worlds now save/load byte-identical.

golden.json UNCHANGED (the fix is on the load path only). check.py green, 19 gates.

### Item 3 — intervention library breadth ✓ (branch: claude/intervention-library)

Grew the Layer-3 library from one action to a representative, reputation+capital-gated
ladder, all generic (each acts on the scenario's OWN crisis/capital good) and each
scored by the index (goods it adds are rooted in the founder's lineage):

  * haul_relief   (standing 15) -- a one-time relief shipment of the crisis good.
  * found_mill    (standing 40) -- found/upgrade the scenario's capital good.
  * hire_crew     (standing 60) -- permanent boost to the founder's crisis-good output.
  * endow_granary (standing 90) -- seed a communal buffer with the market maker.
  * open_trade_route (standing 120) -- a PERSISTENT importer of the crisis good.

Engine generalization to support these: `Asset` can now carry its OWN producer spec
(output_resource/per_level + optional upkeep), so an intervention-founded producer
(the trade route) runs generically in the capital phase with no scenario.capital
entry; persistence carries the extra fields backward-compatibly (frostpine assets
unchanged). The capital-phase gate is now `capital_goods_enabled` alone, so
intervention producers work even in worlds with no scenario capital of their own.

New gate `test_intervention_library.py` (ladder / gated / effects+scored / works on a
no-capital world). Updated `test_interventions.py` to reference found_mill by key (the
first library rung is now haul_relief). golden.json UNCHANGED (interventions + the new
tunables are off/gated by default). check.py green, 20 gates.
