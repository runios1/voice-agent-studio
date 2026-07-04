/**
 * The frontend's door to `backend/auth`: session check, Google sign-in redirect,
 * sign-out. The session itself lives in an httponly cookie the browser manages —
 * nothing here reads or stores a token.
 */
export interface AuthUser {
  id: string;
  email: string;
  name: string;
  picture: string | null;
}

/** GET /api/auth/me — null when not signed in (401), never throws for that case. */
export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const res = await fetch("/api/auth/me", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Couldn't check your session (${res.status}).`);
  return (await res.json()) as AuthUser;
}

/** A real navigation (not fetch) — the backend 302s the browser to Google. */
export function beginGoogleLogin(): void {
  window.location.href = "/api/auth/google/login";
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
}
