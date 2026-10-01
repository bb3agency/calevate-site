"use client";

import { ArrowUp, Printer } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * Prints the document. Browsers already offer this, but a reader keeping a copy of the
 * terms they accepted is common enough that the control earns its place, and the page's
 * print styles (chrome hidden, contents hidden, plain ink) are what make the result worth
 * keeping. The class comes from the server caller (`PILL_LINK`), so this client module does
 * not pull the marketing shell into the browser bundle.
 */
export function PrintButton({ className }: { className: string }) {
  return (
    <button type="button" onClick={() => window.print()} className={className}>
      <Printer aria-hidden className="h-4 w-4" />
      Print
    </button>
  );
}

/**
 * The way back to the top of a long document, shown once the reader has scrolled past
 * the opening screen.
 *
 * An anchor to `#top` rather than a scripted scroll, so it moves the keyboard's starting
 * point too. While hidden it is `inert`: invisible but focusable would be a tab stop
 * nobody can see.
 */
export function BackToTop() {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      setShown(window.scrollY > window.innerHeight * 1.5);
    };
    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
    };
  }, []);

  return (
    <a
      href="#top"
      inert={!shown}
      aria-label="Back to top"
      className={`press fixed right-5 bottom-[calc(1.25rem+env(safe-area-inset-bottom,0px))] z-20 inline-flex h-11 w-11 items-center justify-center rounded-full border border-line bg-surface text-ink shadow-raised transition-[opacity,translate] duration-(--duration-base) ease-out hover:text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 sm:right-6 print:hidden ${
        shown ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-2 opacity-0"
      }`}
    >
      <ArrowUp aria-hidden className="h-4 w-4" />
    </a>
  );
}
