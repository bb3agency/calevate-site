import type { ReactNode } from "react";

/**
 * The default export of a layout that exists only to carry `metadata` for a `"use client"`
 * page, which cannot export it itself (Next ignores the export silently). Without one, the
 * auth screens' tab, history entry and screen-reader page announcement all read the bare
 * root title "Calevate" (WCAG 2.4.2, Page Titled). It renders nothing of its own, so the
 * jsdom accessibility sweep, which renders pages without layouts, loses no chrome.
 */
export function TitleOnlyLayout({ children }: { children: ReactNode }) {
  return children;
}
