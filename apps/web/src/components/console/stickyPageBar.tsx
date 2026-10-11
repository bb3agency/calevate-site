"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * A bar that stays at the top of the page while it scrolls: a workbench's title, its save
 * state and its one primary action (the script builder's toolbar).
 *
 * It must be the FIRST child of the page, because it cancels the shell's top padding
 * (`SHELL_MAIN_CLASS`: `py-4`, `lg:py-8`) to sit flush under the shell header. A sticky
 * offset that does not match that padding leaves a strip above the bar where the page
 * shows through as it scrolls.
 *
 * Its contents stay on the content rail, so they line up with the shell header's title
 * and buttons; its background and bottom hairline run the full width of `<main>`, like
 * the header's. The full width is painted with `border-image` outset rather than negative
 * margins: an outset is ink overflow, so it widens the paint without widening the scroll
 * area, and `<main>` clips it at its own edges.
 *
 * It publishes its height on `<main>` as `--sticky-bar-h`, so a sticky panel lower on the
 * page (the script builder's editor) can stop just under it instead of guessing a height
 * that changes when the bar wraps.
 */
export function StickyPageBar({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const bar = ref.current;
    const main = bar?.closest("main");
    if (!bar || !main) return;
    const publish = () => main.style.setProperty("--sticky-bar-h", `${bar.offsetHeight}px`);
    publish();
    if (typeof ResizeObserver === "undefined") return () => main.style.removeProperty("--sticky-bar-h");
    const observer = new ResizeObserver(publish);
    observer.observe(bar);
    return () => {
      observer.disconnect();
      main.style.removeProperty("--sticky-bar-h");
    };
  }, []);
  return (
    <div ref={ref} className={`${STICKY_PAGE_BAR_CLASS} ${className}`}>
      {children}
    </div>
  );
}

const STICKY_PAGE_BAR_CLASS =
  "sticky -top-4 z-20 -mt-4 bg-surface py-3 lg:-top-8 lg:-mt-8 " +
  "[border-image:linear-gradient(to_bottom,var(--color-surface)_calc(100%_-_1px),var(--color-line)_0)_fill_0//0_100vmax]";

/**
 * Where a sticky panel below a `StickyPageBar` stops, from `lg` up: just under the bar,
 * with the page's 16px gap. `top` is measured from `<main>`'s padding edge, so the shell's
 * `lg:py-8` comes off.
 */
export const BELOW_PAGE_BAR_STICKY =
  "lg:sticky lg:top-[calc(var(--sticky-bar-h,0px)_-_2rem_+_1rem)] lg:max-h-[calc(100dvh_-_72px_-_var(--sticky-bar-h,0px)_-_2rem)] lg:overflow-y-auto lg:overscroll-contain";
