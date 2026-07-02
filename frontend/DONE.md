# WS1 — Frontend — DONE

Chat-first React UI for voice-agent-studio. Depends only on `contracts/api`
(consumed as `src/types/contracts.ts`, a read-only TS mirror of the frozen
schema / field_policy / api contract). No backend business logic lives here.

## Internal decisions (grill outcomes)
Proceeded on recommendations (user was away):
- **Stack:** Vite + React + TypeScript + Tailwind + Radix (`Collapsible`).
- **Patch model: server-authoritative.** The UI is a reflection of server truth,
  never ahead of it. Builder patches apply on the SSE `patch` event; manual edits
  apply only after `PATCH /fields` returns success; typed errors become notices and
  leave the config untouched. (Mirrors the D-security "server is the real gate" rule.)
- **State:** one Zustand store (`src/store/agentStore.ts`) holds the shared config,
  policy, both transcripts, and stream status — so chat + panel stay in sync.
- **SSE UX:** `token` → the assistant bubble; `patch` → the panel field materializes
  silently with a brief highlight (no chat clutter); `notice` → an inline muted line.

## What's done
- **Renders a fixture `AgentConfig` + `FIELD_POLICY`** with lock badges and a
  "🔒 Set by platform" section (`AgentPanel`, `FieldRow`). Locked fields are
  read-only; platform `default` fields are tunable and tagged.
- **Progressive disclosure** — a user field appears only once decided; enum/select
  fields (schema defaults) require an explicit patch (no empty selector showing an
  answer the user never gave).
- **Builder chat consumes SSE and interleaves** token/patch/notice; a patch
  materializes a panel field mid-stream (proven event-by-event).
- **Manual edit of an open field** calls `PATCH /agents/{id}/fields` via
  `editField` → `api.patchField`; accepted patches apply, locked/invalid become
  conversational notices.
- **Preview chat surface** (`PreviewChat`) — talk *to* the built agent; text-only,
  swappable for the voice Live API in Phase 2.
- Radix collapsible Agent panel (collapsed by default); D13 `wishlist` shown in a
  quiet "Noted for later (not active)" section.

## What's mocked (and where the real thing plugs in)
- **The entire backend.** `AgentApi` (`src/api/agentApi.ts`) is the single seam.
  - `src/dev/mockApi.ts` — a scripted builder interview for `npm run dev` before
    WS2–6 are merged.
  - `src/test/mocks.ts` — fine-grained doubles for tests.
  - **Integration flip:** run with `VITE_USE_MOCK=false` (FastAPI up) → the real
    `createHttpAgentApi()` talks to the seam via the Vite `/api` proxy. No component
    changes; only `src/main.tsx` reads the flag.
- Fixtures (`src/fixtures/agentFixture.ts`) mirror `field_policy.py` and the shape
  `POST /agents` returns. If they drift from the frozen contract, that's a bug here.

## Known Phase-1 limitations (intentional)
- List/object fields (qualification criteria, objections, calendar, email) are
  **display-only** in the panel — edited via chat, not inline. Scalar open/default
  fields are inline-editable. Noted for a later pass.
- A `select` field the user set won't **re-materialize on reload** (its value is
  indistinguishable from the schema default). It re-appears as soon as it's patched
  again. Acceptable for the skeleton; revisit if reload UX needs it.

## Contract points consumed
`GET /agents/{id}` (config + resolved `FIELD_POLICY`), builder SSE
(`token`/`patch`/`notice`/`done`), preview SSE (`token`/`done`),
`PATCH /agents/{id}/fields`, and the typed error shape
(`locked_path|validation|screening_blocked|screening_flagged|rate_limited`).
No contract-change-request was needed — the frozen `contracts/api` was sufficient.

## How to verify
```bash
cd frontend
npm install
npm run typecheck   # tsc -b --noEmit — clean
npm test            # vitest run — 23 tests across 7 files, all green
npm run build       # tsc -b && vite build — succeeds
npm run dev         # http://localhost:5173 — runs against the mock interview
```
Automated coverage (all passing):
- `src/lib/paths.test.ts` — dotted get/set (immutable) + meaningfulness.
- `src/api/sse.test.ts` — SSE parsing across chunk boundaries, CRLF, trailing record.
- `src/store/agentStore.test.ts` — materialization seeding; token/patch/notice
  interleaving; server-authoritative accept + locked-path rejection.
- `src/store/interleave.test.ts` — a patch materializes mid-stream, before `done`.
- `src/components/AgentPanel.test.tsx` — locked section read-only; progressive
  disclosure; default-field editability; empty-state.
- `src/components/FieldRow.test.tsx` — open-field edit fires `PATCH`; locked field
  has no editor.
- `src/components/PreviewChat.test.tsx` — agent reply streams into the transcript.

**Manual browser check (not run here — no browser extension connected in this
session):** `npm run dev`, describe an agent turn-by-turn, watch fields materialize
in the panel, hand-edit an open field, switch to the Preview tab and talk to the
agent. The RTL tests exercise the same flows against a real DOM.

## Handoff
Branch `ws/1-frontend`. Do NOT merge — integrator merges in dependency order
(6 → 5 → 2 → {3,4} → 1). At WS1 merge: set `VITE_USE_MOCK=false`, bring up FastAPI,
delete reliance on `src/dev/mockApi.ts`, and run the full-loop browser E2E.
