# contracts/ — the frozen critical path

> **STATUS: FROZEN for Phase 1** (ratified in the contract-freeze pass). Safe to
> fan out the six workstreams against these. To change a contract, file a
> `docs/contract-change-requests/` entry — do not edit in place. Expect deliberate
> versioning after Phase 1 once we see what fails and succeeds.

These three contracts block everything. Freeze them, then all six workstreams
fan out in parallel against them (D14). Change them only deliberately, and
announce it — a change here is a cross-cutting event.

| Contract | File | Consumed by |
|---|---|---|
| **Config schema** | `config_schema/schema.py` + `field_policy.py` | every workstream |
| **API contract** | `api/api_contract.md` | frontend ⇄ backend |
| **Model wrapper interface** | `model_wrapper/interface.py` | builder, runtime, security, wrapper impl |

Rule of thumb: if two workstreams need to agree on something, it belongs here.

## Phase 2 contracts — FROZEN

Ratified in the Phase-2 freeze pass. Fan out P2-1…P2-7 against these
(`docs/phase2-workstream-prompts.md`). Same rule: change via
`docs/contract-change-requests/`, never edit in place.

| Contract | File | Consumed by |
|---|---|---|
| **Event schema** *(keystone)* | `events/schema.py` | P2-5, P2-6, P2-7, every emitter |
| **Tool registry interface** | `tool_registry/interface.py` | P2-1, P2-3, P2-4 |
| **Campaign + lead model** | `campaign/model.py` | P2-2, P2-7 |
| **Voice-runtime interface** | `voice_runtime/interface.py` | P2-1, P2-2 |

Design notes locked in the freeze grill: `EventType` is a **closed enum**; event
`payload` is a **generic dict** validated per-type by P2-5; tools are keyed by
automation-block name so **no Phase-1 schema change is needed**; the campaign
`GuardrailEnvelope` can only be equal-or-stricter than the locked guardrails.
