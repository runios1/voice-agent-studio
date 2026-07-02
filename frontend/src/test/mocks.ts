/**
 * Test doubles for AgentApi. Two flavors:
 *   - arrayApi:   builder stream replays a fixed event list (whole-turn assertions).
 *   - channelApi: builder stream is driven event-by-event from the test, so we can
 *                 assert TRUE interleaving (a patch lands mid-stream, before done).
 * patchField mimics the server gate: locked paths throw the typed locked_path error.
 */
import type { AgentApi, ApiFailure as _AF } from "../api/agentApi";
import { ApiFailure } from "../api/agentApi";
import type { AgentConfig, ConfigPatch, FieldPolicy } from "../types/contracts";
import type { RawSseEvent } from "../api/sse";
import { FIELD_POLICY, makeSeededDraft } from "../fixtures/agentFixture";

export type PatchSpy = (id: string, path: string, value: unknown) => void;

interface Opts {
  config?: AgentConfig;
  policy?: FieldPolicy[];
  onPatch?: PatchSpy;
  builderEvents?: RawSseEvent[];
  previewEvents?: RawSseEvent[];
}

function makeGate(policy: FieldPolicy[], onPatch?: PatchSpy) {
  const locked = new Set(
    policy.filter((p) => p.mutability === "locked").map((p) => p.path),
  );
  return async (id: string, path: string, value: unknown): Promise<ConfigPatch> => {
    onPatch?.(id, path, value);
    if (locked.has(path)) {
      throw new ApiFailure({
        kind: "locked_path",
        path,
        message: "That field is locked by the platform.",
      });
    }
    return { path, value };
  };
}

export function arrayApi(opts: Opts = {}): AgentApi {
  const config = opts.config ?? makeSeededDraft();
  const policy = opts.policy ?? FIELD_POLICY;
  const patch = makeGate(policy, opts.onPatch);
  return {
    getAgent: async () => ({ config: structuredClone(config), policy }),
    patchField: (id, path, value) => patch(id, path, value),
    async *openBuilderStream() {
      for (const ev of opts.builderEvents ?? []) yield ev;
    },
    async *openPreviewStream() {
      for (const ev of opts.previewEvents ?? []) yield ev;
    },
  };
}

/** An async channel: the test pushes events; the consumer (store) awaits them. */
export function makeChannel<T>() {
  const queue: T[] = [];
  let resolveNext: ((v: IteratorResult<T>) => void) | null = null;
  let closed = false;

  const push = (v: T) => {
    if (resolveNext) {
      resolveNext({ value: v, done: false });
      resolveNext = null;
    } else {
      queue.push(v);
    }
  };
  const close = () => {
    closed = true;
    if (resolveNext) {
      resolveNext({ value: undefined as unknown as T, done: true });
      resolveNext = null;
    }
  };
  const iterator: AsyncGenerator<T> = {
    async next() {
      if (queue.length) return { value: queue.shift() as T, done: false };
      if (closed) return { value: undefined as unknown as T, done: true };
      return new Promise((res) => (resolveNext = res));
    },
    async return() {
      closed = true;
      return { value: undefined as unknown as T, done: true };
    },
    async throw(e) {
      throw e;
    },
    [Symbol.asyncIterator]() {
      return this;
    },
  };
  return { push, close, iterator };
}

export function channelApi(
  channel: ReturnType<typeof makeChannel<RawSseEvent>>,
  opts: Opts = {},
): AgentApi {
  const base = arrayApi(opts);
  return {
    ...base,
    openBuilderStream: () => channel.iterator,
  };
}

export type { _AF as ApiFailureType };
