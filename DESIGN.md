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

## Non-negotiables (see AGENTS.md for detail)

The wall (all actions through the contract); the frozen contract; the golden ritual;
flag-gate new mechanics off by default; determinism; the **LLM lives only at the
edges** (dialogue, negotiation, *proposing* world-changes) and never holds
quantitative state or mutates world truth; the authored causal model is
load-bearing, the LLM proposes, the sim validates.
