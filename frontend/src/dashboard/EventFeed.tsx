/** A live, newest-first list of events — the shared "trail" element used by the
 *  campaign and live-call views. Render-only. */
import type { Event } from "./types";
import { EventTypeLabel, SeverityDot, formatTime } from "./ui";

export function EventFeed({
  events,
  emptyText = "No events yet.",
  max = 200,
}: {
  events: Event[];
  emptyText?: string;
  max?: number;
}) {
  const rows = events.slice(-max).reverse();
  if (rows.length === 0) {
    return <p className="px-1 py-4 text-sm text-muted">{emptyText}</p>;
  }
  return (
    <ul data-testid="event-feed" className="divide-y divide-line">
      {rows.map((e) => (
        <li key={e.event_id} className="flex items-center gap-3 py-1.5 text-sm">
          <SeverityDot severity={e.severity} />
          <span className="w-20 shrink-0 text-xs tabular-nums text-muted">
            {formatTime(e.occurred_at)}
          </span>
          <EventTypeLabel type={e.type} />
          <span className="truncate text-xs text-muted">{summarize(e)}</span>
        </li>
      ))}
    </ul>
  );
}

/** A one-line, human summary of an event from whatever its generic payload carries.
 *  We only READ known keys; unknown payloads degrade to the correlation ids. */
function summarize(e: Event): string {
  const p = e.payload ?? {};
  switch (e.type) {
    case "disclosure.spoken":
      return "AI disclosure delivered";
    case "slot.booked":
      return p.slot ? `booked ${String(p.slot)}` : "meeting booked";
    case "lead.outcome":
      return `outcome: ${String(p.outcome ?? "—")}`;
    case "guardrail.tripped":
      return `guardrail: ${String(p.rule ?? p.reason ?? "tripped")}`;
    case "tool.invoked":
      return `tool: ${String(p.tool ?? p.name ?? "—")}`;
    case "call.escalated":
      return "warm transfer to human";
    case "campaign.autopaused":
      return `auto-paused: ${String(p.reason ?? "threshold")}`;
    default:
      return [e.lead_id, e.call_id].filter(Boolean).join(" · ");
  }
}
