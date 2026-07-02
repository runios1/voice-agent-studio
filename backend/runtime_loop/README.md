# Workstream 4 — Runtime loop (chat that EXECUTES the config)

**Depends on:** `contracts/config_schema` + `contracts/model_wrapper`.

## Responsibility
- Reads the `conversation` section of a config and **behaves as that agent**. In
  Phase 1 this is the **text preview** (D12) — the embryonic runtime. In Phase 2
  the text I/O is swapped for the voice Live API and in-call functions are added;
  the loop is a piece you keep, not a throwaway.
- **Structural guardrail enforcement (D-security).** Critical guardrails are
  enforced HERE in code, not as prompt text an injected persona could override:
  - AI disclosure is a hard runtime step when `must_disclose_ai` (not a prompt line);
  - no `offer_discount` function exists above the cap → the agent physically can't;
  - links come only from `allowed_link_domains` → no free-composed URLs (D-security).
- Composes the runtime prompt so LOCKED guardrails outrank user persona text in
  precedence, and never feeds `wishlist` items as instructions.

## Boundaries — do NOT
- Do not let free-text config fields grant capabilities. Capability == a function
  you exposed, nothing more.
- Phase 1: no real tools, no telephony. Keep the in-call function layer as the
  place where in-call guardrails will live (D6).
