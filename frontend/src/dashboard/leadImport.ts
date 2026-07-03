/**
 * Lead-import shape/validation for the campaign builder. Pure functions (no
 * store/React) so the parsing rules are unit-testable in isolation from the UI.
 *
 * Accepted shape: one lead per line, `phone` then an optional `name`, separated
 * by a comma or tab (a plain CSV export or a quick paste both work). A header
 * row (first cell reads "phone", case-insensitive) is recognized and skipped.
 */
import type { NewLead } from "./types";

export interface InvalidLeadRow {
  raw: string;
  reason: string;
}

export interface LeadParseResult {
  valid: NewLead[];
  invalid: InvalidLeadRow[];
}

/** E.164-ish: an optional leading "+", 7-15 digits once separators are stripped. */
export function normalizePhone(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const stripped = trimmed.replace(/[\s().-]/g, "");
  if (!/^\+?\d{7,15}$/.test(stripped)) return null;
  return stripped;
}

function splitRow(line: string): string[] {
  const sep = line.includes("\t") ? "\t" : ",";
  return line.split(sep).map((cell) => cell.trim().replace(/^"(.*)"$/, "$1"));
}

/** Parse pasted/uploaded lead text. Existing leads (already added, e.g. from a
 *  prior import or manual entry) are passed in so CSV rows that dupe them land
 *  in `invalid` with a clear reason rather than silently double-booking a lead. */
export function parseLeadsCsv(text: string, existing: NewLead[] = []): LeadParseResult {
  const seen = new Set(existing.map((l) => normalizePhone(l.phone)).filter(Boolean));
  const valid: NewLead[] = [];
  const invalid: InvalidLeadRow[] = [];

  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  for (const [i, line] of lines.entries()) {
    const cells = splitRow(line);
    if (i === 0 && cells[0]?.toLowerCase() === "phone") continue; // header row
    const [rawPhone, rawName] = cells;
    const phone = normalizePhone(rawPhone ?? "");
    if (!phone) {
      invalid.push({ raw: line, reason: "not a valid phone number" });
      continue;
    }
    if (seen.has(phone)) {
      invalid.push({ raw: line, reason: "duplicate phone number" });
      continue;
    }
    seen.add(phone);
    const display_name = rawName?.trim() || undefined;
    valid.push({ phone, display_name });
  }
  return { valid, invalid };
}
