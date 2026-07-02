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
