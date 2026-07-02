# Workstream 5 — Security / screening — DONE

The OUTER layer of defense in depth (D-security): a probabilistic screener wrapped
around **every** model in/out, plus a free-text screen the config gate calls on
every mutation. The "layer allowed to fail" — never relied on; it raises residual
risk on top of the two structural layers (can't-do-it / can't-know-it) owned by
config_gate + runtime.

## What's built

| File | Role |
|---|---|
| `models.py` | Neutral types: `Direction`, `Category`, `Severity`, `Finding`, `ScreenResult`; policy output `Decision` / `ScreenDecision` (maps to API `screening_blocked` / `screening_flagged`). |
| `screener.py` | `Screener` ABC — the pluggable vendor seam (Model Armor v1, Lakera later). |
| `screeners/model_armor.py` | **Real** Google Model Armor REST client (`sanitizeUserPrompt` / `sanitizeModelResponse`), defensive parsing, transport/timeout error → `available=False` (never a false "clean"). |
| `screeners/mock.py` | Deterministic offline `MockScreener` for CI; recognises injection/jailbreak phrasings, known-bad URLs, PII. **Not** a security control. |
| `guardrail_domains.py` | Local detector for **locked-guardrail subversion** (suppress AI disclosure / bypass DNC / out-of-range promises) — our concept, not the external screener's. Detects *intent to subvert*, not mere topic mention (tuning the disclosure script still passes). |
| `policy.py` | Combines screener findings + guardrail detection → accept / flag / block, incl. fail-open/fail-closed. |
| `engine.py` | The single screen→policy→audit path shared by both public surfaces (source-agnostic). |
| `decorator.py` | **`ScreeningModelWrapper`** — IS-A `ModelWrapper`; screens inbound messages + outbound text & tool-call args; raises typed `ScreeningBlocked`. |
| `gate.py` | **`screen_free_text(screener, path, value)`** — the door WS2 (config gate) calls per mutation. |
| `audit.py` | Structured decision logging; logs a **content fingerprint (sha256[:12])**, never raw text — logs don't re-leak injection payloads / PII. |
| `config.py` | `ScreeningConfig` (timeout, fail-open/closed) + `ModelArmorSettings.from_env()`. Secrets read from env only. |
| `errors.py` | `ScreeningBlocked` + `.to_api_error()` → the contract's typed error body. |
| `__init__.py` | Public surface + `build_screener()` (real Model Armor if env present, else mock). |

## Decisions made (STEP-1 grill, confirmed by owner)
- **Screener v1:** Model Armor, behind a pluggable `Screener` interface; real REST
  client + deterministic mock for CI.
- **Timing:** synchronous, inline, per-call timeout (`ScreeningConfig.timeout_seconds`,
  default 2.5s). A timeout is treated as *unavailable*, handed to the failure policy.
- **Failure mode:** **fail-closed on locked-guardrail domains, fail-open elsewhere.**
  A screener outage can't take the product down, but can't wave through content that
  touches disclosure / DNC / forbidden-claims. Locked-guardrail *subversion* is
  hard-blocked regardless of screener availability.
- **Hard-block vs accept-but-flag:** guardrail-domain subversion + HIGH-severity
  injection/jailbreak/malicious-URL → **block**; merely-odd / PII / low-severity →
  **accept-but-flag** (don't police creativity).
- **Logging:** every decision logged; content fingerprinted, never raw.

## What's mocked / deferred
- **Model Armor is live code but CI-mocked.** CI uses `MockScreener`; the real
  client needs credentials (below). Its response parser is defensive because the
  preview REST shape churns — **verify field names against the live API when you
  wire credentials.**
- **Outbound streaming:** `stream()` screens inbound then delegates tokens; per-token
  outbound screening is intentionally not inline (would defeat streaming). Streamed
  content that becomes config is re-screened at the config gate (defense in depth).
  `stream_screened_buffered()` is available where full-text outbound screening is
  required (trades latency).
- No top-level repo packaging yet (Phase-1 scaffold); tests add the repo root to
  `sys.path` via `tests/conftest.py`.

## Contract points consumed (read-only, unmodified)
- `contracts/model_wrapper/interface.py` — `ModelWrapper`, `Message`, `ModelResponse`,
  `ToolCall`, `ToolDef` (decorator implements the interface).
- `contracts/api/api_contract.md` — error kinds `screening_blocked` / `screening_flagged`.
- Guardrail domains mirror the LOCKED fields in `contracts/config_schema/field_policy.py`
  (disclosure / DNC / forbidden-claims) — read for reference, not imported.

No contract was edited; no contract-change-request was needed.

## How integrators wire it in
```python
from backend.security import ScreeningModelWrapper, build_screener
wrapped = ScreeningModelWrapper(GeminiWrapper(...), build_screener())   # WS3/WS4

from backend.security import screen_free_text, build_screener            # WS2
decision = await screen_free_text(build_screener(), path, value)
if decision.blocked:  # -> reject mutation, return decision.error_kind + decision.message
    ...
```

## Verify

Automated tests (32, all passing):
```
cd backend/security && python3 -m pytest -q
```
Covers: guardrail-domain detect vs benign, policy matrix (block/flag/accept +
fail-open/closed), gate door, decorator in/out screening + streaming + typed-error
rendering, Model Armor response parsing + env gating.

End-to-end behavior demo (run from repo root):
```
python3 backend/security/scripts/demo.py
```
Shows: benign pass-through; injection sample blocked before the model call; outbound
malicious URL blocked; gate hard-block on guardrail subversion; PII accept-but-flag;
fail-closed vs fail-open on screener outage — with fingerprint-only audit logs.

### Live Model Armor smoke (manual — needs credentials)
```
export MODEL_ARMOR_API_KEY=...        # never commit; .env is gitignored
export GOOGLE_CLOUD_PROJECT=...
export MODEL_ARMOR_TEMPLATE=...       # a Model Armor template id
export MODEL_ARMOR_LOCATION=us-central1
python3 backend/security/scripts/live_smoke.py
```
`build_screener()` auto-selects the real client when this env is present. Confirm a
known injection sample + malicious URL are flagged by the live API, and re-check the
response field names in `_parse` against what the API actually returns.
```
