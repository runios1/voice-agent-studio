import type {
  CalendarAutomation,
  EmailAutomation,
  Objection,
  QualificationCriterion,
} from "../types/contracts";

/** Human-readable rendering of a read-only value for the panel. */
export function formatValue(path: string, value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    if (path === "conversation.qualification.criteria") {
      return (value as QualificationCriterion[])
        .map((c) => (c.disqualifying ? `${c.label} (disqualifying)` : c.label))
        .join(", ");
    }
    if (path === "conversation.objections") {
      return (value as Objection[]).map((o) => o.trigger).join(", ");
    }
    return (value as unknown[]).map(String).join(", ");
  }
  if (typeof value === "object") {
    if (path === "guardrails.calling_hours") {
      const v = value as { start_hour_local: number; end_hour_local: number };
      return `${v.start_hour_local}:00 – ${v.end_hour_local}:00`;
    }
    if (path === "automation.calendar") {
      const v = value as CalendarAutomation;
      return v.enabled
        ? `On · ${v.meeting_length_minutes} min · ${v.booking_window_days}-day window`
        : "Off";
    }
    if (path === "automation.email") {
      const v = value as EmailAutomation;
      return v.enabled ? `On · ${v.template_ids.length} template(s)` : "Off";
    }
    return JSON.stringify(value);
  }
  return String(value);
}
