# CR: `EmailClient.send` (and `Lead`) have no recipient address to send to
- **Workstream:** P3-2 — Resend email client
- **Contract affected:** `contracts/provider_clients/interface.py` (`EmailClient.send`),
  and upstream of it `contracts/campaign/model.py` (`Lead`)
- **Status:** approved (implemented for the live-preview scheduling feature — items 2
  and 3 below landed as proposed; item 1, `Lead.email`, is still open, see note below)

## Problem
`EmailClient.send(self, access_token: str, template: EmailTemplate) -> SentEmailReceipt`
takes no recipient. Neither does the handler that calls it
(`backend/tool_registry/handlers.py::EmailHandler.execute` calls
`self._client.send(token, template)`), and neither does `ToolContext`
(`contracts/tool_registry/interface.py`) — it carries `lead_id` but not an address.
Tracing it further back, `Lead` (`contracts/campaign/model.py`) has `phone` +
`display_name` but no `email` field at all, so the address doesn't exist anywhere in
the frozen data model yet.

The in-repo mock (`MockEmailClient.send`) doesn't need one — it fabricates a receipt
with no network. A **real** Resend API call requires a `to` field
(`POST https://api.resend.com/emails` rejects a payload without one), so
`ResendEmailClient` cannot address a real send from the current signature alone. This
was latent since Phase 2 (the mock never surfaced it); it becomes load-bearing the
moment a real send has to leave the process.

## Proposed change
Thread the recipient down from where it already exists at campaign-authoring time.
Minimal version, smallest surface first:

1. `contracts/campaign/model.py::Lead` — add `email: Optional[str] = None`.
2. `contracts/tool_registry/interface.py::ToolContext` — add
   `lead_email: Optional[str] = None`, resolved by whatever builds the context per
   call (same place `lead_id` is already resolved).
3. `contracts/provider_clients/interface.py::EmailClient.send` — add the recipient as
   an explicit param (mirrors `CalendarClient.book` already taking multiple business
   params beyond the token):
   ```python
   def send(
       self, access_token: str, to_address: str, template: EmailTemplate
   ) -> SentEmailReceipt: ...
   ```
4. `EmailHandler.execute` — read `ctx.lead_email`, raise a `GuardrailViolation` (not a
   `ProviderError`) if absent (a lead with no email is a data problem, not a provider
   failure), then pass it through.

## Blast radius
- `backend/tool_registry/handlers.py` (`EmailHandler.execute`) — one new guardrail
  check + one new positional arg on the `send` call.
- `backend/tool_registry/integrations.py::MockEmailClient.send` — signature grows to
  match; trivial (it never used the token for addressing either).
- `backend/integration/resend_email.py` (this workstream) — signature grows to match;
  the `to` field becomes real instead of a stand-in.
- Any campaign-authoring / lead-import UI (P3-6) needs an email input alongside phone.
- `backend/integration/tests/test_contract_provider_clients.py` — reference test
  updates its call sites.

Nothing here changes `CalendarClient`, events, or campaign state machine shape.

## Workaround while pending
`ResendEmailClient` (this file) ships against the **current** frozen signature so it
drops in without a handler change today. Lacking a real recipient, it sends to a
single platform-configured stand-in address (`RESEND_DEV_RECIPIENT`, falling back to
the `from` address) and logs that it did so — clearly not a real per-lead send. This
keeps the client honest about the gap instead of inventing a hidden side channel, and
means the "live smoke: one real send" DONE criterion for P3-2 is satisfiable (mail
arrives), but not yet "one real send **to the lead**" — that lands when this CR is
approved and merged.

## Resolution (live-preview scheduling feature)
Items 2 and 3 landed as proposed: `ToolContext.lead_email` and
`EmailClient.send(access_token, to_address, template)` (implemented in
`ResendEmailClient`, `MockEmailClient`, and `EmailHandler.execute`, which now raises
`GuardrailViolation` when `ctx.lead_email` is absent — exactly as proposed above).
`RESEND_DEV_RECIPIENT` remains only as a last-resort fallback if `to_address` is
somehow empty; it should not be hit on the normal path.

**Item 1 (`Lead.email`) is deliberately NOT part of this change** — the live-preview
call flow has no `Lead` record at all (it's a browser tester, not a campaign lead), so
`lead_email` is populated a different way: the agent asks for the lead's email as part
of its closing directions, passes it through the `calendar` tool's optional
`attendee_email` param (a value it already collected verbally, not a free choice —
see `backend/tool_registry/catalog.py`), and `backend/live_agent/session.py` attaches
it to the `ToolContext` for the one post-call `email` invocation it makes. The real
campaign/dialer path (`backend/integration/dialer.py`) still has no source for
`lead_email` — `Lead.email` remains open for whoever wires that path to email next.
