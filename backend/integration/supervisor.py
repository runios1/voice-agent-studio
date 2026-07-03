"""Bounded autonomy, wired: when a human authorizes (or resumes) a campaign, its
dispatch loop starts running on its own — unsupervised, within the envelope.

Phase-2's orchestrator had `authorize_campaign` (create + mark RUNNING) and `run_campaign`
(the dispatch loop) as SEPARATE calls, and nothing joined them, so an authorized campaign
just sat there. `SupervisedOrchestrator` closes that gap: it launches `run_campaign` as a
tracked background task on authorize/resume. That is exactly the P2-D1 contract — the human
authorizes, the agent runs the leads itself.

Why this is safe:
  * The runner re-reads campaign state from the repo every tick and stops launching new
    dials the instant the kill switch flips (pause / auto-pause / emergency stop), letting
    in-flight calls finish. So pausing does NOT require cancelling the task — it drains.
  * One task per campaign (idempotent): a second authorize/resume while a loop is live is a
    no-op, so we never double-drive a campaign (no double-dial).
  * `shutdown()` cancels everything for a clean process exit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from contracts.campaign.model import Campaign

from backend.orchestrator.service import OrchestratorService

log = logging.getLogger("voice_agent_studio.supervisor")


class SupervisedOrchestrator(OrchestratorService):
    """An `OrchestratorService` that auto-drives every RUNNING campaign it creates."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._runners: dict[str, asyncio.Task] = {}

    async def authorize_campaign(self, *args, **kwargs) -> Campaign:
        campaign = await super().authorize_campaign(*args, **kwargs)
        self._ensure_running(campaign.id, campaign.tenant_id)
        return campaign

    async def resume(self, campaign_id: str, tenant_id: str) -> Campaign:
        campaign = await super().resume(campaign_id, tenant_id)
        # Only (re)launch if the resume actually left it RUNNING.
        if campaign.state.value == "running":
            self._ensure_running(campaign_id, tenant_id)
        return campaign

    # --- task management -----------------------------------------------------
    def _ensure_running(self, campaign_id: str, tenant_id: str) -> None:
        existing = self._runners.get(campaign_id)
        if existing is not None and not existing.done():
            return  # already being driven — never double-dial (P2-D2)
        task = asyncio.create_task(
            self._drive(campaign_id, tenant_id), name=f"campaign:{campaign_id}"
        )
        self._runners[campaign_id] = task

    async def _drive(self, campaign_id: str, tenant_id: str) -> None:
        try:
            await self.run_campaign(campaign_id, tenant_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # a runner crash must not take the process down
            log.exception("campaign runner crashed: %s", campaign_id)
        finally:
            # Let a future resume re-spawn a fresh loop.
            if self._runners.get(campaign_id) is asyncio.current_task():
                self._runners.pop(campaign_id, None)

    async def wait_for(self, campaign_id: str) -> None:
        """Await the campaign's dispatch loop to finish (drain to completion/pause).
        No-op if it isn't being driven. Handy for tests and orderly single-campaign
        shutdown; production leaves loops running in the background."""
        task = self._runners.get(campaign_id)
        if task is not None:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def shutdown(self) -> None:
        """Cancel all in-flight campaign loops (clean process exit)."""
        tasks = [t for t in self._runners.values() if not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._runners.clear()
