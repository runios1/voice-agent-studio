# Contract-change request — `campaign.autopaused` payload requires `trigger` no producer sends

**Filed by:** INT-C (demo scenario + live producers)
**Severity:** blocks the JOIN E2E (and would break real P2-6 auto-pause in production)
**Surface:** `backend/events/payloads.py` — `CampaignAutopausedPayload`

## The mismatch
`CampaignAutopausedPayload.trigger` is declared **REQUIRED** (no default):

```python
class CampaignAutopausedPayload(_Payload):
    trigger: str  # REQUIRED — which detection rule tripped.
    count: Optional[int] = None
    window_seconds: Optional[int] = None
```

But **no producer of `campaign.autopaused` emits a `trigger` field**:

- `backend/orchestrator/service.py::OrchestratorService.autopause` emits
  `payload={"reason": reason}`.
- `backend/autopause/engine.py::_autopaused_event` (P2-6) emits
  `payload={"rule": ..., "reason": ..., "triggered_by_event_id": ..., "triggered_by_type": ...}`.

Because `EventService.emit` validates payloads per type (`validate_payload`), and
`extra="allow"` still enforces REQUIRED known fields, **both producers raise
`EventValidationError` the moment they emit through the real P2-5 `EventService`**
(the wiring the Phase-2 assembly, `phase2_app.py`, uses). In isolation each stream
passed only because its test sink did not validate.

INT-C is the first thing to exercise `orch.autopause` through the real `EventService`
(contract §4c requires the trip), so it surfaces here first — but this is a producer/
events contract bug, not an INT-C bug, and it blocks the JOIN checklist item
"the `campaign.paused`/autopause event appears in the Audit log".

## Why the model is the outlier (not the producers)
1. Two independently-built producers (P2-2 and P2-6) agree on `reason`; the payload
   model alone invented `trigger`.
2. `backend/events/payloads.py`'s **own** docstring lists the compliance-critical
   events with REQUIRED fields as `disclosure.spoken`, `guardrail.tripped`,
   `lead.outcome`, `slot.booked` — **`campaign.autopaused` is deliberately not in
   that set.** A REQUIRED field on it contradicts the file's stated design.
3. No events test asserts a `trigger` field, so relaxing it regresses nothing.

## Requested fix (minimal, applied on branch `int/C`, announced as cross-cutting)
Make `trigger` optional and recognize the fields producers actually send, so every
producer validates without changing any producer:

```python
class CampaignAutopausedPayload(_Payload):
    # `campaign.autopaused` is NOT in the compliance-critical REQUIRED set (see module
    # docstring). Producers name the tripped rule differently — orchestrator sends
    # `reason`; P2-6 sends `rule` + `reason` — so none is REQUIRED; all are recognized.
    trigger: Optional[str] = None   # legacy alias some emitters may use
    rule: Optional[str] = None      # P2-6 engine: the detection rule name
    reason: Optional[str] = None    # human-readable reason (orchestrator + P2-6)
    count: Optional[int] = None
    window_seconds: Optional[int] = None
```

This is a P2-5 **implementation** file (`backend/events/payloads.py`), not a frozen
`contracts/` file, so it is a bugfix rather than a schema-version bump. `contracts/
events/schema.py` (the frozen envelope) is untouched. If P2-5's owner prefers instead
to make the producers emit `trigger`, that is a two-file producer change — either
resolves the JOIN; this CCR picks the model relaxation because it unblocks all
producers at once and matches the module's own compliance-field policy.
