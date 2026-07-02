# Workstream 3 — Builder loop (chat that EDITS the config)

**Depends on:** `contracts/config_schema` + `contracts/model_wrapper`.

## Responsibility
- The **goal-seeking interviewer** (D11). Holds the completeness model
  (`required_for_ready` fields) and conversationally guides the user to fill the
  gaps, absorbing anything volunteered out of order. Interview with a goal — not a
  fixed script (robotic), not a blank page (hollow agents). Guides, never gates.
- Emits changes as **structured tool-calls** (`set_field`, `add_*`, `clear_field`)
  — patches, not whole-config regeneration (D5). Schema-constrained generation so
  malformed output is impossible at the source (D-reliability).
- Runs the **four-way triage** on volunteered detail (D13): harmful → refuse;
  supported capability → structured field; harmless flavor → free-text pocket;
  capability-we-don't-offer → acknowledge + push to `wishlist`, keep OUT of
  operative config.
- Sends every proposed patch through the **config gate** (workstream 2). The gate,
  not this loop, is the security boundary — a rejected patch becomes a
  conversational `notice`, and the loop bounded-retries on validation errors
  before gracefully re-asking the user (D-reliability).

## Boundaries — do NOT
- Do not write to the config directly; always go through the gate.
- Do not put secrets/system internals in the model context (least context, D-security).
