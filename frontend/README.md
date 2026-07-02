# Workstream 1 — Frontend

**Stack:** React (D10). **Depends only on:** `contracts/api`.

## Responsibility
- **Chat-first UI** — full-width, ChatGPT/Gemini-feeling. This is the primary and
  *only required* surface (D-UX). The builder confirms progress conversationally,
  inline — not via a filling form.
- **Agent panel — progressive disclosure.** Collapsed by default. When open, shows
  the agent's identity **materializing live**: a field appears only once an answer
  has established it (D-UX). NO empty user selectors before a field is decided.
- **Locked guardrails** shown from the start in a distinct "🔒 Set by platform"
  section (D11) — read-only, a trust feature.
- **Manual editing** of `open`/`default` fields via `PATCH /agents/{id}/fields`.
  Manual edits and chat edits mutate the same config; keep them in sync.
- **Preview chat** — a separate surface to talk *to* the built agent (runtime loop).

## Boundaries — do NOT
- Do not enforce locks/validation only in the UI. The UI reflects policy for UX,
  but the server is the real gate. Show read-only badges from `FIELD_POLICY`.
- Do not hold business logic; render contracts.

## Consumes
`GET /agents/{id}` (config + policy), builder SSE, preview SSE, `PATCH .../fields`.
