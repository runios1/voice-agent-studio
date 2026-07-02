"""Encrypted, tenant-scoped credential storage — the isolation enforcement point.

Implements the frozen `CredentialStore` Protocol (`contracts/tool_registry`). Two
guarantees the design leans on (D-security):

  1. **Tokens are NEVER in the clear at rest.** They are encrypted with Fernet
     (AES-128-CBC + HMAC) before storage; the key comes from the environment
     (`TOOL_REGISTRY_ENC_KEY`), never the repo, never a model's context. A leaked
     store row is ciphertext.

  2. **A tenant can only ever reach its OWN connection.** `get_access_token` takes
     BOTH the `tenant_id` and the `connection_ref` and verifies the ref was stored
     FOR that tenant. A cross-tenant ref is refused as a plain "no such connection"
     (`TenantAccessDenied`) — existence is not leaked, mirroring the config-gate's
     not-found-vs-forbidden stance. This is enforced in code; no prompt is trusted.

The store is keyed internally by `connection_ref`, but every read re-checks the
owning tenant, so guessing/forging another tenant's ref buys nothing. The in-memory
backing is for CI/dev; a Postgres-backed store implements the same Protocol against
an encrypted `bytea` column (swap-in, no caller change), just like the config-gate's
repository pattern.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.tool_registry.errors import ProviderError, TenantAccessDenied


def generate_key() -> str:
    """A fresh urlsafe base64 Fernet key. For tests/dev bootstrap only — production
    keys are provisioned out-of-band and injected via the environment."""
    return Fernet.generate_key().decode()


def _load_key() -> bytes:
    """Fetch the encryption key from the environment. Absent key is a hard error —
    we never silently fall back to plaintext (that would defeat the guarantee)."""
    raw = os.environ.get("TOOL_REGISTRY_ENC_KEY")
    if not raw:
        raise ProviderError(
            "Credential encryption key is not configured (TOOL_REGISTRY_ENC_KEY)."
        )
    return raw.encode()


@dataclass
class _StoredCredential:
    tenant_id: str
    provider: str
    ciphertext: bytes            # Fernet-encrypted access token
    refresh_ciphertext: Optional[bytes] = None
    scopes: list[str] = field(default_factory=list)
    stored_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EncryptedCredentialStore:
    """In-memory, encrypted-at-rest, tenant-scoped credential store (CI/dev).

    Satisfies the `CredentialStore` Protocol. Pass `key` explicitly in tests;
    production reads it from the environment.
    """

    def __init__(self, key: Optional[str] = None):
        self._fernet = Fernet((key or _load_key_str()).encode())
        self._by_ref: dict[str, _StoredCredential] = {}

    # --- write path (used by the connection manager after OAuth) ---
    def put(
        self,
        tenant_id: str,
        connection_ref: str,
        provider: str,
        access_token: str,
        *,
        refresh_token: Optional[str] = None,
        scopes: Optional[list[str]] = None,
    ) -> None:
        """Encrypt and store a token for `tenant_id` under `connection_ref`."""
        self._by_ref[connection_ref] = _StoredCredential(
            tenant_id=tenant_id,
            provider=provider,
            ciphertext=self._fernet.encrypt(access_token.encode()),
            refresh_ciphertext=(
                self._fernet.encrypt(refresh_token.encode()) if refresh_token else None
            ),
            scopes=list(scopes or []),
        )

    # --- read path (the frozen Protocol method) ---
    async def get_access_token(self, tenant_id: str, connection_ref: str) -> str:
        """Decrypt and return the access token IFF `connection_ref` belongs to
        `tenant_id`. Cross-tenant or unknown refs both raise `TenantAccessDenied`
        with an identical message so existence is never leaked."""
        cred = self._by_ref.get(connection_ref)
        # Same failure for "doesn't exist" and "belongs to someone else" — no leak.
        if cred is None or cred.tenant_id != tenant_id:
            raise TenantAccessDenied()
        try:
            return self._fernet.decrypt(cred.ciphertext).decode()
        except InvalidToken:  # wrong key / corrupted row — never expose specifics
            raise ProviderError("Stored credential could not be read.")

    # --- lifecycle ---
    def revoke(self, tenant_id: str, connection_ref: str) -> None:
        """Remove a connection's credential. Tenant-checked, silent on miss (so a
        cross-tenant revoke can neither succeed nor confirm existence)."""
        cred = self._by_ref.get(connection_ref)
        if cred is not None and cred.tenant_id == tenant_id:
            del self._by_ref[connection_ref]


def _load_key_str() -> str:
    return _load_key().decode()
