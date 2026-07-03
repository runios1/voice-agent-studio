# CR: `EmailClient.send` (and `Lead`) have no recipient address to send to
- **Workstream:** P3-2 — Resend email client
- **Contract affected:** `contracts/provider_clients/interface.py` (`EmailClient.send`),
  and upstream of it `contracts/campaign/model.py` (`Lead`)
- **Status:** proposed

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
