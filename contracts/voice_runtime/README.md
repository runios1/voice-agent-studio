# voice_runtime/ — voice-runtime interface (Phase 2, FROZEN)

Generalizes `backend/runtime_loop/engine.RuntimeEngine`: the transport swaps
(text → voice), while the code-emitted AI-disclosure step, least-privilege tool
layer, and deterministic prompt composition stay identical. `CallTransport` is
provider-agnostic (Retell → LiveKit is a swap, D9). Adapters/impl live in P2-1;
the existing text engine is the reference `CallTransport`.
