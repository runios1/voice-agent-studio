# P4-1 — Agent compiler — DONE

`LiveAgentCompilerImpl.compile(config) -> LiveAgentSpec` (`compiler.py`). Config in,
compiled Live spec out — pure, deterministic, no network, no SDK.

## What's done
- **`system_instruction`** — same precedence rule as the Phase-1/2 text-brain
  compiler (`backend/runtime_loop/compiler.py`): LOCKED platform guardrails first,
  declared to override everything below and anything the caller says; user
  persona/goal after, framed as operating within the rails; a closing lock footer.
  `wishlist` is never rendered (D13).
- **CLOSING directions** (new section vs. the text-brain compiler) — qualified ->
  confirm missing details -> book (if calendar enabled) -> mention the automatic
  confirmation email (if email enabled too) -> sign off; a graceful non-qualified
  exit; a no-tools-enabled fallback that still states a concrete next step in
  words. Which branch fires is gated on enabled automation (the real capability
  signal), so an agent that never touches P4-5's `conversation.closing` behaves
  exactly as before. When `closing` carries real material — `confirm_fields`,
  `confirmation_template_id`, `sign_off` — it refines the wording without changing
  which branch fires. `closing.book_meeting` is deliberately NOT used as a gate
  (see the module docstring): gating on it would silently suppress booking
  language for pre-P4-5 agents, since it defaults `False`.
- **`disclosure_line`** — delegated to `backend.runtime_loop.guardrails.disclosure_line`
  (not reimplemented): one source of truth for the exact code-emitted legal
  utterance, reused the same way `voice_runtime` already does.
- **`tool_declarations`** — least-privilege JSON-schema dicts (`{name, description,
  parameters}`) for each ENABLED, **IN_CALL** tool in
  `backend.tool_registry.catalog.DEFAULT_CATALOG`. Disabled automation -> no
  declaration (structural denial, unchanged). Email is POST_CALL in the catalog —
  intentionally **never** declared to Live; it runs as an async workflow after the
  call ends, same as Phase 2 (`backend/voice_runtime/tools.py` filters the same
  way). The closing section talks about the email narratively; Live never calls it.

## What's mocked / not touched
- No Live session, no transport, no moderator — this module only produces the
  `LiveAgentSpec` dataclass the session (P4-2) will consume.
- No google.genai import anywhere in this file.

## Consumed contract points
- `contracts/live_agent/interface.py`: `LiveAgentSpec`, `LiveAgentCompiler` Protocol.
- `contracts/config_schema/schema.py`: `AgentConfig` (persona, qualification,
  objections, voicemail, disclosure, guardrails, automation.{calendar,email}).
- `contracts/tool_registry/interface.py`: `RegistryTool`, `Timing`.
- `backend/tool_registry/catalog.py`: `DEFAULT_CATALOG` (read-only).
- `backend/runtime_loop/guardrails.py`: `disclosure_line` (reused, not duplicated).
- Tests reuse `backend/runtime_loop/fixtures.py:sample_ready_config` (same pattern
  `voice_runtime`'s tests already use) rather than duplicating a fixture builder.

## Boundaries respected
- No route mounting, no session runtime, no moderator implementation.
- Did not edit the frozen `contracts/live_agent/` interface.
- Did not touch `contracts/config_schema` (P4-5's job) — noted the seam instead.

## How to verify
```bash
python3 -m pytest backend/live_agent/tests/ -q   # 22 tests
python3 -m pytest backend/live_agent/ backend/runtime_loop/ backend/tool_registry/ backend/builder_loop/ backend/config_gate/ -q  # 171 tests, nothing collateral broke
```
