"""
The `Screener` interface — the pluggable seam over an off-the-shelf screener.

v1 concrete implementation: Model Armor (screeners/model_armor.py). A deterministic
`MockScreener` (screeners/mock.py) backs CI. Lakera Guard is a drop-in alternative
later. The rest of the layer (policy, decorator, gate) depends ONLY on this
interface, so swapping the vendor is a one-line change.

A screener reports NEUTRAL findings (see models.Category) — it must not encode our
product's guardrails. It must also be honest about failure: on timeout / network /
auth error it returns `ScreenResult(available=False)`, never a clean result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Direction, ScreenResult


class Screener(ABC):
    @abstractmethod
    async def screen(self, text: str, direction: Direction) -> ScreenResult:
        """Screen one piece of text. Never raises for content reasons; on infra
        failure returns ScreenResult(available=False) rather than raising."""
        raise NotImplementedError
