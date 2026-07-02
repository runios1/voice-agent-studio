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

  /** guards so the agent/builder only auto-opens once per surface */
  builderOpened: boolean;
  previewOpened: boolean;
  /** the preview thread id echoed back on each turn (server-issued) */
  previewSessionId: string | null;

  // actions
  init: (api: AgentApi) => void;
  loadAgent: (id: string) => Promise<void>;
  applyPatch: (path: string, value: unknown) => void;
  editField: (path: string, value: unknown) => Promise<void>;
  sendBuilderMessage: (text: string) => Promise<void>;
  sendPreviewMessage: (text: string) => Promise<void>;
  /** the builder speaks first (greets + asks the first question) */
  startBuilder: () => Promise<void>;
  /** the agent opens the call in preview (an outbound SDR speaks first) */
  startPreview: () => Promise<void>;
  togglePanel: (open?: boolean) => void;
}

let idSeq = 0;
const nextId = (p: string) => `${p}-${++idSeq}`;

/**
 * The builder's opening message. Deliberately STATIC and rendered client-side, so
 * it appears instantly and — crucially — survives a refresh or a new window. A
 * model-generated greeting depended on server session state (an empty-message turn
 * returned nothing once the session already had history), which left the chat blank
 * after a reload. A fixed first line is reliable and costs nothing.
 */
export const BUILDER_GREETING =
  "Hi! I'm your build assistant — I'll turn what you tell me into a working voice " +
  "SDR agent. To start: who will it be calling on behalf of, and what should it do " +
  "on the call (its role and goal)?";

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

export const useAgentStore = create<AgentState>((set, get) => {
  // ------------------------------------------------------------------------- //
  // Builder turn runner. `opening=true` = the builder speaks first (no user
  // bubble, empty message to the server). Otherwise it's a normal user turn.
  // ------------------------------------------------------------------------- //
  const runBuilderTurn = async (text: string, opening: boolean) => {
    const { api, agentId } = get();
    if (!api || !agentId || get().builderStreaming) return;
    if (!opening && !text.trim()) return;

    const assistantId = nextId("a");
    set((s) => ({
      builderStreaming: true,
      messages: [
        ...s.messages,
        ...(opening
          ? []
          : [{ id: nextId("u"), role: "user" as const, text }]),
        { id: assistantId, role: "assistant" as const, text: "", streaming: true },
      ],
    }));

    const appendToken = (chunk: string) =>
      set((s) => ({
        messages: s.messages.map((m) =>
          m.id === assistantId ? { ...m, text: m.text + chunk } : m,
        ),
      }));

    try {
      for await (const ev of api.openBuilderStream(agentId, opening ? "" : text)) {
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
  };

  // ------------------------------------------------------------------------- //
  // Preview turn runner. `opening=true` = the agent opens the call (no user
  // bubble). Threads the server-issued session id so the conversation continues
  // one session — without it every turn would re-disclose and re-open.
  // ------------------------------------------------------------------------- //
  const runPreviewTurn = async (text: string, opening: boolean) => {
    const { api, agentId } = get();
    if (!api || !agentId || get().previewStreaming) return;
    if (!opening && !text.trim()) return;

    const agentMsgId = nextId("pa");
    set((s) => ({
      previewStreaming: true,
      previewMessages: [
        ...s.previewMessages,
        ...(opening
          ? []
          : [{ id: nextId("pu"), role: "user" as const, text }]),
        { id: agentMsgId, role: "assistant" as const, text: "", streaming: true },
      ],
    }));

    try {
      for await (const ev of api.openPreviewStream(
        agentId,
        opening ? "" : text,
        get().previewSessionId,
      )) {
        if (ev.event === "session") {
          const sid = (ev.data as { session_id?: string }).session_id;
          if (sid) set({ previewSessionId: sid });
        } else if (ev.event === "token") {
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
          { id: nextId("notice"), role: "notice", text: "(preview disconnected)" },
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
  };

  return {
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
  builderOpened: false,
  previewOpened: false,
  previewSessionId: null,

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

  sendBuilderMessage: (text) => runBuilderTurn(text, false),
  sendPreviewMessage: (text) => runPreviewTurn(text, false),

  startBuilder: async () => {
    if (get().builderOpened) return;
    // Seed the greeting synchronously and client-side: instant, refresh-safe, no
    // backend round-trip. The user answers this and the real builder loop takes
    // over from their first message.
    set((s) => ({
      builderOpened: true,
      messages: s.messages.length
        ? s.messages
        : [{ id: nextId("greet"), role: "assistant", text: BUILDER_GREETING }],
    }));
  },

  startPreview: async () => {
    if (get().previewOpened) return;
    set({ previewOpened: true });
    await runPreviewTurn("", true);
  },

  togglePanel: (open) => set((s) => ({ panelOpen: open ?? !s.panelOpen })),
  };
});
