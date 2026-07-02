import { describe, expect, it } from "vitest";
import { parseSseStream, type RawSseEvent } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) controller.enqueue(enc.encode(chunks[i++]));
      else controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<RawSseEvent[]> {
  const out: RawSseEvent[] = [];
  for await (const ev of parseSseStream(stream)) out.push(ev);
  return out;
}

describe("parseSseStream", () => {
  it("parses event + JSON data records", async () => {
    const events = await collect(
      streamOf([
        'event: token\ndata: {"text":"Hello"}\n\n',
        'event: patch\ndata: {"path":"conversation.persona.role","value":"SDR"}\n\n',
      ]),
    );
    expect(events).toEqual([
      { event: "token", data: { text: "Hello" } },
      { event: "patch", data: { path: "conversation.persona.role", value: "SDR" } },
    ]);
  });

  it("reassembles records split across chunk boundaries", async () => {
    const events = await collect(
      streamOf(["event: to", "ken\ndata: {\"te", 'xt":"Hi"}\n', "\n"]),
    );
    expect(events).toEqual([{ event: "token", data: { text: "Hi" } }]);
  });

  it("strips a single leading space after the colon and tolerates CRLF", async () => {
    const events = await collect(streamOf(["event: notice\r\ndata: plain text\r\n\r\n"]));
    expect(events).toEqual([{ event: "notice", data: "plain text" }]);
  });

  it("flushes a trailing record with no terminating blank line", async () => {
    const events = await collect(streamOf(['event: done\ndata: {}']));
    expect(events).toEqual([{ event: "done", data: {} }]);
  });
});
