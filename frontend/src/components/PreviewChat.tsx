/** Preview chat — a separate surface to talk *to* the built agent (runtime loop,
 * D12). Text (Phase 1) and live voice (P3-5, `../preview/VoicePreview`) are two
 * modes of the same surface — both drive the identical CallEngine turn loop. */
import { useState } from "react";
import clsx from "clsx";
import { useAgentStore } from "../store/agentStore";
import { ChatSurface } from "./ChatSurface";
import { VoicePreview } from "../preview/VoicePreview";

type Mode = "text" | "voice";

export function PreviewChat() {
  const messages = useAgentStore((s) => s.previewMessages);
  const streaming = useAgentStore((s) => s.previewStreaming);
  const send = useAgentStore((s) => s.sendPreviewMessage);
  const agentId = useAgentStore((s) => s.agentId);
  const [mode, setMode] = useState<Mode>("text");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-line bg-panel px-4 py-2 text-xs text-muted">
        <span>
          Preview — you're talking <span className="font-medium">to</span> the
          agent, not the builder.
        </span>
        <div className="flex gap-1">
          <ModeButton testid="preview-mode-text" active={mode === "text"} onClick={() => setMode("text")}>
            ⌨️ Text
          </ModeButton>
          <ModeButton testid="preview-mode-voice" active={mode === "voice"} onClick={() => setMode("voice")}>
            🎙️ Talk
          </ModeButton>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {mode === "text" ? (
          <ChatSurface
            testid="preview-chat"
            messages={messages}
            streaming={streaming}
            placeholder="Say something to the agent…"
            onSend={send}
          />
        ) : agentId ? (
          <VoicePreview agentId={agentId} />
        ) : null}
      </div>
    </div>
  );
}

function ModeButton({
  testid,
  active,
  onClick,
  children,
}: {
  testid: string;
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={clsx(
        "rounded px-2 py-1",
        active ? "bg-white font-medium text-ink shadow-sm" : "text-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
