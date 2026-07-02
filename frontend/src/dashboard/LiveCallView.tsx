/** Live-call altitude: one call's status + its event trail (transcript lines when
 *  the stream carries them), and the ESCALATE control (warm transfer to a human,
 *  P2-D6). Status is derived from the call's own events — rendered, not invented. */
import { useDashboardStore } from "./store";
import { callTrail } from "./metrics";
import type { Event } from "./types";
import { EventFeed } from "./EventFeed";
import { ControlButton, formatTime } from "./ui";

export function LiveCallView() {
  const callId = useDashboardStore((s) => s.selectedCallId);
  const liveEvents = useDashboardStore((s) => s.liveEvents);
  const pending = useDashboardStore((s) => s.pending);
  const escalate = useDashboardStore((s) => s.escalateCall);

  if (!callId) {
    return <p className="p-6 text-sm text-muted">No call selected.</p>;
  }
  const trail = callTrail(liveEvents, callId);
  const ended = trail.some((e) => e.type === "call.ended");
  const escalated = trail.some((e) => e.type === "call.escalated");
  const disclosed = trail.some((e) => e.type === "disclosure.spoken");
  const status = ended ? "ended" : escalated ? "escalated" : "in call";
  const transcript = trail.filter((e) => typeof e.payload?.utterance === "string");

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-center gap-3">
          <span
            className={
              ended
                ? "h-2 w-2 rounded-full bg-slate-400"
                : "h-2 w-2 animate-pulse rounded-full bg-emerald-500"
            }
          />
          <h2 className="font-mono text-sm">{callId}</h2>
          <span
            data-testid="call-status"
            className="text-xs capitalize text-muted"
          >
            {status}
          </span>
          {disclosed && (
            <span
              className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700"
              data-testid="disclosure-ok"
            >
              ✓ disclosed
            </span>
          )}
        </div>
        <ControlButton
          testid="escalate"
          danger
          pending={pending[`escalate:${callId}`]}
          disabled={ended || escalated}
          onClick={() => escalate(callId)}
        >
          ↗ Escalate to human
        </ControlButton>
      </div>

      {transcript.length > 0 && (
        <section className="border-b border-line px-5 py-3">
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
            Transcript
          </h3>
          <ul data-testid="transcript" className="space-y-1 text-sm">
            {transcript.map((e) => (
              <li key={e.event_id} className="flex gap-2">
                <span className="w-16 shrink-0 text-xs tabular-nums text-muted">
                  {formatTime(e.occurred_at)}
                </span>
                <span className="font-medium text-muted">
                  {String((e.payload as Record<string, unknown>).speaker ?? "•")}:
                </span>
                <span>{String((e as Event).payload.utterance)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="min-h-0 flex-1 overflow-auto px-5 py-3">
        <h3 className="mb-2 text-xs font-semibold uppercase text-muted">
          Call trail
        </h3>
        <EventFeed events={trail} emptyText="Waiting for call events…" />
      </section>
    </div>
  );
}
