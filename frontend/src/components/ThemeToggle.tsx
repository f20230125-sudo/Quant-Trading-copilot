"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

type Theme = "system" | "light" | "dark";
const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const ICON = { system: Monitor, light: Sun, dark: Moon };

// The theme lives on <html data-theme>, set before paint by the script in layout.tsx.
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

function readTheme(): Theme {
  const t = document.documentElement.dataset.theme;
  return t === "light" || t === "dark" ? t : "system";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, readTheme, () => "system" as Theme);
  const Icon = ICON[theme];

  const change = () => {
    const next = NEXT[theme];
    if (next === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    try {
      if (next === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", next);
    } catch {
      /* storage unavailable: the choice lasts for this page view */
    }
  };

  return (
    <button
      type="button"
      onClick={change}
      title={`Theme: ${theme}`}
      aria-label={`Theme: ${theme}. Click to change.`}
      className="grid h-8 w-8 place-items-center rounded-lg border border-line text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
    >
      <Icon size={15} aria-hidden />
    </button>
  );
}
