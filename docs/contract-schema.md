# The SimCore contract as a JSON wire format (UE5 / sim-as-a-service)

The contract (`contract.py`) is the wall: **Intents** in, **Events** + a **Snapshot**
out. This document is its JSON wire shape, so a body in another process or engine
(a UE5 client, a web front-end) can drive the *same* sim across a boundary with
nothing but JSON crossing it. The codec is `contract_json.py`; the server endpoint
is `simservice.py`; a working example is `demo_service.py`.

`contract_json.schema()` returns this shape machine-readably (derived from the
dataclasses, so it can never drift). **Contract version: `1.5`** — the JSON is
versioned by `CONTRACT_VERSION`; a client should read `schema().contract_version`
and refuse a major it doesn't support. All changes are additive within a major.

## Transport-agnostic

`SimService.handle(request: dict) -> dict` is the whole server side. The transport
is your choice — HTTP POST of JSON bodies, a socket, UE5's `HttpModule`. Requests
and responses are plain JSON objects; a malformed request returns
`{"error": "..."}` and never raises across the boundary.

## Request envelope

| Request | Response |
|---|---|
| `{"op": "schema"}` | `{"schema": {...}}` — the shapes below |
| `{"op": "snapshot"}` | `{"snapshot": {...}}` — the current world view |
| `{"op": "submit", "intents": [ {intent}, ... ]}` | `{"ok": true, "queued": n}` |
| `{"op": "step"}` | `{"snapshot": {...}, "events": [ {event}, ... ], "done": bool}` |
| `{"op": "save"}` | `{"save": {...}}` — a full JSON save blob (from `persistence.py`) |
| `{"op": "load", "save": {...}}` | `{"snapshot": {...}}` — resume from a blob |

The service keeps the sim at a **day boundary** between requests, so a `save` is
always clean and a `load` resumes byte-identically. `submit` queues the player's
intents for the next `step`; `step` applies them, advances one day, and returns the
day's events plus the new snapshot.

## Intents (client → sim)

A tagged object `{"type": "<name>", ...fields}`. `type` is the lower-cased class name.

| type | fields |
|---|---|
| `gather` | `resource` |
| `crafttool` | — |
| `buildwoodlot` | — (establish/upgrade the scenario's capital good) |
| `trade` | `resource`, `side` (`"buy"`/`"sell"`), `qty`, `price` |
| `speak` | `resource`, `magnitude`, `truth`, `root_id`, `authority` |
| `perform` | `key` (an intervention key, e.g. `"found_mill"`) |
| `acceptdeal` | `key`, `principal`, `interest`, `term_days`, `merchant_id` |

Example: `{"type": "gather", "resource": "fish"}`.

## Snapshot (sim → client, read-only)

```
{ day, season, agents:[AgentView], markets:[MarketView], problems:[ProblemView],
  loans:[LoanView], shortage_agents, total_contribution_paid, total_penalty, done,
  scenario, primary_resource, consumables:[str], village_unmet:{resource: float},
  village_unmet_wood, village_unmet_food }
```

The **generic** fields — `scenario`, `primary_resource`, `consumables`,
`village_unmet` (a `{resource: amount}` map), and each `AgentView.holdings` /
`.fears` map — let a client render **any** world without knowing wood from fish.
The frostpine-named fields (`village_unmet_wood`, `AgentView.wood/food/…`) are the
legacy slices, still populated for that world.

- **AgentView**: `id, kind, money, wood, food, tool, stamina, fear_wood, fear_food, is_player, contribution_earned, woodlots, woodlot_level, woodlot_output, holdings:{resource:qty}, fears:{resource:0..1}`
- **MarketView**: `resource, ref_price, fair_price, last_clear_price, last_volume, bounty`
- **ProblemView**: `key, kind, location, subject, severity` (Layer 1, worst-first)
- **LoanView**: `agent_id, lender_id, principal, interest, balance, term_days, struck_day, per_day, defaulted`

## Events (sim → client, what happened this step)

Each is `{"type": "<Name>", ...fields}` (class name, PascalCase). The set:
`DayAdvanced, Produced, TradeCleared, Settled, ContributionPaid, ContributionDetail,
Shortage, HoardFlagged, HoldingFee, AssetBuilt, BeliefState, InterventionPerformed,
DealResolved, LoanUpdated`. A client styles the ones it cares about and ignores the
rest (additive-safe — new event types never break an old client).

## Determinism across the boundary

The sim is seeded; the JSON codec is lossless. The same JSON intents in the same
order reproduce an in-process run **byte-identically** (asserted by
`test_service.py` for every registered world). Live play is reproducible given its
intent log — exactly the guarantee the in-process contract makes.

## Worked example

`python demo_service.py [scenario]` drives a full year over `json.dumps`/`json.loads`
around every crossing (a stand-in for the network), then saves mid-year and resumes
in a fresh service — nothing but JSON crosses. That is the entire UE5 client
contract; only the transport differs.
