/**
 * One field row in the Agent panel. Renders per FIELD_POLICY:
 *   - locked  -> read-only value, no editor (the server is the real lock; the UI
 *                only *reflects* it — a trust feature, D11).
 *   - default -> editable, tagged "default" so the user knows the platform suggested it.
 *   - open    -> editable.
 * Edits are server-authoritative: they call store.editField -> PATCH /fields, and
 * the value only changes once the gate accepts it.
 */
import { useEffect, useState } from "react";
import clsx from "clsx";
import type { FieldPolicy } from "../types/contracts";
import { metaFor } from "../lib/fieldMeta";
import { formatValue } from "../lib/format";
import { getPath } from "../lib/paths";
import { useAgentStore } from "../store/agentStore";
import {
  CAPABILITY_PROVIDER,
  useConnectionsStore,
} from "../connections/connectionsStore";
import { PROVIDER_CATALOG } from "../connections/catalog";

/** Deep-link into the ops dashboard's Connections screen (see store `initialView`). */
const CONNECTIONS_URL = "/dashboard.html#connections";
const providerLabel = (id: string) =>
  PROVIDER_CATALOG.find((p) => p.id === id)?.label ?? id;

interface Props {
  policy: FieldPolicy;
}

export function FieldRow({ policy }: Props) {
  const meta = metaFor(policy.path);
  const config = useAgentStore((s) => s.config);
  const editField = useAgentStore((s) => s.editField);
  const flashing = useAgentStore((s) => !!s.flashing[policy.path]);

  const value = config ? getPath(config, policy.path) : undefined;
  const locked = policy.mutability === "locked";
  const editable = !locked && meta.editor.kind !== "readonly";

  return (
    <div
      data-testid={`field-${policy.path}`}
      data-flashing={flashing || undefined}
      className={clsx(
        "rounded-lg px-3 py-2 text-sm transition-colors hover:bg-surface/60",
        flashing && "animate-flash",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-ink">{meta.label}</span>
        {locked && (
          <span title="locked by the platform" className="text-[11px] text-muted">
            🔒
          </span>
        )}
        {policy.mutability === "default" && (
          <span className="rounded-full bg-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
            default
          </span>
        )}
        {policy.required_for_ready && (
          <span
            title="required for the agent to be deploy-ready"
            className="rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent"
          >
            required
          </span>
        )}
      </div>

      {editable ? (
        <FieldEditor path={policy.path} value={value} onCommit={editField} meta={meta} />
      ) : (
        <div className="mt-1 whitespace-pre-wrap text-muted" data-testid={`value-${policy.path}`}>
          {formatValue(policy.path, value)}
        </div>
      )}
    </div>
  );
}

/**
 * A capability on/off switch (calendar / email). Connection-gated: if the backing
 * provider isn't connected, the switch can't be turned ON and we point the user at
 * Connections instead — a capability we can't fulfil is never quietly enabled.
 * (Turning an already-on capability OFF stays allowed, e.g. after a disconnect.)
 */
function ToggleEditor({
  path,
  value,
  onCommit,
  meta,
}: {
  path: string;
  value: unknown;
  onCommit: (path: string, value: unknown) => void;
  meta: ReturnType<typeof metaFor>;
}) {
  const field = (meta.editor.kind === "toggle" && meta.editor.field) || "enabled";
  const hint = meta.editor.kind === "toggle" ? meta.editor.hint : undefined;
  const on = !!(value as Record<string, unknown> | undefined)?.[field];

  const provider = CAPABILITY_PROVIDER[path];
  const loaded = useConnectionsStore((s) => s.loaded);
  const connected = useConnectionsStore((s) =>
    provider ? !!s.byProvider[provider]?.connected : true,
  );
  // Gate only once we actually know the state (avoid flashing a Connect prompt on load).
  const gated = !!provider && loaded && !connected;

  return (
    <div className="mt-1">
      <label
        className={clsx(
          "flex items-center gap-2",
          gated && !on ? "cursor-not-allowed opacity-60" : "cursor-pointer",
        )}
      >
        <input
          type="checkbox"
          data-testid={`input-${path}`}
          checked={on}
          disabled={gated && !on}
          onChange={(e) => onCommit(`${path}.${field}`, e.target.checked)}
        />
        <span className="text-muted">{on ? "On" : "Off"}</span>
        {gated && (
          <span
            data-testid={`capability-locked-${path}`}
            className="rounded-full bg-line px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted"
          >
            needs connection
          </span>
        )}
      </label>

      {gated ? (
        <p className="mt-1 text-xs text-muted">
          {providerLabel(provider!)} isn’t connected, so this can’t run on a live
          call.{" "}
          <a
            data-testid={`connect-link-${path}`}
            href={CONNECTIONS_URL}
            className="font-medium text-accent hover:underline"
          >
            Connect {providerLabel(provider!)} →
          </a>
        </p>
      ) : (
        hint && <p className="mt-1 text-xs text-muted">{hint}</p>
      )}
    </div>
  );
}

function FieldEditor({
  path,
  value,
  onCommit,
  meta,
}: {
  path: string;
  value: unknown;
  onCommit: (path: string, value: unknown) => void;
  meta: ReturnType<typeof metaFor>;
}) {
  const asText =
    value == null || typeof value === "object" ? "" : String(value);
  const [draft, setDraft] = useState(asText);

  // keep the local draft in sync when the config changes underneath us
  // (e.g. a builder patch to the same field while it isn't focused).
  useEffect(() => setDraft(asText), [asText]);

  const commit = () => {
    if (draft !== asText) onCommit(path, draft);
  };

  if (meta.editor.kind === "toggle") {
    return <ToggleEditor path={path} value={value} onCommit={onCommit} meta={meta} />;
  }

  if (meta.editor.kind === "select") {
    return (
      <select
        data-testid={`input-${path}`}
        className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink"
        value={asText}
        onChange={(e) => onCommit(path, e.target.value)}
      >
        {!asText && (
          <option value="" disabled>
            Choose…
          </option>
        )}
        {meta.editor.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }

  const common = {
    "data-testid": `input-${path}`,
    className:
      "mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none",
    value: draft,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setDraft(e.target.value),
    onBlur: commit,
  };

  if (meta.editor.kind === "textarea") {
    return (
      <textarea
        {...common}
        rows={2}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
      />
    );
  }

  return (
    <input
      {...common}
      type="text"
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        }
      }}
    />
  );
}
