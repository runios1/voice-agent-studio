/**
 * The Agent panel — progressive disclosure (D-UX, D11). Collapsed by default.
 * Two sections:
 *   - "🔒 Set by platform": the base-characteristics/guardrail layer, shown from
 *     the start as a trust feature. Locked fields are read-only; platform DEFAULT
 *     fields (e.g. disclosure script) are tunable.
 *   - "Your agent": user-owned fields that MATERIALIZE one at a time — a field
 *     appears only once an answer has decided it (never an empty selector).
 * A quiet "Noted for later" section reflects the D13 wishlist quarantine, so the
 * user feels heard without those items entering the operative config.
 */
import * as Collapsible from "@radix-ui/react-collapsible";
import type { FieldPolicy } from "../types/contracts";
import { useAgentStore } from "../store/agentStore";
import { FieldRow } from "./FieldRow";

export function AgentPanel() {
  const config = useAgentStore((s) => s.config);
  const policy = useAgentStore((s) => s.policy);
  const materialized = useAgentStore((s) => s.materialized);
  const panelOpen = useAgentStore((s) => s.panelOpen);
  const togglePanel = useAgentStore((s) => s.togglePanel);

  if (!config) return null;

  const platformFields = policy.filter((p) => p.owner_layer === "platform");
  const userFields = policy.filter(
    (p) => p.owner_layer === "user" && materialized[p.path],
  );
  const requiredTotal = policy.filter((p) => p.required_for_ready).length;
  const requiredDone = policy.filter(
    (p) => p.required_for_ready && materialized[p.path],
  ).length;

  return (
    <Collapsible.Root
      open={panelOpen}
      onOpenChange={(o) => togglePanel(o)}
      className="flex h-full flex-col border-l border-line bg-panel"
    >
      <Collapsible.Trigger
        data-testid="panel-toggle"
        className="flex items-center justify-between gap-2 border-b border-line px-4 py-3 text-left"
      >
        <div>
          <div className="text-sm font-semibold text-ink">{config.meta.name}</div>
          <div className="text-xs text-muted">
            <StatusPill status={config.meta.status} /> · {requiredDone}/
            {requiredTotal} required fields
          </div>
        </div>
        <span className="text-muted">{panelOpen ? "▸" : "◂"}</span>
      </Collapsible.Trigger>

      <Collapsible.Content
        className="min-h-0 flex-1 overflow-y-auto"
        data-testid="panel-content"
      >
        <Section title="🔒 Set by platform">
          {platformFields.map((p) => (
            <FieldRow key={p.path} policy={p} />
          ))}
        </Section>

        <Section title="Your agent">
          {userFields.length === 0 ? (
            <p className="px-3 py-2 text-sm text-muted">
              Fields appear here as you describe your agent.
            </p>
          ) : (
            userFields.map((p: FieldPolicy) => <FieldRow key={p.path} policy={p} />)
          )}
        </Section>

        {config.wishlist.length > 0 && (
          <Section title="Noted for later (not active)">
            <ul className="px-3 py-1 text-sm text-muted">
              {config.wishlist.map((w, i) => (
                <li key={i} className="list-inside list-disc">
                  {w}
                </li>
              ))}
            </ul>
          </Section>
        )}
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-line py-2">
      <h3 className="px-4 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
        {title}
      </h3>
      <div className="flex flex-col gap-1 px-1">{children}</div>
    </section>
  );
}

function StatusPill({ status }: { status: string }) {
  const ready = status === "ready";
  return (
    <span
      data-testid="agent-status"
      className={
        ready ? "font-medium text-accent" : "font-medium text-muted"
      }
    >
      {ready ? "Ready" : "Draft"}
    </span>
  );
}
