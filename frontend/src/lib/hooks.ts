"use client";

import { useEffect, useRef, useState } from "react";

/** Tracks an element's content width. */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/**
 * Resolved values of CSS custom properties, re-read whenever the theme changes
 * (OS preference or the data-theme attribute). Needed by canvas charts, which
 * can't use var() directly.
 */
export function useCssVars<K extends string>(names: readonly K[]): Record<K, string> | null {
  const [values, setValues] = useState<Record<K, string> | null>(null);
  const key = names.join(",");
  useEffect(() => {
    const read = () => {
      const style = getComputedStyle(document.documentElement);
      setValues(
        Object.fromEntries(key.split(",").map((n) => [n, style.getPropertyValue(`--${n}`).trim()])) as Record<K, string>,
      );
    };
    read();
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", read);
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      media.removeEventListener("change", read);
      observer.disconnect();
    };
  }, [key]);
  return values;
}
