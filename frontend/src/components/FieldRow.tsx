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
        "rounded-md px-3 py-2 text-sm",
        flashing && "animate-flash",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-ink">{meta.label}</span>
        {policy.mutability === "default" && (
          <span className="rounded bg-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
            default
          </span>
        )}
        {policy.required_for_ready && (
          <span
            title="required for the agent to be deploy-ready"
            className="text-[10px] text-accent"
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
  const asText = value == null ? "" : String(value);
  const [draft, setDraft] = useState(asText);

  // keep the local draft in sync when the config changes underneath us
  // (e.g. a builder patch to the same field while it isn't focused).
  useEffect(() => setDraft(asText), [asText]);

  const commit = () => {
    if (draft !== asText) onCommit(path, draft);
  };

  if (meta.editor.kind === "select") {
    return (
      <select
        data-testid={`input-${path}`}
        className="mt-1 w-full rounded border border-line bg-white px-2 py-1 text-sm"
        value={asText}
        onChange={(e) => onCommit(path, e.target.value)}
      >
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
      "mt-1 w-full rounded border border-line bg-white px-2 py-1 text-sm focus:border-accent focus:outline-none",
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
