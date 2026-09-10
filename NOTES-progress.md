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

### Item 4 — modularity breadth ✓ (branch: claude/modularity-breadth)

Two new REGISTERED worlds, each a single data entry (a builder + a registry line +
a golden row), ZERO new engine logic — each exercising a combination no prior world did:

  * dustveil   -- a drought town: a CYCLICAL SUPPLY crisis (drought driver collapses
    the water draw) relieved by CAPITAL (a cistern storing the wet season). Combines
    a driver-driven crisis and capital relief in one world (frostpine has capital but
    a consumption-spike crisis; tidewater is cyclical but capital-less; emberforge is
    capital but non-cyclical). Fires: water unmet 434, contribution 531, drought price
    15.8 vs calm 5.7.
  * fallowmere -- a poisoned-harvest SUBSTITUTION crisis: one driver simultaneously
    collapses grain YIELD (blight) and spikes DEMAND onto the slower-dug roots, so
    roots go short exactly in blight. A new use of the driver (flip yield on one good,
    demand onto another). Fires: roots unmet 209, contribution 191, blight price 11.8
    vs calm 6.3.

Golden captured ADDITIVELY: 0 pre-existing rows changed, +SCENARIO_DUSTVEIL,
+SCENARIO_FALLOWMERE (now 16 scenarios). The saltmarsh acceptance test
(test_modularity.py) and the cross-scenario guard (test_scenarios.py, now 7 worlds)
both cover the claim — a new world is one data entry, zero new logic. check.py green,
20 gates.

### Item 5 — UE5 / sim-as-a-service seam ✓ (branch: claude/contract-json-seam)

Documented and shipped the contract's JSON wire format so an out-of-process body
(a UE5 client, a web front-end) can drive the SAME sim across a boundary:

  * contract_json.py -- lossless codec: intent_from_json / intent_to_json,
    event_to_json, snapshot_to_json, and a machine-readable schema() derived from
    the dataclasses (can't drift from the contract).
  * simservice.py -- SimService.handle(request)->response, a JSON-RPC-like endpoint
    (ops: schema/snapshot/submit/step/save/load) that keeps the core at a DAY
    BOUNDARY between requests so save/load is always clean. Transport-agnostic;
    bad requests return {"error":...}, never raise.
  * demo_service.py -- a working client that drives a full year with json.dumps/
    json.loads around every crossing, then saves mid-year and resumes in a fresh
    service. Nothing but JSON crosses.
  * docs/contract-schema.md -- the wire schema (intents/events/snapshot/views), the
    request envelope, determinism guarantee, and the worked example.

New gate test_service.py: schema / json-safe (every world's snapshot+events
serialize with stdlib json) / DETERMINISM ACROSS THE BOUNDARY (a JSON-string-driven
run == an in-process run, byte-identical welfare, for every world) / save-load over
the wire / robust to bad requests. Found & fixed a real bug: the service first saved
mid-turn (not at a boundary) so load re-saved differently -- fixed by keeping the
core at a boundary between requests. golden.json UNCHANGED (new seam only). check.py
green, 21 gates.

### Item 6 — docs coherence ✓ (branch: claude/docs-coherence)

Brought the docs current with the integrated + backlog state:
  * DESIGN.md status note: all three layers built AND deepened; 7 worlds; the
    intervention ladder; reputation = propagated deeds; edge LLM merchant; the
    playable View; the JSON contract boundary; golden 16 scenarios / 225 metrics.
  * README: status block rewritten (21 gates, 7 worlds, the new capabilities);
    "worlds are data" now lists all seven; file map already carried view_play.py /
    contract_json.py / simservice.py / reputation.py; golden count -> 16/225.
  * AGENTS.md: "what to build next" recap of everything now built + the honest
    frontier (pygame per-world rendering deferred; the fun playtest is the human's);
    contract marked FROZEN v1.5; brittle "140 golden metrics" phrasings reworded to
    "baseline golden metrics" (feature-off = baseline unchanged, no stale number).
  * CONTRACT schema doc shipped in item 5 (docs/contract-schema.md); linked from
    README/DESIGN/AGENTS.
  * llm-merchant doc: "140 golden metrics" -> "baseline golden metrics".

Docs-only; no code, golden.json UNCHANGED. check.py green, 21 gates.

## DEFINITION OF SATISFACTORY — met

- **main integrates A/B/C, check.py green.** 21 gates, FOUNDATION HOLDS on `main`
  (6290861). Contract v1.5 (additive-only); no history rewrite; every merge was
  fast-forward + green before push.
- **Every registered scenario** (7: frostpine, tidewater, guildhall, plaguewatch,
  emberforge, dustveil, fallowmere) runs headless, fires a real crisis (nonzero
  unmet + contribution + crisis-phase price spike), save/loads byte-identically, and
  drives through the contract — the `cross-scenario` gate asserts all of it for every
  world. Golden 16 scenarios / 225 metrics, baselines byte-identical, new worlds additive.
- **The playable View can pick and play any scenario** — `view_play.py` (+ `--demo`
  over all worlds; view_text.py/game.py `--scenario` delegate to it). `playable view` gate.
- **A representative intervention library works with reputation-gating** — the ladder
  (haul_relief / found_mill / hire_crew / endow_granary / open_trade_route), each
  capital+standing gated and index-scored, on capital and capital-less worlds.
  `intervention library` gate; reputation = propagated deeds (`reputation` gate).
- **The contract JSON boundary is documented with a working example** —
  docs/contract-schema.md + contract_json.py + simservice.py + demo_service.py;
  `json service` gate proves determinism across the boundary for every world.
- **The modularity acceptance test still passes** (`modularity` gate, saltmarsh) and
  **docs are current** (item 6).

### Bugs found & fixed along the way
1. persistence couldn't load guildhall/plaguewatch (hardcoded agent-class list missing
   InstitutionBuyer) — fixed by deriving from ARCHETYPES (item 2).
2. the JSON service saved mid-turn, so a resumed state re-saved differently — fixed by
   holding the core at a day boundary between requests (item 5).

### Flagged for the human (deliberate, reversible)
- The **pygame `game.py` UI and the frostpine `GameSession`** were NOT rewritten to be
  generic. GameSession is the authored frostpine game (win=survive winter, warn-winter,
  starvation, counterfactual); generalizing it is authored-content work that risks the
  game golden, and the pixel layout can't be visually verified here. The
  scenario-agnostic playable View is a separate body (`view_play.py`); frostpine's game
  stays byte-identical. Making the pygame body render every world generically is a
  dedicated UI task for a session that can see the screen.

PRs opened (each its own, all merged to main): #5 playable view, #6 cross-scenario,
#7 intervention library, #8 modularity breadth, #9 JSON seam, #10 docs. (Phase-1
integration of #2/#3/#4 landed directly on main.)

## Post-satisfactory continuation ("keep going")

### Item 7 — Layer-3 financing wired into the generic playable body ✓ (branch: claude/layer3-in-body)

Closes the frontier item "wiring negotiation into the interactive bodies" for the
scenario-agnostic body. `view_play.py` now drives the WHOLE Layer-3 loop on any
world through the contract:
  * _core enables interventions + capital goods + loans + reward-at-fair-value +
    reputation propagation, so the body plays the full game (not just gathering).
  * dashboard shows your standing (descriptor + value) and any loans owed.
  * new `deal <key>` command: negotiate a loan with the deterministic ScriptedMerchant
    (merchant.negotiate + make_view_builder) to fund an intervention, then submit
    AcceptDeal -- the sim is the hard gate. No LLM in this path (offline, deterministic).

Verified end-to-end: build reputation (deeds propagate to reach 1.0), broke player
negotiates 80 at 15%, sim funds + founds the mill (woodlot Lv1, loan recorded); an
unproven borrower is declined by the merchant. New sub-test LAYER3-FINANCING in
test_view_play.py. golden.json UNCHANGED (generic body config + a new command; the
sim/contract/golden untouched). check.py green, 21 gates.

### Item 8 — loan default → propagated reputation hit ✓ (branch: claude/default-reputation)

Closes DESIGN.md §8's remaining loan consequence: a default is a bad DEED that
spreads. When `world._loan_phase` marks a loan defaulted, it records a default fact
in the reputation network (keyed `default:<id>`); `standing` is then discounted by
`disrepute` (the fraction of the village that has heard of the default), tunable via
`reputation_default_penalty` (default 1.0). So a defaulter's hard-won standing
collapses as word travels -- verified: 300 -> 0 at full penalty, softened at 0.5.

Runs on the same reputation rng/graph (own stream), flag-gated (reputation off by
default), and persisted for free (default facts are ordinary reputation beliefs).
New sub-test DEFAULT-HIT in test_reputation.py. golden.json UNCHANGED. check.py
green, 21 gates.

### Item 9 — Layer-3 read surface over the JSON boundary ✓ (branch: claude/service-layer3)

Rounded out the sim-as-a-service seam so a UE5/web client can drive the WHOLE game
over JSON, not just gather/trade:
  * SimService gained a `flags` dict (arbitrary cfg overrides: loans/capital/
    reputation/…) and two read ops -- {"op":"interventions"} (the Layer-3 action
    menu with can_perform + gate reason) and {"op":"reputation"} (standing +
    descriptor). Perform/AcceptDeal already crossed as intents; now the client can
    also READ the menu and reputation it needs to decide.
  * docs/contract-schema.md + the service docstring list the new ops.
  * New sub-test LAYER3-WIRE in test_service.py: read the menu + reputation over the
    wire, then Perform an intervention as a submitted JSON intent and confirm an
    InterventionPerformed(accepted) event comes back over the wire.

golden.json UNCHANGED (service reads only; no sim/contract change). check.py green,
21 gates.
