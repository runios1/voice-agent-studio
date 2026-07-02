# P2-3 — Tool registry + integrations — DONE

Owner boundary: `backend/tool_registry/` only. No `contracts/` edits, no other
workstream dirs touched. Consumes the frozen `contracts/tool_registry` interface;
emits to the P2-5 event stream via the frozen `contracts/events` schema.

## What's done (against the DONE criteria)

- **Curated catalog ≥ calendar + email** — `catalog.py`. Two `RegistryTool`s keyed
  by `automation` block name (`calendar` IN_CALL, `email` POST_CALL), each with a
  **least-privilege, sealed** param schema (`additionalProperties: false`; model
  picks only a start time / an approved template id — never a calendar, attendee,
  body, or URL). Curated, not self-serve (P2-D4); wishlist→registry graduation is
  appending an entry here.
- **Per-tenant OAuth connect + encrypted, tenant-scoped storage** —
  `oauth.py` (authorization-code flow: real `GoogleOAuthProvider` + CI `FakeOAuthProvider`),
  `connections.py` (`ConnectionManager` begin/complete with **state-pinned tenant**;
  tenant-scoped `ConnectionStore`), `credentials.py` (`EncryptedCredentialStore`,
  Fernet, key from `TOOL_REGISTRY_ENC_KEY`). Tokens are **ciphertext at rest**; the
  `Connection` only holds an opaque ref.
- **Guardrails enforced in code (the enforcement point, D6)** — `guardrails.py` +
  `handlers.py`. Calendar rejects out-of-hours / past / beyond-booking-window slots;
  email rejects unapproved templates and any baked-in link whose domain is off the
  platform allowlist (subdomains allowed). Every trip emits `GUARDRAIL_TRIPPED`
  before raising. Success emits `TOOL_INVOKED` (+ `SLOT_BOOKED`).
- **Cross-tenant access DENIED** — enforced twice: the `ConnectionStore` filters by
  tenant in code, and `EncryptedCredentialStore.get_access_token` re-checks the ref's
  owner (a forged `ToolContext` carrying another tenant's ref is denied). Unknown ref
  and cross-tenant ref are **indistinguishable** (no existence leak).
- **Registry assembly** — `registry.py` `build_registry(config, …)`: distills a
  `GuardrailPolicy` from the frozen config, injects the concrete approved-template
  enum into the email schema, and exposes a tool **only if its automation block is
  enabled** (structural denial, the Phase-1 rule). The registry resolves the
  `ToolContext` (incl. the tenant's connection); handlers never pick their own tenant.

## What's mocked (and the real swap)

- **Event stream (P2-5)** — not merged. `events.py` defines a tiny `EventSink`
  Protocol + `InMemoryEventSink`; we depend only on the frozen event *schema* and
  build `Event` envelopes. Swap `InMemoryEventSink` → P2-5's bus at integration.
- **Provider APIs** — `integrations.py` `MockCalendarClient` / `MockEmailClient`
  (+ the approved-template store) stand in for Google Calendar / Gmail behind the
  method signatures the real clients will use. The handler passes the tenant's
  decrypted token in, so the execution path is real; only the outbound HTTP is faked.
- **OAuth token exchange** — `FakeOAuthProvider` in CI (no network/secret).
  `GoogleOAuthProvider` is the real shape; its `exchange_code` uses an injected async
  `http_post`, so wiring a real poster + `GOOGLE_OAUTH_CLIENT_ID/SECRET` is the swap.

## Verify

```bash
# from the repo root (worktree: ../vas-p2-3-tool-registry)
python -m pytest backend/tool_registry/tests/ -q        # 36 passing
python -m backend.tool_registry.demo                    # end-to-end walkthrough

# regression: whole backend still green
python -m pytest backend/ -q                            # 183 passed, 3 skipped (pre-existing)
```

`demo.py` prints the full flow: OAuth connect → encrypted-at-rest token → valid
booking (with event trail) → out-of-hours slot rejected in code → a second tenant
denied access to the first tenant's connection.

## Contract points consumed

- `contracts/tool_registry/interface.py` — `RegistryTool`, `Timing`, `Connection`,
  `CredentialStore`, `ToolContext`, `ToolHandler`, `ToolRegistry` (all implemented).
- `contracts/events/schema.py` — `Event`, `EventType` (`TOOL_INVOKED`, `SLOT_BOOKED`,
  `GUARDRAIL_TRIPPED`), `Severity`.
- `contracts/config_schema/schema.py` — `AgentConfig` (guardrails + automation) as
  the source of the per-agent `GuardrailPolicy`.
- `contracts/model_wrapper/interface.py` — `ToolDef` (via `RegistryTool.to_tool_def`).

No contract change requests filed — the frozen interface was sufficient.

### One design note for the integrator
Per-agent guardrail *values* (calling hours, allowlist, booking window, approved
templates) are injected into handlers via `GuardrailPolicy.from_config`, because the
frozen `ToolContext` intentionally carries only WHO + WHICH-connection, not the
config. Handlers thus enforce in code with **least context**. No contract change was
needed; flagging it so the P2-1 voice-runtime integration builds the registry
per-agent with `build_registry(config, …)`.
