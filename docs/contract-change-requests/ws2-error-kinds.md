# CR: add `conflict` and `not_found` to the API error taxonomy
- **Workstream:** WS2 — Config gate + persistence
- **Contract affected:** `contracts/api/api_contract.md` (Error shape → `kind` enum)
- **Status:** proposed

## Problem
The frozen error shape enumerates exactly these `kind`s:

    locked_path | validation | screening_blocked | screening_flagged | rate_limited

WS2 owns two rejection cases that don't map cleanly to any of them, and squashing
them into an existing kind would lie to the UI:

1. **Optimistic-concurrency loser.** Two edits (e.g. a builder patch and a manual
   PATCH) race on the same agent; the stale one must be told "reload and retry."
   This is not `validation` (the value was fine) — it's a distinct, retryable
   conflict. HTTP 409.
2. **Tenant-scoped miss.** A read/patch/revert for an agent the authed user does
   not own must be indistinguishable from "no such agent" (don't leak existence).
   That needs a `not_found`. HTTP 404.

## Proposed change
Extend the `kind` enum by two values (additive; no existing value changes):

    "error": { "kind":
      "locked_path | validation | screening_blocked | screening_flagged
       | rate_limited | conflict | not_found", ... }

`conflict` accompanies an optional `expected_version` on `PATCH /agents/{id}/fields`
(also additive — omitting it preserves the frozen `{path, value}` body and gives
last-write-wins).

## Blast radius
- **WS1 (frontend):** should handle 409 (offer reload) and 404. Purely additive —
  a client that ignores the new kinds still degrades gracefully via the generic
  error surface. No rework of existing handling.
- **WS3/WS4:** consume the gate; already receive typed `GateError`s. No change.
- No other contract file is touched.

## Workaround while pending
Implemented in WS2's own `backend/config_gate/errors.py` (NOT by editing the
contract): `ErrorKind` includes `CONFLICT` and `NOT_FOUND`, flagged in-code as
pending this CR. `expected_version` is an optional field on the PATCH body. If the
integrator rejects the extension, the fallback is to map `conflict → validation`
and return a bare 404 without a typed body — both strictly worse for the UI.
