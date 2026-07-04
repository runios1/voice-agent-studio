import type { AgentConfig, AgentMeta } from "../types/contracts";

/**
 * Real accounts have no fixed `agent-demo` to fall back on — each user gets their
 * OWN agents. This resolves which one to open on login: the most recently updated
 * agent if any exist (so returning users land back where they left off), or a
 * freshly created one for a brand-new account.
 */
export async function resolveAgentId(): Promise<string> {
  const listRes = await fetch("/api/agents", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!listRes.ok) throw new Error(`Couldn't load your agents (${listRes.status}).`);
  const agents = (await listRes.json()) as AgentMeta[];
  if (agents.length > 0) {
    const mostRecent = [...agents].sort((a, b) =>
      a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0,
    )[0];
    return mostRecent.id;
  }

  const createRes = await fetch("/api/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({}),
  });
  if (!createRes.ok) throw new Error(`Couldn't create a starting agent (${createRes.status}).`);
  const created = (await createRes.json()) as AgentConfig;
  return created.meta.id;
}
