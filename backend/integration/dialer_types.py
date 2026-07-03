"""Small structural type shared by the runtime + dialer (kept separate to avoid an
import cycle between `runtime.py` and `dialer.py`)."""

from __future__ import annotations

from typing import Protocol

from contracts.campaign.model import Lead
from contracts.voice_runtime.interface import CallTransport


class TransportFactory(Protocol):
    """Builds the per-call transport (phone medium). Owned by the runtime layer."""

    def create(self, lead: Lead) -> CallTransport: ...
