import { beginGoogleLogin } from "../auth/authApi";

/** The only unauthenticated surface: sign in, or nothing. */
export function LoginScreen({ error }: { error?: string | null }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-center">
      <span className="text-lg font-semibold">Voice Agent Studio</span>
      <p className="max-w-sm text-sm text-muted">
        Sign in to build, preview, and run your voice AI SDR agents.
      </p>
      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
      <button
        onClick={beginGoogleLogin}
        className="rounded-md border border-line bg-white px-4 py-2 text-sm font-medium text-ink shadow-sm hover:bg-panel"
      >
        Sign in with Google
      </button>
    </div>
  );
}
