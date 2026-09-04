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

## 4. What to build next (Phase 2 / "Track A — make the loop fun")

**Already done this track:** contribution made *felt* (the news feed names *who*
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
   *Follow-up (index change, needs owner sign-off):* the contribution index credits
   WOOD consumption only (`world._consumption_phase`), so feeding the hungry earns
   rescued welfare but no *score*. Scoring the food axis means extending
   `reward_consumption` to food — flag-gate it and re-capture golden intentionally.
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
