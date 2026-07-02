"""Runnable end-to-end drive of the post-call pipeline with mocked contracts.

    python3 backend/async_workflows/demo.py

Shows: a `booked` outcome -> confirmation email + CRM write; a `no_answer` outcome ->
a follow-up touch scheduled with backoff, then fired when the clock advances; a
REPLAY of the booked outcome sending nothing new (idempotent). Every side effect is
mirrored to the event sink, printed as the audit trail.
"""

from __future__ import annotations

import asyncio

from .clock import ManualClock
from .fixtures import build_pipeline, outcome_event


async def main() -> None:
    clock = ManualClock()
    p = build_pipeline(clock)

    booked = outcome_event("booked", lead_id="lead-booked", event_id="evt-booked")
    no_answer = outcome_event("no_answer", lead_id="lead-noans", attempts=1, event_id="evt-noans")

    print("== feed booked + no_answer ==")
    await p.feed(booked, no_answer)
    print(f"emails sent      : {p.registry.email.calls}")
    print(f"crm writes       : {p.registry.crm.calls}")
    print(f"events emitted   : {[e.type.value for e in p.sink.events]}")

    print("\n== replay booked (idempotent) ==")
    await p.feed(booked)
    print(f"emails sent      : {len(p.registry.email.calls)} (unchanged)")

    print("\n== advance clock 2h, fire due follow-ups ==")
    clock.advance(2 * 3600)
    await p.tick()
    print(f"emails sent      : {p.registry.email.calls}")
    print(f"events emitted   : {[e.type.value for e in p.sink.events]}")


if __name__ == "__main__":
    asyncio.run(main())
