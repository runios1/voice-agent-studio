/**
 * "Connect Google Calendar" / "Connect Gmail" — tenant-level tool connections
 * (contracts/connections_http). Renders the provider catalog merged with
 * whatever the server reports as connected; Connect begins OAuth and redirects
 * the browser; Disconnect is a two-click confirm (revoking access is the kind
 * of action worth a deliberate second click, same posture as campaign
 * authorization).
 */
import { useEffect, useState } from "react";
import clsx from "clsx";
import { PROVIDER_CATALOG } from "./catalog";
import type { ConnectionInfo, ConnectionsApi } from "./connectionsApi";
import { ConnectionsFailure } from "./connectionsApi";

export function ConnectionsView({
  api,
  navigate = (url: string) => {
    window.location.href = url;
  },
}: {
  api: ConnectionsApi;
  /** Overridable for tests; defaults to a real browser redirect. */
  navigate?: (url: string) => void;
}) {
  const [connections, setConnections] = useState<ConnectionInfo[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [confirming, setConfirming] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = () => {
    setLoadError(null);
    api
      .list()
      .then(setConnections)
      .catch(() => setLoadError("Couldn't load your connections. Is the backend running?"));
  };

  useEffect(load, [api]);

  const byProvider = new Map((connections ?? []).map((c) => [c.provider, c]));
  const setBusy = (provider: string, busy: boolean) =>
    setPending((p) => {
      const next = { ...p };
      if (busy) next[provider] = true;
      else delete next[provider];
      return next;
    });

  async function onConnect(provider: string) {
    setActionError(null);
    setBusy(provider, true);
    try {
      const url = await api.authorize(provider);
      navigate(url);
    } catch (err) {
      setActionError(
        err instanceof ConnectionsFailure ? err.message : "Couldn't start that connection.",
      );
      setBusy(provider, false);
    }
  }

  async function onDisconnect(provider: string) {
    setActionError(null);
    setConfirming(null);
    setBusy(provider, true);
    try {
      setConnections(await api.disconnect(provider));
    } catch (err) {
      setActionError(
        err instanceof ConnectionsFailure ? err.message : "Couldn't disconnect that.",
      );
    } finally {
      setBusy(provider, false);
    }
  }

  if (loadError) {
    return <p className="p-6 text-sm text-red-700">{loadError}</p>;
  }
  if (!connections) {
    return <p className="p-6 text-sm text-muted">Loading connections…</p>;
  }

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="border-b border-line px-5 py-3">
        <h2 className="text-sm font-semibold">Connections</h2>
        <p className="mt-0.5 text-xs text-muted">
          Grant your agents access to the real tools they book on. Revoking here
          stops new bookings/sends immediately — calls already in progress finish
          on what they already have.
        </p>
      </div>

      {actionError && (
        <div className="bg-red-50 px-5 py-2 text-sm text-red-700" role="alert">
          {actionError}
        </div>
      )}

      <ul className="divide-y divide-line px-5">
        {PROVIDER_CATALOG.map((entry) => {
          const conn = byProvider.get(entry.id);
          const connected = conn?.connected ?? false;
          const busy = pending[entry.id];
          return (
            <li
              key={entry.id}
              data-testid={`connection-row-${entry.id}`}
              className="flex items-center justify-between gap-4 py-3"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{entry.label}</span>
                  <span
                    data-testid={`connection-status-${entry.id}`}
                    className={clsx(
                      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                      connected
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-line text-muted",
                    )}
                  >
                    <span
                      className={clsx(
                        "h-1.5 w-1.5 rounded-full",
                        connected ? "bg-emerald-500" : "bg-slate-400",
                      )}
                    />
                    {connected ? "Connected" : "Not connected"}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-muted">{entry.description}</p>
              </div>

              {connected ? (
                confirming === entry.id ? (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-amber-700">Disconnect?</span>
                    <button
                      data-testid={`confirm-disconnect-${entry.id}`}
                      disabled={busy}
                      onClick={() => onDisconnect(entry.id)}
                      className="rounded-md bg-red-600 px-3 py-1 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                    >
                      {busy ? "…" : "Confirm"}
                    </button>
                    <button
                      onClick={() => setConfirming(null)}
                      className="rounded-md border border-line px-3 py-1 text-sm text-muted hover:bg-panel"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    data-testid={`disconnect-${entry.id}`}
                    onClick={() => setConfirming(entry.id)}
                    className="rounded-md border border-line bg-canvas px-3 py-1 text-sm font-medium text-ink hover:bg-panel"
                  >
                    Disconnect
                  </button>
                )
              ) : (
                <button
                  data-testid={`connect-${entry.id}`}
                  disabled={busy}
                  onClick={() => onConnect(entry.id)}
                  className="rounded-md border border-line bg-canvas px-3 py-1 text-sm font-medium text-ink hover:bg-panel disabled:opacity-50"
                >
                  {busy ? "…" : `Connect ${entry.label}`}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
