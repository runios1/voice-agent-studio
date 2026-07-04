/**
 * "Talk to your agent" — the Live-native spoken preview (P4-4). Same shell as
 * Phase 3's `VoicePreview`, plus what's new because Live drives the call itself:
 * a speaking/listening indicator (no server turn-boundary event exists, so it's
 * inferred client-side — see `liveVoiceSession.ts`), inline badges for tool calls
 * and moderation verdicts, still never a stack trace on error.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import {
  LiveVoiceSession,
  type LiveVoiceSessionDeps,
  type SessionStatus,
  type SpeakingIndicator,
} from "./liveVoiceSession";
import { PreviewCallDashboard } from "./PreviewCallDashboard";
import type { Event as DashboardEvent } from "../dashboard/types";

type LineKind = "agent" | "lead" | "tool" | "moderation";

interface Line {
  id: string;
  kind: LineKind;
  text: string;
  moderationVerdict?: "flag" | "block";
}

let lineSeq = 0;

export function LiveVoicePreview({
  agentId,
  deps,
}: {
  agentId: string;
  /** Injected socket/mic/playback — real by default; a scripted double in the dev
   *  demo and (via module mock) in tests. */
  deps?: LiveVoiceSessionDeps;
}) {
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [indicator, setIndicator] = useState<SpeakingIndicator>("listening");
  const [lines, setLines] = useState<Line[]>([]);
  const [disclosed, setDisclosed] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<DashboardEvent[]>([]);
  const sessionRef = useRef<LiveVoiceSession | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [lines]);

  useEffect(() => () => sessionRef.current?.stop(), []);

  const startCall = useCallback(() => {
    setLines([]);
    setDisclosed(false);
    setOutcome(null);
    setError(null);
    setEvents([]);
    setIndicator("listening");
    const session = new LiveVoiceSession(agentId, {
      onStatus: setStatus,
      onIndicator: setIndicator,
      onTranscript: (role, text) =>
        setLines((ls) => [...ls, { id: `l-${++lineSeq}`, kind: role, text }]),
      onDisclosure: () => setDisclosed(true),
      onTool: (name, timing) =>
        setLines((ls) => [
          ...ls,
          { id: `l-${++lineSeq}`, kind: "tool", text: `${name} (${timing.replace("_", " ")})` },
        ]),
      onModeration: (verdict) =>
        setLines((ls) => [
          ...ls,
          {
            id: `l-${++lineSeq}`,
            kind: "moderation",
            text: verdict === "block" ? "cut off — steering back" : "flagged",
            moderationVerdict: verdict,
          },
        ]),
      onOutcome: setOutcome,
      onError: setError,
      onEnded: (o) => setOutcome((prev) => o ?? prev),
      onEvent: (e) => setEvents((es) => [...es, e]),
    }, deps);
    sessionRef.current = session;
    void session.start();
  }, [agentId, deps]);

  const hangUp = useCallback(() => {
    sessionRef.current?.stop();
  }, []);

  const busy = status === "connecting" || status === "live";

  return (
    <div
      className="grid h-full min-h-0 grid-cols-1 md:grid-cols-[minmax(0,1fr)_480px] xl:grid-cols-[minmax(0,1fr)_640px] 2xl:grid-cols-[minmax(0,1fr)_860px]"
      data-testid="live-voice-preview"
    >
      <div className="flex min-h-0 min-w-0 flex-col overflow-hidden md:border-r md:border-line">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-3">
          {disclosed && (
            <div
              data-testid="disclosure-badge"
              className="mx-auto rounded-full bg-line/60 px-3 py-1 text-xs text-muted"
            >
              🔒 AI disclosed
            </div>
          )}
          {status === "live" && (
            <div
              data-testid="speaking-indicator"
              className="mx-auto rounded-full bg-line/40 px-3 py-1 text-xs text-muted"
            >
              {indicator === "agent" ? "🔊 Agent speaking…" : "🎙️ Listening…"}
            </div>
          )}
          {lines.map((l) => {
            if (l.kind === "tool") {
              return (
                <div
                  key={l.id}
                  data-testid="live-line-tool"
                  className="mx-auto rounded-md bg-panel px-3 py-1.5 text-center text-xs text-muted"
                >
                  🛠️ used {l.text}
                </div>
              );
            }
            if (l.kind === "moderation") {
              return (
                <div
                  key={l.id}
                  data-testid="live-line-moderation"
                  className={clsx(
                    "mx-auto rounded-md px-3 py-1.5 text-center text-xs",
                    l.moderationVerdict === "block"
                      ? "bg-red-500/10 text-red-600 dark:text-red-300"
                      : "bg-yellow-500/10 text-yellow-700 dark:text-yellow-300",
                  )}
                >
                  ⚠️ {l.text}
                </div>
              );
            }
            return (
              <div
                key={l.id}
                data-testid={l.kind === "agent" ? "live-line-agent" : "live-line-lead"}
                className={clsx("flex", l.kind === "lead" ? "justify-end" : "justify-start")}
              >
                <div
                  className={clsx(
                    "max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm shadow-card",
                    l.kind === "lead"
                      ? "rounded-br-md bg-accent text-accent-ink"
                      : "rounded-bl-md border border-line bg-surface text-ink",
                  )}
                >
                  {l.text}
                </div>
              </div>
            );
          })}
          {outcome && (
            <div
              data-testid="live-outcome"
              className="mx-auto rounded-md bg-panel px-3 py-1.5 text-center text-xs text-muted"
            >
              Outcome: {outcome}
            </div>
          )}
          {error && (
            <div
              data-testid="live-error"
              role="alert"
              className="mx-auto rounded-md bg-red-500/10 px-3 py-1.5 text-center text-xs text-red-600 dark:text-red-300"
            >
              {error}
            </div>
          )}
          {status === "idle" && !error && (
            <div className="mx-auto text-center text-sm text-muted">
              Click Talk and start speaking — your agent opens the call.
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t border-line px-4 py-3">
        <div className="mx-auto flex max-w-2xl items-center justify-center gap-2">
          {busy ? (
            <button
              data-testid="live-hang-up"
              onClick={hangUp}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white"
            >
              {status === "connecting" ? "Connecting…" : "Hang up"}
            </button>
          ) : (
            <button
              data-testid="live-talk-button"
              onClick={startCall}
              className="btn-primary rounded-lg px-4 py-2 text-sm font-semibold"
            >
              🎙️ Talk to your agent
            </button>
          )}
        </div>
      </div>
      </div>

      {/* Live mirror of how this call lands in the ops Call-details view — fills in as
          the call progresses. Hidden on narrow screens (conversation takes full width). */}
      <div className="hidden min-h-0 min-w-0 overflow-hidden md:flex md:flex-col">
        <PreviewCallDashboard events={events} />
      </div>
    </div>
  );
}
