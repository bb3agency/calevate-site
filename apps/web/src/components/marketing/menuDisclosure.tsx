"use client";

/**
 * The header menu's `<details>`, with the three ways out a phone visitor expects.
 *
 * The element stays the platform disclosure (siteHeader.tsx says why), so without this
 * script the menu still opens and closes. What the script adds, following the WAI-ARIA
 * APG disclosure-navigation example (w3.org/WAI/ARIA/apg/patterns/disclosure/examples/
 * disclosure-navigation/): Escape closes it and returns focus to the trigger; a tap
 * outside closes it, because on a phone the panel sits over the page and there is no
 * other way to put it away short of finding the trigger again; and following one of its
 * links closes it, which matters for a link to the page already showing — Next keeps this
 * subtree mounted, so the panel would otherwise stay open over the page it just "opened".
 *
 * No focus trap and no scroll lock: the panel is a non-modal disclosure anchored to the
 * header, not a dialog over the page, so Tab is allowed to walk on past it.
 */

import { useEffect, useRef, type ReactNode } from "react";

export function MenuDisclosure({ className, children }: { className: string; children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const details = ref.current;
    if (!details) return;

    const close = (returnFocus: boolean) => {
      if (!details.open) return;
      details.open = false;
      if (returnFocus) details.querySelector("summary")?.focus();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      // Focus moves back only when it was inside the menu; pulling it from elsewhere on the
      // page would lose the visitor's place.
      if (event.key === "Escape") close(details.contains(document.activeElement));
    };
    // `pointerdown`, not `click`: it lands before a tap on the page underneath acts, and it
    // fires for a touch that turns into a scroll, which is also a way of moving on.
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !details.contains(event.target)) close(false);
    };
    const onClick = (event: MouseEvent) => {
      if (event.target instanceof Element && event.target.closest("a")) close(false);
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    details.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
      details.removeEventListener("click", onClick);
    };
  }, []);

  return (
    <details ref={ref} className={className}>
      {children}
    </details>
  );
}
