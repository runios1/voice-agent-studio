/**
 * SSE reader over fetch. The API contract uses POST for both chat surfaces
 * (builder + preview), so the browser EventSource (GET-only) can't be used;
 * we parse the text/event-stream body off a fetch ReadableStream instead.
 *
 * Yields one parsed event per SSE record. Records are separated by a blank line;
 * `event:` and `data:` fields are accumulated per the SSE spec. `data:` is
 * assumed to be JSON (our server encodes event payloads as JSON).
 */

export interface RawSseEvent {
  event: string;
  data: unknown;
}

export async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<RawSseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      // SSE records are delimited by a blank line ("\n\n").
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const record = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const parsed = parseRecord(record);
        if (parsed) yield parsed;
      }
    }
    // flush a trailing record with no terminating blank line
    const tail = parseRecord(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}

function parseRecord(record: string): RawSseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const rawLine of record.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue; // comment / blank
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    // per spec: a single leading space after the colon is stripped
    let val = idx === -1 ? "" : line.slice(idx + 1);
    if (val.startsWith(" ")) val = val.slice(1);
    if (field === "event") event = val;
    else if (field === "data") dataLines.push(val);
  }
  if (dataLines.length === 0 && event === "message") return null;
  const dataStr = dataLines.join("\n");
  let data: unknown = dataStr;
  if (dataStr) {
    try {
      data = JSON.parse(dataStr);
    } catch {
      data = dataStr; // tolerate non-JSON payloads
    }
  }
  return { event, data };
}
