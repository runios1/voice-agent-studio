/** The presentational, records-driven Call-details table — shared verbatim by the ops
 *  dashboard (a campaign's leads) and the live voice preview ("what this call looks like
 *  in your dashboard"). Pure: it takes already-built `LeadRecord`s and renders the
 *  summary strip, filters, and the expandable per-lead rows. It owns only view-local
 *  state (search text, filter selections, which row is expanded) — never business or
 *  server state. The store-bound wrapper lives in CampaignCallDetails.tsx; the preview
 *  wrapper in ../preview/PreviewCallDashboard.tsx. */
import { useState } from "react";
import clsx from "clsx";
import type { AnswerStatus, LeadRecord } from "./metrics";
import { EventFeed } from "./EventFeed";
import { LeadStateBadge, TONE } from "./ui";

type AnswerFilter = "all" | "answered" | "unanswered" | "not_dialed";
type OutcomeFilter = "all" | "qualified" | "not_qualified" | "unknown";

export interface CallDetailsTableProps {
  records: LeadRecord[];
  /** Drill into a call by id (dashboard). Omit to hide the "open call ↗" affordance. */
  onOpenCall?: (callId: string) => void;
  /** Summary strip of totals (default on). */
  showSummary?: boolean;
  /** Search + filter controls (default on). Off for a single-call preview. */
  showFilters?: boolean;
  /** Show a subtle "loading history…" hint next to the filters. */
  historyLoading?: boolean;
  emptyText?: string;
  /** Row (by lead id) to start expanded — used by the single-call preview. */
  defaultExpandedId?: string | null;
}

export function CallDetailsTable({
  records,
  onOpenCall,
  showSummary = true,
  showFilters = true,
  historyLoading = false,
  emptyText,
  defaultExpandedId = null,
}: CallDetailsTableProps) {
  const [query, setQuery] = useState("");
  const [answerFilter, setAnswerFilter] = useState<AnswerFilter>("all");
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");
  const [expanded, setExpanded] = useState<string | null>(defaultExpandedId);

  const totals = summarize(records);

  const q = query.trim().toLowerCase();
  const filtered = records.filter((r) => {
    if (q) {
      const hay = `${r.lead.display_name ?? ""} ${r.lead.phone}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (answerFilter === "answered" && r.answer !== "answered") return false;
    if (
      answerFilter === "unanswered" &&
      !(r.answer === "no_answer" || r.answer === "voicemail" || r.answer === "failed")
    )
      return false;
    if (answerFilter === "not_dialed" && r.dialed) return false;
    if (outcomeFilter === "qualified" && r.qualified !== true) return false;
    if (outcomeFilter === "not_qualified" && r.qualified !== false) return false;
    if (outcomeFilter === "unknown" && r.qualified !== null) return false;
    return true;
  });

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {showSummary && (
        <div
          data-testid="detail-summary"
          className="grid grid-cols-3 gap-2 border-b border-line px-5 py-3 text-sm sm:grid-cols-6"
        >
          <Stat label="Leads" value={records.length} />
          <Stat label="Dialed" value={totals.dialed} />
          <Stat label="Answered" value={totals.answered} />
          <Stat label="Qualified" value={totals.qualified} tone="emerald" />
          <Stat label="Meetings" value={totals.booked} tone="emerald" />
          <Stat label="Emails" value={totals.emailed} />
        </div>
      )}

      {showFilters && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-2">
          <input
            data-testid="lead-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name or number…"
            className="w-56 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
          <SelectFilter
            testid="answer-filter"
            value={answerFilter}
            onChange={(v) => setAnswerFilter(v as AnswerFilter)}
            options={[
              ["all", "Any dial"],
              ["answered", "Answered"],
              ["unanswered", "No answer / VM"],
              ["not_dialed", "Not dialed"],
            ]}
          />
          <SelectFilter
            testid="outcome-filter"
            value={outcomeFilter}
            onChange={(v) => setOutcomeFilter(v as OutcomeFilter)}
            options={[
              ["all", "Any outcome"],
              ["qualified", "Qualified"],
              ["not_qualified", "Not qualified"],
              ["unknown", "No outcome yet"],
            ]}
          />
          {historyLoading && (
            <span data-testid="history-loading" className="text-xs text-muted">
              loading history…
            </span>
          )}
          <span className="ml-auto text-xs text-muted">
            {filtered.length} of {records.length}
          </span>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <p className="px-5 py-8 text-sm text-muted">
            {records.length === 0
              ? emptyText ?? "No leads yet."
              : "No leads match."}
          </p>
        ) : (
          <table className="w-full border-collapse text-sm" data-testid="lead-table">
            <thead className="sticky top-0 z-10 bg-canvas text-left text-xs uppercase text-muted">
              <tr className="border-b border-line">
                <Th>Lead</Th>
                <Th>State</Th>
                <Th>Dialed</Th>
                <Th>Answer</Th>
                <Th>Qualified</Th>
                <Th>Meeting</Th>
                <Th>Email</Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <LeadRow
                  key={r.lead.id}
                  record={r}
                  open={expanded === r.lead.id}
                  onToggle={() =>
                    setExpanded((cur) => (cur === r.lead.id ? null : r.lead.id))
                  }
                  onOpenCall={onOpenCall}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Row
// --------------------------------------------------------------------------- //
function LeadRow({
  record: r,
  open,
  onToggle,
  onOpenCall,
}: {
  record: LeadRecord;
  open: boolean;
  onToggle: () => void;
  onOpenCall?: (callId: string) => void;
}) {
  return (
    <>
      <tr
        data-testid={`lead-row-${r.lead.id}`}
        className="cursor-pointer border-b border-line align-top hover:bg-panel"
        onClick={onToggle}
      >
        <Td>
          <div className="flex items-center gap-1.5">
            <span className="text-muted">{open ? "▾" : "▸"}</span>
            <div>
              <div className="font-medium">
                {r.lead.display_name ?? r.lead.phone}
              </div>
              {r.lead.display_name && r.lead.phone && (
                <div className="font-mono text-xs text-muted">{r.lead.phone}</div>
              )}
            </div>
          </div>
        </Td>
        <Td>
          <LeadStateBadge state={r.lead.state} />
        </Td>
        <Td>
          {r.dialed ? (
            <span className="text-muted">
              {r.attempts > 0 ? `${r.attempts}×` : "yes"}
            </span>
          ) : (
            <Dash />
          )}
        </Td>
        <Td>
          <AnswerBadge answer={r.answer} />
        </Td>
        <Td>
          <QualifiedBadge qualified={r.qualified} outcome={r.outcome} />
        </Td>
        <Td>
          {r.booking ? (
            <span
              className="text-emerald-600 dark:text-emerald-400"
              data-testid={`meeting-${r.lead.id}`}
            >
              📅 {formatWhen(r.booking.start)}
            </span>
          ) : (
            <Dash />
          )}
        </Td>
        <Td>
          {r.email ? (
            <span className="text-ink" data-testid={`email-${r.lead.id}`}>
              ✉️ {formatWhen(r.email.at)}
            </span>
          ) : (
            <Dash />
          )}
        </Td>
      </tr>
      {open && (
        <tr className="border-b border-line bg-panel/50">
          <td colSpan={7} className="px-5 py-3">
            <LeadDetail record={r} onOpenCall={onOpenCall} />
          </td>
        </tr>
      )}
    </>
  );
}

/** The expanded "what / when / where" panel: a fact grid plus the lead's full event
 *  timeline (reusing the shared EventFeed). */
function LeadDetail({
  record: r,
  onOpenCall,
}: {
  record: LeadRecord;
  onOpenCall?: (callId: string) => void;
}) {
  const facts: [string, React.ReactNode][] = [];
  facts.push(["Number dialed", <span className="font-mono">{r.toNumber || "—"}</span>]);
  facts.push(["Attempts", r.attempts || (r.dialed ? "1" : "0")]);
  facts.push([
    "Call result",
    r.endedReason ? r.endedReason.replace(/_/g, " ") : answerLabel(r.answer),
  ]);
  facts.push(["AI disclosure", r.disclosed ? "✓ spoken" : "—"]);
  facts.push(["Outcome", r.outcome ? r.outcome.replace(/_/g, " ") : "—"]);
  if (r.booking) {
    facts.push([
      "Meeting booked",
      <span className="text-emerald-600 dark:text-emerald-400">
        {formatWhen(r.booking.start, true)}
        {r.booking.end ? ` – ${formatWhen(r.booking.end)}` : ""}
      </span>,
    ]);
    if (r.booking.where) facts.push(["Meeting on", r.booking.where]);
  }
  if (r.email) {
    facts.push([
      "Email sent",
      <span>
        {formatWhen(r.email.at, true)}
        {r.email.to ? ` → ${r.email.to}` : ""}
        {r.email.status && r.email.status !== "ok" ? ` (${r.email.status})` : ""}
      </span>,
    ]);
  }
  if (r.followups > 0) facts.push(["Follow-ups scheduled", r.followups]);
  if (r.escalated) facts.push(["Escalated", "↗ warm transfer to human"]);
  if (r.guardrailTrips > 0)
    facts.push([
      "Guardrail trips",
      <span className="text-amber-600 dark:text-amber-300">{r.guardrailTrips}</span>,
    ]);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <h4 className="text-xs font-semibold uppercase text-muted">Details</h4>
          {r.callId && onOpenCall && (
            <button
              data-testid={`open-call-detail-${r.lead.id}`}
              className="text-xs text-accent hover:underline"
              onClick={(e) => {
                e.stopPropagation();
                onOpenCall(r.callId!);
              }}
            >
              open call ↗
            </button>
          )}
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {facts.map(([k, v], i) => (
            <div key={i} className="contents">
              <dt className="text-muted">{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase text-muted">Timeline</h4>
        <EventFeed events={r.events} emptyText="No events recorded for this lead yet." />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Small presentational bits
// --------------------------------------------------------------------------- //
function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "emerald";
}) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 shadow-card">
      <div className="text-xs text-muted">{label}</div>
      <div
        className={clsx(
          "text-lg font-semibold tabular-nums",
          tone === "emerald" && value > 0
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-ink",
        )}
      >
        {value}
      </div>
    </div>
  );
}

const ANSWER_TONE: Record<AnswerStatus, string> = {
  answered: TONE.success,
  in_progress: TONE.info,
  voicemail: TONE.warning,
  no_answer: TONE.neutral,
  failed: TONE.danger,
  not_dialed: TONE.neutral,
};

export function answerLabel(a: AnswerStatus): string {
  switch (a) {
    case "answered":
      return "Answered";
    case "in_progress":
      return "In call";
    case "voicemail":
      return "Voicemail";
    case "no_answer":
      return "No answer";
    case "failed":
      return "Failed";
    default:
      return "Not dialed";
  }
}

function AnswerBadge({ answer }: { answer: AnswerStatus }) {
  return (
    <span
      data-testid={`answer-${answer}`}
      className={clsx(
        "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
        ANSWER_TONE[answer],
      )}
    >
      {answerLabel(answer)}
    </span>
  );
}

function QualifiedBadge({
  qualified,
  outcome,
}: {
  qualified: boolean | null;
  outcome: string | null;
}) {
  if (qualified === true)
    return (
      <span className={clsx("inline-block rounded-full px-2 py-0.5 text-xs font-medium", TONE.success)}>
        Qualified
      </span>
    );
  if (qualified === false)
    return (
      <span className={clsx("inline-block rounded-full px-2 py-0.5 text-xs font-medium", TONE.neutral)}>
        {outcome === "do_not_call" || outcome === "opted_out" ? "Do not call" : "Not qualified"}
      </span>
    );
  return <Dash />;
}

function SelectFilter({
  value,
  onChange,
  options,
  testid,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  testid: string;
}) {
  return (
    <select
      data-testid={testid}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink"
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>
          {label}
        </option>
      ))}
    </select>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 font-medium">{children}</th>;
}
function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-2">{children}</td>;
}
function Dash() {
  return <span className="text-muted">—</span>;
}

/** Format an ISO datetime for display; if it isn't a parseable date (e.g. a free
 *  label like "Thu 2:00pm" from an early emitter), show it verbatim. */
export function formatWhen(value?: string, withDate = false): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return withDate
    ? d.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function summarize(records: LeadRecord[]) {
  let dialed = 0;
  let answered = 0;
  let qualified = 0;
  let booked = 0;
  let emailed = 0;
  for (const r of records) {
    if (r.dialed) dialed++;
    if (r.answer === "answered") answered++;
    if (r.qualified === true) qualified++;
    if (r.booking) booked++;
    if (r.email) emailed++;
  }
  return { dialed, answered, qualified, booked, emailed };
}
