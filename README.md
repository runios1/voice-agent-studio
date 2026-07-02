# voice-agent-studio *(codename — rename freely)*

A platform where a user **chats with a builder AI** that generates a **voice-AI
SDR assistant** — one that calls leads, qualifies them, and books meetings. The
provider (you) defines base characteristics + locked guardrails; the end user
tunes the details within those rails.

> **Full product spec & architecture:** [`CLAUDE.md`](./CLAUDE.md)
> **Locked design decisions:** [`docs/decisions.md`](./docs/decisions.md)

## How this repo is meant to be built — in parallel

Tiny **critical path**, then a wide **fan-out** (see `CLAUDE.md` → Parallelization).

1. **Freeze the 3 contracts first** (`contracts/`): config schema, API, model wrapper.
2. Then six workstreams proceed independently against those frozen seams:

| # | Workstream | Path |
|---|---|---|
| 1 | Frontend (chat-first UI + Agent panel + preview) | `frontend/` |
| 2 | Config gate + persistence (the enforcement boundary) | `backend/config_gate/` |
| 3 | Builder loop (goal-seeking interviewer, patches) | `backend/builder_loop/` |
| 4 | Runtime loop (text preview → voice later) | `backend/runtime_loop/` |
| 5 | Security / screening (Model Armor at the wrapper) | `backend/security/` |
| 6 | Model wrapper impl (Gemini adapter) | `backend/wrapper_impl/` |

Each workstream's `README.md` states its responsibility, its dependencies, and —
importantly — its **boundaries** (what NOT to do, so streams don't collide).

## Status
Scaffold + frozen contracts + stubs. No working code yet — each stream fills in
its own. This is Phase 1: prove the chat→config pipe on the right models, no
random errors; no real telephony or tools yet (architected so they slot in).
