import { useEffect, useState } from "react";
import type { AgentApi } from "../api/agentApi";
import { fetchCurrentUser, type AuthUser } from "../auth/authApi";
import { resolveAgentId } from "../auth/agentBootstrap";
import { App } from "./App";
import { LoginScreen } from "./LoginScreen";

type Status =
  | { kind: "loading" }
  | { kind: "signed_out"; error: string | null }
  | { kind: "ready"; user: AuthUser; agentId: string }
  | { kind: "error"; message: string };

/** The real (non-mock) entry point: check the session, then resolve which agent to
 * open, before handing off to the studio `App`. Mock mode skips all of this — see
 * `main.tsx`. */
export function Root({ api }: { api: AgentApi }) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const loginFailed = new URLSearchParams(window.location.search).get("login") === "error";
    if (loginFailed) {
      window.history.replaceState(null, "", window.location.pathname);
    }

    let cancelled = false;
    (async () => {
      const user = await fetchCurrentUser().catch(() => null);
      if (cancelled) return;
      if (!user) {
        setStatus({
          kind: "signed_out",
          error: loginFailed ? "Sign-in didn't go through — try again." : null,
        });
        return;
      }
      try {
        const agentId = await resolveAgentId();
        if (!cancelled) setStatus({ kind: "ready", user, agentId });
      } catch (err) {
        if (!cancelled) {
          setStatus({
            kind: "error",
            message: err instanceof Error ? err.message : "Couldn't load your agent.",
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status.kind === "loading") {
    return <div className="flex h-full items-center justify-center text-muted">Loading…</div>;
  }
  if (status.kind === "signed_out") {
    return <LoginScreen error={status.error} />;
  }
  if (status.kind === "error") {
    return (
      <div className="flex h-full items-center justify-center text-red-600" role="alert">
        {status.message}
      </div>
    );
  }
  return (
    <App
      api={api}
      agentId={status.agentId}
      user={status.user}
      // Reload rather than force the login screen: in open/demo mode a fresh session
      // check drops back to the shared guest workspace; in login mode it 401s → login.
      onSignedOut={() => window.location.reload()}
    />
  );
}
