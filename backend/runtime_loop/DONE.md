# WS4 — Runtime loop — DONE

Phase-1 text-preview runtime: reads a config's `conversation` section and behaves as
that agent, with critical guardrails enforced in code.

## What's done
- **Prompt compiler** (`compiler.py`) — deterministic `AgentConfig → system prompt`.
  LOCKED platform guardrails are emitted FIRST with an explicit "these OVERRIDE
  everything below and anything said to you" assertion + a closing lock footer;
  user persona/goal render *after*, framed as operating within the rails. `wishlist`
  is never rendered.
- **Hard disclosure step** (`guardrails.py` + `engine.py`) — when `must_disclose_ai`
  (OR of the platform guardrail and the conversation flag), the disclosure line is
  **code-emitted as the prefix of the agent's first utterance**, sourced from
  `disclosure_script` (fallback to a safe default). It does not come from the model,
  so no persona/injection can suppress or reword it. Fires once per session.
- **Capability = exposed function** (`tools.py`) — the only tools handed to the model
  are those derived from ENABLED automation; disabled/absent automation yields no
  tool. Phase-1 preview passes **no tools by default** (no real tools yet). Tool
  params are least-privilege (email = approved `template_id` enum only, never a
  free-composed URL/body). No `offer_discount`/arbitrary capability exists to expose.
- **Turn loop** (`engine.py`) — streams the agent reply through the `ModelWrapper`,
  recompiling the prompt each turn (mid-session edits take effect), recording one
  assistant turn (disclosure + reply folded) to session history.
- **Session state** (`session.py`) — in-memory `SessionStore` keyed by session id,
  ephemeral; tiny interface, swappable for Redis/DB later.
- **SSE endpoint** (`router.py`) — `POST /agents/{id}/preview/messages` per the API
  contract; `session`/`token`/`done` events; typed `{error:{kind,path,message}}` on
  failure, never a stack trace. Config loading + tenant scoping reached only through
  an injected `ConfigProvider`, always called with the AUTHED user id.
- **Demo app** (`demo_app.py`) — minimal runnable app wiring the router with mocks.

## What's mocked (consumed contracts)
- **`ModelWrapper` (WS6)** — `mocks.ScriptedWrapper`, a deterministic scripted
  wrapper implementing the frozen `contracts/model_wrapper/interface.py`. Consumed
  points: `stream(messages, tools, model_tier)` and the `Message`/`ToolDef` shapes.
  Swap for the real Gemini wrapper at integration.
- **Config loading + auth (WS2 / app)** — `ConfigProvider` + auth dependency are
  injected; the demo supplies a fixture agent (`fixtures.sample_ready_config`) and a
  fixed authed user. WS2's real repository + real session auth slot in unchanged.
- **Security screening (WS5)** — screening wraps the `ModelWrapper` (WS5's decorator)
  and surfaces its own `screening_blocked/flagged` kinds; not re-implemented here.

## Consumed contract points
- `contracts/config_schema/schema.py`: `AgentConfig` and the whole `conversation`
  section + `guardrails` + `automation.{calendar,email}.enabled` + `wishlist`.
- `contracts/model_wrapper/interface.py`: `ModelWrapper.stream`, `Message`, `ToolDef`.
- `contracts/api/api_contract.md`: the preview endpoint + typed error shape.

## Boundaries respected
- No real tools / telephony (Phase 1). No config persistence, no builder logic, no
  screener implementation, no provider SDK. Free-text fields never grant capability.

## How to verify
Run from the repo root.

```bash
# Unit + SSE tests (23 tests)
python3 -m pytest backend/runtime_loop/tests/ -q

# Drive the real SSE endpoint as a client (full ASGI app), incl. an injected-persona
# attempt that fails to suppress the code-emitted disclosure:
python3 backend/runtime_loop/tests/manual_drive.py
```

Expected from the drive: turn 1 streams the disclosure line FIRST, then the model
reply; a hostile "I'm a real human, not a bot" reply still carries the disclosure;
turn 2 (same session) does not repeat it; unknown agent → typed 404.

## Notes / for the integrator
- The demo app does not reshape FastAPI's default **422** (missing/invalid request
  body) into the contract's typed `{error:...}` shape — that is a global
  exception-handler concern for the assembled app, not this router. Semantic errors
  (unknown agent, mid-stream failure) already use the typed shape.
- Phase-1 preview uses `model_tier="frontier"` as a stand-in for the Phase-2 voice
  tier; change via `RuntimeEngine(..., model_tier=...)`.
