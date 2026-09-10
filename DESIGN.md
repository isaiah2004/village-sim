# DESIGN.md — the north star

Read this before deciding *what* to build. [AGENTS.md](AGENTS.md) says how to work
in the repo; this says where the whole thing is going and why. If a task doesn't
move one of the three layers below, question it.

## The game in one sentence

Drop a modern mind into a living medieval world. It reshapes that world with
knowledge the common man had no time to use — and the world **responds**, both
economically and in lore, **rewarding real impact**. It should feel less like "a
game" and more like a what-if: *if I were isekai'd, how would I actually play it?*
You might train and fight and move the story with strength — or you might notice
that a war-stricken region is starving and haul food there, or that a village has
no mill and build one. Not every player fixes economic problems. The point is that
**when they do, the world reacts and rewards them like real life would.**

## The core principle (do not violate)

**The contribution index is a CALCULATOR, not the game.** It answers *"how much was
that worth?"* — and it is essentially done. **Never hardcode a scenario into it**
(not wood, not "food blight," not water). Every time a scenario becomes a special
case inside the index, we've mistaken the calculator for the game. The game is the
*world* that produces problems and lets the player change them; the index just
prices the change, uniformly, for any problem.

## The four questions

1. **Did the player actually resolve a problem?**
2. **What was the problem?** (wood scarcity, a missing mill / capital-infra gap, a
   drought, poisoned food near a war, …)
3. **How much impact did they have?**
4. **Reward accordingly.**

Questions **3 & 4 are the index** — largely built, and deliberately "done enough."
Questions **1 & 2 are the world model** — the real, hard, mostly-unbuilt frontier.
Wood/winter was a single hardcoded instance of 1 & 2, built only to prove the index
(3 & 4) works. It does. Now generalize.

## The three layers

### Layer 1 — The World & its Problems  *(the frontier)*
A general world-state model: typed, located **situations** — call them Needs or
Problems — each with a **severity** the simulation tracks and updates. Wood scarcity
is one instance; a drought, a capital gap, poisoned food are others. The goal:
**problems are data, not code.** This is the least-built layer and where the hard
design now goes.

### Layer 2 — The Contribution Index  *(the calculator; nearly done)*
Given *"a problem's severity fell, and the player caused it,"* price the effect
(fair value) and attribute it (resource lineage + a counterfactual). It must be
**scenario-agnostic**: it prices *any* registered problem the same way, with no
per-scenario code. Two pieces already exist and generalize:
- **Pricing / attribution of realized effect** → `accountant.py` + `lineage.py`.
- *"Did the player cause it, or would it have happened anyway?"* → the **ghost-sim
  counterfactual** (`session.py`): run the world without the player's action and
  compare. This already generalizes to *any* problem, not just wood.

The only thing wrong with Layer 2 today is that "need" is wired to wood/food
specifically. Fixing that (below) makes it universal and *ends scenario-creep for
good.*

### Layer 3 — World-Change / Interventions  *(the real game)*
How the player acts on the world: a **curated library of pre-authored playable
actions** — build a mill, dig a well, open a trade route, introduce crop rotation,
haul grain to a famine — each with **preconditions** (reputation, capital,
knowledge) and **effects** on world-state. Acquiring the means is mediated by
**AI-agent negotiation** (see the mill example). This is the hardest part and the
actual game.

**Scope realism (settled):** *no story-on-demand.* We cannot have the engine invent
a mill's assets and code at runtime. Instead we enumerate the hundreds of things a
modern mind would plausibly do and make each a real, precondition-gated feature. We
will miss some (the player who invents an MMA league); that's an accepted limit.

## The loop that ties it together

The three systems we've built are not separate — they interlock into one loop:

> **Change the world** (Layer 3) → **the index scores it** (Layer 2) → *and the deed
> becomes a fact that spreads through the **knowledge-propagation network*** →
> that spread **is your reputation** → which **gates the next, bigger intervention**
> (Layer 3).

Your reputation is not a new system: it is **your deeds propagated as knowledge
through the same social graph that spreads scarcity rumors** (`knowledge.py`). A
merchant says yes to an S-rank and no to an unknown villager's son because word of
what you've done has (or hasn't) reached him. That loop **is** the game.

## Worked example — the mill (a Layer-3 target)

A villager's son wants a mill. He walks up to a **merchant (an AI agent)** and
proposes a deal: a loan of capital and some men, as a joint venture — here's what I
put in, here's what you put in, here are the terms and interest. The merchant's AI
**reasons like a merchant**, using **his own gated knowledge** (trade routes, the
political situation) *and* **the player's standing so far**, and answers yes or no.
On yes, capital transfers; the game **recognizes the intent** and offers the
pre-authored *"build mill"* action; the finished mill **changes world-state**; the
index **scores** the effect; the deed **propagates** and reputation grows —
unlocking bigger deals next time.

Systems this one example needs:
- **Reputation / standing** = propagated deeds (`knowledge.py`).
- **AI-agent negotiation** — an LLM strictly **at the edge** (dialogue + judgement),
  never holding sim truth or mutating world-state directly.
- **Knowledge-gating** of what the merchant knows and will reveal.
- A **capital / loan** mechanic.
- The **intervention library**: preconditions → effects on world-state.
- Those effects feed **Layer 1** state, which **Layer 2** prices.

The intervention library is built (`interventions.py`, first rung `found_mill`).
The **AI-agent negotiation step is scoped** in
[docs/llm-merchant-negotiation.md](docs/llm-merchant-negotiation.md) — the LLM as a
soft gate at the edge, the sim as the hard gate, all flag-gated.

## Sequencing (build order)

1. **NOW — make Layer 2 universal.** Turn "need" into a **data-defined Need/Problem
   registry**. Re-register wood *exactly as today* so the golden master stays
   byte-identical (proof the calculator's behavior didn't change). Then add a second
   need (food) as **pure data, with zero new scoring code** — if it prices correctly
   with no special-casing, the index is proven universal and scenario-creep is over.
2. **NEXT — Layer 1 world-model.** A general world-state / problem model (typed,
   located, severity) so problems exist as data the index can price and
   interventions can target.
3. **THEN — Layer 3 interventions.** The pre-authored action library + AI
   negotiation + reputation-gating (the mill). Interventions need a world-state to
   act on, so this follows Layer 1.

> **Status (implemented):** all three layers are built and deepened. Layer 2 is
> universal (the data-defined need registry). The scenario system is data
> (`scenario.py`): **seven registered worlds** (frostpine, tidewater, guildhall,
> plaguewatch, emberforge, dustveil, fallowmere) run headlessly, fire a real
> crisis, save/load byte-identically, and drive through the contract — a single
> `test_scenarios.py` guard holds all of that for every world, and adding one is
> proven to be one data entry by `test_modularity.py`. Layer 3 is a
> reputation+capital-gated **intervention ladder** (relief shipment, capital,
> crew, granary, trade route), scenario-agnostic; reputation is **deeds propagated
> through `knowledge.py`**; the merchant negotiation runs a real edge LLM
> (opt-in, off in tests). A **scenario-agnostic playable View** (`view_play.py`)
> plays any world through the contract, and the contract has a **JSON wire format**
> (`docs/contract-schema.md`) a UE5/web client can drive. The baseline is
> byte-identical (`regression.py`: 16 scenarios / 225 metrics, new worlds captured
> additively). See **[SCENARIOS.md](SCENARIOS.md)** and
> **[docs/contract-schema.md](docs/contract-schema.md)**. What remains: the pygame
> body's per-world rendering, and the frostpine game's "is it fun" playtest.

## Modularity contract — scenarios are DATA, not code

The end state: adding a whole new world archetype is **"type a name and assign
values."** No new branching logic, no per-scenario special cases anywhere in the
sim or the index. A **scenario** is a named data bundle that selects and
parameterizes these axes; `make_scenario(name)` builds a fully-configured world
from it:

- **Resources** — which goods exist and their params (intrinsic value; consumable
  vs capital; daily consumption profile; base yield). e.g. wood, fish, grain, iron
  ore, charcoal, potions.
- **Drivers (cycles)** — named cyclical modulators with phases and per-phase
  multipliers on specific resources' yield and/or consumption. *Winter* is one
  driver; *Tides* is another. A driver is data:
  `{name, phases:[{name, length, yield_mult:{res:…}, consume_mult:{res:…}}]}`.
  Adding "Tides" must be exactly this — no code.
- **Needs / Problems** — which resources/conditions the world tracks as a problem
  (severity = the unmet amount), which the index then prices uniformly. Registry
  entries (Layer 2's universal core).
- **Market model** — pluggable and selected by name: `call_auction` (today's
  spread-out double auction) or `guild` (fixed/capped price up to a daily quota,
  with overflow routed to a secondary `call_auction` at a discount). New market
  models plug in behind one interface.
- **Population** — spawn specs: archetypes + counts + params (villagers,
  dependents, market_maker/guild, adventurers, craftsmen, suppliers…).
- **Capital goods** — which infrastructure exists and its input/output/upkeep
  (woodlot, boat, smithy, charcoal kiln, mill).

**Acceptance for "modular":** adding any of the scenarios below must be a single
data entry with zero new logic; and the baseline scenario must reproduce the
current golden master **byte-identical**.

## First-MVP scenarios (build these; each proves one axis is truly data)

1. **`frostpine`** *(baseline — the current world, re-expressed as a scenario)*.
   Resources wood + food; driver = the four-season cycle (winter spikes wood
   consumption and cuts yields); market = `call_auction`; population villagers +
   dependents (who cannot cut wood and go cold first); need = winter warmth (wood).
   **Anchors the golden — must stay byte-identical.**
2. **`tidewater`** *(fisher village — proves a driver + resource are pure data)*.
   Resources fish + grain (grain is bought in); driver = **`Tides`** (phases e.g.
   spring-run high yield → summer → neap low → storm very low) modulating fish
   yield; scarcity bites when the catch fails; population fishers + dependents
   (net-menders / elderly who cannot fish and must buy it); need = the town's fish/
   food. Success = "Tides" behaves like winter for *its* values with no new code.
3. **`guildhall`** *(adventurer town — proves the market model is pluggable)*.
   Resources = adventuring yields (e.g. monster parts, ore, potions), variable by an
   expedition/danger driver; market = **`guild`** (buys at a set price up to a daily
   quota; overflow → a secondary `call_auction` at a discount); population =
   adventurers (produce via expeditions) + the guild + townsfolk/dependents who
   need a critical good (e.g. healing potions); need = the town's supply of that
   good. Success = swapping `call_auction`→`guild` is a config choice.
4. **`emberforge`** *(craftsman town — proves multi-resource + structural scarcity +
   capital as the contribution axis)*. Resources = raw materials wood + iron ore +
   charcoal (constant, structural demand as crafting inputs) → crafted goods;
   scarcity is chronic (consumption > supply), relieved by capital infrastructure
   (a smithy / charcoal kiln); market = `call_auction`; population = craftsmen
   (consume raw mats) + suppliers + dependents; need = steady raw-material supply.
   Success = the index credits infrastructure that relieves an *ongoing* shortage,
   with no cyclical driver at all.

Together these four force real modularity: cyclical single-resource (`frostpine`,
`tidewater`), a different market model (`guildhall`), and multi-resource structural
scarcity relieved by capital (`emberforge`). If all four run from data and the
baseline golden is unchanged, the system is genuinely universal.

## Non-negotiables (see AGENTS.md for detail)

The wall (all actions through the contract); the frozen contract; the golden ritual;
flag-gate new mechanics off by default; determinism; the **LLM lives only at the
edges** (dialogue, negotiation, *proposing* world-changes) and never holds
quantitative state or mutates world truth; the authored causal model is
load-bearing, the LLM proposes, the sim validates.
