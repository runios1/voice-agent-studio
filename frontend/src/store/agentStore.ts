/**
 * The single source of UI truth: one Zustand store holds the shared AgentConfig,
 * the FIELD_POLICY, both chat transcripts, and stream status. The builder loop and
 * manual edits mutate THIS same config, so the chat and the panel stay in sync
 * (D-UX bidirectional sync).
 *
 * Patch model = SERVER-AUTHORITATIVE. The UI is a reflection of server truth, never
 * ahead of it (mirrors the D-security rule that the server gate — not the UI — is
 * the boundary):
 *   - builder patches apply when the SSE `patch` event arrives (already accepted);
 *   - manual edits apply ONLY after PATCH /fields returns success; a typed error
 *     becomes a conversational notice and the config is left untouched.
 */
import { create } from "zustand";
import type {
  AgentConfig,
  FieldPolicy,
} from "../types/contracts";
import type { AgentApi } from "../api/agentApi";
import { ApiFailure } from "../api/agentApi";
import { getPath, isMeaningful, setPath } from "../lib/paths";
import { metaFor } from "../lib/fieldMeta";

export type ChatRole = "user" | "assistant" | "notice";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  streaming?: boolean;
}

export interface AgentState {
  api: AgentApi | null;
  agentId: string | null;
  config: AgentConfig | null;
  policy: FieldPolicy[];

  /** user-field paths that have been "decided" and should show in the panel */
  materialized: Record<string, true>;
  /** paths that just changed — drives the brief highlight animation */
  flashing: Record<string, true>;

  messages: ChatMessage[]; // builder transcript
  previewMessages: ChatMessage[]; // preview (talk-to-agent) transcript
  builderStreaming: boolean;
  previewStreaming: boolean;
  panelOpen: boolean;

  // actions
  init: (api: AgentApi) => void;
  loadAgent: (id: string) => Promise<void>;
  applyPatch: (path: string, value: unknown) => void;
  editField: (path: string, value: unknown) => Promise<void>;
  sendBuilderMessage: (text: string) => Promise<void>;
  sendPreviewMessage: (text: string) => Promise<void>;
  togglePanel: (open?: boolean) => void;
}

let idSeq = 0;
const nextId = (p: string) => `${p}-${++idSeq}`;

/** Seed which user fields are already "decided" from a loaded config. Only strings
 * and non-empty lists auto-materialize; enums/bools/numbers/objects with schema
 * defaults must be explicitly patched to appear (no empty-selector-before-answer). */
export function seedMaterialized(
  config: AgentConfig,
  policy: FieldPolicy[],
): Record<string, true> {
  const out: Record<string, true> = {};
  for (const fp of policy) {
    if (fp.owner_layer !== "user") continue;
    // A select/enum field carries a schema default (e.g. voicemail = "hang_up")
    // that is indistinguishable from a real choice by value alone. Don't seed it
    // from load — it materializes only on an explicit patch (D-UX: no empty
    // selector showing an answer the user never gave). Known Phase-1 limitation:
    // such a field won't re-materialize on reload; see DONE.md.
    if (metaFor(fp.path).editor.kind === "select") continue;
    const v = getPath(config, fp.path);
    if ((typeof v === "string" || Array.isArray(v)) && isMeaningful(v)) {
      out[fp.path] = true;
    }
  }
  return out;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  api: null,
  agentId: null,
  config: null,
  policy: [],
  materialized: {},
  flashing: {},
  messages: [],
  previewMessages: [],
  builderStreaming: false,
  previewStreaming: false,
  panelOpen: false,

  init: (api) => set({ api }),

  loadAgent: async (id) => {
    const api = get().api;
    if (!api) throw new Error("agentStore.init(api) must be called first");
    const { config, policy } = await api.getAgent(id);
    set({
      agentId: id,
      config,
      policy,
      materialized: seedMaterialized(config, policy),
      flashing: {},
    });
  },

  applyPatch: (path, value) => {
    const cfg = get().config;
    if (!cfg) return;
    const next = setPath(cfg, path, value);
    set((s) => ({
      config: next,
      materialized: { ...s.materialized, [path]: true },
      flashing: { ...s.flashing, [path]: true },
    }));
    // clear the highlight after the animation window
    setTimeout(() => {
      set((s) => {
        if (!s.flashing[path]) return s;
        const { [path]: _drop, ...rest } = s.flashing;
        return { flashing: rest };
      });
    }, 1200);
  },

  editField: async (path, value) => {
    const { api, agentId } = get();
    if (!api || !agentId) return;
    try {
      const accepted = await api.patchField(agentId, path, value);
      // server-authoritative: apply only what the gate accepted
      get().applyPatch(accepted.path, accepted.value);
    } catch (err) {
      const message =
        err instanceof ApiFailure
          ? err.payload.message
          : "I couldn't save that just now — try again in a moment.";
      set((s) => ({
        messages: [
          ...s.messages,
          { id: nextId("notice"), role: "notice", text: message },
        ],
      }));
    }
  },

  sendBuilderMessage: async (text) => {
    const { api, agentId } = get();
    if (!api || !agentId || !text.trim() || get().builderStreaming) return;

    const assistantId = nextId("a");
    set((s) => ({
      builderStreaming: true,
      messages: [
        ...s.messages,
        { id: nextId("u"), role: "user", text },
        { id: assistantId, role: "assistant", text: "", streaming: true },
      ],
    }));

    const appendToken = (chunk: string) =>
      set((s) => ({
        messages: s.messages.map((m) =>
          m.id === assistantId ? { ...m, text: m.text + chunk } : m,
        ),
      }));

    try {
      for await (const ev of api.openBuilderStream(agentId, text)) {
        if (ev.event === "token") {
          appendToken((ev.data as { text: string }).text ?? "");
        } else if (ev.event === "patch") {
          const p = ev.data as { path: string; value: unknown };
          get().applyPatch(p.path, p.value);
        } else if (ev.event === "notice") {
          const n = ev.data as { message: string };
          set((s) => ({
            messages: [
              ...s.messages,
              { id: nextId("notice"), role: "notice", text: n.message },
            ],
          }));
        } else if (ev.event === "done") {
          break;
        }
      }
    } catch {
      set((s) => ({
        messages: [
          ...s.messages,
          {
            id: nextId("notice"),
            role: "notice",
            text: "I lost the connection for a second — say that again?",
          },
        ],
      }));
    } finally {
      set((s) => ({
        builderStreaming: false,
        messages: s.messages.map((m) =>
          m.id === assistantId ? { ...m, streaming: false } : m,
        ),
      }));
    }
  },

  sendPreviewMessage: async (text) => {
    const { api, agentId } = get();
    if (!api || !agentId || !text.trim() || get().previewStreaming) return;

    const agentMsgId = nextId("pa");
    set((s) => ({
      previewStreaming: true,
      previewMessages: [
        ...s.previewMessages,
        { id: nextId("pu"), role: "user", text },
        { id: agentMsgId, role: "assistant", text: "", streaming: true },
      ],
    }));

    try {
      for await (const ev of api.openPreviewStream(agentId, text)) {
        if (ev.event === "token") {
          const chunk = (ev.data as { text: string }).text ?? "";
          set((s) => ({
            previewMessages: s.previewMessages.map((m) =>
              m.id === agentMsgId ? { ...m, text: m.text + chunk } : m,
            ),
          }));
        } else if (ev.event === "done") {
          break;
        }
      }
    } catch {
      set((s) => ({
        previewMessages: [
          ...s.previewMessages,
          {
            id: nextId("notice"),
            role: "notice",
            text: "(preview disconnected)",
          },
        ],
      }));
    } finally {
      set((s) => ({
        previewStreaming: false,
        previewMessages: s.previewMessages.map((m) =>
          m.id === agentMsgId ? { ...m, streaming: false } : m,
        ),
      }));
    }
  },

  togglePanel: (open) =>
    set((s) => ({ panelOpen: open ?? !s.panelOpen })),
}));
