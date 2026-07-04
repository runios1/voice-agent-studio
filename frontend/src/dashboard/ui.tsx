/** Small presentational primitives shared across the four dashboard views. Pure
 *  rendering — no store access, no control logic. */
import clsx from "clsx";
import type { CampaignState, EventType, LeadState, Severity } from "./types";

/** Semantic status tints, theme-aware (readable in light AND dark). Shared so every
 *  badge/pill across the dashboard speaks the same color language. */
export const TONE = {
  success: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  warning: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  danger: "bg-red-500/15 text-red-600 dark:text-red-300",
  info: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  neutral: "bg-line text-muted",
} as const;

const CAMPAIGN_TONE: Record<CampaignState, string> = {
  draft: TONE.neutral,
  running: TONE.success,
  paused: TONE.warning,
  completed: TONE.neutral,
};

export function CampaignStateBadge({ state }: { state: CampaignState }) {
  return (
    <span
      data-testid={`campaign-state-${state}`}
      className={clsx(
        "inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize",
        CAMPAIGN_TONE[state],
      )}
    >
      {state}
    </span>
  );
}

export function LeadStateBadge({ state }: { state: LeadState }) {
  return (
    <span className="inline-block rounded px-1.5 py-0.5 text-xs capitalize text-muted">
      {state.replace("_", " ")}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity, string> = {
  info: "bg-muted/60",
  warning: "bg-amber-400",
  critical: "bg-red-500",
};

export function SeverityDot({ severity }: { severity: Severity }) {
  return (
    <span
      title={severity}
      aria-label={severity}
      className={clsx(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        SEVERITY_TONE[severity],
      )}
    />
  );
}

/** Compliance-critical event types get a subtle emphasis in the trail/audit. */
const CRITICAL_TYPES = new Set<EventType>([
  "disclosure.spoken",
  "guardrail.tripped",
  "campaign.autopaused",
  "call.escalated",
]);

export function EventTypeLabel({ type }: { type: EventType }) {
  return (
    <span
      className={clsx(
        "font-mono text-xs",
        CRITICAL_TYPES.has(type) ? "font-semibold text-ink" : "text-muted",
      )}
    >
      {type}
    </span>
  );
}

export function ControlButton({
  onClick,
  pending,
  disabled,
  danger,
  children,
  testid,
  title,
}: {
  onClick: () => void;
  pending?: boolean;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
  testid?: string;
  title?: string;
}) {
  return (
    <button
      data-testid={testid}
      title={title}
      onClick={onClick}
      disabled={disabled || pending}
      className={clsx(
        "rounded-lg px-3 py-1.5 text-sm font-medium shadow-card transition disabled:opacity-50",
        danger
          ? "bg-red-600 text-white hover:bg-red-700"
          : "border border-line bg-surface text-ink hover:bg-panel",
      )}
    >
      {pending ? "…" : children}
    </button>
  );
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function ProgressBar({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-line">
      <div
        className="h-full rounded-full transition-all"
        style={{
          width: `${pct}%`,
          backgroundImage:
            "linear-gradient(90deg, rgb(var(--c-accent)), rgb(var(--c-signal)))",
        }}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  );
}
