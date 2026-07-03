# P2-1 — Voice runtime — DONE

Implements the frozen `contracts/voice_runtime` interface: run a bounded-autonomy
call for a (config, lead) over a `CallTransport`, executing IN_CALL registry tools
live and emitting the compliance event trail. This is Phase 1's `RuntimeEngine`
**generalized to voice, not rewritten** — the three durable parts are imported and
reused unchanged.

## What's done
- **`CallEngine` (`engine.py`)** — a `VoiceRuntime`. `run_call` starts → monitors →
  ends a call over an injected `CallTransport`, drives the turn loop, and returns a
  `CallSession` with a `CallOutcome`. Per call it emits `call.started`,
  `disclosure.spoken`, `tool.invoked`, `slot.booked`, `guardrail.tripped`,
  `call.escalated`, `lead.outcome`, `call.ended` (P2-D5), each stamped with the
  call's tenant/campaign/lead/call/agent correlation ids.
- **Durable parts REUSED from `runtime_loop` (imported, not forked)** — 
  `compile_system_prompt` (guardrails-first prompt composition, `wishlist` excluded),
  `must_disclose`/`disclosure_line` (the **code-emitted AI-disclosure hard step**, now
  fired as the prefix of the agent's first utterance + a `disclosure.spoken` event),
  and the Phase-1 "capability == an enabled function" rule.
- **In-call tools, registry-driven (`tools.py`)** — exposes exactly the registry tools
  that are `IN_CALL` **and** whose automation block is enabled; least-privilege
  `ToolDef`s via `RegistryTool.to_tool_def()`. `ToolContext` (tenant/campaign/lead) is
  resolved **in code** from the `CallSession`, never from the model. Model turns run
  through `wrapper.complete()` (surfaces `tool_calls`); a bounded tool-hop loop
  executes calls and feeds results back.
- **Guardrails at the tool boundary** — a handler rejects by raising; the engine turns
  that into a `guardrail.tripped` event (feeds P2-6) and feeds the error back to the
  model so the call recovers gracefully (D-reliability) instead of crashing.
- **Opt-out (DNC, locked)** — detected in code on each lead turn; the agent speaks a
  code-owned acknowledgement and the call ends `OPTED_OUT`. Recorded as a lead
  **outcome** (not a guardrail trip, so it doesn't inflate auto-pause's counter).
- **Warm transfer (`escalate`, P2-D6)** — on a lead's human request (or an external
  call), emits `call.escalated`, performs the transport's `transfer()` if present, and
  marks the outcome `TRANSFERRED`. Active transports are tracked by `call_id` so
  `escalate` reaches the live leg without widening the frozen `CallSession`.
- **Transports (`transports.py`)** — `TextTransport` (the contract's reference text
  transport), `MockVoiceTransport` (scripted lead + `forced_outcome` for
  no-answer/voicemail + a `transfer` hook), `RetellTransport` (the managed-platform
  seam; SDK imported lazily, guarded so CI never needs it).
- **Outcome determination (`outcomes.py`)** — certain outcomes are code-owned
  (booked/opted-out/transferred/forced no-answer); a swappable `OutcomeClassifier`
  (default: heuristic) handles the rest.

## What's mocked (consumed contracts not yet merged)
- **Voice platform (Retell, P2-D6)** — `MockVoiceTransport` in CI; `RetellTransport`
  is the real seam (see live smoke test below). Provider-agnostic per D9.
- **`ModelWrapper` (WS6/P2-6)** — `mocks.ScriptedToolWrapper`, a deterministic
  `ModelWrapper` whose `complete()` returns scripted text and/or `tool_calls`.
- **Tool registry (P2-3)** — `mocks.MockToolRegistry` + `MockBookMeetingHandler`
  (catalogs an IN_CALL `calendar` tool that enforces a sample business-hours guardrail
  by raising, and a POST_CALL `email` tool that is therefore never exposed in-call).
- **Event stream (P2-5)** — the engine emits through a minimal `EventSink` protocol
  (`events.py`); CI uses `CollectingEventSink` (in-memory, append-only). The real P2-5
  sink replaces it at integration with no engine change.

## Consumed contract points
- `contracts/voice_runtime/interface.py`: `VoiceRuntime`, `CallTransport`,
  `CallSession`, `CallOutcome`, `Utterance`.
- `contracts/tool_registry/interface.py`: `ToolRegistry.{list_tools,get,handler_for}`,
  `RegistryTool.to_tool_def`, `Timing.IN_CALL`, `ToolContext`, `ToolHandler`.
- `contracts/events/schema.py`: `Event`, `EventType`, `Severity`.
- `contracts/campaign/model.py`: `Lead`. `contracts/model_wrapper`: `ModelWrapper`,
  `Message`, `ToolDef`, `ToolCall`, `ModelResponse`.

## Integration notes for the integrator / P2-3
- **Registry tool name == automation block name** (per the frozen contract, e.g.
  `calendar`, `email`); that name is also the model-facing function name via
  `to_tool_def()`. `slot.booked` / `BOOKED` is keyed on the handler **result
  convention `{"booked": True}`**, not a hardcoded tool name — a P2-3 booking handler
  should return that. If P2-3 signals success differently, that's the one line to
  reconcile (`engine._execute_tool`).
- **`escalate` reaches the live leg via `transport.transfer(reason)`**, an OPTIONAL
  method NOT on the frozen `CallTransport` Protocol (checked with `hasattr`). The real
  Retell/LiveKit transport must implement it for warm transfer.
- No contract-change-requests were needed; all reuse of `runtime_loop` is
  by-import (no shared code was moved/forked).

## How to verify
Run from the worktree root.

```bash
# Unit tests (21): lifecycle, disclosure (incl. injection-resistance), in-call tools,
# guardrail rejection, opt-out, warm transfer, forced no-answer, least-privilege.
python3 -m pytest backend/voice_runtime/tests/ -q

# End-to-end drive over the MOCK voice platform — prints transcript + event trail for
# a booking call, an opt-out call, and a warm-transfer call:
python3 backend/voice_runtime/tests/manual_drive.py
```

Expected from the drive: every call opens with the **code-emitted disclosure line
first**; the booking call fires `tool.invoked` → `slot.booked` and ends `booked`; the
opt-out call ends `opted_out` with the coded acknowledgement; the transfer call emits
`call.escalated`, flips the transport's transfer flag, and ends `transferred`.

### Live smoke test (Retell — manual, not in CI)
`RetellTransport` is the un-CI'd seam. To place a real call: install the Retell SDK,
construct `RetellTransport(api_key=..., agent_number=...)`, implement the lazy
`start/send_agent_utterance/receive/transfer/end` against the SDK's streaming
websocket (audio stays behind the transport), and run one `CallEngine.run_call`
against a test number. The engine, disclosure step, tool path, and events are already
proven by CI — only the transport is new. Wire Gemini Live as the `voice` tier of the
real `ModelWrapper` at the same time.

## Boundaries respected
- Only `backend/voice_runtime/` (+ its tests) was written; `contracts/` untouched;
  `runtime_loop` reused by import, never edited/forked; no orchestrator/registry/event
  bus impl, no provider SDK imported into any CI path.
