/** Preview — talk TO the built agent (runtime loop, D12). Voice-only: the agent is
 * now Gemini Live (Phase 4, audio-to-audio), so a text preview would run a different
 * brain (the old text runtime loop) and misrepresent what the agent actually says on
 * a real call. It was removed for exactly that reason. */
import { useAgentStore } from "../store/agentStore";
import { LiveVoicePreview } from "../preview/LiveVoicePreview";

export function PreviewChat() {
  const agentId = useAgentStore((s) => s.agentId);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-line bg-panel px-4 py-2 text-xs text-muted">
        <span>
          Preview — you're talking <span className="font-medium">to</span> the agent
          (live voice), not the builder.
        </span>
      </div>
      <div className="min-h-0 flex-1">
        {agentId ? <LiveVoicePreview agentId={agentId} /> : null}
      </div>
    </div>
  );
}
