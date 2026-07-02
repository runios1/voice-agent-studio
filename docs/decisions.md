# Decision log

Locked decisions from the design session. Contributors (human or agent) should
treat these as settled — do not re-litigate; if reality forces a change, amend
here and flag it as cross-cutting.

| # | Decision | Rationale (short) |
|---|---|---|
| **D0** | Product = a **voice-AI SDR-in-a-box**: chat with a builder AI → it generates a voice assistant that calls leads, qualifies, books meetings. | — |
| **D0.1** | "Phases" = incremental build, not demo milestones. Keep the full picture in mind; flag any choice that caps future voice/tools. | — |
| **D1** | **Phase 1 = the skeleton, de-risked**: website + user UX + a working chat→config generation pipe, on the right models, no random errors. NOT a hand-crafted production SDR yet. | Validate the pipe and pick the tools. |
| **D3** | An agent is a **structured config object with free-text pockets**, not a prompt blob. Per-field control metadata: locked / default / open. | Only shape where the guardrail thesis is *enforceable*, not aspirational. |
| **D4** | **Two control layers**: platform (locked defaults + suggested defaults) and user (open overrides). (Org/team layer deferred — accepted as a resolution-engine rewrite if ever needed.) | Keep Phase 1 lean. |
| **D5** | Builder **patches via structured tool-calls**; locked paths rejected at the patch boundary; live "agent card" reflects each change. Chat is the only editing surface in Phase 1 (+ manual field edits). | Enforceable locks + auditable diffs + deterministic. |
| **D6** | Runtime split by **timing**, not predictable-vs-unpredictable: fast **in-call functions** (LLM+tools) vs **async n8n-style workflows** post-call. Schema carries `conversation` (say-guardrails) + `automation` (do-guardrails). | In-call actions happen mid-conversation; graphs are too slow for that. |
| **D7** | **Vertical (SDR)** in content; engine kept vertical-agnostic (guardrail packs per vertical later). | Horizontal guts the provider-value thesis → commodity. |
| **D8** | **Own the generation loop** on a frontier model (Gemini for now) behind a wrapper. Model tiers picked; AI-Studio-now / Vertex-later access. | A managed platform hides the exact layer that IS the product. |
| **D9** | **Provider-agnostic model wrapper**; builder-LLM and voice-LLM may differ (voice frameworks are model-agnostic). Builder model = "whatever frontier model you can start on today." | Wrapper makes model choice a config line; low-stakes/reversible. |
| **D10** | Stack: **React + FastAPI + Postgres (jsonb) + SSE**. Two-pane rejected in favor of chat-first. | Python-first keeps backend + future voice runtime one language. |
| **D-UX** | **Chat-first with progressive disclosure.** Single chat is primary & sufficient; a collapsible Agent panel shows identity **materializing live** (a field appears only once decided — no empty user selectors); manual editing available; bidirectional sync with chat. | Freedom + precision + trust, without form-theater. |
| **D11** | Locked platform guardrails shown up front in a "🔒 Set by platform" section. Rule = "no empty *user* fields before decided," not "nothing before answered." | Transparency = trust, not clutter. |
| **D12** | Builder = **goal-seeking interviewer** driven by an **authored completeness model** (= the required fields in `field_policy.py`), which also defines "deploy-ready". Text **preview** included → two loops (builder edits / runtime executes) over one config. | Complete agents without a robotic script; config that never runs isn't validated. |
| **D13** | **Four-way triage** of user-volunteered detail: harmful→refuse; supported→structured field; flavor→free-text pocket; unsupported-capability→acknowledge + quarantine to `wishlist`, keep out of operative config. | A live agent must never be configured to promise what it can't do. |
| **D-security** | Enforcement at a **source-agnostic server-side gate**. **Defense in depth**: (1) can't-do-it (least-privilege function params, allowlisted URLs), (2) can't-know-it (least context, server-side tenant isolation), (3) probabilistic screening (Model Armor / Lakera) on every model in/out — the layer *allowed to fail*. | Can't enumerate every threat → remove capability & knowledge, then screen the rest. |
| **D-reliability** | **Constrain → validate → gracefully recover.** Schema-constrained generation makes malformed output impossible; validation catches semantic slips; bounded auto-retry; worst case = a calm re-ask, never a stack trace. Schema is single source of truth. | Direct answer to "no random errors." |
| **D14** | Build for **parallel dev**: tiny critical path (3 frozen contracts) → 6-way fan-out. Repo = scaffold + frozen contracts + stubs (no working code yet). | Parallelism is earned by frozen seams. |
| **D-defaults** | Multiple agents per user; versioned config + undo; minimal single-provider OAuth; SDR completeness-model v1 drafted into `field_policy.py`. | Sensible defaults, changeable. |

## Phase 2 decisions

See `docs/phase2-plan.md` for the full architecture + parallel decomposition.

| # | Decision | Rationale (short) |
|---|---|---|
| **P2-D1** | **Bounded autonomy**: a human authorizes a campaign (agent + lead list + schedule + guardrail envelope); the agent then runs it **unsupervised within that envelope** — dials, qualifies, books, follows up, retries — with hard stops + escalation, no per-call approval. | Real independence + a human-authorized boundary, the only responsible posture for autonomously dialing strangers under DNC/disclosure law. |
| **P2-D2** | **Execution = queue + per-lead state persisted in Postgres** (resume-from-DB after crash; idempotent, no double-dial). Lifecycle isolated behind an interface so a durable-workflow engine can replace it later. n8n-style engine stays for user-configurable post-call automations (D6). | Lean start the user asked for, without painting into a corner. |
| **P2-D3** | **Kill switch, 4 layers, one mechanism** (a state flag workers honor): campaign pause, global emergency stop, and auto-pause triggers (guardrail-trip patterns/anomalies). On stop: **stop new calls immediately, let live calls finish gracefully.** | Most important control for an autonomous dialer; hard-aborting a live human call is itself a compliance risk. |
| **P2-D4** | **Tooling = platform tool registry** (curated catalog; least-privilege scopes; guardrailed params) **+ per-tenant OAuth connections** (encrypted, tenant-scoped) **+ config references the registry.** Registry **is** the four-way-triage capability list; adding a tool graduates wishlist items. Curated, not self-serve. | Keeps every guardrail at the tool boundary (D6/D-security); tenant isolation intact; capability surface is your roadmap. |
| **P2-D5** | **Observability = a structured event stream** (`call.started`, `disclosure.spoken`, `guardrail.tripped`, `slot.booked`, `call.escalated`, `campaign.autopaused`, `lead.outcome`, …) as the **single source** feeding dashboard + auto-pause + audit log + analytics. Immutable event log = compliance proof. Dashboard altitudes: fleet / campaign / live-call / audit. | One source for four consumers; auto-pause requires it; audit log keeps you out of legal trouble. |
| **P2-D6** *(flagged defaults)* | Voice runtime **starts on a managed platform (Retell — compliance-leaning), behind the runtime-loop interface**, swap to LiveKit at scale (D9 model-agnostic). Live-call **escalation = warm transfer-to-human** as a registry action on defined conditions (lead asks for a human / low confidence / guardrail edge). | Managed-first gets real calls working fast (start-of-dev), swap later per the <10k/>10k-min research. |
