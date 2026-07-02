/**
 * Dotted-path get/set into the AgentConfig tree, mirroring the backend gate's
 * addressing (contracts/config_schema field_policy paths are dotted). The panel
 * reads values by policy path; patches arrive addressed by the same paths.
 *
 * setPath is immutable: it returns a shallow-cloned tree so React/Zustand see a
 * new reference on the changed branch only.
 */

export function getPath<T = unknown>(root: unknown, path: string): T | undefined {
  const parts = path.split(".");
  let cur: unknown = root;
  for (const key of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[key];
  }
  return cur as T | undefined;
}

export function setPath<R>(root: R, path: string, value: unknown): R {
  const parts = path.split(".");
  const clone: R = Array.isArray(root)
    ? ([...(root as unknown[])] as R)
    : ({ ...(root as object) } as R);

  let cur = clone as Record<string, unknown>;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    const child = cur[key];
    cur[key] =
      child != null && typeof child === "object"
        ? Array.isArray(child)
          ? [...(child as unknown[])]
          : { ...(child as object) }
        : {};
    cur = cur[key] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]] = value;
  return clone;
}

/**
 * "Meaningful" = a user actually decided this. Drives progressive disclosure:
 * a user field materializes in the panel only once it has a meaningful value
 * (D-UX: no empty user selectors before the question is answered). null / "" /
 * [] / {} do not count. Booleans/numbers/enums count only when set explicitly
 * (we never seed them from load — see store's materialization seeding).
 */
export function isMeaningful(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true; // number / boolean / etc.
}
