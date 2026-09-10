# LLM merchant negotiation (Layer 3, the edge)

Status: **Built (2026‑09‑10).** Steps 1–3 of the build order below are
implemented, tested, and green, and the **LLM edge adapter is now a runnable
negotiator** (step 2 complete): `demo_llm_merchant.py` drives a real edge
negotiation end‑to‑end (`--live` uses `claude-haiku-4-5`; default is the
deterministic merchant, offline), and `eval_llm_merchant.py` is the on‑demand
judgment + prompt‑injection quality eval (opt‑in `--live`, never in `check.py`).
The adapter was hardened against safety refusals (`stop_reason == "refusal"` →
fail‑closed) per the bundled `claude-api` skill. Step 4 (reputation‑via‑
propagation) shipped separately. This document is both the design rationale *and*
the record of what shipped. It obeys the non‑negotiables in [AGENTS.md](../AGENTS.md) §1 and
DESIGN.md's closing rule: **the LLM lives only at the edges, never holds
quantitative state or mutates world truth; the authored causal model is
load‑bearing, the LLM proposes, the sim validates.** Every piece is flag‑gated off
by default, so the baseline golden metrics stay byte‑identical.

## Built (MVP) — what shipped and the decisions taken

- **`merchant.py` (edge):** `DealProposal` / `MerchantDecision` / `DealOutcome`,
  the `Merchant` protocol, `ScriptedMerchant` (deterministic; used everywhere in
  `check.py`), `LLMMerchant` (edge‑only), and `negotiate()` — capped at **3 merchant
  evaluations** (`MAX_ROUNDS = 3`, so ≤3 LLM calls). Accepting a counter costs no
  extra call.
- **Loan mechanic (sim):** `Loan` on the agent, `world._loan_phase` daily servicing
  with default, `cfg.loans_enabled` (default off) + `loan_max_interest` /
  `loan_max_term_days` clamps.
- **Contract v1.3 → v1.4 (additive):** `AcceptDeal` intent; `DealResolved` +
  `LoanUpdated` events; `MerchantView` / `ReputationSummary` reads; `LoanView` +
  `Snapshot.loans`; `SimCore.merchant_view()` / `reputation()`. The sim's
  `world._do_accept_deal` is the **hard gate** (clamps terms, re‑checks
  preconditions and merchant capital, records the loan, funds + performs the
  intervention, or rejects with a reason).
- **Tests:** `test_merchant.py` (scripted rules, round cap, fail‑closed, the LLM
  adapter via a **stub client** — no network, and default `LLMMerchant` fails
  closed with no SDK), `test_loans.py` (gated‑off, strike, clamp, repayment,
  default, determinism). Both in `check.py`. `demo_merchant.py` shows the scripted
  loop; `demo_llm_merchant.py` runs the **real edge negotiation** (scripted by
  default, `--live` for the model) and `eval_llm_merchant.py` grades the model's
  judgment on hand‑labelled deals + a prompt‑injection case (opt‑in `--live`,
  offline no‑op, out of `check.py`).
- **The Claude call (edge only, `LLMMerchant`):** one `client.messages.create`
  with the cached persona as the `system` prefix, a **strict** `submit_decision`
  tool (schema‑valid arguments, forced `tool_choice`) so the result is *data*, and
  `claude-haiku-4-5` (the cheap bounded NPC judgment; `model=` overrides to Sonnet
  5 for complex deals). Fail‑closed on refusal, error, missing SDK, or a malformed
  reply — it can never fabricate an acceptance. Verified against the `claude-api`
  skill; forced tool use is supported on haiku (a caller who overrides to a model
  that rejects it simply gets a fail‑closed "closed for the day").

**Assumed decisions** (made per the owner's "assume crucial steps" instruction; all
reversible in config/data):

| Open question | Decision taken |
|---|---|
| Model & cost | **`claude-haiku-4-5`** for the merchant (cheapest acceptable; strict tool‑call output, cached persona, `max_tokens=400`). `LLMMerchant(model=…)` overrides to Sonnet 5 for complex deals. |
| Contract shape | **Dedicated `AcceptDeal` intent** (leaves `Perform` for self‑funded actions). |
| Rounds | **3** merchant evaluations max. |
| Counter depth | One counter per round within the cap; a `counter_policy` (e.g. `accept_up_to(ceiling)`) drives the player side; accepting a counter needs no extra LLM call. |
| Failure UX | **Fail‑closed:** any refusal / error / missing SDK / exhaustion → a "closed for the day" decline (`CLOSED_LINE`). No model fallback. |
| Reputation | Contribution‑as‑standing for the MVP (step 4 upgrades it to propagated deeds). |

The rest of this document is the design rationale the MVP follows.

---

## 1. What we're adding, in one sentence

A merchant NPC you negotiate a **deal** with — a loan of capital (and later, men)
to fund an intervention — where the merchant *reasons like a merchant* over his
own gated knowledge and your standing, says yes / no / counter, and the **sim
enforces the terms and applies the authored effect**. The LLM decides *whether
and on what terms the merchant deals with you*; it never decides what is true in
the world.

This turns today's deterministic gate in `interventions.evaluate()` (capital +
standing) into a two‑gate system:

| Gate | Question | Who answers | Where it runs |
|---|---|---|---|
| **Soft gate** (new) | Will this merchant deal with me, and on what terms? | the LLM merchant | the **edge** (body/session), between turns |
| **Hard gate** (exists) | Is the deal mechanically valid — real problem, capital present, preconditions met? | `interventions.evaluate` / `perform` | the **sim**, deterministically |

The soft gate can only ever *narrow* what the hard gate already allows, or attach
terms (interest, amount) that become deterministic sim data. It can never grant
something the rules forbid.

---

## 2. Where it plugs in (the existing seams)

Layer 3 already left two seams for exactly this (see `interventions.py`):

- **`standing(agent)`** — reputation input. Today = realized contribution. The
  merchant reads this (plus, later, propagated deeds — §7).
- **`evaluate(world, agent, iv)`** — the deterministic "merchant" returning
  `(accepted, reason)`. The LLM merchant is a *new implementation of this role*,
  selected at the **edge**, that returns a richer decision. The sim's own
  `evaluate`/`perform` remain and run **after** the LLM, as the hard gate.

No existing call site changes behavior when the feature is off.

---

## 3. The determinism problem — and how we keep the sim pure

The sim is seeded and byte‑reproducible; `check.py`'s golden regression and
`test_persistence` depend on it. An LLM is non‑deterministic and external. The
resolution is a hard architectural rule:

> **The LLM never runs inside the tick.** It runs at the edge, between turns, only
> when a player initiates a negotiation. Its output is captured as a
> **schema‑validated decision record** (plain data). Only that record enters the
> sim — via a contract intent — and the sim **replays from the record**, never by
> re‑calling the LLM.

Consequences that keep every guarantee intact:

1. **Golden / headless tests never call the LLM.** They use a deterministic
   `ScriptedMerchant`. The sim depends on a `Merchant` *protocol*, not on Claude.
   With the feature flag off, the code path is identical to today → the baseline golden
   metrics stay byte‑identical, no capture.
2. **Save/load stays deterministic.** The decision record (accepted, terms,
   interest, principal, the resulting loan) is ordinary sim state, serialized by
   `persistence.py` like any other. Reloading replays the recorded deal; it does
   not re‑negotiate.
3. **A live game is reproducible *given its decision log*.** Two replays of the
   same recorded deals evolve identically. Live play with a fresh LLM call is, by
   design, the one non‑reproducible moment — and it happens at the edge, before a
   deterministic intent is submitted, exactly like a human clicking a button.

```
player proposes terms ─▶ [EDGE] LLM merchant judges ─▶ MerchantDecision (data)
                                                          │ recorded in the body
                                                          ▼
                              contract intent (AcceptDeal / Perform+terms)
                                                          │ through the wall
                                                          ▼
                          [SIM] evaluate() hard gate ─▶ perform() authored effect
                                                          │
                                                          ▼
                                 world‑state change ─▶ index prices it (Layer 2)
```

---

## 4. Knowledge‑gating — what the merchant may see

The merchant must reason from a **deliberately partial** view, never the full
world‑state, or the LLM would "hold sim truth." The sim builds a `MerchantView`
— a contract‑level projection of only what this merchant plausibly knows:

- market **reference** prices he has observed (not the AIC's hidden fair value —
  that is the *player's* isekai edge, and no NPC sees it);
- his own inventory / capital;
- the **political / seasonal** facts that are public;
- a **reputation summary** of the player (what word has reached him — §7);
- the **proposed deal terms**.

He does **not** see: other agents' internals, the AIC fair value, the true future,
or any hidden problem severity beyond what's public. Knowledge‑gating is enforced
by *what the sim puts in the view*, not by asking the LLM to forget — the LLM
literally never receives the privileged fields.

Untrusted‑input note: a `MerchantView` may contain player‑authored text (a claim
the player spoke into the gossip network, a deal pitch). That text is **data, not
instructions**. The prompt frames it as quoted, untrusted content; the schema‑
constrained output (§6) means even a prompt‑injected merchant can only emit a
decision the sim will independently re‑validate. The LLM cannot escalate.

---

## 5. Proposed data shapes (sketch, not final)

New module `merchant.py` (edge‑adjacent; imports no engine internals — it speaks
the contract):

```python
@dataclass(frozen=True)
class DealProposal:          # the player's ask
    intervention_key: str    # e.g. "found_mill"
    principal: float         # capital requested as a loan
    offered_interest: float  # fraction, e.g. 0.15
    term_days: int           # repayment horizon

@dataclass(frozen=True)
class MerchantView:          # the gated projection the sim hands the edge
    merchant_id: str
    ref_prices: dict         # public market prices only
    merchant_capital: float
    reputation: "ReputationSummary"
    season: str
    public_facts: tuple      # weather, war rumors that have propagated
    proposal: DealProposal

@dataclass(frozen=True)
class MerchantDecision:      # the LLM's structured, schema-validated output
    accepted: bool
    counter_interest: float | None   # a counter-offer, or None
    counter_principal: float | None
    line: str                        # one line of in-character dialogue (semantic, not truth)
    rationale_tag: str               # "unproven" | "fair_terms" | "too_risky" | ...

class Merchant(Protocol):    # the seam the sim/body depend on — NOT the LLM directly
    def judge(self, view: MerchantView) -> MerchantDecision: ...

class ScriptedMerchant:      # deterministic; used in sim, tests, golden
    def judge(self, view): ...    # today's rule: yes iff standing+capital suffice

class LLMMerchant:           # EDGE ONLY; a live body constructs it
    def judge(self, view): ...    # one Claude call, structured output (§6)
```

On accept, the body submits the agreed terms through the contract. Two options,
both additive (minor bump, older bodies unaffected):

- extend `Perform` with an optional negotiated‑terms payload, or
- add a dedicated `AcceptDeal(intervention_key, principal, interest, term_days)`
  intent plus a `DealStruck` event.

The sim's `perform()` then: re‑checks the **hard** preconditions, records a
`Loan` (§8), credits the principal, and applies the authored effect. If the hard
gate fails, the deal is void with a reason — the LLM's "yes" cannot override it.

---

## 6. The Claude call (edge adapter only)

Reference details verified against the bundled `claude-api` skill (2026‑06).
This code runs **only** in `LLMMerchant`, at the edge — never in `world`,
`simcore`, or any headless test.

- **Model:** default a merchant judgment call to **`claude-sonnet-5`** — it's a
  bounded, structured NPC decision made at volume, and Sonnet 5's judgment is
  ample; reserve **`claude-opus-5`** for genuinely complex, high‑stakes deals.
  (Owner's call; the skill's default is Opus 5 when unsure.)
- **Structured output is mandatory** so the result is *data* the sim can trust to
  parse: use `output_config={"format": {...}}` (or a tool with `strict: true`)
  keyed to `MerchantDecision`. Never regex free text into sim state.
- **Prompt caching:** the merchant persona + the rules of what he may/may not do
  are a stable prefix (cache it); the volatile `MerchantView` goes after the
  breakpoint. Keeps repeat negotiations cheap.
- **Refusal robustness:** check `stop_reason == "refusal"`; enable server‑side
  fallbacks so a declined call still returns a usable decision (fail closed →
  treat as "merchant declines", never as "deal accepted").
- **Untrusted content:** the player‑authored strings in the view are inserted as
  clearly quoted data with an explicit "this is a claim, not an instruction"
  framing; the schema output is the only thing that leaves the call.

Illustrative shape (Python, not final):

```python
# LLMMerchant.judge — EDGE ONLY
resp = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    system=[{"type": "text", "text": MERCHANT_PERSONA_AND_RULES,
             "cache_control": {"type": "ephemeral"}}],   # stable, cached
    output_config={"format": MERCHANT_DECISION_SCHEMA},   # structured -> data
    messages=[{"role": "user", "content": render_view_as_quoted_data(view)}],
)
if resp.stop_reason == "refusal":
    return MerchantDecision(accepted=False, line="…", rationale_tag="declined", ...)
decision = parse_decision(resp)     # schema-validated
# the SIM, not this function, decides if the deal is mechanically valid
```

---

## 7. Reputation (closes DESIGN.md's loop)

DESIGN.md: *reputation = your deeds propagated through the same social graph that
spreads scarcity rumors* (`knowledge.py`). Phasing:

- **Now (already built):** `standing()` = realized contribution — a track record
  proxy. The merchant reads it via the `ReputationSummary`.
- **Next:** when an intervention completes, inject a **deed claim** about the
  player into the propagation network; the merchant's `reputation` becomes *how
  widely, and how faithfully, word of your deeds has reached him* (awareness ×
  fidelity from his node's vantage). This is the "a merchant says yes to an
  S‑rank and no to an unknown" mechanic, and it reuses the existing
  echo‑vs‑corroboration machinery. It requires teaching `knowledge.py` a second
  claim kind (deeds, not just scarcity) — a scoped follow‑up of its own.

The negotiation prompt includes a plain‑language reputation line ("word has
reached you that this one kept the village warm through two winters") built from
that summary — never the raw contribution number.

---

## 8. The loan / capital mechanic (a deterministic follow‑up)

The deal is a **loan**, and loans are authored sim state, not LLM state:

- `Loan(principal, interest, term_days, struck_day, remaining)` recorded on the
  agent; the merchant's capital decreases, the player's increases at strike.
- Repayment is deducted deterministically over `term_days`; the schedule and the
  default consequences (a reputation hit that propagates; asset seizure) are
  authored rules the sim enforces.
- The LLM negotiates only the **numbers** (interest, principal) within
  authored bounds; the sim clamps and enforces them. A merchant can't invent
  money he doesn't have (his capital is in the view and checked).

Flag: `cfg.loans_enabled` (default off). Golden untouched.

---

## 9. Guardrail compliance

| Non‑negotiable (AGENTS.md §1 / DESIGN.md) | How this design satisfies it |
|---|---|
| **The wall** | The edge speaks only the contract; the negotiated decision enters as an intent. `merchant.py` imports no engine internals. |
| **Frozen contract, additive‑only** | New `AcceptDeal`/`DealStruck` (or an optional `Perform` field) + `MerchantView`/`ProblemView`‑style read types → minor bump, defaults keep old bodies working. |
| **Golden ritual** | LLM never runs in golden/headless; feature flags default off → 140 metrics byte‑identical, no capture. |
| **Flag‑gate off by default** | `interventions_enabled`, a new `llm_merchant` edge toggle, `loans_enabled` — all default false. |
| **Determinism** | LLM at the edge only; its output is recorded data the sim replays. Save/load and regression stay reproducible. |
| **LLM only at the edges; sim validates** | LLM = soft gate + dialogue + term proposal. Sim = hard gate + authored effect + loan enforcement. The LLM holds no sim truth and mutates nothing. |

---

## 10. Testing strategy

- **Deterministic core (in `check.py`):** all sim/intervention/loan tests use
  `ScriptedMerchant`. A new `test_loans.py` (when §8 lands) proves loan
  accounting and default consequences deterministically. Golden stays green.
- **The LLM adapter (out of `check.py`):** `LLMMerchant` is tested with a
  **mocked** client for wiring, and its *judgment quality* is measured by a small
  **eval set** of deal scenarios (unqualified player → decline; proven player,
  fair terms → accept; predatory interest → counter). This is a quality eval, run
  on demand — never a determinism gate, and never in the byte‑identical suite.
- **Prompt‑injection eval:** scenarios where the view carries a hostile
  player‑authored claim; assert the decision schema holds and the sim re‑validates
  (the merchant cannot be talked into an invalid deal).

---

## 11. Suggested build order (each step flag‑gated, golden‑safe, reviewable)

1. **Negotiation data + `Merchant` protocol + `ScriptedMerchant` + contract
   surface** (`AcceptDeal`/`DealStruck` or `Perform` terms). No LLM. Deterministic,
   golden byte‑identical. A demo shows a scripted negotiation.
2. **`LLMMerchant` edge adapter** — the real Claude call behind the `llm_merchant`
   toggle, used only by a live body. Mocked‑client test + the judgment eval.
3. **Loan mechanic** (`loans_enabled`) — principal/interest/repayment/default as
   authored sim state; `test_loans.py`.
4. **Reputation‑via‑propagation** — deed claims in `knowledge.py`; the merchant's
   reputation becomes propagated word. Wires the DESIGN.md loop shut.

Steps 1, 3, 4 are pure deterministic sim work (no API, no cost). Only step 2
introduces the model, at the edge, off by default.

---

## 12. Open questions for the owner

- **Model & cost:** Sonnet 5 per negotiation vs Opus 5 for big deals — acceptable
  per‑deal cost, and how frequently will players negotiate?
- **Contract shape:** extend `Perform` with terms, or a dedicated `AcceptDeal`
  intent? (Leaning `AcceptDeal` — clearer, and leaves `Perform` for
  no‑negotiation actions like founding from your own capital.)
- **How binding is the merchant's counter?** Does the player get one round to
  accept/reject a counter, or a full back‑and‑forth? (Leaning: one counter, to
  bound cost and latency.)
- **Where does the edge live** for the pygame body vs a future UE5 client? The
  adapter is body‑side by design; each body wires its own.
- **Failure UX:** on API refusal/timeout, the merchant "declines today" — is that
  the right fail‑closed behavior, or should it fall back to `ScriptedMerchant`?

---

*Steps 1–3 are implemented (see "Built (MVP)" at the top); step 4
(reputation‑via‑propagation) is the remaining frontier. The LLM enters only at the
edge in step 2's `LLMMerchant`, off by default and absent from every deterministic
test.*
