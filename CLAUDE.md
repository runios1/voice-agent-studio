# CLAUDE.md — voice-agent-studio

Guidance for anyone (human or agent) working in this repo. This is the full
product picture; `docs/decisions.md` is the terse decision log; each workstream
`README.md` is the local contract. When these conflict, `docs/decisions.md` wins,
then this file, then the workstream READMEs.

---

## 1. What we're building

A platform where a user **describes an agent in natural language by chatting with
a builder AI**, and the system **generates a voice-AI SDR assistant** from that
conversation. The assistant does two kinds of work:

- **Live back-and-forth** (calling a lead, qualifying, handling objections) — the
  conversational half.
- **Deterministic automation** (read a calendar, hold a slot, send a confirmation,
  write to CRM) — the tool/workflow half.

The core business idea: **the provider (you) defines the base characteristics and
guardrails; the end user gets granular control of the details within those rails.**
That split is only meaningful because this is a **vertical** product (outbound
sales / lead qualification) where the platform's locked guardrails — AI disclosure,
Do-Not-Call, calling hours, no out-of-range promises — are genuinely valuable and
specific. A horizontal "build any agent" product would have an empty guardrail
layer and no provider value (D7).

## 2. Vision & phasing

Phases are **incremental construction, not demos** (D0.1). Always keep the full
picture in mind and flag any choice that would cap a future capability.

- **Phase 1 (this scaffold): the skeleton, de-risked (D1).** The website, the user
  UX, and a working chat→config **generation pipe** — proven to run end-to-end on
  the right models with no random errors. A built agent can be tested in a **text
  preview**. No real telephony, no real tools yet — but the architecture slots them
  in without a rewrite.
- **Phase 2: tooling + bounded autonomy + dashboard** (full plan:
  `docs/phase2-plan.md`, decisions P2-D1…P2-D6). Real voice (managed platform +
  Gemini Live) with in-call functions; **bounded autonomy** (human authorizes a
  campaign, agent runs it unsupervised with a 4-layer kill switch); a **platform
  tool registry** + per-tenant OAuth (guardrails at the tool boundary); async
  post-call workflows (pulled in from the old Phase 3); and a **dashboard** over a
  **structured event stream** that also powers auto-pause and the compliance audit
  log. Runtime provider stays behind an interface (Retell → LiveKit swap).

## 3. The agent model (the keystone)

An agent is a **structured config object with free-text pockets** — never a prompt
blob (D3). The schema (`contracts/config_schema/schema.py`) is the single source of
truth that (a) constrains generation, (b) drives validation, (c) renders the UI,
(d) is executed at runtime.

- **Two control layers** (D4): **platform** (you) sets locked guardrails + suggested
  defaults; **user** fills the open details. Every field is `locked` / `default` /
  `open`, encoded in `contracts/config_schema/field_policy.py` (data vs. policy kept
  separate on purpose).
- **Timing split** (D6): the schema has a `conversation` section (guardrails
  constrain what the agent may **say**) and an `automation` section (guardrails
  constrain what it may **do**).
- **Completeness model** (D12): the `required_for_ready` fields *are* the target the
  builder interviews toward, and define when an agent is deploy-ready.
- **Extensibility + four-way triage** (D13): user-volunteered detail is triaged —
  harmful → refused; supported capability → structured field; harmless flavor →
  free-text pocket; **capability we don't offer → acknowledged and quarantined to
  `wishlist`, kept out of everything the agent acts on.** A live agent must never be
  configured to promise what it can't deliver.

## 4. Architecture — two loops over one config

The app has **two loops that share one config artifact**, running in opposite
directions:

- **Builder loop** (`backend/builder_loop`, D5, D12) — a chat that **edits** the
  config. A **goal-seeking interviewer**: knows the completeness model, guides the
  user to fill gaps, absorbs anything volunteered out of order, never gates. Emits
  changes as **structured tool-call patches** (not whole-config regeneration), each
  routed through the config gate.
- **Runtime loop** (`backend/runtime_loop`, D12) — a chat that **executes** the
  config. Phase 1 = text preview; Phase 2 = voice. This is the piece you keep.

### The UX that ties them together (D-UX, D11)
**Chat-first with progressive disclosure.** A single, full-width, ChatGPT-feeling
chat is the primary and *only required* surface — the builder confirms progress
conversationally, inline, never via a filling form. Alongside it, a **collapsible
Agent panel** shows the agent's identity **materializing live**: a user field
appears only once an answer has decided it (no empty selectors sitting ahead of the
question). Locked platform guardrails are shown up front in a "🔒 Set by platform"
section. `open`/`default` fields are manually editable; manual edits and chat edits
mutate the same config and stay in sync.

## 5. Security model — the part to get right (D-security)

You cannot enumerate every bad thing a user or an injection might attempt. So don't
try: **remove the capability and the knowledge to do harm, then screen for the
rest.** Enforcement lives at a **source-agnostic, server-side config gate**
(`backend/config_gate`) — every mutation (builder patch, manual edit, or forged
request) passes the *same* checks. The LLM's triage is UX politeness; the gate is
the security boundary.

**Defense in depth, inner → outer:**
1. **Can't-do-it (structural):** least-privilege function params; links only from an
   **allowlist** (no free-composed URLs); no `offer_discount` function above the cap.
   The runtime enforces critical guardrails (AI disclosure, DNC) **in code, as hard
   runtime steps** — not as prompt text a malicious persona could override.
2. **Can't-know-it (structural):** **least context** — secrets, infra detail, other
   tenants' data never enter a model's window; **server-side tenant isolation** (data
   tools scoped by code, never by a prompt instruction). If the model doesn't know
   it, no injection can leak it.
3. **Screening (probabilistic):** every model in/out is wrapped with an off-the-shelf
   screener — **Google Model Armor** (v1: provider-agnostic REST; prompt-injection /
   jailbreak + malicious-URL in *and* out + PII). Alternative: **Lakera Guard**.
   **This is the layer allowed to fail** — never the one you rely on; it's
   probabilistic and bypassable (OWASP LLM01).

## 6. Reliability — "no random errors" (D-reliability)

**Constrain → validate → gracefully recover.** Use the provider's **schema-
constrained tool-calling** so malformed output is *structurally impossible* at the
source. Validate each patch against the schema + `FIELD_POLICY`. On a semantic slip
(locked path, bad value): bounded auto-retry feeding the error back to the model;
if it still fails, the user sees a calm "I didn't quite catch that — rephrase?" —
**never a stack trace.** The config schema is the single source of truth across
generation, validation, rendering, and runtime.

## 7. Tech stack & models

- **Frontend:** React. **Backend:** Python / FastAPI (keeps backend + future voice
  runtime one language). **DB:** Postgres, config stored as `jsonb` (schema evolves
  fast). **Streaming:** SSE for both chat surfaces. (D10)
- **Model wrapper (D8/D9):** every model call goes through `ModelWrapper`
  (`contracts/model_wrapper`). Provider SDKs imported ONLY in `backend/wrapper_impl`.
  Builder-LLM and voice-LLM may be different providers.
- **Model picks (verify exact IDs in the AI Studio console — preview names churn):**
  - Builder brain (`frontier`): **Gemini 3.1 Pro**.
  - Fast helpers (`fast`): **Gemini 3.5 Flash**.
  - Voice runtime (`voice`, Phase 2): **Gemini 3.1 Flash Live**.
  - The builder model is "whatever frontier model you can start on today, behind the
    wrapper" — low-stakes and swappable (D9).
- **Access path:** start on a Google AI Studio API key; migrate to **Vertex AI** for
  production behind the wrapper (a config change, not a rewrite).

## 8. Parallelization — how to build this (D14)

Parallel work is earned by **frozen contracts**. Tiny critical path, wide fan-out.

**Critical path (do first, blocks everything — keep it tiny):**
1. `contracts/config_schema` — the central artifact.
2. `contracts/api` — frontend ⇄ backend seam.
3. `contracts/model_wrapper` — the provider-agnostic interface.

**Fan-out (six streams, independent once contracts are frozen):**

| # | Workstream | Path | Depends only on |
|---|---|---|---|
| 1 | Frontend | `frontend/` | api |
| 2 | Config gate + persistence | `backend/config_gate/` | config_schema |
| 3 | Builder loop | `backend/builder_loop/` | config_schema + wrapper |
| 4 | Runtime loop | `backend/runtime_loop/` | config_schema + wrapper |
| 5 | Security / screening | `backend/security/` | wrapper |
| 6 | Wrapper impl (Gemini) | `backend/wrapper_impl/` | wrapper |

**Rule:** anything two workstreams must agree on belongs in `contracts/`. Changing a
contract is a cross-cutting event — announce it. Each workstream README lists its
**boundaries** (what NOT to do) precisely so parallel streams don't collide.

**Dispatching the work:** `docs/workstream-prompts.md` is the dispatch kit — a
shared prompt template + per-stream inserts + the integration/E2E protocol
(merge order **6 → 5 → 2 → {3,4} → 1**). Contracts must be **frozen** before
dispatch. A stream that finds a contract insufficient files a
`docs/contract-change-requests/` entry rather than editing the contract.

## 9. Conventions

- Never commit secrets; never let secrets/infra detail reach a model's context.
- Never trust client-supplied identity; scope every query to the authed user in code.
- A field's presence in the schema implies the runtime can honor it — don't add
  fields for capabilities that don't exist (use `wishlist`).
- Locks/validation are enforced server-side; the UI only *reflects* them for UX.
