/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // neutral, ChatGPT-ish surface palette
        canvas: "#ffffff",
        panel: "#f7f7f8",
        ink: "#111827",
        muted: "#6b7280",
        line: "#e5e7eb",
        accent: "#10a37f",
      },
      keyframes: {
        flash: {
          "0%": { backgroundColor: "rgba(16,163,127,0.18)" },
          "100%": { backgroundColor: "transparent" },
        },
      },
      animation: {
        flash: "flash 1.2s ease-out",
      },
    },
  },
  plugins: [],
};
