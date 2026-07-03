"""ResendEmailClient — unit tests against a stubbed HTTP poster (no network).

Live smoke (documented, not run in CI): set `RESEND_API_KEY` + `RESEND_FROM_EMAIL`
in the environment, construct `ResendEmailClient()` with no args, call
`send("tok", client.get_template("intro"))`, and confirm one real message lands in
the Resend dashboard / the configured `RESEND_DEV_RECIPIENT` inbox.
"""

from __future__ import annotations

import pytest

from contracts.provider_clients.interface import EmailClient, EmailTemplate, SentEmailReceipt
from backend.integration.resend_email import EmailTemplate as EmailTemplateStub
from backend.integration.resend_email import ResendEmailClient
from backend.tool_registry.errors import ProviderError


class _Resp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _client(poster, **kw) -> ResendEmailClient:
    return ResendEmailClient(
        api_key="key_test",
        from_address="agent@example.com",
        poster=poster,
        **kw,
    )


def test_satisfies_the_frozen_contract():
    client = _client(lambda *a: _Resp(200, {"id": "msg_1"}))
    assert isinstance(client, EmailClient)
    tpl = client.get_template("intro")
    assert isinstance(tpl, EmailTemplate)
    receipt = client.send("tok", tpl)
    assert isinstance(receipt, SentEmailReceipt)


def test_send_posts_the_template_unaltered_and_returns_the_provider_id():
    calls = []

    def poster(url, body, headers):
        calls.append((url, body, headers))
        return _Resp(200, {"id": "msg_abc"})

    client = _client(poster)
    tpl = client.get_template("intro")
    receipt = client.send("tok", tpl)

    assert receipt.provider_message_id == "msg_abc"
    assert receipt.template_id == "intro"

    [(url, body, headers)] = calls
    assert url == "https://api.resend.com/emails"
    assert body["from"] == "agent@example.com"
    assert body["subject"] == tpl.subject
    assert body["text"] == tpl.body  # body/links untouched, per the contract
    assert headers["Authorization"] == "Bearer key_test"


def test_missing_access_token_is_a_provider_error():
    client = _client(lambda *a: _Resp(200, {"id": "x"}))
    with pytest.raises(ProviderError):
        client.send("", client.get_template("intro"))


def test_unknown_template_is_a_provider_error():
    client = _client(lambda *a: _Resp(200, {"id": "x"}))
    with pytest.raises(ProviderError):
        client.get_template("no-such-template")


def test_non_2xx_response_is_mapped_to_provider_error_not_leaked():
    def poster(url, body, headers):
        return _Resp(422, {"message": "invalid `to` field", "name": "validation_error"})

    client = _client(poster)
    with pytest.raises(ProviderError) as exc:
        client.send("tok", client.get_template("intro"))
    # generic, client-safe — the raw provider body never surfaces (least context)
    assert "invalid" not in str(exc.value)


def test_transport_failure_is_mapped_to_provider_error():
    def poster(url, body, headers):
        raise ConnectionError("boom")

    client = _client(poster)
    with pytest.raises(ProviderError):
        client.send("tok", client.get_template("intro"))


def test_missing_api_key_refuses_to_construct():
    import os

    old = os.environ.pop("RESEND_API_KEY", None)
    try:
        with pytest.raises(ProviderError):
            ResendEmailClient(from_address="agent@example.com")
    finally:
        if old is not None:
            os.environ["RESEND_API_KEY"] = old


def test_custom_template_store_overrides_the_default_catalog():
    custom = {
        "welcome": EmailTemplateStub("welcome", "Hi!", "Body", []),
    }
    client = _client(lambda *a: _Resp(200, {"id": "x"}), templates=custom)
    assert client.get_template("welcome").subject == "Hi!"
    with pytest.raises(ProviderError):
        client.get_template("intro")  # no longer in the store
