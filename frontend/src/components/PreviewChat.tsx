/** Preview chat — a separate surface to talk *to* the built agent (runtime loop,
 * D12). Phase 1 is text only; Phase 2 swaps the I/O for the voice Live API. */
import { useAgentStore } from "../store/agentStore";
import { ChatSurface } from "./ChatSurface";

export function PreviewChat() {
  const messages = useAgentStore((s) => s.previewMessages);
  const streaming = useAgentStore((s) => s.previewStreaming);
  const send = useAgentStore((s) => s.sendPreviewMessage);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line bg-panel px-4 py-2 text-xs text-muted">
        Preview — you're talking <span className="font-medium">to</span> the agent,
        not the builder. Text only in Phase 1.
      </div>
      <div className="min-h-0 flex-1">
        <ChatSurface
          testid="preview-chat"
          messages={messages}
          streaming={streaming}
          placeholder="Say something to the agent…"
          onSend={send}
        />
      </div>
    </div>
  );
}
