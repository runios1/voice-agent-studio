"""Policy lookups over the frozen FIELD_POLICY (D4, D-security).

FIELD_POLICY (in the frozen contract) says who owns each field and whether it is
locked / default / open. This module turns that flat list into the two questions
the gate asks on every mutation:

  * `is_locked(path)`   — may this path be changed at all?
  * `is_prose(path)`    — is this a free-text field that must be screened?

Locked determination is deliberately conservative and covers the sub-tree:

  * SYSTEM-MANAGED prefixes (`meta`) are never patchable — meta.owner_user_id is
    the tenant identity and meta.version/status are managed by the gate itself.
    This is the structural half of "forged-identity rejected": a client cannot
    reassign ownership or forge a version by PATCHing meta.*.
  * a path IS locked if it equals a LOCKED policy path, is a DESCENDANT of one
    (can't sneak under a lock), or is an ANCESTOR of one (can't overwrite a
    parent sub-tree that contains a locked child).
  * everything else is allowed (subject to type validation + screening). Locked
    is the security-bearing set; other guardrails are structural (functions,
    allowlists) and enforced at runtime, not here.
"""

from __future__ import annotations

from contracts.config_schema.field_policy import FIELD_POLICY, Mutability

# Sub-trees the gate manages itself — never mutated via a patch, from any source.
SYSTEM_MANAGED_PREFIXES: tuple[str, ...] = ("meta",)

_LOCKED_PATHS: frozenset[str] = frozenset(
    p.path for p in FIELD_POLICY if p.mutability == Mutability.LOCKED
)

# Prose (free-text) fields that must be routed through screening. Kept explicit
# rather than "any string field" so structural strings (enum values like
# voicemail.action, template ids, calendar_ref) are not needlessly screened.
_PROSE_PATHS: frozenset[str] = frozenset(
    {
        "conversation.persona.display_name",
        "conversation.persona.role",
        "conversation.persona.tone",
        "conversation.persona.style_notes",
        "conversation.opening",
        "conversation.primary_objective",
        "conversation.voicemail.message",
        "conversation.custom_instructions",
        "conversation.disclosure.disclosure_script",
        "conversation.qualification.framework",
        "conversation.closing.sign_off",
        # sub-trees whose string leaves are prose (objection guidance, criteria text)
        "conversation.objections",
        "conversation.qualification.criteria",
    }
)


def _covers(policy_path: str, path: str) -> bool:
    """True if `policy_path` and `path` are equal or one nests the other."""
    return (
        path == policy_path
        or path.startswith(policy_path + ".")
        or policy_path.startswith(path + ".")
    )


def is_system_managed(path: str) -> bool:
    return any(
        path == pre or path.startswith(pre + ".") or pre.startswith(path + ".")
        for pre in SYSTEM_MANAGED_PREFIXES
    )


def is_locked(path: str) -> bool:
    if is_system_managed(path):
        return True
    return any(_covers(lp, path) for lp in _LOCKED_PATHS)


def is_prose(path: str) -> bool:
    """Whether a patch at `path` carries free-text that WS5 should screen."""
    return any(
        path == pp or path.startswith(pp + ".") or pp.startswith(path + ".")
        for pp in _PROSE_PATHS
    )
