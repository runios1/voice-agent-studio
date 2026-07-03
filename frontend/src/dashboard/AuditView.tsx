/** Audit altitude: a filterable, exportable window onto the immutable event log.
 *  Filtering is server-side (the store passes the filter to `queryAudit`); this view
 *  drives the filter and exports whatever the server returned. The log itself is the
 *  compliance record (P2-D5) — we never mutate it, only read/slice/export. */
import { useState } from "react";
import { useDashboardStore } from "./store";
import type { EventType, Severity } from "./types";
import { EventTypeLabel, SeverityDot, formatTime } from "./ui";

const EVENT_TYPES: EventType[] = [
  "call.started",
  "call.ended",
  "disclosure.spoken",
  "call.escalated",
  "slot.booked",
  "tool.invoked",
  "lead.outcome",
  "followup.scheduled",
  "guardrail.tripped",
  "campaign.started",
  "campaign.paused",
  "campaign.autopaused",
  "campaign.resumed",
];

const SEVERITIES: Severity[] = ["info", "warning", "critical"];

export function AuditView() {
  const filter = useDashboardStore((s) => s.auditFilter);
  const results = useDashboardStore((s) => s.auditResults);
  const loading = useDashboardStore((s) => s.auditLoading);
  const setFilter = useDashboardStore((s) => s.setAuditFilter);
  const runAudit = useDashboardStore((s) => s.runAudit);
  const [typeSel, setTypeSel] = useState<EventType | "">(
    filter.types?.[0] ?? "",
  );

  const apply = (patch: Partial<typeof filter>) => {
    const next = { ...filter, ...patch };
    setFilter(next);
    void runAudit();
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
        <h2 className="text-sm font-semibold">Audit log</h2>

        <select
          data-testid="filter-type"
          className="rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          value={typeSel}
          onChange={(e) => {
            const v = e.target.value as EventType | "";
            setTypeSel(v);
            apply({ types: v ? [v] : undefined });
          }}
        >
          <option value="">All types</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <select
          data-testid="filter-severity"
          className="rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          value={filter.severity ?? ""}
          onChange={(e) =>
            apply({ severity: (e.target.value || undefined) as Severity | undefined })
          }
        >
          <option value="">Any severity</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <input
          data-testid="filter-campaign"
          placeholder="campaign id"
          className="rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          defaultValue={filter.campaign_id ?? ""}
          onBlur={(e) => apply({ campaign_id: e.target.value || undefined })}
        />

        <div className="ml-auto flex items-center gap-2 text-xs text-muted">
          <span data-testid="audit-count">{results.length} events</span>
          <button
            data-testid="export-json"
            className="rounded-md border border-line px-2 py-1 text-ink hover:bg-panel"
            disabled={results.length === 0}
            onClick={() => exportJson(results)}
          >
            Export JSON
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-5 py-2">
        {loading ? (
          <p className="py-8 text-center text-sm text-muted">Loading…</p>
        ) : results.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            No events match this filter.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                <th className="py-1 font-medium">Time</th>
                <th className="py-1 font-medium">Sev</th>
                <th className="py-1 font-medium">Type</th>
                <th className="py-1 font-medium">Campaign</th>
                <th className="py-1 font-medium">Call</th>
              </tr>
            </thead>
            <tbody data-testid="audit-rows">
              {results.map((e) => (
                <tr key={e.event_id} className="border-b border-line/60">
                  <td className="py-1 text-xs tabular-nums text-muted">
                    {formatTime(e.occurred_at)}
                  </td>
                  <td className="py-1">
                    <SeverityDot severity={e.severity} />
                  </td>
                  <td className="py-1">
                    <EventTypeLabel type={e.type} />
                  </td>
                  <td className="py-1 font-mono text-xs text-muted">
                    {e.campaign_id ?? ""}
                  </td>
                  <td className="py-1 font-mono text-xs text-muted">
                    {e.call_id ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/** Download the returned events as pretty JSON — the raw immutable records, so an
 *  export is a faithful copy of the compliance log slice (no client reshaping). */
export function exportJson(events: unknown[]): void {
  const blob = new Blob([JSON.stringify(events, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `audit-export-${new Date().toISOString().slice(0, 19)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
