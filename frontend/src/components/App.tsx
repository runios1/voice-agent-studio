import { useEffect, useState } from "react";
import clsx from "clsx";
import type { AgentApi } from "../api/agentApi";
import { useAgentStore } from "../store/agentStore";
import { BuilderChat } from "./BuilderChat";
import { PreviewChat } from "./PreviewChat";
import { AgentPanel } from "./AgentPanel";

type Tab = "build" | "preview";

/** App shell: a full-width chat is the primary surface, with the collapsible Agent
 * panel alongside. A tab flips the chat between the builder loop and the preview
 * (talk-to-agent) loop — both share the one config the panel reflects. */
export function App({ api, agentId }: { api: AgentApi; agentId: string }) {
  const init = useAgentStore((s) => s.init);
  const loadAgent = useAgentStore((s) => s.loadAgent);
  const config = useAgentStore((s) => s.config);
  const [tab, setTab] = useState<Tab>("build");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    init(api);
    loadAgent(agentId).catch(() =>
      setError("Couldn't load this agent. Is the backend running?"),
    );
  }, [api, agentId, init, loadAgent]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-line px-4 py-2">
        <span className="text-sm font-semibold">Voice Agent Studio</span>
        <nav className="flex gap-1">
          <TabButton active={tab === "build"} onClick={() => setTab("build")}>
            Build
          </TabButton>
          <TabButton active={tab === "preview"} onClick={() => setTab("preview")}>
            Preview
          </TabButton>
        </nav>
      </header>

      {error && (
        <div className="bg-red-50 px-4 py-2 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_360px]">
        <main className="min-h-0">
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
        <aside className="min-h-0">
          <AgentPanel />
        </aside>
      </div>
    </div>
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
        "rounded-md px-3 py-1 text-sm",
        active ? "bg-panel font-medium text-ink" : "text-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
