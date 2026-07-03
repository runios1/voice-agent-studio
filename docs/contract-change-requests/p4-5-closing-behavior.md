# CR: additive `conversation.closing` field on `AgentConfig`
- **Workstream:** P4-5 — Closing directions in config + builder
- **Contract affected:** `contracts/config_schema/schema.py`, `contracts/config_schema/field_policy.py`
- **Status:** applied (additive, non-breaking — filed for visibility per the P4-5 DONE criteria, not for approval-then-block)

## Problem
The Phase 4 compiler (P4-1) needs real material to generate the "closing directions"
half of the Live system instruction (qualified -> confirm missing details -> book ->
email -> sign off). Before this change nothing in `AgentConfig` captured that
wrap-up flow — the closest existing fields (`automation.calendar`,
`automation.email.template_ids`) say WHETHER those tools exist, not what to do with
them once a lead is qualified.

## Change (additive only — nothing existing is renamed, retyped, or removed)
`contracts/config_schema/schema.py`:
```python
class ClosingBehavior(BaseModel):
    book_meeting: bool = False
    confirm_fields: list[str] = Field(default_factory=list)
    confirmation_template_id: Optional[str] = None
    sign_off: Optional[str] = None

class ConversationConfig(BaseModel):
    ...
    closing: ClosingBehavior = Field(default_factory=ClosingBehavior)
```
`contracts/config_schema/field_policy.py`: one new row, subtree granularity (same
pattern as `automation.calendar` / `automation.email`) —
`FieldPolicy(path="conversation.closing", owner_layer=USER, mutability=OPEN, required_for_ready=False)`.

Every field defaults to its inert value, so an `AgentConfig.model_validate` of any
config produced before this change round-trips unchanged, and no existing
`required_for_ready` gap set changes (`required_for_ready=False` on the whole
subtree — see `backend/builder_loop/tests/test_completeness.py::test_closing_flow_is_additive_and_optional`).

## Blast radius
- `backend/config_gate` (WS2): none of its logic enumerates fields, so type
  validation / locked-path / completeness all pick this up for free. Added
  `conversation.closing.sign_off` to `policy._PROSE_PATHS` (it's the one free-text
  leaf in the subtree) so it's screened like other prose fields.
- `backend/builder_loop` (WS3): `interviewer.py`'s four-way-triage text and
  "all filled" closing message now mention the wrap-up flow as an optional
  refinement; `tools.py`'s `set_field` description names the four new leaf paths.
  No new tool type was needed — `set_field` already accepts arbitrary JSON values
  (lists included), matching how `automation.email.template_ids` is set today.
- `frontend/` (WS1): NOT touched. The TS mirror (`frontend/src/types/contracts.ts`)
  and `fieldMeta.ts` don't yet know about `closing` — the panel simply won't render
  it until WS1 picks it up. This is a display gap, not a correctness bug (the field
  still round-trips through the API as JSON); flagging here so WS1/the integrator
  knows to add it rather than being surprised by an extra key in the payload.
- `backend/live_agent/compiler.py` (P4-1): this is the intended consumer. Until this
  lands (already true at merge time per plan order P4-5 -> P4-1), the compiler
  should compile from existing fields + treat an all-default `closing` as "no
  wrap-up guidance was given" — no crash, just a thinner system instruction.

## Workaround while pending
None needed — applied directly (additive, no consumer breaks), per the plan's own
call: "P4-5 is an additive schema+builder change (do early — P4-1 consumes it)."
