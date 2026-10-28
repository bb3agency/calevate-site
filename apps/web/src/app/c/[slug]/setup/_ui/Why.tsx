import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/**
 * THE EXPLANATION BEHIND A TAP ("buttons, not paragraphs"): a short visible label that opens
 * the longer words in place, for a reader who wants them.
 *
 * A native `<details>` rather than the kit's ⓘ (`InfoTip`): the trigger is a WORD a
 * non-technical reader recognises as tappable ("Why?", "How this works"), it needs no
 * script, and the text opens inline instead of in a floating panel a phone keyboard can
 * cover. Never for an error, a refusal or a compliance sentence: those stay visible.
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
    <details className={`group text-meta ${className}`}>
      <summary className="press -mx-2 inline-flex min-h-8 cursor-pointer list-none items-center gap-1 rounded-md px-2 font-medium text-brand-strong hover:bg-brand/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 [&::-webkit-details-marker]:hidden">
        {label}
        <ChevronDown aria-hidden className="h-3.5 w-3.5 transition-transform duration-(--duration-fast) group-open:rotate-180" />
      </summary>
      <div className="mt-1 max-w-prose space-y-1.5 text-ink-muted">{children}</div>
    </details>
  );
}
