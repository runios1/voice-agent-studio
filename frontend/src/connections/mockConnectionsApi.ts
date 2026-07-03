/**
 * A mock ConnectionsApi for `npm run dev` before P3-1 is merged. `authorize`
 * doesn't hit a real OAuth provider — it "connects" immediately and returns a
 * harmless `about:blank#...` URL so the dev flow completes without a browser
 * redirect loop. DEV SCAFFOLDING, not a contract — tests use their own fine-
 * grained doubles (see ConnectionsView.test.tsx).
 */
import type { ConnectionInfo, ConnectionsApi } from "./connectionsApi";

export function createMockConnectionsApi(): ConnectionsApi {
  const connections = new Map<string, ConnectionInfo>([
    [
      "google_calendar",
      {
        provider: "google_calendar",
        connected: true,
        scopes: ["https://www.googleapis.com/auth/calendar.events"],
        connection_ref: "conn-calendar-demo",
      },
    ],
  ]);

  return {
    async list() {
      return Array.from(connections.values()).map((c) => ({ ...c }));
    },

    async authorize(provider) {
      connections.set(provider, {
        provider,
        connected: true,
        scopes: [],
        connection_ref: `conn-${provider}-demo`,
      });
      return `about:blank#mock-oauth-${provider}`;
    },

    async disconnect(provider) {
      connections.delete(provider);
      return Array.from(connections.values()).map((c) => ({ ...c }));
    },
  };
}
