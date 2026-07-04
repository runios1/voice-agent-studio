/**
 * The product's visual identity: a soundwave glyph in a gradient tile plus the
 * wordmark. Kept in one place so the header, login, and agent avatar all speak
 * with the same voice. The mark is inline SVG (no asset pipeline, themes cleanly).
 */
import clsx from "clsx";

export function Logomark({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        "inline-grid place-items-center rounded-[10px] shadow-card",
        className,
      )}
      style={{
        backgroundImage:
          "linear-gradient(135deg, rgb(var(--c-accent)), rgb(var(--c-signal)))",
      }}
      aria-hidden
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="rgb(var(--c-accent-ink))"
        strokeWidth="2"
        strokeLinecap="round"
        className="h-[58%] w-[58%]"
      >
        {/* a compact waveform — the "voice" */}
        <path d="M3 12h1.5" />
        <path d="M7 8.5v7" />
        <path d="M11 5v14" />
        <path d="M15 8v8" />
        <path d="M19 10.5v3" />
        <path d="M22.5 12H21" />
      </svg>
    </span>
  );
}

/** Full lockup: mark + gradient wordmark. */
export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5 select-none">
      <Logomark className="h-8 w-8" />
      {!compact && (
        <span className="flex flex-col leading-none">
          <span className="font-display text-[15px] font-bold tracking-tight text-ink">
            Voice Agent{" "}
            <span className="text-brand-gradient font-bold">Studio</span>
          </span>
        </span>
      )}
    </span>
  );
}
