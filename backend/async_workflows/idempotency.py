"""The idempotency ledger — the guarantee that "the same outcome event must not send
two emails" (this stream's README).

The event stream is at-least-once: P2-5 (or a crash-resume in the orchestrator) can
redeliver the same `lead.outcome` event, and a workflow that crashed mid-run gets
replayed. So EVERY side-effecting step is fenced by a key derived from the run's
`run_id` + its position. `check_and_record` is a single atomic test-and-set:

  * returns True  -> first time; the caller proceeds with the side effect.
  * returns False -> already done; the caller SKIPS.

Per-step (not per-workflow) keys mean a run that died after step 1 replays cleanly:
step 1 is skipped, step 2 runs. In-memory here (deterministic, tenant-scoped keys);
the Protocol is the seam for a Postgres-backed unique-index implementation later.
"""

from __future__ import annotations

from typing import Protocol


def step_key(run_id: str, step_index: int, discriminator: str) -> str:
    """Stable fence key for one side effect. `discriminator` (e.g. the tool name or
    a scheduled-action id) keeps distinct effects at the same index separate."""
    return f"{run_id}::{step_index}::{discriminator}"


class RunLedger(Protocol):
    async def check_and_record(self, key: str) -> bool: ...


class InMemoryRunLedger:
    """Test/demo ledger. A real one is a Postgres table with a UNIQUE(key) column
    where the INSERT ... ON CONFLICT DO NOTHING return decides proceed-vs-skip."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def check_and_record(self, key: str) -> bool:
        if key in self._seen:
            return False
        self._seen.add(key)
        return True
