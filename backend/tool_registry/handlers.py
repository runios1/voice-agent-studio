"""Tool handlers — where a RegistryTool actually runs, and where guardrails BITE.

This is the enforcement point (D6/D-security). Each handler:

  1. resolves the tenant's decrypted access token from the connection in the
     `ToolContext` — via the encrypted, tenant-scoped `CredentialStore`, so a handler
     never touches a raw token store and never picks its own tenant;
  2. enforces its guardrails IN CODE against the injected `GuardrailPolicy` (calling
     hours, booking window, link allowlist, approved templates) — a breach raises
     `GuardrailViolation` AFTER emitting `GUARDRAIL_TRIPPED` (the event auto-pause,
     P2-6, watches);
  3. performs the action against the (mock) provider client and returns a
     JSON-serializable result the caller feeds back to the model / workflow;
  4. emits `TOOL_INVOKED` (always) and any domain event (`SLOT_BOOKED`).

Handlers satisfy the frozen `ToolHandler` Protocol (`async execute(args, ctx)`).
They are constructed per-agent by `registry.build_registry`, closing over the
policy, the credential store, the provider client, and the event sink.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from contracts.events.schema import Event, EventType, Severity
from contracts.tool_registry.interface import ToolContext
from backend.tool_registry import guardrails as gr
from backend.tool_registry.credentials import EncryptedCredentialStore
from backend.tool_registry.errors import GuardrailViolation, NotConnected, ProviderError
from backend.tool_registry.events import EventSink
from backend.tool_registry.guardrails import GuardrailPolicy
from backend.tool_registry.integrations import MockCalendarClient, MockEmailClient


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(
    type_: EventType, ctx: ToolContext, *, severity: Severity = Severity.INFO, **payload
) -> Event:
    """Build an Event envelope per the frozen schema, correlated from the context."""
    return Event(
        event_id=str(uuid.uuid4()),
        type=type_,
        occurred_at=_now(),
        severity=severity,
        tenant_id=ctx.tenant_id,
        campaign_id=ctx.campaign_id,
        lead_id=ctx.lead_id,
        payload=payload,
    )


class _BaseHandler:
    """Shared plumbing: token resolution + the two always/guardrail event emissions."""

    tool_name: str

    def __init__(
        self,
        policy: GuardrailPolicy,
        credentials: EncryptedCredentialStore,
        sink: EventSink,
    ):
        self._policy = policy
        self._credentials = credentials
        self._sink = sink

    async def _access_token(self, ctx: ToolContext) -> str:
        """Decrypt the tenant's token for this call's connection. Enforces that a
        connection is present AND (in the store) that it belongs to this tenant."""
        if ctx.connection is None:
            raise NotConnected(
                "No connected account for this action.", tool=self.tool_name
            )
        # get_access_token re-checks tenant ownership; a cross-tenant ref is denied.
        return await self._credentials.get_access_token(
            ctx.tenant_id, ctx.connection.connection_ref
        )

    async def _emit_invoked(self, ctx: ToolContext, **payload) -> None:
        # ToolInvokedPayload REQUIRES `tool_name` (backend.events.payloads); extra keys
        # (e.g. provider_event_id) ride along under extra="allow".
        await self._sink.emit(
            _event(EventType.TOOL_INVOKED, ctx, tool_name=self.tool_name, **payload)
        )

    async def _trip(self, ctx: ToolContext, violation: GuardrailViolation) -> None:
        # GuardrailTrippedPayload REQUIRES `guardrail` (also what auto-pause counts) and
        # takes an optional `detail`; param rides along as an extra.
        await self._sink.emit(
            _event(
                EventType.GUARDRAIL_TRIPPED,
                ctx,
                severity=Severity.WARNING,
                guardrail=self.tool_name,
                detail=violation.message,
                param=violation.param,
            )
        )


class CalendarHandler(_BaseHandler):
    """Books a slot on the tenant's connected calendar, honoring calling hours and
    the booking window. The model picks only the start time; length/calendar are
    handler-controlled (least-privilege)."""

    tool_name = "calendar"

    def __init__(self, *args, client: MockCalendarClient | None = None, **kw):
        super().__init__(*args, **kw)
        self._client = client or MockCalendarClient()

    async def execute(self, args: dict, ctx: ToolContext) -> dict:
        start = _parse_iso(args.get("start_iso"), tool=self.tool_name)

        # --- guardrails, in code, before any side effect ---
        try:
            gr.check_within_calling_hours(start, self._policy, tool=self.tool_name)
            gr.check_within_booking_window(start, _now_like(start), self._policy, tool=self.tool_name)
        except GuardrailViolation as v:
            await self._trip(ctx, v)
            raise

        token = await self._access_token(ctx)
        slot = self._client.book(token, start, self._policy.meeting_length_minutes)

        await self._emit_invoked(ctx, provider_event_id=slot.provider_event_id)
        await self._sink.emit(
            _event(
                EventType.SLOT_BOOKED,
                ctx,
                slot_start=slot.start_iso,  # SlotBookedPayload REQUIRES slot_start
                slot_end=slot.end_iso,
                provider_event_id=slot.provider_event_id,
            )
        )
        return {
            "booked": True,
            "start_iso": slot.start_iso,
            "end_iso": slot.end_iso,
            "event_id": slot.provider_event_id,
        }


class EmailHandler(_BaseHandler):
    """Sends one approved template. The model names only a template id; the body and
    every link are pre-authored, and each link is re-checked against the platform
    allowlist at send time (defense in depth — the template store is trusted, but the
    allowlist is the locked guardrail)."""

    tool_name = "email"

    def __init__(self, *args, client: MockEmailClient | None = None, **kw):
        super().__init__(*args, **kw)
        self._client = client or MockEmailClient()

    async def execute(self, args: dict, ctx: ToolContext) -> dict:
        template_id = args.get("template_id")
        if not isinstance(template_id, str) or not template_id:
            raise GuardrailViolation(
                "No template selected.", tool=self.tool_name, param="template_id"
            )

        try:
            gr.check_template_approved(template_id, self._policy, tool=self.tool_name)
        except GuardrailViolation as v:
            await self._trip(ctx, v)
            raise

        template = self._client.get_template(template_id)
        # Re-screen every baked-in link against the locked allowlist.
        try:
            for link in template.links:
                gr.check_domain_allowlisted(link, self._policy, tool=self.tool_name)
        except GuardrailViolation as v:
            await self._trip(ctx, v)
            raise

        token = await self._access_token(ctx)
        sent = self._client.send(token, template)

        await self._emit_invoked(ctx, template_id=template_id, message_id=sent.provider_message_id)
        return {"sent": True, "template_id": template_id, "message_id": sent.provider_message_id}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _parse_iso(raw, *, tool: str) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise GuardrailViolation("Missing start time.", tool=tool, param="start_iso")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise GuardrailViolation(
            "Start time was not a valid ISO-8601 timestamp.", tool=tool, param="start_iso"
        )


def _now_like(start: datetime) -> datetime:
    """`now` matched to the awareness of `start` so the subtraction is valid — aware
    if the slot carries an offset, naive otherwise."""
    if start.tzinfo is not None:
        return datetime.now(timezone.utc)
    return datetime.now()
