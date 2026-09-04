# Village Sim — a contribution-indexed world simulator

A persistent fantasy-world economy where a player (isekai framing: a modern mind
dropped into a medieval village) reshapes a *living* civilization through real
systemic impact, not scripted quests. An **AI Accountant** watches the whole
economy and rewards **realized effect** — keeping someone warm through winter —
rather than grinding. Knowledge is not free: beliefs **propagate** through a
social graph with delay and distortion, and only the player can read the
Accountant's fair-value signal (the "isekai information edge").

This repository is the **engine-agnostic simulation core** plus a small 2D
fun-test. The base game will later be built in Unreal Engine 5; this core is
designed to drop underneath it unchanged.

> **Continuing this project?** Read **[AGENTS.md](AGENTS.md)** first — it has the
> working conventions (a foundation gate you must keep green), the phased plan,
> the locked decisions, and exactly what to build next.

## Quickstart

```bash
pip install pygame
python game.py          # the 2D click-sim ("Say the Word")
python view_text.py     # the SAME game rendered in the terminal (a 2nd body)
python check.py         # the foundation gate — runs every test; must say "FOUNDATION HOLDS"
```

## The three ideas

- **Contribution Index / AI Accountant.** The Accountant is an *observer*, not a
  planner. It prices opportunity and pays out only when a resource does *realized
  stabilising work* (is consumed to meet a real need), crediting the original
  producer backward through a resource-lineage DAG. Priced at **fair value**, so
  solving a crisis is rewarded — not zeroed out. It also polices exploitation
  (hoarding a cornered stock during scarcity draws a holding fee).
- **Knowledge propagation.** A scarcity claim injected into one villager spreads
  across a social graph with delay, per-hop fidelity loss, and echo caps (100
  people repeating one rumour ≠ 100 witnesses). A *false* claim can still move
  markets. Deterministic, rule-based, runs every tick for every agent — no LLM in
  the loop.
- **Isekai information edge.** Villagers act only on what they can observe (their
  reserves, market prices, felt/heard scarcity). Only the player sees the
  Accountant's fair-value channel. The crisis is real: if the player does nothing,
  the village suffers, and the Accountant merely measures it.

## Architecture — "one brain, many bodies"

```
SimCore (the simulation)  ←  GameSession (the game's rules)  ←  a View (the skin)
   engine-agnostic             engine-agnostic, no rendering      pygame / terminal / …
```

A new presentation — a top-down pixel game with walking characters, or the eventual
UE5 client — is **just another View** over the same `GameSession`, changing nothing
in the rules or the sim. `view_text.py` (a terminal body sharing nothing with
`game.py`) is the living proof of this.

## File map

| File | Role |
|---|---|
| `contract.py` | **Frozen v1.1** engine-agnostic interface: Intents / Events / Snapshot. The "wall" — every action passes through it. |
| `simcore.py` | `SimCore` facade over the reference world; the only thing a body touches. Plus `serialize`/`load`. |
| `world.py` | The simulation clock/orchestrator (production → market → consumption → belief → surveillance). |
| `agents.py` | Agents (Villager, Dependent, MarketMaker, Merchant, Player) + player strategies + spawn specs. |
| `accountant.py` | The AI Accountant: bounty, fair value, realized-effect payout, hoard surveillance. |
| `lineage.py` | Resource-lineage DAG + backward credit propagation. |
| `market.py` | Per-resource call auction (sealed-bid double auction). |
| `knowledge.py` | Social graph + belief propagation (the echo-cap keystone). |
| `metrics.py` | Per-day series + welfare summary. |
| `config.py` | All tunables; `Resource`/`Season` enums. |
| `session.py` | `GameSession` — engine-agnostic game rules (turn flow, action economy, win/lose, impact ledger, counterfactual, semantic news feed). **No rendering.** |
| `game.py` | pygame **View** ("Say the Word"). Window, palette, layout, input→intent. |
| `view_text.py` | Terminal **View** — a second body proving the skin is swappable. |
| `persistence.py` | Full-fidelity JSON save/load for `SimCore`. |
| `check.py` | The foundation gate: regression + conformance + persistence + unit tests. |
| `regression.py` + `golden.json` | Golden-master safety net (9 scenarios, 126 metrics). |
| `test_*.py` | Behavioural + contract + persistence tests. |
| `main.py`, `demo_knowledge.py` | Headless scenario runners the golden master mirrors. |
| `*.html`, `plot_*.png`, `sim_data.json` | Published demo pages and plots (project artifacts). |

## Status

**Phase 1 (lock the model + contract) is finalized.** The contract is frozen,
save/load is implemented, and the golden master is locked. **Phase 2 (prove it's
fun) is in progress** — the 2D fun-test exists and the contribution loop is made
legible. See **[AGENTS.md](AGENTS.md)** for the full roadmap and next steps.
