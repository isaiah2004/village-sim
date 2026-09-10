# AGENTS.md — how to continue building this project

This is the handoff for anyone (human or AI agent) picking up the build. Read it
fully before changing code. It assumes only this repository — no external context.

Start by reading [README.md](README.md) for the vision, architecture, and file
map. This file covers **how to work here**, **the plan**, **the locked
decisions**, and **exactly what to build next**.

---

## 0. The one command that matters

```bash
python check.py      # must print "FOUNDATION HOLDS"
```

Run it **before and after every change.** It runs, fail-fast-reporting:
golden regression → contract conformance → save/load round-trip → behavioural
unit tests. If it's green before your change and red after, you regressed
something — investigate, don't paper over it.

Individual pieces (all stdlib-only, each runs standalone):

```bash
python regression.py            # check current behaviour vs golden.json
python regression.py --capture  # RE-write golden.json (only on an intentional, reviewed change)
python test_contract.py         # contract conformance
python test_persistence.py      # save/load round-trips byte-identically
python test_simcore.py test_capital.py test_dependents.py   # behavioural
python game.py                  # play the pygame build
python view_text.py --demo      # scripted terminal run (CI-safe, no input)
```

---

## 1. Non-negotiable conventions (these are the guardrails)

1. **The wall.** Every action — player *and* NPC — reaches the world only through
   the `SimCore` contract (`contract.py`). A game/UI layer must **never** mutate
   sim state directly. `session.py` and `game.py` talk to the sim only via
   `SimCore`; they must not import `world`/`agents`/`accountant` internals to
   *drive logic*. This wall is what keeps the contribution accounting honest and
   makes the shipped game double as the research harness.

2. **The contract is FROZEN (v1.1).** In `contract.py`:
   - *Additive* changes (a new optional field with a default, a wholly new Event
     type) → **minor** version bump + a one-line note. These keep old bodies working.
   - *Breaking* changes (rename/retype/re-mean a field) → **major** bump + a
     migration note. Don't do these casually.
   - `test_contract.py` fails if the sim emits an undeclared event, if a snapshot
     shape drifts, or if a body references a contract name that no longer exists.

3. **The golden ritual.** `golden.json` is the recorded output of every validated
   scenario. Re-capture it (`python regression.py --capture`) **only** on an
   intentional, reviewed behaviour change — **never** to silence a red bar. A
   surprise regression means investigate.

4. **Flag-gate new mechanics OFF by default** so the golden master stays
   byte-identical until you deliberately turn a feature on. Existing examples in
   `config.py`: `capital_goods_enabled`, `reward_at_fair_value`,
   `propagation_enabled` (all default `False`). The game turns them on in
   `session.make_config()`.

5. **Determinism.** The sim is seeded. Propagation uses its **own** RNG so gossip
   shuffles never perturb the economic stream. Same intents in the same order →
   the same run. Save/load depends on this; don't introduce unseeded randomness or
   rely on set-iteration order (sort for determinism — see `knowledge.py`).

---

## 2. The layers (where new code goes)

```
SimCore + contract  →  GameSession (session.py)  →  View (game.py, view_text.py)
   simulation             game RULES                    skin
```

- **New simulation mechanic** (a new resource, a new belief dynamic, world-change):
  goes in the sim (`world.py` / `agents.py` / `accountant.py` / `knowledge.py`),
  flag-gated, with golden re-captured intentionally, and surfaced through the
  contract (new Event/field, minor bump).
- **New game rule** (an objective, an action, a win/lose condition, scoring):
  goes in `session.py` as intent + guard methods. No rendering there.
- **New presentation** (a different skin, a pixel-art body, a UE5 client): a new
  View that reads `GameSession` state and calls its action methods. The news feed
  is **semantically tagged** (`contribution`, `cold`, `word`, …), never colored —
  a View maps tags to colors/sprites/sounds (`TAG_COLORS` in `game.py`).

---

## 3. The plan (seven gated phases — take our time, not time-boxed)

- **0. Foundations** ✓ done.
- **1. Lock model + contract** ✓ done — merged prototypes into one Python
  reference, added capital goods + the dependent/inelastic subgroup, froze the
  Intent/Event/Snapshot schema, built the regression suite, implemented save/load.
- **2. Prove it's fun** ← **YOU ARE HERE.** A 2D game on the Python model
  (pygame, zero porting). This is the **go/no-go gate** — it comes *before* any
  C++. Success = the loop is fun in a real playtest.
- **3. C++ SimCore** — zero engine deps, parity-tested against the Python
  reference (Python stays the balancing oracle forever).
- **4. UE5 plugin** — a thin adapter; a `USimWorldSubsystem` owns/ticks the core.
- **5. Deepen** — gated dialogue (LLM at the edge only), the hybrid world-change
  engine, more domains one at a time.
- **6. The real game** — open world / story / art (deliberately last).

### Locked decisions (do not relitigate without the owner)

- **Goal = "both, sequenced":** ship the game first, *then* use it as a research
  testbed. The discipline this requires is convention #1 (the wall).
- **World-changes = "hybrid":** an authored causal DAG is the load-bearing sim; an
  LLM only *proposes* new nodes/edges; a sandboxed sim-fork + the contribution
  index *validates* proposals before they enter the canonical graph. The LLM never
  holds quantitative state.
- **Unreal bridge (deferred until fun is proven):** the leaning is
  **sim-as-a-service** with the frozen contract serialized as JSON as the wire
  format — which the freeze + `persistence.py` make nearly free. Alternatives:
  embed CPython, or port SimCore to C++ (phase 3). Decide when phase 2 passes.

---

## 4. What to build next

> **North star: [DESIGN.md](DESIGN.md).** Read it before choosing work. The index
> is a **calculator, not the game**; never hardcode a scenario into it. The build
> order is settled there: **(1) make Layer 2 (the index) universal — DONE below;
> (2) Layer 1 world-model + the scenario system — DONE below; (3) Layer 3
> interventions — first piece DONE below, now scenario-agnostic.** All three
> layers work, the **world model is fully data-driven (scenarios are data)**, and
> everything is drivable through the contract by any View/UE5. The frontier is
> deepening each layer (esp. reputation-via-propagation and the LLM merchant at
> the edge) and the frostpine game. Confirm scope with the owner before the next
> big step.

**The world model is now DATA — the scenario system.** A world's axes (resources,
the cyclical driver, needs, the market model, population, capital goods) are a
named `Scenario` value in `scenario.py`; the sim, the index, and the contract read
them generically with **no per-scenario branching**. `make_config(name)` /
`make_world(name)` build a fully-configured world from a name. Four MVP worlds
ship — **frostpine** (the byte-identical baseline), **tidewater** (a driver +
resources are data), **guildhall** (an adventurer town with a DEMAND-side crisis:
a war quartermaster — a new `buyer` archetype — enters the guild market during a
mobilization window and the index pays whoever supplies the front), **emberforge**
(multi-resource structural scarcity relieved by a generic capital good). A fifth,
**plaguewatch** (a plague apothecary on the call auction), is the demand event as
pure data. The capital-goods system, the player's skill, agent inventories,
metrics, problems, the `found_mill` intervention, per-consumer needs
(`NeedSpec.consumer`), trade-good production (`produces`), and the demand-side
driver were all generalized off scenario data while keeping frostpine
**byte-identical** (`regression.py` now 14 scenarios / 197 metrics, the new worlds
captured **additively** — frostpine's 140 untouched). The contract went **v1.4 →
v1.5** (additive): `AgentView.holdings`/`.fears` and `Snapshot.scenario`/
`.primary_resource`/`.consumables`/`.village_unmet` are generic resource-keyed
reads, so a body renders any world without knowing wood/food. `demo_scenarios.py`
is a thin scenario-agnostic body proving it; `test_modularity.py` adds a throwaway
world ("saltmarsh") and proves a new world is **one data entry, zero new logic**.
See **[SCENARIOS.md](SCENARIOS.md)** for the axes and the add-a-world guide.

**Layer 2 is now universal — the need registry.** "Need" is DATA (`needs.py`): a
`Need` = an identity, the resource whose consumption meets it (the lineage
attribution hook), a per-agent seasonal requirement (severity source), and whether
meeting it is rewarded. The accountant prices and pays *every* registered need
through one pipeline with **no per-resource code** (`accountant.start_day` /
`rewarded_needs` / `reward_consumption`; `world._consumption_phase`). Wood is
re-registered exactly as before — the **9 original golden scenarios are
byte-identical** (`python regression.py`, no capture). Food is registered as pure
data; flipping `cfg.reward_food_need` routes food through the identical
reward+lineage pipeline (proven in `test_needs.py`, and locked as the additive
`FOOD_NEED_BLIGHT` golden scenario — new rows only, existing 126 untouched). *This
ended scenario-creep: adding a need is a registry row, never new index logic.*

**Layer 1 is now data — the world-state problem board (first piece).** Problems are
DATA (`problems.py`): a `Problem` = key, TYPE (kind), LOCATION, subject; its
**severity (0..1) is read from world-state each day**, so the sim tracks it as the
world moves. Two authored TYPES ship — `scarcity` (reuses the index's own scarcity
signal) and `capital_gap` (a non-consumption "missing infrastructure" problem, the
mill shape). The board is observational (`problems.refresh` in `world.begin_day`,
mutates nothing → the **140 golden metrics stay byte-identical**, no capture) and
exposed additively on the contract (`ProblemView` + `Snapshot.problems`, **v1.1 →
v1.2**, plus `SimCore.problems()`). `demo_problems.py` shows it over a year;
`test_problems.py` proves typed/located/data, world-tracked severity, that building
a woodlot lowers the capital gap, and that a scarcity problem's severity *is* the
index's own signal (one definition shared by Layers 1 and 2). This is DESIGN.md
question 2 ("what is the problem?") made first-class.

**Layer 1 — what remains (frontier):** more problem TYPES as needed; *located*
problems beyond the single "village" (regions arrive with the Stage-2 knowledge
layer); and richer severity readers.

**Layer 3 is now data — the intervention library (first piece).** How the player
CHANGES the world (`interventions.py`): an `Intervention` is data (key, title, the
Layer-1 problem it `targets`, `capital_cost`, `min_standing`, enabling `requires`
flags). A new `Perform(key)` contract intent (**v1.2 → v1.3**, additive, + an
`InterventionPerformed` event) routes through `world._do_intervention` →
`interventions.perform`, which checks preconditions and applies one authored,
deterministic EFFECT to world-state — the ONLY place an intervention touches the
sim. First rung: `found_mill` — a capital-financed woodlot that lowers the
`capital_gap:wood` problem and whose wood the index credits to the founder. OFF by
default (`cfg.interventions_enabled`) → the **140 golden metrics stay byte-identical**
(no capture). `demo_interventions.py` shows the two-year loop (locked early → prove
yourself → found & grow the mill → capital gap 1.00→0.00); `test_interventions.py`
proves library-data, gated-off no-op, precondition gating, the world-change effect +
index pricing, and determinism. Two seams are deliberate and documented in
`interventions.py`: **standing** (`interventions.standing`, today = realized
contribution; DESIGN.md's reputation = deeds propagated through `knowledge.py` plugs
in here) and **negotiation** (`interventions.evaluate`, today a deterministic
merchant; an LLM merchant replaces it AT THE EDGE — proposes/judges, sim validates,
never mutates state).

**Layer 3 — merchant negotiation + loans (MVP built).** You fund an intervention
by negotiating a loan with a merchant. `merchant.py` (edge) has the `Merchant`
protocol, a deterministic `ScriptedMerchant` (used everywhere in `check.py`), an
edge-only fail-closed `LLMMerchant` (cheap `claude-haiku-4-5`, strict tool output,
cached persona), and `negotiate()` capped at **3 rounds**. The settled terms enter
the sim as the additive `AcceptDeal` intent (**contract v1.3 → v1.4**; +
`DealResolved`/`LoanUpdated` events, `MerchantView`/`LoanView` reads,
`SimCore.merchant_view`/`reputation`), where `world._do_accept_deal` is the HARD
gate and `world._loan_phase` services a deterministic `Loan` (`cfg.loans_enabled`,
default off → **140 golden metrics byte-identical**). `demo_merchant.py` shows the
loop; `test_merchant.py` + `test_loans.py` cover it (LLM stubbed, never live in
tests). Full design + the assumed decisions:
[docs/llm-merchant-negotiation.md](docs/llm-merchant-negotiation.md).

**Layer 3 — what remains (frontier, the actual game):** more interventions in the
library (dig a well, open a trade route, haul grain to a famine); **reputation via
propagation** (deeds → `knowledge.py` → standing — the scope doc's step 4, the one
piece of the merchant loop still on the contribution proxy); wiring negotiation into
the interactive bodies (`game.py`/`view_text.py`); and, when a live model is wanted,
enabling `LLMMerchant` in a body (it is edge-only and off in the sim). **Confirm
scope with the owner before the next big Layer-3 step.**

**Track A (make the loop fun) — done this track:** contribution made *felt* (the news feed names *who*
you kept warm and *why* it was worth what it was — `ContributionDetail` event);
a persistent **impact ledger**; the **warning** as a real second lever (costs an
action, spreads visibly, and reports a **measured** end-of-year effect via a
counterfactual ghost sim); the over-hoard tension made legible; and the
three-layer split + a second (terminal) body.

**Open candidates** (a real playtest should choose the order — the owner will
playtest "much later"; until then, prefer low-risk, high-legibility work):

1. **Fold the warning's measured effect into the numeric score.** *Deferred —
   playtest-gated.* It's a balance decision (how much is a warning worth vs a
   woodlot?) that wants feel-data. Nothing is foreclosed by waiting: the effect is
   already measured (`result["warning_effect"]`) and shown. Two flavors when it's
   time: **cheap** (session adds `warning_effect × k`) vs **deep** (the AIC scores
   information acts as realized contribution — the "knowledge = value" unification;
   this is a *design-with-owner* piece and likely wants the phase-5 sim-fork
   validator).
2. **A second scarce good / second crisis** (e.g., a summer food blight) to test
   whether the loop stays interesting under competing pressures rather than one
   wood/winter axis. *Mechanic implemented — `food_blight_enabled` (default OFF),
   cuts food gather yield to 12% in summer; `demo_blight.py` + `test_blight.py`.*
   A real summer crisis appears (idle village ~43 food unmet) and a food-stocking
   player rescues it. **Owner calls whether to turn it on in the game and playtest.**
   *Scoring the food axis is now handled the RIGHT way* — not as a food special-case
   but via the universal need registry above (`cfg.reward_food_need`). Feeding the
   hungry earns realized contribution through the same pipeline as wood; the blight
   is just one mechanic that makes food scarce enough to be worth pricing.
3. **NPC dialogue stub** — walk-up-and-talk that renders a villager's *actual*
   belief. `SimCore.belief(agent_id, resource)` already returns `(value,
   confidence)`. This is the first concrete step toward a pixel-art / UE5 body.
   *Done — `session.villager_line` / `worried_voices` (belief read through the
   contract); pygame hover bubble + terminal `t`/voices; `test_dialogue.py`.*
4. **Surface save/load in a body** (e.g. S/L keys). Persistence exists
   (`persistence.py`, `SimCore.serialize/load`) but no View exposes it yet.
   *Done — whole-game save/load (`GameSession.save/load`, sim through the wall +
   session layer), captured at a clean day boundary; `game.py` S/L keys + toast,
   `view_text.py` save/load; `test_save_load_game.py`.*

---

## 5. Gotchas & facts worth knowing

- **Headless testing / rendering:** set `SDL_VIDEODRIVER=dummy` and save frames
  with `pygame.image.save(screen, "shot.png")`. `shot_*.png` is gitignored.
- **The GameSession runs with no renderer** — importing `session` never imports
  pygame. That's the modularity contract; keep it true.
- **World calendar:** `season_length=30`, 4 seasons, `years` configurable. In the
  game (`years=1.0`) **winter = days 90–119**. Wood is the scarce good; food is
  comfortably producible, so wood/winter is the crisis.
- **Dependents** (ids `d##`) can garden food but **cannot chop wood** — they buy
  it and go cold first in winter. They are *why* information and hoarding matter
  (a cornered market shuts them out). Villagers `v##`, market maker `mk##`,
  player `PLAYER`.
- **The player** has the Accountant's fair-value channel; villagers do not. That
  asymmetry is the whole isekai fantasy, made mechanical.
- **Counterfactuals** are computed by running a parallel `SimCore` with no player
  intents (a "ghost") — see `session.py`. Pure-contract; no reach into internals.

### The single most important design finding

Contribution **must** be priced at *fair value* (`reward_at_fair_value=True`), not
at the marginal bounty. The marginal bounty collapses to ~0 exactly when you
*solve* a shortage, so solving a crisis would score ~0 — the opposite of the
project's aim. Fair-value pricing (floors at intrinsic, rises with scarcity) makes
the score reward realized **impact**. This flag is the heart of the index; the
game turns it on. Verified it does not reward hoarding (a responder out-earns a
hoarder ~4×, and the hoarder still goes bankrupt to holding fees).

---

## 6. Commit / workflow notes

- Keep `python check.py` green in every commit.
- Match the surrounding code's style (compact, comment the *why*, dependency-light
  — stdlib + pygame only).
- When you change sim behaviour on purpose, re-capture the golden in the *same*
  commit and say so in the message.
- Contract changes: bump `CONTRACT_VERSION` and note it in `contract.py`.
