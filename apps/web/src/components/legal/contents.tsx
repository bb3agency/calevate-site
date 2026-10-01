"use client";

import { ChevronDown } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

/**
 * The legal reader's table of contents: a sticky rail from `lg`, a collapsed disclosure
 * above the text below it, and a scroll spy that marks where the reader is.
 *
 * The LINKS are not rendered here. `lib/legal/document.tsx` renders them and passes them
 * in as `children`, because the anchors are what `tests/responsive.test.ts` measures for
 * tap-target size and what `tests/legal.test.tsx` checks against every section id. This
 * component owns only the two behaviours a server component cannot have.
 *
 * ONE `<nav>` serves both layouts rather than a phone copy and a desktop copy: two
 * navigation landmarks with the same name are a choice a screen-reader user cannot tell
 * apart, and two lists are two things to keep in step.
 */
export function LegalContents({
  count,
  children,
}: {
  /** How many top-level sections the list holds, shown on the collapsed control. */
  count: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const navRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useScrollSpy(navRef, listRef);

  // Following a link from the phone panel closes it, so the reader lands on the clause
  // rather than on a list that is still open above where they were going.
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const close = (event: MouseEvent) => {
      if (event.target instanceof Element && event.target.closest("a")) setOpen(false);
    };
    list.addEventListener("click", close);
    return () => list.removeEventListener("click", close);
  }, []);

  return (
    <nav
      ref={navRef}
      aria-label="On this page"
      className="rounded-2xl border border-line bg-surface shadow-card lg:rounded-none lg:border-0 lg:bg-transparent lg:shadow-none print:hidden"
    >
      <h2 className="text-base font-semibold text-ink lg:text-sm">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((value) => !value)}
          className="flex min-h-12 w-full items-center gap-3 rounded-2xl px-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong lg:hidden"
        >
          <span className="flex-1">On this page</span>
          <span className="text-sm font-normal text-ink-muted">
            {count} sections
          </span>
          <ChevronDown
            aria-hidden
            className={`h-4 w-4 shrink-0 text-ink-muted transition-transform duration-(--duration-base) ease-out ${
              open ? "rotate-180" : ""
            }`}
          />
        </button>
        <span className="hidden lg:block">On this page</span>
      </h2>
      <div
        ref={listRef}
        id={listId}
        className={`${open ? "block" : "hidden"} border-t border-line px-4 pt-2 pb-4 lg:mt-3 lg:block lg:max-h-[calc(100svh-10rem)] lg:overflow-y-auto lg:overscroll-contain lg:[scrollbar-width:thin] lg:border-0 lg:p-0 lg:pr-2`}
      >
        {children}
      </div>
    </nav>
  );
}

/**
 * Where the reader is, as `aria-current="location"` on the matching contents link.
 *
 * A scroll position rather than an IntersectionObserver over the headings: the question
 * is "which heading did the reader most recently pass", and an observer over headings
 * goes blank between two headings that are a screen apart — exactly the long clauses of
 * a legal document. `location` is the ARIA token for a position within the current page.
 * The attribute is set on the DOM directly because the links are server-rendered
 * children, and nothing else writes it.
 */
function useScrollSpy(
  navRef: RefObject<HTMLElement | null>,
  listRef: RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const pairs = [...nav.querySelectorAll<HTMLAnchorElement>('a[href^="#"]')]
      .map((link) => ({
        link,
        target: document.getElementById(decodeURIComponent(link.hash.slice(1))),
      }))
      .filter(
        (pair): pair is { link: HTMLAnchorElement; target: HTMLElement } =>
          pair.target !== null,
      );
    if (pairs.length === 0) return;

    let frame = 0;
    let current: HTMLAnchorElement | null = null;

    const update = () => {
      frame = 0;
      // The reading line sits below the sticky site header with room to spare, so a
      // heading counts as "passed" once it is where the eye starts reading.
      const line = 140;
      let active: HTMLAnchorElement | null = null;
      for (const { link, target } of pairs) {
        if (target.getBoundingClientRect().top - line > 0) break;
        active = link;
      }
      if (active === current) return;
      current?.removeAttribute("aria-current");
      for (const marked of nav.querySelectorAll("[data-active]")) {
        marked.removeAttribute("data-active");
      }
      if (active) {
        active.setAttribute("aria-current", "location");
        active.closest("[data-toc-section]")?.setAttribute("data-active", "");
        keepInView(listRef.current, active);
      }
      current = active;
    };

    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [navRef, listRef]);
}

/**
 * Scroll the desktop rail so the active entry stays visible. The rail's own `scrollTop`
 * and never `scrollIntoView`, which would also scroll the window and fight the reader.
 */
function keepInView(scroller: HTMLElement | null, link: HTMLElement) {
  if (!scroller || scroller.scrollHeight <= scroller.clientHeight) return;
  const box = scroller.getBoundingClientRect();
  const at = link.getBoundingClientRect();
  const margin = 48;
  if (at.top < box.top + margin) {
    scroller.scrollTop -= box.top + margin - at.top;
  } else if (at.bottom > box.bottom - margin) {
    scroller.scrollTop += at.bottom - (box.bottom - margin);
  }
}
