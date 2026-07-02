/**
 * A mock AgentApi for `npm run dev` before workstreams 2–6 are merged. It replays
 * a scripted builder interview: each user turn materializes the next required field
 * and streams a conversational confirmation, and one turn demonstrates a `notice`
 * (a locked-path attempt refused conversationally). This is DEV SCAFFOLDING, not a
 * contract — the real backend replaces it wholesale. Tests use their own fine-
 * grained mocks (see src/test/mocks.ts); they do not import this file.
 */
import type { AgentApi } from "../api/agentApi";
import { ApiFailure } from "../api/agentApi";
import type { AgentEnvelope, ConfigPatch } from "../types/contracts";
import { getPath } from "../lib/paths";
import { RawSseEvent } from "../api/sse";
import { FIELD_POLICY, makeSeededDraft } from "../fixtures/agentFixture";

interface Step {
  reply: string;
  patch?: ConfigPatch;
  notice?: string;
}

const SCRIPT: Step[] = [
  {
    reply: "Great — an SDR for Acme. I'll set the role. What tone should it strike?",
    patch: { path: "conversation.persona.role", value: "SDR for Acme" },
  },
  {
    reply: "Warm and consultative it is. How should it open a call?",
    patch: { path: "conversation.persona.tone", value: "warm, consultative" },
  },
  {
    reply: "Nice opener. What's the main goal of each call?",
    patch: {
      path: "conversation.opening",
      value: "Hi, this is Acme — do you have 30 seconds?",
    },
  },
  {
    reply: "Booking a 15-min discovery call — good. And if nobody picks up?",
    patch: {
      path: "conversation.primary_objective",
      value: "book a 15-minute discovery call",
    },
  },
  {
    reply: "It'll leave a short voicemail. Let's capture how it qualifies leads.",
    patch: { path: "conversation.voicemail.action", value: "leave_message" },
  },
  {
    reply:
      "Added a budget + timeline check. That's every required field — the agent is deploy-ready. Try it in Preview.",
    patch: {
      path: "conversation.qualification.criteria",
      value: [
        { label: "Budget", question: "Do you have budget allocated?", disqualifying: false },
        { label: "Timeline", question: "When are you looking to start?", disqualifying: false },
      ],
    },
  },
  {
    reply:
      "I hear you, but AI disclosure is a locked platform guardrail — it can't be turned off. Everything else is yours to shape, though.",
    notice: "AI disclosure is required by the platform and can't be disabled.",
  },
];

export function createMockAgentApi(agentId = "agent-demo"): AgentApi {
  const config = makeSeededDraft(agentId);
  let step = 0;

  const policyLocked = new Set(
    FIELD_POLICY.filter((p) => p.mutability === "locked").map((p) => p.path),
  );

  async function getAgent(): Promise<AgentEnvelope> {
    return { config: structuredClone(config), policy: FIELD_POLICY };
  }

  async function patchField(
    _id: string,
    path: string,
    value: unknown,
  ): Promise<ConfigPatch> {
    if (policyLocked.has(path)) {
      throw new ApiFailure({
        kind: "locked_path",
        path,
        message: "That's a locked platform guardrail — it can't be changed.",
      });
    }
    if (getPath(config, path) === undefined) {
      throw new ApiFailure({
        kind: "validation",
        path,
        message: "I didn't quite catch that field — rephrase?",
      });
    }
    return { path, value };
  }

  async function* openBuilderStream(): AsyncGenerator<RawSseEvent> {
    const s = SCRIPT[Math.min(step, SCRIPT.length - 1)];
    step++;
    for (const word of s.reply.split(" ")) {
      await delay(18);
      yield { event: "token", data: { text: word + " " } };
    }
    if (s.patch) yield { event: "patch", data: s.patch };
    if (s.notice) yield { event: "notice", data: { message: s.notice } };
    yield { event: "done", data: {} };
  }

  async function* openPreviewStream(
    _id: string,
    message: string,
  ): AsyncGenerator<RawSseEvent> {
    const reply = `Hi! I'm an AI assistant calling on behalf of Acme. You said: "${message}". Is now a good time for a quick 30 seconds?`;
    for (const word of reply.split(" ")) {
      await delay(18);
      yield { event: "token", data: { text: word + " " } };
    }
    yield { event: "done", data: {} };
  }

  return { getAgent, patchField, openBuilderStream, openPreviewStream };
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));
