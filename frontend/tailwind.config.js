/** @type {import('tailwindcss').Config} */

// Colors are driven by CSS variables (defined in src/index.css) so a single token
// set powers both light and dark themes. Variables hold "R G B" triplets so
// Tailwind's `/opacity` modifiers keep working (e.g. bg-accent/20).
const withVar = (v) => `rgb(var(${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: withVar("--c-canvas"),
        surface: withVar("--c-surface"),
        panel: withVar("--c-panel"),
        ink: withVar("--c-ink"),
        muted: withVar("--c-muted"),
        line: withVar("--c-line"),
        accent: withVar("--c-accent"),
        "accent-ink": withVar("--c-accent-ink"),
        signal: withVar("--c-signal"),
      },
      fontFamily: {
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Space Grotesk"', '"Inter"', "ui-sans-serif", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgb(var(--c-shadow) / 0.06), 0 8px 24px -12px rgb(var(--c-shadow) / 0.18)",
        pop: "0 12px 40px -12px rgb(var(--c-shadow) / 0.28)",
        glow: "0 0 0 1px rgb(var(--c-accent) / 0.35), 0 8px 30px -10px rgb(var(--c-accent) / 0.45)",
      },
      keyframes: {
        flash: {
          "0%": { backgroundColor: "rgb(var(--c-accent) / 0.16)" },
          "100%": { backgroundColor: "transparent" },
        },
        "rise-in": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-ring": {
          "0%, 100%": { opacity: "0.55", transform: "scale(0.92)" },
          "50%": { opacity: "1", transform: "scale(1)" },
        },
      },
      animation: {
        flash: "flash 1.2s ease-out",
        "rise-in": "rise-in 0.28s cubic-bezier(0.22, 1, 0.36, 1)",
        "pulse-ring": "pulse-ring 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
