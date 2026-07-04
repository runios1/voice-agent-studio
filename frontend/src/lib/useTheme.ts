/**
 * Light/dark theme, persisted. The token layer (src/index.css) reacts to
 * `data-theme` on <html>; this hook is just the toggle + persistence over it.
 * "system" means: no attribute, let prefers-color-scheme decide.
 */
import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

function currentAttr(): Theme | null {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || t === "light" ? t : null;
}

/** Effective theme right now, resolving "system" against the OS preference. */
function resolved(): Theme {
  return (
    currentAttr() ??
    (window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light")
  );
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(resolved);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("vas-theme", theme);
    } catch {
      /* private mode — theme just won't persist */
    }
  }, [theme]);

  return {
    theme,
    toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  };
}
