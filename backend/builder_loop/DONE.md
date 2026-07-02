# WS3 — Builder loop — DONE

Chat that **edits** the config: a goal-seeking interviewer that emits structured
patches, runs the four-way triage, and routes every mutation through the config
gate. Built against the frozen contracts (`config_schema`, `model_wrapper`); the
gate (WS2) and a concrete `ModelWrapper` (WS6) are mocked per the dispatch protocol.

## What's done

| Piece | File |
|---|---|
| Public surface (`BuilderLoop`, events, seams) | `__init__.py` |
| Streamed events (`token`/`patch`/`notice`) matching the API SSE shape | `events.py` |
| Config-gate **seam** the builder consumes (`Gate` Protocol, `Patch`, `GateAccepted`, `GateError`) + dotted-path helpers | `gate.py` |
| Completeness model (deterministic gaps from `FIELD_POLICY`, status eval) | `completeness.py` |
| Structured tool-calls the LLM may emit | `tools.py` |
| Goal-seeking interviewer system prompt (gaps + guardrails + four-way triage) | `interviewer.py` |
| Conversation state behind a `SessionStore` Protocol (in-memory impl) | `session.py` |
| Turn orchestration: model → gate → events, with bounded retry | `loop.py` |
| Test doubles: `FakeGate`, `ScriptedModel` | `testing.py` |
| Tests | `tests/` |

## Grill decisions (recommendations taken; user was away)
1. **Tool granularity:** hybrid — generic `set_field` for scalars, `add_objection`
   / `add_qualification_criterion` for list items, `push_to_wishlist` for the
   unsupported-capability triage bucket, `clear_field` to remove. Each maps to one
   gate patch; list-append helpers read-modify-write the whole list so the gate's
   `{path, value}` set-semantics contract is preserved.
2. **Interviewer / completeness:** computed in CODE from config + `FIELD_POLICY`
   (never trust the model); remaining gaps injected into the system prompt each
   turn. The gate owns the authoritative status flip; the builder reflects it.
3. **Bounded retry:** on a gate rejection, feed the typed error back to the model
   as a tool result and let it self-correct up to **2** times; then a calm `notice`
   (never a stack trace). Uniform across all rejection kinds (bounded → no loop).
4. **State:** in-memory `SessionStore` behind a Protocol; Postgres impl drops in
   later without touching the loop.

## What's mocked (and the seam to reconcile at integration)
- **Config gate (WS2):** `FakeGate` in `testing.py` faithfully enforces the parts
  the builder leans on — locked-path rejection (via `FIELD_POLICY`), schema/type
  validation (via `AgentConfig`), version bump, authoritative status flip, and a
  `screener` hook for the free-text screening the real gate delegates to WS5. It
  does **not** implement WS2's own responsibilities (Postgres persistence, versioned
  history/undo, tenant isolation by user id). **Integration action:** WS2's gate must
  satisfy the `Gate` Protocol in `gate.py` and raise `GateError` with the same
  `kind` taxonomy (`locked_path | validation | screening_blocked | screening_flagged
  | rate_limited`), or an adapter must bridge it. Then delete `FakeGate` from the
  wiring and re-run the E2E check.
- **ModelWrapper (WS6):** `ScriptedModel` plays back fixed `ModelResponse`s. Swap
  for the real (screened) wrapper; the builder calls `complete(..., tools=…,
  model_tier="frontier")` only.

## Known caveats / notes for integration
- **Token streaming:** Phase 1 uses `complete()` (tool-calling) and emits the reply
  text as `token` chunks after patches. Real progressive interleaving of tokens and
  patches is the transport/API layer's concern (or a future `stream()`-based turn).
- **Retry idempotency:** on retry the model is fed tool-results marking which calls
  succeeded and is expected to re-emit only corrections. `set_field` is idempotent;
  `add_*` is not, so a model that re-emits an already-accepted `add_*` on retry would
  double-append. The prompt + tool-result feedback guide against this; the real
  wrapper should preserve that feedback.
- `meta.status` is emitted as a synthetic `patch` (`value:"ready"`) when the agent
  flips to READY, so the panel can react. It is derived, not a user-settable field.

## Boundaries respected
- Never writes the config directly — every mutation goes through the gate.
- No secrets/system internals in the model context (platform guardrails are product
  policy, not secrets, and are named so the model can explain the rails).

## How to verify
From the repo root:

```bash
python -m pytest backend/builder_loop/tests -q
```

Expected: **13 passed**. Coverage:
- `test_completeness.py` — gaps derived from policy; status flips READY when filled.
- `test_loop.py`:
  - `test_conversation_drives_empty_to_ready` — scripted chat drives empty → READY;
    one synthetic `meta.status=ready` patch on the flip.
  - four `test_triage_*` — supported → structured field; flavor → free-text pocket;
    unsupported → **wishlist quarantine, kept out of operative config**; harmful →
    refused in prose, no patch, locked guardrail untouched.
  - `test_locked_path_rejection_becomes_notice` — locked-path attempt → `notice`
    (kind `locked_path`), no patch, guardrail intact.
  - `test_bounded_retry_recovers_from_a_type_slip` — validation error fed back,
    self-corrected within budget, no notice.
  - `test_retry_exhaustion_yields_a_calm_notice` — exhausts retries → one calm notice.
  - `test_screening_block_becomes_notice` — screener block → `notice`
    (kind `screening_blocked`).
```
