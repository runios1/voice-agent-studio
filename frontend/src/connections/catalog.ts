/** Display-only catalog of connectable providers. Mirrors the ids in
 *  `backend/tool_registry/catalog.py` (GOOGLE_CALENDAR / GMAIL) — this is
 *  presentation metadata only, not a source of truth for what a provider can do. */
export interface ProviderCatalogEntry {
  id: string;
  label: string;
  description: string;
}

export const PROVIDER_CATALOG: ProviderCatalogEntry[] = [
  {
    id: "google_calendar",
    label: "Google Calendar",
    description: "Lets your agents hold real slots and book on your calendar.",
  },
  {
    id: "gmail",
    label: "Gmail",
    description: "Lets your agents send confirmation emails as you.",
  },
];
