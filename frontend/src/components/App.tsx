import { useEffect, useState } from "react";
import clsx from "clsx";
import type { AgentApi } from "../api/agentApi";
import type { AuthUser } from "../auth/authApi";
import { logout } from "../auth/authApi";
import { useAgentStore } from "../store/agentStore";
import { useConnectionsStore } from "../connections/connectionsStore";
import { useTheme } from "../lib/useTheme";
import { BuilderChat } from "./BuilderChat";
import { PreviewChat } from "./PreviewChat";
import { AgentPanel } from "./AgentPanel";
import { Wordmark } from "./Brand";

type Tab = "build" | "preview";

/** App shell: a full-width chat is the primary surface, with the collapsible Agent
 * panel alongside. A tab flips the chat between the builder loop and the preview
 * (talk-to-agent) loop — both share the one config the panel reflects.
 *
 * `user`/`onSignedOut` are absent in mock mode (no backend session to reflect). */
export function App({
  api,
  agentId,
  user,
  onSignedOut,
}: {
  api: AgentApi;
  agentId: string;
  user?: AuthUser;
  onSignedOut?: () => void;
}) {
  const init = useAgentStore((s) => s.init);
  const loadAgent = useAgentStore((s) => s.loadAgent);
  const startBuilder = useAgentStore((s) => s.startBuilder);
  const startPreview = useAgentStore((s) => s.startPreview);
  const config = useAgentStore((s) => s.config);
  const [tab, setTab] = useState<Tab>("build");
  const [error, setError] = useState<string | null>(null);
  const { theme, toggle } = useTheme();

  // Load the agent, then let the builder open the conversation (it speaks first).
  useEffect(() => {
    init(api);
    loadAgent(agentId)
      .then(() => startBuilder())
      .catch(() =>
        setError("Couldn't load this agent. Is the backend running?"),
      );
  }, [api, agentId, init, loadAgent, startBuilder]);

  // The first time the user opens Preview, the agent opens the call (outbound SDR
  // speaks first). startPreview guards itself so this fires once.
  useEffect(() => {
    if (tab === "preview" && config) startPreview();
  }, [tab, config, startPreview]);

  // Re-check tenant connections when the window regains focus, so connecting a
  // provider in the Connections tab (a separate page) ungates the matching
  // capability toggle here without needing a manual reload.
  useEffect(() => {
    const refresh = () => void useConnectionsStore.getState().refresh();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header className="glass sticky top-0 z-10 flex items-center gap-4 border-b border-line/70 px-4 py-2.5">
        <Wordmark />

        <nav className="ml-2 flex gap-1 rounded-full border border-line/70 bg-panel/60 p-1">
          <TabButton active={tab === "build"} onClick={() => setTab("build")}>
            Build
          </TabButton>
          <TabButton active={tab === "preview"} onClick={() => setTab("preview")}>
            Preview
          </TabButton>
        </nav>

        <div className="ml-auto flex items-center gap-1.5">
          {/* Cross-link to the operations dashboard (P2-7). Separate entry/root, so a
              plain navigation rather than an in-app tab — keeps the two surfaces and
              their stores decoupled while making the dashboard discoverable. */}
          <a
            href="/dashboard.html"
            className="hidden rounded-full px-3 py-1.5 text-sm text-muted transition-colors hover:bg-panel hover:text-ink sm:block"
          >
            Operations ↗
          </a>
          <button
            onClick={toggle}
            aria-label="Toggle color theme"
            title="Toggle theme"
            className="grid h-8 w-8 place-items-center rounded-full text-muted transition-colors hover:bg-panel hover:text-ink"
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
          {user && (
            <div className="flex items-center gap-2 border-l border-line/70 pl-2 text-sm text-muted">
              <span className="hidden md:inline">{user.email}</span>
              <button
                onClick={() => {
                  logout().then(() => onSignedOut?.());
                }}
                className="rounded-full px-3 py-1.5 transition-colors hover:bg-panel hover:text-ink"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      {error && (
        <div
          className="border-b border-red-500/20 bg-red-500/10 px-4 py-2 text-sm text-red-600 dark:text-red-300"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Build shows the Agent panel (agent details) alongside the chat. Preview drops
          it and goes full-width: the talking preview already carries its own live
          "In your dashboard" pane, so the agent-config panel is redundant there and the
          Call-details table gets the whole width. */}
      <div
        className={clsx(
          "grid min-h-0 flex-1",
          tab === "preview" ? "grid-cols-1" : "grid-cols-[1fr_360px]",
        )}
      >
        <main className="chat-backdrop min-h-0">
          {!config ? (
            <div className="flex h-full items-center justify-center text-muted">
              Loading…
            </div>
          ) : tab === "build" ? (
            <BuilderChat />
          ) : (
            <PreviewChat />
          )}
        </main>
        {tab !== "preview" && (
          <aside className="min-h-0">
            <AgentPanel />
          </aside>
        )}
      </div>
    </div>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="currentColor">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-[18px] w-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "rounded-full px-4 py-1 text-sm transition-all",
        active
          ? "bg-surface font-semibold text-ink shadow-card"
          : "text-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
