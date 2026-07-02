# Workstream 6 — Model wrapper implementation

**Depends on:** `contracts/model_wrapper`.

## Responsibility
- Implement `ModelWrapper` for the chosen provider. **v1: Gemini** — but the builder
  model is "whatever frontier model you can start on today, behind this interface"
  (D8), so this is swappable, not sacred.
- Model tiers (verify exact IDs in the AI Studio console before wiring — preview
  names churn):
  - `frontier` (builder brain): **Gemini 3.1 Pro** — strong reasoning + tool-calls.
  - `fast` (validation/suggestions): **Gemini 3.5 Flash**.
  - `voice` (Phase 2 runtime): **Gemini 3.1 Flash Live** — low-latency Live API.
- **Access path:** start on a Google AI Studio API key; keep calls behind this
  interface so the **AI-Studio → Vertex AI** move (prod quotas/governance) is a
  config change, not a rewrite (D8).

## Boundaries — do NOT
- This is the ONLY place a provider SDK is imported.
- Do not add screening here; that's `backend/security`, applied as a decorator.
