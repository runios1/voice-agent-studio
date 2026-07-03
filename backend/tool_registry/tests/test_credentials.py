"""Encrypted, tenant-scoped credential store — the isolation enforcement point."""

from __future__ import annotations

import pytest

from backend.tool_registry.credentials import EncryptedCredentialStore
from backend.tool_registry.errors import ProviderError, TenantAccessDenied

from .conftest import OTHER, TENANT


async def test_roundtrip(credentials: EncryptedCredentialStore):
    credentials.put(TENANT, "ref-1", "google_calendar", "tok-abc")
    assert await credentials.get_access_token(TENANT, "ref-1") == "tok-abc"


def test_token_is_encrypted_at_rest(credentials: EncryptedCredentialStore):
    credentials.put(TENANT, "ref-1", "google_calendar", "super-secret-token")
    stored = credentials._by_ref["ref-1"].ciphertext
    assert b"super-secret-token" not in stored          # not plaintext
    assert isinstance(stored, (bytes, bytearray))


async def test_cross_tenant_ref_is_denied(credentials: EncryptedCredentialStore):
    # Alice connects; Bob forges/guesses her ref. Denied in code.
    credentials.put(TENANT, "alice-ref", "google_calendar", "alice-token")
    with pytest.raises(TenantAccessDenied):
        await credentials.get_access_token(OTHER, "alice-ref")


async def test_unknown_ref_and_cross_tenant_are_indistinguishable(credentials):
    # Same exception + message either way, so existence isn't leaked.
    credentials.put(TENANT, "alice-ref", "google_calendar", "alice-token")
    with pytest.raises(TenantAccessDenied) as miss:
        await credentials.get_access_token(OTHER, "nope-ref")
    with pytest.raises(TenantAccessDenied) as cross:
        await credentials.get_access_token(OTHER, "alice-ref")
    assert str(miss.value) == str(cross.value)


async def test_revoke_is_tenant_checked(credentials: EncryptedCredentialStore):
    credentials.put(TENANT, "alice-ref", "google_calendar", "alice-token")
    credentials.revoke(OTHER, "alice-ref")               # cross-tenant revoke: no-op
    assert await credentials.get_access_token(TENANT, "alice-ref") == "alice-token"
    credentials.revoke(TENANT, "alice-ref")              # owner revoke: gone
    with pytest.raises(TenantAccessDenied):
        await credentials.get_access_token(TENANT, "alice-ref")


async def test_wrong_key_cannot_read(enc_key: str):
    store = EncryptedCredentialStore(key=enc_key)
    store.put(TENANT, "ref-1", "google_calendar", "tok")
    from backend.tool_registry.credentials import generate_key

    other = EncryptedCredentialStore(key=generate_key())
    other._by_ref = store._by_ref                        # same ciphertext, wrong key
    with pytest.raises(ProviderError):
        await other.get_access_token(TENANT, "ref-1")
