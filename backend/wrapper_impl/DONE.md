# WS6 — Gemini wrapper impl — DONE

Concrete `ModelWrapper` (D8/D9) on the **`google-genai`** SDK. This package is the
ONLY place a provider SDK is imported. No screening here (that's WS5, applied as a
decorator around this wrapper).

## What's done
- `GeminiWrapper` implements the frozen `contracts/model_wrapper` interface:
  - `complete()` → `ModelResponse` (text and/or parsed `ToolCall`s).
  - `stream()` → `AsyncIterator[str]` — **text deltas only**; function-call parts
    are dropped from the token feed (the contract yields `str`).
- **Schema-constrained tool-calling:** `ToolDef.parameters` (raw JSON Schema) is
  passed through verbatim as Gemini `FunctionDeclaration.parameters_json_schema`;
  the model's function calls come back as contract `ToolCall`s. SDK auto-invocation
  is disabled — the caller runs the tool.
- **`tools` vs `response_schema` are mutually exclusive** (Gemini can't do both in
  one generation): supplying both raises `WrapperUsageError` (a `ValueError`) — a
  caller bug, fail-fast, never retried.
- **Tier → model-id map**, all env-overridable (`config.py`):
  | tier | env var | default |
  |---|---|---|
  | `frontier` | `GEMINI_MODEL_FRONTIER` | `gemini-3.5-flash` |
  | `fast` | `GEMINI_MODEL_FAST` | `gemini-3.5-flash` |
  | `voice` | `GEMINI_MODEL_VOICE` | `gemini-3.5-flash` |
  Unknown tier → falls back to `frontier` (a typo degrades, doesn't crash).
- **Reliability (D-reliability):** per-call timeout (`GEMINI_TIMEOUT_S`, default 60s)
  + bounded exponential-backoff-with-jitter retry (`GEMINI_MAX_RETRIES`, default 2)
  on **transient** errors only (timeouts, 429, 5xx). 4xx/auth fail immediately.
  A streamed call is only retried on open; once tokens flow it is not restarted
  (avoids duplicate emitted text).
- **Key/config:** read from env at construction — `GEMINI_API_KEY` or
  `GOOGLE_API_KEY`; missing key → clear `ConfigError`, not a mid-call crash. Never
  committed (see `.gitignore`).
- **Vertex seam (D8):** `GEMINI_USE_VERTEX=1` (+ `GOOGLE_CLOUD_PROJECT` /
  `GOOGLE_CLOUD_LOCATION`) builds the same client against Vertex — a config change.
  Not exercised (per direction, we're staying on the AI-Studio key path).

## What's mocked
- **The google-genai async client** in tests (`tests/fakes.py`): scripts responses,
  streams, and error sequences with zero network. The wrapper's own request-shaping,
  response-collapsing, retry, and streaming logic run for real against it.
- **Live smoke** (`tests/test_smoke_live.py`) is **skipped without a key** and was
  NOT run in this environment (no key present). Run it manually — see below.

## Known limitation / contract note (NOT worked around silently)
- Contract `Message` is `{role, content: str}` with no function name. A `tool`
  message is therefore mapped **lossily** to a `user` turn prefixed
  `"[tool result] "` — enough for preview/builder flows, which only echo the text
  of a tool result. If the builder loop ever needs **typed** function-response
  round-trips (Gemini `function_response` keyed by name), that's a genuine contract
  gap: file `docs/contract-change-requests/ws6.md` proposing `Message` gain an
  optional `name`/`tool_call_id`. Do **not** bend the contract silently.

## Verify
From repo root:

```bash
# Hermetic suite (no network, no key) — 25 pass, 3 live tests skip:
python -m pytest backend/wrapper_impl/tests/ -q

# Live smoke (manual — needs a real key). Proves E2E integration-step-1:
# a real schema-constrained tool-call round-trips through the interface.
GEMINI_API_KEY=<your-key> python -m pytest backend/wrapper_impl/tests/test_smoke_live.py -v -s
```

Last hermetic run here: **25 passed, 3 skipped**.

## Contract points consumed
- `contracts/model_wrapper/interface.py`: `ModelWrapper`, `Message`, `ToolDef`,
  `ToolCall`, `ModelResponse`. No edits to any contract.
