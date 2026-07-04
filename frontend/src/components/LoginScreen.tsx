import { beginGoogleLogin } from "../auth/authApi";
import { Logomark } from "./Brand";

/** The only unauthenticated surface: sign in, or nothing. */
export function LoginScreen({ error }: { error?: string | null }) {
  return (
    <div className="chat-backdrop flex h-full flex-col items-center justify-center px-4 text-center">
      <div className="w-full max-w-sm rounded-3xl border border-line bg-surface/80 p-8 shadow-pop backdrop-blur">
        <Logomark className="mx-auto mb-5 h-14 w-14" />
        <h1 className="font-display text-2xl font-bold tracking-tight text-ink">
          Voice Agent <span className="text-brand-gradient">Studio</span>
        </h1>
        <p className="mx-auto mt-2 max-w-xs text-sm text-muted">
          Describe an agent in plain language. We turn it into a working voice AI
          SDR — with the guardrails already in place.
        </p>

        {error && (
          <p className="mt-4 text-sm text-red-500" role="alert">
            {error}
          </p>
        )}

        <button
          onClick={beginGoogleLogin}
          className="btn-primary mt-6 inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold"
        >
          <GoogleGlyph />
          Continue with Google
        </button>
        <p className="mt-4 text-[11px] text-muted">
          Outbound calling, on rails: AI disclosure, Do-Not-Call, and calling
          hours enforced by the platform.
        </p>
      </div>
    </div>
  );
}

function GoogleGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" aria-hidden>
      <path
        fill="#FFC107"
        d="M21.35 11.1h-9.17v2.98h5.27c-.23 1.42-1.64 4.16-5.27 4.16-3.17 0-5.76-2.63-5.76-5.86s2.59-5.86 5.76-5.86c1.81 0 3.02.77 3.71 1.44l2.53-2.44C16.9 3.58 14.76 2.6 12.18 2.6 6.98 2.6 2.8 6.78 2.8 12s4.18 9.4 9.38 9.4c5.42 0 9.01-3.81 9.01-9.17 0-.62-.07-1.09-.16-1.56z"
      />
      <path
        fill="#FF3D00"
        d="M4.34 7.34 6.8 9.15c.67-1.6 2.2-2.71 3.98-2.71 1.81 0 3.02.77 3.71 1.44l2.53-2.44C16.9 3.58 14.76 2.6 12.18 2.6 8.6 2.6 5.5 4.63 4.34 7.34z"
        opacity="0"
      />
      <path
        fill="#4CAF50"
        d="M12.18 21.4c2.5 0 4.6-.82 6.14-2.24l-2.83-2.33c-.79.55-1.86.94-3.31.94-3.61 0-5.02-2.72-5.26-4.13l-2.9 2.24c1.15 2.66 4.24 5.52 8.16 5.52z"
      />
      <path
        fill="#1976D2"
        d="M21.35 11.1h-9.17v2.98h5.27c-.22 1.35-1.07 2.4-2.14 3.09l2.83 2.33c1.66-1.53 2.79-3.8 2.79-6.84 0-.62-.07-1.09-.18-1.56z"
      />
    </svg>
  );
}
