"""Events the builder loop streams back for one user turn.

These map 1:1 to the SSE event kinds in contracts/api/api_contract.md:
  * token  — assistant reply text (materializes the conversational answer)
  * patch  — an accepted config mutation {path, value} (materializes a panel field)
  * notice — a rejection/refusal explained conversationally (NOT emitted as a patch)

The API/transport layer (frontend seam) serializes these onto the wire; this
workstream only produces them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union


@dataclass
class TokenEvent:
    text: str
    type: str = "token"


@dataclass
class PatchEvent:
    path: str
    value: Any
    type: str = "patch"


@dataclass
class NoticeEvent:
    # `kind` mirrors the gate's typed-error taxonomy (locked_path | validation |
    # screening_blocked | screening_flagged | rate_limited) so the UI can style it;
    # `message` is the human-friendly, conversational explanation.
    kind: str
    message: str
    path: Optional[str] = None
    type: str = "notice"


BuilderEvent = Union[TokenEvent, PatchEvent, NoticeEvent]
