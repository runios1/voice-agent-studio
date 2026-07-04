/**
 * Reusable chat surface — a full-width, ChatGPT-feeling transcript + composer.
 * Used by both the builder chat (edits the config) and the preview chat (talks to
 * the built agent). Renders the three interleaved kinds cleanly:
 *   - user      -> right-aligned gradient bubble
 *   - assistant -> left-aligned bubble with the brand mark as avatar (streams)
 *   - notice    -> a centered, muted inline line (a rejected mutation explained
 *                  conversationally — never a stack trace, D-reliability)
 */
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import type { ChatMessage } from "../store/agentStore";
import { Logomark } from "./Brand";

interface Props {
  messages: ChatMessage[];
  streaming: boolean;
  placeholder: string;
  onSend: (text: string) => void;
  testid?: string;
}

export function ChatSurface({ messages, streaming, placeholder, onSend, testid }: Props) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  const submit = () => {
    const text = draft.trim();
    if (!text || streaming) return;
    onSend(text);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid={testid}>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-8">
        <div className="mx-auto flex max-w-2xl flex-col gap-5">
          {messages.map((m) => (
            <Bubble key={m.id} message={m} />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div className="px-4 pb-5 pt-2">
        <div className="mx-auto flex max-w-2xl items-end gap-2 rounded-2xl border border-line bg-surface p-2 shadow-card transition focus-within:shadow-glow">
          <textarea
            data-testid="composer-input"
            className="max-h-40 flex-1 resize-none bg-transparent px-2.5 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none"
            rows={1}
            placeholder={placeholder}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <button
            data-testid="composer-send"
            aria-label="Send"
            className="btn-primary grid h-9 w-9 shrink-0 place-items-center rounded-xl disabled:opacity-40"
            disabled={streaming || !draft.trim()}
            onClick={submit}
          >
            <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="currentColor">
              <path d="M3.4 20.4 21 12 3.4 3.6 3.4 10l11 2-11 2z" />
            </svg>
          </button>
        </div>
        <p className="mx-auto mt-2 max-w-2xl text-center text-[11px] text-muted">
          Enter to send · Shift+Enter for a new line
        </p>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  if (message.role === "notice") {
    return (
      <div
        data-testid="msg-notice"
        className="mx-auto max-w-lg animate-rise-in rounded-full border border-line bg-panel/70 px-3.5 py-1.5 text-center text-xs text-muted"
      >
        {message.text}
      </div>
    );
  }
  const isUser = message.role === "user";
  return (
    <div
      data-testid={isUser ? "msg-user" : "msg-assistant"}
      className={clsx(
        "flex animate-rise-in items-end gap-2.5",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      {!isUser && <Logomark className="h-7 w-7 shrink-0" />}
      <div
        className={clsx(
          "max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "rounded-br-md bg-accent text-accent-ink shadow-card"
            : "rounded-bl-md border border-line bg-surface text-ink shadow-card",
        )}
        style={
          isUser
            ? {
                backgroundImage:
                  "linear-gradient(135deg, rgb(var(--c-accent)), color-mix(in srgb, rgb(var(--c-accent)) 72%, rgb(var(--c-signal))))",
              }
            : undefined
        }
      >
        {message.text}
        {message.streaming && (
          <span
            data-testid="cursor"
            className="ml-0.5 inline-block h-3.5 w-[3px] translate-y-0.5 animate-pulse rounded-full bg-accent align-middle"
          />
        )}
      </div>
    </div>
  );
}
