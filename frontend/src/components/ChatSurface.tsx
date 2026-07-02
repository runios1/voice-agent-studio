/**
 * Reusable chat surface — a full-width, ChatGPT-feeling transcript + composer.
 * Used by both the builder chat (edits the config) and the preview chat (talks to
 * the built agent). Renders the three interleaved kinds cleanly:
 *   - user      -> right-aligned bubble
 *   - assistant -> left-aligned bubble (streams token-by-token)
 *   - notice    -> a centered, muted inline line (a rejected mutation explained
 *                  conversationally — never a stack trace, D-reliability)
 */
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import type { ChatMessage } from "../store/agentStore";

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
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {messages.map((m) => (
            <Bubble key={m.id} message={m} />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t border-line px-4 py-3">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <textarea
            data-testid="composer-input"
            className="max-h-40 flex-1 resize-none rounded-lg border border-line bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none"
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
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            disabled={streaming || !draft.trim()}
            onClick={submit}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  if (message.role === "notice") {
    return (
      <div
        data-testid="msg-notice"
        className="mx-auto max-w-lg rounded-md bg-line/60 px-3 py-1.5 text-center text-xs text-muted"
      >
        {message.text}
      </div>
    );
  }
  const isUser = message.role === "user";
  return (
    <div
      data-testid={isUser ? "msg-user" : "msg-assistant"}
      className={clsx("flex", isUser ? "justify-end" : "justify-start")}
    >
      <div
        className={clsx(
          "max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm",
          isUser ? "bg-accent text-white" : "bg-white text-ink shadow-sm",
        )}
      >
        {message.text}
        {message.streaming && (
          <span data-testid="cursor" className="ml-0.5 animate-pulse">
            ▍
          </span>
        )}
      </div>
    </div>
  );
}
