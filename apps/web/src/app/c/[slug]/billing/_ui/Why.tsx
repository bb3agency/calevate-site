import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The explanation behind a tap: a short line stays on screen, and the sentence that argues
 * it opens under a "Why?" / "Details" summary.
 *
 * A native `<details>` rather than the ⓘ popover (`InfoTip`): the text stays in the
 * document while closed, so find-in-page and a screen reader still reach a money or
 * compliance qualification, and nothing has to be positioned on a phone. The summary is
 * 44px tall on touch screens.
 */
export function Why({
  label = "Why?",
  children,
  className = "",
}: {
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={`group/why ${className}`}>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-meta font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 [&::-webkit-details-marker]:hidden">
        {label}
        <ChevronDown
          aria-hidden
          className="h-3.5 w-3.5 transition-transform duration-150 motion-reduce:transition-none [details[open]>summary>&]:rotate-180"
        />
      </summary>
      <div className="mt-1 max-w-prose space-y-1 text-meta text-ink-muted [text-wrap:pretty]">
        {children}
      </div>
    </details>
  );
}
