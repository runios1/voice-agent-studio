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
import clsx from "clsx";
import type { FieldPolicy } from "../types/contracts";
import { useAgentStore } from "../store/agentStore";
import { FieldRow } from "./FieldRow";
import { Logomark } from "./Brand";

export function AgentPanel() {
  const config = useAgentStore((s) => s.config);
  const policy = useAgentStore((s) => s.policy);
  const materialized = useAgentStore((s) => s.materialized);
  const panelOpen = useAgentStore((s) => s.panelOpen);
  const togglePanel = useAgentStore((s) => s.togglePanel);

  if (!config) return null;

  const platformFields = policy.filter((p) => p.owner_layer === "platform");
  // Capability switches (calendar/email automation) live in their own always-visible
  // section — they're toggles the user must be able to FIND and flip, not interview
  // answers that materialize once decided. Kept out of the progressive-disclosure
  // list below so they don't depend on `materialized` (and so an unenabled capability
  // still shows an off switch instead of hiding).
  const capabilityFields = policy.filter((p) => p.path.startsWith("automation."));
  const userFields = policy.filter(
    (p) =>
      p.owner_layer === "user" &&
      materialized[p.path] &&
      !p.path.startsWith("automation."),
  );
  const requiredTotal = policy.filter((p) => p.required_for_ready).length;
  const requiredDone = policy.filter(
    (p) => p.required_for_ready && materialized[p.path],
  ).length;

  return (
    <Collapsible.Root
      open={panelOpen}
      onOpenChange={(o) => togglePanel(o)}
      className="flex h-full flex-col border-l border-line bg-panel/60"
    >
      <Collapsible.Trigger
        data-testid="panel-toggle"
        className="group flex items-center gap-3 border-b border-line px-4 py-3.5 text-left transition-colors hover:bg-panel"
      >
        <ProgressRing done={requiredDone} total={requiredTotal} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-ink">
            {config.meta.name}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
            <StatusPill status={config.meta.status} />
            <span>
              {requiredDone}/{requiredTotal} required
            </span>
          </div>
        </div>
        <span className="text-muted transition-transform group-hover:text-ink">
          {panelOpen ? "▸" : "◂"}
        </span>
      </Collapsible.Trigger>

      <Collapsible.Content
        className="min-h-0 flex-1 overflow-y-auto"
        data-testid="panel-content"
      >
        <Section title="🔒 Set by platform" tone="locked">
          {platformFields.map((p) => (
            <FieldRow key={p.path} policy={p} />
          ))}
        </Section>

        <Section title="Your agent">
          {userFields.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-3 py-6 text-center">
              <Logomark className="h-9 w-9 opacity-60" />
              <p className="max-w-[16rem] text-sm text-muted">
                Your agent takes shape here — fields appear here as you describe
                it in the chat.
              </p>
            </div>
          ) : (
            userFields.map((p: FieldPolicy) => <FieldRow key={p.path} policy={p} />)
          )}
        </Section>

        {capabilityFields.length > 0 && (
          <Section title="Capabilities">
            {capabilityFields.map((p: FieldPolicy) => (
              <FieldRow key={p.path} policy={p} />
            ))}
          </Section>
        )}

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

function Section({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: "locked";
  children: React.ReactNode;
}) {
  return (
    <section
      className={clsx(
        "border-b border-line py-2",
        tone === "locked" && "bg-accent/[0.04]",
      )}
    >
      <h3 className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted">
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
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        ready
          ? "bg-signal/15 text-signal"
          : "bg-muted/15 text-muted",
      )}
    >
      <span
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          ready ? "bg-signal animate-pulse-ring" : "bg-muted",
        )}
      />
      {ready ? "Ready" : "Draft"}
    </span>
  );
}

/** A compact conic progress ring for required-field completion. */
function ProgressRing({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div
      className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full"
      style={{
        background: `conic-gradient(rgb(var(--c-accent)) ${pct}%, rgb(var(--c-line)) 0)`,
      }}
      aria-label={`${done} of ${total} required fields complete`}
    >
      <span className="grid h-7 w-7 place-items-center rounded-full bg-panel text-[10px] font-semibold text-ink">
        {pct}%
      </span>
    </div>
  );
}
