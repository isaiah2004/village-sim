# Village Economic Simulation — AIC as Observer

A closed, fully-observable village economy used to develop the economic core
for a UE5 fantasy-life simulation. The economy is a substrate that runs **with
or without the player**; the AI Accountant (AIC) observes it, prices
opportunity, and rewards realized contribution — **but does not stabilize the
village on its own**. Whether the village survives winter depends on whether
the player chooses to act.

This is the headless Python prototype. The validated model will later be
ported to UE5 C++; UE5 will be the visualization + human-player layer.

## Design philosophy (post-redesign)

The previous iteration had the AIC effectively solving the crisis by nudging
villagers to gather more. That made the AIC a central planner — not what we
want. The current design splits two roles:

1. **The Simulator** (descriptive). Villagers act on local information only:
   own reserves, market prices, a `perceived_scarcity` belief that rises with
   felt + witnessed shortage. They never see the AIC. Crisis is real and has
   consequences if no one helps.
2. **The AIC** (analytical). Measures everything, publishes a *bounty* on a
   channel **only the human player can read**, and pays realized-effect
   bounty when a contributor's resource actually meets someone else's need.
   It is the "isekai information edge" in mechanical form — privileged
   knowledge a normal villager doesn't have.

The bounty is **information, not subsidy**. In practice (see results below)
the player's profit comes from real market trade; the bounty served only to
*point* the player at where their effort would be most valuable.

## Quick start

```bash
python ui.py              # interactive: play one human in the village
python main.py            # headless: run all scenarios, print + plot
python main.py --no-plot  # skip PNG generation
```

### Interactive UI (`ui.py`)

Tkinter window (stdlib only, no install). The console is designed around
**cause-and-effect visibility**: every panel either shows a primitive of the
sim or names how a derived number was computed. Top: status cards
(Money / Stamina / Wood / Food / Wood Fair-Value / Flag). Below: AIC panel
(its reasoning) and Market Book (yesterday's top bids + asks per resource).
Below: village snapshot (totals, tight-on-reserves count, fear, broke
villagers). Below: action queue, order entry, advance/reset. Below: timeline
chart + last-day event log explaining what happened and *why*.

**The AIC signal is the FAIR VALUE, not an explicit bounty.** The AIC
publishes its estimate of what each resource *should* cost given the forecast
(`fair = intrinsic × (1 + 2 × scarcity)`); the player sees this side-by-side
with the actual market price and infers — "market is well below fair → wood
is undervalued → gather/buy". When wood market = $2 but fair value = $11
because winter is coming, the gap *is* the opportunity. Villagers do not see
fair value — they only see the market price and their own fear. That asymmetry
is the player's information edge.

Realized-contribution payments still flow underneath (when your wood actually
meets someone's need, the AIC credits you) — but the rate isn't broadcast.
You see it as a "stabilisation payment" entry in the log when it lands.

**Reset Simulation** (top-right) throws out the current run and starts over
from day 0 — useful for testing strategies against the same seed.

## Scenarios + results

| Scenario | Winter unmet (village) | Shortage days | Player money | What it shows |
|---|---|---|---|---|
| `ACCOUNTANT_OFF` | 106 | 237 | 150 | Baseline — no AIC, idle player. |
| **`NO_PLAYER`** | **106** | **237** | 150 | AIC is on; village outcome **identical** to ACCT_OFF — proves the AIC doesn't modify villager behaviour. |
| `PLAYER_IGNORES` | 107 | 37 | 396 | Player exists, lives like a villager. Village outcome same — presence alone doesn't help. |
| **`PLAYER_RESPONDS`** | **14** | **11** | **1515** | Player chases AIC bounties. The **only** run where the village is rescued; profit is from market trade, not the bounty itself. |
| `PLAYER_HOARDS` | 50 | 33 | **0** | Player corners wood through winter. Village suffers more than baseline; surveillance levies fees and bankrupts the player. |

Key read: the AIC is doing what an economist (or a labor market signalling
board) would do — it tells the truth about marginal value. Whether anyone
acts on that truth is the player's call.

## Belief-driven demand (the seam for knowledge gating)

Villagers carry a `perceived_scarcity` belief per resource that rises with
their own unmet need + (weakly) witnessed neighbours' unmet need, and decays
otherwise. Higher fear:

* inflates their reservation price (panic-buying),
* inflates their target reserve (stockpile-for-self).

This is the **single seam** where the knowledge-gating system will plug in:
today the "witness" signal is a village-wide aggregate; later it becomes
gossip propagation with delay + distortion per the knowledge architecture
(rumours travel slow, lose fidelity, gate by social tier). At that point fear
becomes a *belief* held against possibly-stale information — and the player's
information edge becomes exploitable in obvious ways (buy grain before the
village hears war is coming).

## Architecture

| Module | Responsibility |
|---|---|
| `config.py`     | All tunables (seasons, yields, belief params, AIC settings). |
| `lineage.py`    | Resource provenance DAG + backward credit propagation. |
| `market.py`     | Per-resource call auction. |
| `agents.py`     | Villagers (belief-driven, AIC-blind) + Player (strategy-driven: idle / ignore / responsive / hoarder). |
| `accountant.py` | Observer: publishes bounty, pays on realized effect, surveils hoarding. |
| `world.py`      | Orchestrates production → market → consumption → belief update → surveillance. |
| `metrics.py`    | Records village welfare, market signals, AIC ledger, player. |
| `main.py`       | Runs the five scenarios and prints the head-to-head. |

## What survived from the previous iteration

* The **resource-lineage DAG** + backward credit propagation. Still core: it
  makes hoarded wood worthless (it never does stabilising work), and it pays
  upstream contributors fractionally when their work enabled the realized effect.
* The **call-auction market** with price discovery.
* Realized-effect payout (refined: producer ≠ consumer required).
* Hoarding surveillance (rewritten: combined honest-offer + sales signal).

## What changed

* **AIC ↛ Villagers.** Villagers no longer see the bounty. The bounty channel
  is player-only.
* **Belief / fear** is a first-class villager state (the future knowledge-gating hook).
* **Player archetypes** (`idle`, `ignore`, `responsive`, `hoarder`) instead of a
  single "responsive" + "hoarder" pair, to demonstrate the player-agency axis cleanly.
* **Village welfare** is now the primary metric, not aggregate unmet (which
  conflated villagers and the player).
* **Self-consumption excluded** from bounty payout — contribution must serve
  someone else.

## Extending: adding new archetypes

The system is structured so adding new entity types and player strategies is
**purely additive** — no core module (market / lineage / accountant / world)
needs to change.

### Add a new NPC archetype (Merchant, Noble, Adventurer, …)

1. In `agents.py`, subclass `Agent` (or `Villager`):
   ```python
   class Noble(Agent):
       def __init__(self, agent_id, cfg, rng, **kwargs):
           super().__init__(agent_id, cfg, rng)
           # ... role-specific setup
       def decide_actions(self, ctx): ...
       def make_orders(self, ctx): ...
   ```
2. In your scenario, register them via `SpawnSpec`:
   ```python
   population = [
       SpawnSpec(Villager, 12, id_prefix="v"),
       SpawnSpec(Noble, 1, id_prefix="n", kwargs={"tax_rate": 0.1}),
   ]
   World(cfg, player_strategy="responsive", population=population)
   ```

That's it. The market/lineage/AIC don't need to know Noble exists.

### Add a new player strategy

1. In `agents.py`, subclass `Strategy`:
   ```python
   class RunCaravanStrategy(Strategy):
       name = "caravan"
       daily_stamina_mult = 2.0
       def decide_actions(self, ag, ctx): ...
       def make_orders(self, ag, ctx): ...
   ```
2. Add to the `STRATEGIES` registry one line below.

Now `Player(cfg, ..., strategy="caravan")` works anywhere.

### `WITH_MERCHANTS` scenario in `main.py`

Demonstrates the modularity end-to-end: `Merchant` is a new `Agent` subclass,
3 of them are added via `SpawnSpec`, no other code was touched, and they
participate in markets / lineage / AIC observation transparently. (They also
happen to hurt the village by absorbing supply for arbitrage — useful
emergent dynamic, not a tuned scenario.)

### What's NOT yet modular (planned with knowledge-gating)

* Multi-region markets / belief regions — currently one village, one market.
  Coming as part of Stage 2 (knowledge layer), since regions are central to
  the gating architecture.
* Capital goods that *generate income* (mills, trade routes, owned land) —
  lineage `Lot`s today are consumable; we'll need persistent income-generating
  assets when nobles / guilds / production chains arrive.
* Non-economic roles (taxation, command, ritual) — these don't fit the
  produce-trade-consume loop and will need their own mechanics.

## Stage 2/3: Knowledge Propagation (`knowledge.py` + `demo_knowledge.py`)

The belief seam described above is now realized. `knowledge.py` adds a social
graph, structured `Claim`/`Belief` objects, and a `PropagationEngine`: a scarcity
claim injected into one agent **travels** across the village with delay, per-hop
fidelity loss, and an **echo cap** (repeats of the *same* source barely move
confidence; only *independent* roots corroborate into conviction). It replaces
the village-wide `village_unmet` oracle in `_belief_update_phase` and feeds the
same `perceived_scarcity` that drives panic-buying. All of it is gated behind
`cfg.propagation_enabled` (default **off**), so the validated scenarios above
remain byte-identical.

```bash
python demo_knowledge.py            # headless report + hero plot
python demo_knowledge.py --no-plot
```

Findings (player held idle, so any welfare change is caused purely by belief):

* **Information as contribution.** A *true* winter-wood warning, spread through
  the otherwise-myopic village, cuts winter shortage ~84% (28.8 → 4.6 unmet).
  Information overcomes the 4-day myopia the whole economy is built on — the
  isekai information edge, given away instead of exploited.
* **Popularity is not truth.** A *false* food rumour from one source reaches ~67%
  of the village in awareness but its confidence stays capped ("plausible"),
  while a real winter shortage, independently witnessed by 9 villagers,
  corroborates to conviction (belief 0.75). Echo ≠ corroboration.
* **Honest null result.** A scarcity *lie* does **not** manufacture a famine here
  because supply is elastic (villagers just gather more; panic becomes protective
  over-provisioning). Harmful disinformation-for-profit needs supply inelasticity
  or wealth inequality to bite — the clean next extension.

## Porting to UE5 (later)

The core (`lineage / market / agents / accountant / world`) is pure logic.
It ports to UE5 C++ as a subsystem; UE5 supplies the world rendering and the
human player's actions. The headless Python remains the balancing harness.
