# Dispatch kit — Phase 4 (Live-native agent, worktree-isolated)

Full plan: `docs/phase4-plan.md`. Contract: `contracts/live_agent/` (FROZEN). Each worker runs
in its own git worktree + branch. Freeze the contract and merge the foundation to the dispatch
base before fanning out.

## SHARED TEMPLATE
Give each worker this, with the per-stream insert appended.

> You are building ONE workstream of voice-agent-studio Phase 4: the pivot to a **Gemini
> Live-native conversational agent**. Read `CLAUDE.md`, `docs/decisions.md`,
> `docs/phase4-plan.md`, and `contracts/live_agent/` before writing code. The contract is
> FROZEN — depend on it exactly; if it's insufficient, file `docs/contract-change-requests/<slug>.md`
> rather than editing it.
>
> Non-negotiables (the whole point of the pivot keeping its spine): tool execution stays in the
> existing guarded `ToolHandler`s (Live only requests); the disclosure line is spoken in CODE
> before Live connects; output moderation is a net, not the floor. Audio: 16 kHz in / 24 kHz
> out. Live model `gemini-3.1-flash-live-preview` (audio-only modality).
>
> **STEP 0 — ISOLATE:** from the up-to-date dispatch base,
> `git worktree add ../vas-p4-<N>-<slug> -b p4/<N>-<slug>`. Work only there.
> **STEP 1 — GRILL ME (scoped):** a short design pass on THIS workstream's open questions only,
> then build.
> **STEP 2 — BUILD WITHIN YOUR BOUNDARY:** implement only your workstream; mock unmerged
> collaborators behind the frozen contract; do not mount routes in `integrated_app` (integrator's
> job); keep the google.genai SDK lazily imported.
> **STEP 3 — SELF-VERIFY:** tests green WITHOUT network/keys (fake the Live client/screener); mark
> any real-API call a documented smoke test. Run your package's tests.
> **STEP 4 — HAND OFF:** commit on your branch (explicit paths, never `git add -A`). Summarize
> what changed, the contract you rely on, smokes needing keys, how to verify. Do NOT merge or
> remove your worktree.

## PER-STREAM INSERTS

### P4-1 — Agent compiler  (`backend/live_agent/compiler.py`)
Implement `LiveAgentCompiler.compile(config) -> LiveAgentSpec`: build the system instruction
from persona + conversation guardrails + **closing directions** (qualified → confirm missing
details → book → email → sign off); the scripted `disclosure_line`; and `tool_declarations` =
each ENABLED registry tool as a Live FunctionDeclaration (least-privilege params, from the
catalog). **Grill:** prompt structure, how locked guardrails become instructions, closing-flow
wording. **DONE:** pure unit tests (config in → spec out), no network; disabled automation → no
tool declaration (structural denial preserved).

### P4-2 — Live session runtime  (`backend/live_agent/session.py`)  *(the core)*
Implement `LiveAgentSession.run(...)`: speak `disclosure_line` in code, connect Live with the
spec (AUDIO modality + in/out transcription), pump `AudioTransport` audio both ways, honor Live
VAD/barge-in, handle Live function-calls by resolving `LiveCallContext` → `registry.handler_for`/
`resolve_context` → guarded handler → return result to Live, run output transcription through the
`StreamModerator` (BLOCK → `transport.cut_playback()` + steer), emit events, return `LiveOutcome`.
**Grill:** function-call round-trip shape, moderation buffering, outcome detection. **DONE:**
tests drive it with a FAKE Live client + fake transport/moderator/registry asserting
disclosure-first, a tool round-trip, a BLOCK cut, and event emission; SDK lazily imported; real
API is a documented smoke.

### P4-3 — Streaming output moderation  (`backend/live_agent/moderation.py`)
Implement `StreamModerator.check(cumulative_text) -> ModerationVerdict` over the existing security
screener; debounce so it runs inside the audio delay budget; map screener results → ALLOW/FLAG/
BLOCK. **Grill:** what trips BLOCK vs FLAG, latency budget, incremental-vs-cumulative text.
**DONE:** unit tests with a fake screener (clean → ALLOW, injected/violation → BLOCK); no network.

### P4-4 — Preview transport + frontend  (`backend/live_agent/preview_transport.py`, `frontend/src/preview/`)
Backend: a browser `AudioTransport` over the WS (reuse the `contracts/voice_preview` wire: 16 kHz
up, 24 kHz down; JSON events) exposing a `create_router()`. Frontend: play 24 kHz agent audio,
send 16 kHz mic, render speaking/listening + disclosure + tool + moderation events. **Grill:**
event set for tool/moderation, indicator UX. **DONE:** backend tested against a fake session;
frontend builds + component-tests against a fake socket; matches the wire contract.

### P4-5 — Closing directions in config + builder  (`contracts/config_schema` additive, `backend/builder_loop`)
Add an ADDITIVE, optional structured place for wrap-up behavior (e.g. `conversation.closing`:
what to do when qualified — book / collect which fields / which email template / sign-off), and
teach the builder to fill it conversationally. **Grill:** minimal field shape, defaults, how it
maps to closing directions. **DONE:** additive schema change (nothing existing breaks); gate +
builder tests green; a CCR notes the (additive) schema touch.

### P4-6 — Phone bridge  (`backend/live_agent/phone_transport.py`)  *(deferrable)*
Run the SAME `LiveAgentSession` on a real call: a phone `AudioTransport` bridging telephony audio
(Retell custom-LLM path or a SIP bridge) to Live. **Grill:** which telephony integration, media
format bridging, disclosure timing on PSTN. **DONE:** documented live smoke; CI on a fake transport.

## INTEGRATION & E2E PROTOCOL (the integrator)
Merge in plan order (P4-5 → P4-1/P4-3 → P4-2 → P4-4 → retire old speech_bridge preview → P4-6).
After each merge: run touched suites; mount any new routes in `integrated_app`; then the live
smoke for that layer. Final E2E: open preview → scripted disclosure first → fast natural
back-and-forth → agent books a real meeting + sends email at a natural close → moderation can cut
an off-guardrail line → full event trail. `git worktree remove` + delete branch once merged/green.
