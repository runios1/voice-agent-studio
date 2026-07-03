# contracts/live_agent — FROZEN (Phase 4)

The Live-native conversational agent: Gemini Live drives the call; the security spine stays
around it (tools guarded in code, disclosure scripted in code, output moderation as the net).

**Five seams, one package:**
- `LiveAgentSpec` + `LiveAgentCompiler` — config → (system instruction incl. closing
  directions, disclosure line, Live tool declarations). Owned by **P4-1**.
- `AudioTransport` — raw PCM both ways + UI events; browser now (**P4-4**), phone later (**P4-6**).
- `StreamModerator` + `ModerationVerdict` — streaming output screening. Owned by **P4-3**.
- `LiveAgentSession` + `LiveCallContext` + `LiveOutcome` — the runtime. Owned by **P4-2**.

**Reused unchanged (already frozen):** `config_schema`, `tool_registry` (RegistryTool /
ToolHandler / resolve_context — Live function-calls route straight into the guarded handlers),
`events`, `voice_preview` wire protocol (P4-4's browser transport speaks it).

**Non-negotiables (do not "simplify" away):** tool execution stays in the guarded handlers;
the disclosure line is spoken in code before Live connects; the moderator is a net, not the
floor. Audio rates: 16 kHz in, 24 kHz out. Live model `gemini-3.1-flash-live-preview`.

Changing this surface is a **contract-change-request**, not an edit.
