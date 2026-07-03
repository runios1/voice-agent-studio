/**
 * "Talk to your agent" — the live spoken preview (P3-5). Opens a VoiceSession
 * over the frozen `contracts/voice_preview` WS, renders the same kinds of turns
 * the text preview does (transcript/disclosure/outcome), plus mic-permission and
 * connection errors as calm inline text — never a stack trace.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { VoiceSession, type SessionStatus } from "./voiceSession";

interface TranscriptLine {
  id: string;
  role: "agent" | "lead";
  text: string;
}

let lineSeq = 0;

export function VoicePreview({ agentId }: { agentId: string }) {
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [lines, setLines] = useState<TranscriptLine[]>([]);
  const [disclosed, setDisclosed] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef<VoiceSession | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [lines]);

  // Hang up if the surface unmounts mid-call (e.g. the user flips back to Text).
  useEffect(() => () => sessionRef.current?.stop(), []);

  const startCall = useCallback(() => {
    setLines([]);
    setDisclosed(false);
    setOutcome(null);
    setError(null);
    const session = new VoiceSession(agentId, {
      onStatus: setStatus,
      onTranscript: (role, text) =>
        setLines((ls) => [...ls, { id: `l-${++lineSeq}`, role, text }]),
      onDisclosure: () => setDisclosed(true),
      onOutcome: setOutcome,
      onError: setError,
      onEnded: (o) => setOutcome((prev) => o ?? prev),
    });
    sessionRef.current = session;
    void session.start();
  }, [agentId]);

  const hangUp = useCallback(() => {
    sessionRef.current?.stop();
  }, []);

  const busy = status === "connecting" || status === "live";

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="voice-preview">
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
          {lines.map((l) => (
            <div
              key={l.id}
              data-testid={l.role === "agent" ? "voice-line-agent" : "voice-line-lead"}
              className={clsx("flex", l.role === "lead" ? "justify-end" : "justify-start")}
            >
              <div
                className={clsx(
                  "max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm",
                  l.role === "lead"
                    ? "bg-accent text-white"
                    : "bg-white text-ink shadow-sm",
                )}
              >
                {l.text}
              </div>
            </div>
          ))}
          {outcome && (
            <div
              data-testid="voice-outcome"
              className="mx-auto rounded-md bg-panel px-3 py-1.5 text-center text-xs text-muted"
            >
              Outcome: {outcome}
            </div>
          )}
          {error && (
            <div
              data-testid="voice-error"
              role="alert"
              className="mx-auto rounded-md bg-red-50 px-3 py-1.5 text-center text-xs text-red-700"
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
              data-testid="hang-up"
              onClick={hangUp}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white"
            >
              {status === "connecting" ? "Connecting…" : "Hang up"}
            </button>
          ) : (
            <button
              data-testid="talk-button"
              onClick={startCall}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white"
            >
              🎙️ Talk to your agent
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
