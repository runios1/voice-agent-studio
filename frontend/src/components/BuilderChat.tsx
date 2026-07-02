/** Builder chat — the primary, only-required surface (D-UX). Editing happens by
 * talking; the store routes tokens here and patches to the panel. */
import { useAgentStore } from "../store/agentStore";
import { ChatSurface } from "./ChatSurface";

export function BuilderChat() {
  const messages = useAgentStore((s) => s.messages);
  const streaming = useAgentStore((s) => s.builderStreaming);
  const send = useAgentStore((s) => s.sendBuilderMessage);

  return (
    <ChatSurface
      testid="builder-chat"
      messages={messages}
      streaming={streaming}
      placeholder="Describe the agent you want to build…"
      onSend={send}
    />
  );
}
