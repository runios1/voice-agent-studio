/**
 * The frontend's single door to the backend seam (contracts/api). Everything the
 * UI needs is expressed as this interface so it can be dependency-injected: the
 * real HTTP impl talks to FastAPI; tests and `npm run dev` (pre-integration) pass
 * a mock impl that replays fixtures. WS1 owns no business logic — this is a thin
 * transport that renders contracts.
 */
import type {
  AgentEnvelope,
  ApiError,
  ConfigPatch,
} from "../types/contracts";
import { parseSseStream, type RawSseEvent } from "./sse";

export class ApiFailure extends Error {
  readonly payload: ApiError["error"];
  constructor(payload: ApiError["error"]) {
    super(payload.message);
    this.name = "ApiFailure";
    this.payload = payload;
  }
}

export interface AgentApi {
  /** GET /agents/{id} — full config + resolved FIELD_POLICY. */
  getAgent(id: string): Promise<AgentEnvelope>;

  /**
   * PATCH /agents/{id}/fields — the manual-edit door. Applies the IDENTICAL
   * server-side gate as builder patches. Resolves with the accepted patch or
   * throws ApiFailure carrying the typed error (locked_path / validation / ...).
   */
  patchField(id: string, path: string, value: unknown): Promise<ConfigPatch>;

  /** POST /agents/{id}/builder/messages (SSE) — token | patch | notice events. */
  openBuilderStream(
    id: string,
    message: string,
    signal?: AbortSignal,
  ): AsyncGenerator<RawSseEvent>;

  /** POST /agents/{id}/preview/messages (SSE) — token events (talk TO the agent). */
  openPreviewStream(
    id: string,
    message: string,
    signal?: AbortSignal,
  ): AsyncGenerator<RawSseEvent>;
}

// --------------------------------------------------------------------------- //
// Real HTTP implementation
// --------------------------------------------------------------------------- //
export function createHttpAgentApi(baseUrl = "/api"): AgentApi {
  async function getAgent(id: string): Promise<AgentEnvelope> {
    const res = await fetch(`${baseUrl}/agents/${encodeURIComponent(id)}`, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!res.ok) throw await toFailure(res);
    return (await res.json()) as AgentEnvelope;
  }

  async function patchField(
    id: string,
    path: string,
    value: unknown,
  ): Promise<ConfigPatch> {
    const res = await fetch(
      `${baseUrl}/agents/${encodeURIComponent(id)}/fields`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ path, value }),
      },
    );
    if (!res.ok) throw await toFailure(res);
    return (await res.json()) as ConfigPatch;
  }

  async function* stream(
    path: string,
    message: string,
    signal?: AbortSignal,
  ): AsyncGenerator<RawSseEvent> {
    const res = await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      credentials: "same-origin",
      body: JSON.stringify({ message }),
      signal,
    });
    if (!res.ok || !res.body) throw await toFailure(res);
    yield* parseSseStream(res.body, signal);
  }

  return {
    getAgent,
    patchField,
    openBuilderStream: (id, message, signal) =>
      stream(`/agents/${encodeURIComponent(id)}/builder/messages`, message, signal),
    openPreviewStream: (id, message, signal) =>
      stream(`/agents/${encodeURIComponent(id)}/preview/messages`, message, signal),
  };
}

async function toFailure(res: Response): Promise<ApiFailure> {
  try {
    const body = (await res.json()) as Partial<ApiError>;
    if (body?.error?.message) return new ApiFailure(body.error);
  } catch {
    /* fall through to a generic failure */
  }
  return new ApiFailure({
    kind: "validation",
    message: `Request failed (${res.status}).`,
  });
}
