# Dispatch kit — 6 parallel workstream prompts

How to use:
1. **Freeze contracts first.** Ratify `contracts/` and commit as frozen. Do NOT
   dispatch until this is done — un-frozen contracts + 6 agents = merge hell (D14).
2. For each workstream, paste **the shared template** with that stream's **insert**
   filled in, into a fresh Claude Code session opened in this repo.
3. Kickoff **grills are sequential** — you must be present to answer. Do them one at
   a time, or tell the agent to proceed on its recommendations if you're unavailable.
4. **Integrate in dependency order** (see bottom): 6 → 5 → 2 → {3,4} → 1, with E2E
   at each edge. Agents do NOT merge to main themselves.

---

## SHARED TEMPLATE

```
You are the owner of Workstream <N> — <NAME> — for the voice-agent-studio project.

READ FIRST (in this order), then confirm you've internalized them:
  - README.md, CLAUDE.md, docs/decisions.md   (D0–D14 are SETTLED — do not reopen)
  - contracts/  (READ-ONLY for you — see the rule below)
  - your workstream README: <WS_README_PATH>

CONTRACTS ARE FROZEN AND READ-ONLY. Do not edit anything under contracts/. If you
believe a contract is wrong or insufficient for your work, STOP: write a change
request to docs/contract-change-requests/ws<N>.md describing the problem and your
proposed fix, and surface it to me. Do NOT work around it, fork it, or edit it
silently — a silent contract change breaks every other stream.

STEP 1 — GRILL ME (scoped, tight). Before writing code, run a grilling session
(the grilling skill) on the INTERNAL decisions of THIS workstream only — libraries,
module structure, edge cases within your boundary. Do NOT grill the settled D0–D14
architecture. One question at a time, each with your recommended answer. Suggested
topics: <GRILL_TOPICS>. If I say "you decide," take your recommendation and move on.

STEP 2 — ISOLATE (worktree + branch). From the main repo root, on an up-to-date
main, create your own worktree so no other worker shares your files:
    git worktree add ../vas-ws-<N>-<slug> -b ws/<N>-<slug>
Then cd ../vas-ws-<N>-<slug> and do ALL work there. The integrator removes the
worktree after merge.

STEP 3 — BUILD WITHIN YOUR BOUNDARY. Implement ONLY this workstream's
responsibility; respect the "do NOT" boundaries in your README. Reach other streams
ONLY through the frozen contracts, and MOCK anything not yet merged (e.g. a fake
ModelWrapper, a fixture config). Match the repo's conventions and altitude.

STEP 4 — SELF-VERIFY (definition of done): <DONE_CRITERIA>. Deliver:
  - automated tests that pass (show the run),
  - where a runnable surface exists, prove behavior with the /verify skill,
  - a DONE.md in your workstream dir: what's done, what's mocked, and the EXACT
    commands to verify. Report failures honestly — a red test stated plainly beats
    a green one that lies.

STEP 5 — HAND OFF. Commit. Summarize what changed, which contract points you
consumed, and what you mocked. STOP — do not merge to main. The integrator merges
in dependency order and runs E2E.
```

---

## PER-STREAM INSERTS

### WS1 — Frontend  (`frontend/README.md`)
- **GRILL_TOPICS:** state management + whether patch application is optimistic or
  server-authoritative; how the SSE `token`/`patch`/`notice` streams interleave in
  the UI; the live-materialization UX of the Agent panel; component library.
- **DONE_CRITERIA:** renders a fixture `AgentConfig` + `FIELD_POLICY` (lock badges,
  "🔒 Set by platform" section); chat pane consumes a mock SSE and materializes
  fields on `patch`; manual edit of an open field calls `PATCH /agents/{id}/fields`;
  preview chat surface exists; tests for rendering + stream interleaving.

### WS2 — Config gate + persistence  (`backend/config_gate/README.md`)
- **GRILL_TOPICS:** dotted-path get/set into the schema; versioning storage
  (snapshots vs diffs) + revert; concurrency on simultaneous edits; the typed error
  taxonomy; where free-text screening is *called* (delegates to WS5, mock it).
- **DONE_CRITERIA:** given a config + `FIELD_POLICY`, accepts valid open/default
  patches, rejects locked-path / invalid-type / forged-identity with the contract's
  typed error shape; versioning + revert; tenant scoping enforced in code;
  completeness eval flips status→READY; unit tests per rejection kind.

### WS3 — Builder loop  (`backend/builder_loop/README.md`)
- **GRILL_TOPICS:** tool-call granularity (`set_field` vs coarser ops); the
  goal-seeking interviewer prompt strategy + how completeness is tracked/surfaced;
  bounded-retry policy on validation errors; conversation-state persistence.
- **DONE_CRITERIA:** with a mock ModelWrapper + the real gate, a scripted
  conversation drives a config empty→READY; the four-way triage routes all four
  categories correctly (incl. wishlist quarantine); a gate rejection becomes a
  conversational `notice`; deterministic tests using a scripted mock model.

### WS4 — Runtime loop  (`backend/runtime_loop/README.md`)
- **GRILL_TOPICS:** how a config compiles into a runtime system prompt; precedence
  composition (locked guardrails outrank user persona text); where hard-coded
  guardrail steps live (disclosure); preview session state.
- **DONE_CRITERIA:** given a config, the text preview responds in persona/goal; the
  AI-disclosure step fires when `must_disclose_ai`; the agent exposes no capability
  beyond declared functions; `wishlist` never enters instructions; tests incl. an
  injected-persona attempt that fails to override a locked guardrail.

### WS5 — Security / screening  (`backend/security/README.md`)
- **GRILL_TOPICS:** Model Armor vs Lakera for v1; sync vs async screening + latency
  budget; fail-open vs fail-closed (recommend fail-closed for locked-guardrail
  domains); what strings count as "locked-guardrail domain" for hard-block; logging.
- **DONE_CRITERIA:** a decorator over `ModelWrapper` screens every in/out; blocks a
  known prompt-injection sample and a malicious URL; hard-blocks free-text touching
  a locked-guardrail domain, accept-but-flags merely-odd content; documented
  fail-closed behavior; tests with fixture attack prompts. (Screener API may be
  mocked in CI; live-test manually.)

### WS6 — Wrapper impl (Gemini)  (`backend/wrapper_impl/README.md`)
- **GRILL_TOPICS:** mapping schema-constrained tool-calling to Gemini's function-
  calling / response schema; streaming impl; tier→model-id map (verify IDs in AI
  Studio console); retry/timeout; AI-Studio-key-via-env now, Vertex-swap seam.
- **DONE_CRITERIA:** `complete()` + `stream()` implement the interface and return
  correct shapes; a schema-constrained tool-call round-trips; tier mapping works;
  key read from env (never committed); a smoke test (mockable in CI, live-tested
  manually). Provider SDK imported ONLY here.

---

## INTEGRATION & E2E PROTOCOL  (the integrator — you, or one dedicated session)

Agents don't merge; you do, in **dependency order**, running the E2E checks whose
dependencies just became satisfied:

| Merge step | Bring in | E2E checks now runnable |
|---|---|---|
| 1 | **WS6** wrapper | Live smoke: a real Gemini tool-call round-trips through the interface. |
| 2 | **WS5** security | An injection sample + malicious URL are blocked through the real wrapper. |
| 3 | **WS2** gate | Create agent → patch open field (accepted) → patch locked path (rejected, typed error) → revert a version. |
| 4 | **WS3** builder + **WS4** runtime | Chat drives a config empty→READY (builder+gate+wrapper); talk to the built agent in preview; disclosure fires; injected persona can't defeat a locked guardrail. |
| 5 | **WS1** frontend | Full loop in the browser: build via chat, watch the panel materialize, hand-edit an open field, open preview and talk to the agent. |

At each step: if the merge was supposed to resolve a dependency (e.g. builder's
mock ModelWrapper → real WS6), confirm the mock is removed and the real path passes
the E2E check before moving on. A red check stops the line — fix before the next merge.
```
