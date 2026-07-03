/**
 * The frontend's door to `contracts/connections_http` (FROZEN, Phase 3) — the
 * tenant's "Connect Google Calendar" / "Connect Gmail" flow. Thin transport only,
 * dependency-injected like `AgentApi`/`DashboardApi`: the real impl talks to
 * FastAPI, `npm run dev` and tests pass a mock. This module owns no OAuth logic —
 * it only calls the seam and hands back what the server said.
 *
 * The actual token exchange happens entirely server-side (P3-1): this client
 * only ever sees an opaque `connection_ref`, never a token (contract README §Security).
 */

export interface ConnectionInfo {
  provider: string; // "google_calendar" | "gmail" | ...
  connected: boolean;
  scopes: string[];
  connection_ref?: string | null;
}

export class ConnectionsFailure extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ConnectionsFailure";
    this.status = status;
  }
}

export interface ConnectionsApi {
  /** GET /api/connections — every provider this tenant has (or hasn't) connected. */
  list(): Promise<ConnectionInfo[]>;

  /** POST /api/connections/{provider}/authorize — begin OAuth; resolves with the
   *  URL to send the browser to (the caller redirects `window.location`). */
  authorize(provider: string): Promise<string>;

  /** DELETE /api/connections/{provider} — revoke; returns the refreshed list. */
  disconnect(provider: string): Promise<ConnectionInfo[]>;
}

// --------------------------------------------------------------------------- //
// Real HTTP implementation
// --------------------------------------------------------------------------- //
export function createHttpConnectionsApi(baseUrl = "/api"): ConnectionsApi {
  async function getJson<T>(path: string): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!res.ok) throw await toFailure(res);
    return (await res.json()) as T;
  }

  return {
    async list() {
      const body = await getJson<{ connections: ConnectionInfo[] }>("/connections");
      return body.connections;
    },

    async authorize(provider) {
      const res = await fetch(
        `${baseUrl}/connections/${encodeURIComponent(provider)}/authorize`,
        {
          method: "POST",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        },
      );
      if (!res.ok) throw await toFailure(res);
      const body = (await res.json()) as { authorization_url: string };
      return body.authorization_url;
    },

    async disconnect(provider) {
      const res = await fetch(
        `${baseUrl}/connections/${encodeURIComponent(provider)}`,
        {
          method: "DELETE",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        },
      );
      if (!res.ok) throw await toFailure(res);
      const body = (await res.json()) as { connections: ConnectionInfo[] };
      return body.connections;
    },
  };
}

async function toFailure(res: Response): Promise<ConnectionsFailure> {
  let message = `Request failed (${res.status}).`;
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    if (body?.error?.message) message = body.error.message;
  } catch {
    /* keep the generic message */
  }
  return new ConnectionsFailure(message, res.status);
}
