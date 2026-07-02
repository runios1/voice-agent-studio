# CR: voicemail.action default None (not "hang_up")
- **Workstream:** WS1 — Frontend (surfaced during integration/E2E)
- **Contract affected:** `contracts/config_schema/schema.py` (`VoicemailBehavior.action`)
- **Status:** approved (owner approved during integration; implemented)

## Problem
`voicemail.action` is `required_for_ready`, but its schema default was
`"hang_up"` — a concrete enum value. The completeness model counts any concrete
enum value as "satisfied", so on a fresh agent the field was **already satisfied
by its default**. Two consequences, both observed live:

- The **builder never interviews** for it (it's never in `remaining_gaps`), so the
  user is never asked how the agent should handle voicemail — a real decision for
  an agent that dials strangers.
- The **panel counter can never reach done**: the frontend treats a `select` as
  undecided until explicitly patched (D-UX "no empty selector before answered"),
  while the gate counts the default as answered — so an agent can read
  "Ready · 5/6", a contradiction.

## Proposed change
Make "undecided" representable, so the default is not mistaken for an answer:

```python
# before
action: Literal["leave_message", "hang_up"] = "hang_up"
# after
action: Optional[Literal["leave_message", "hang_up"]] = None
```
Runtime falls back to hang-up when still `None` (safe default), so behavior is
unchanged for a config that never sets it; the difference is only that
completeness now treats `None` as a genuine gap the builder asks about.

## Blast radius
- `backend/config_gate/completeness.py`, `backend/builder_loop/completeness.py`:
  no code change (both already treat `None` as unsatisfied); stale comments updated.
- `backend/runtime_loop/compiler.py`: `None` → hang-up branch (explicit).
- Fixtures/tests that built a "ready" config via the default now set
  `voicemail.action` explicitly (runtime `sample_ready_config`, config-gate
  `READY_PATCHES`, builder drive-to-ready script, completeness tests).
- Frontend: `VoicemailBehavior.action` typed `| null`; fixture seeds `null`;
  select shows a "Choose…" placeholder when unset.

## Workaround while pending
None needed — approved and implemented in the same pass. Backend 147 tests,
frontend 23 tests green.
