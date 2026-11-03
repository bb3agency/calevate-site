import type { ReactNode } from "react";

import { NOTICE_BAR, NOTICE_BASE } from "@/components/ui";

/**
 * A notice at the top of the home screen that is one link to where it is dealt with
 * (the attention queue, a line problem). The whole strip is the target, so it carries the
 * touch height and the focus ring a button would. Callers add the cross-axis alignment:
 * a one-line notice centres, a notice of several lines keeps its link at the top.
 */
export const HOME_NOTICE_LINK = `${NOTICE_BASE} ${NOTICE_BAR.warn} flex justify-between gap-3 touch:min-h-11 transition-colors duration-(--duration-fast) ease-out hover:bg-ink/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2`;

/**
 * One quiet line for a home-screen read that failed, with its way forward. Quiet rather
 * than a `ProblemNotice`: these reads only decide whether a notice appears, so their
 * failure must not be louder than the notice it stands in for — but it must not vanish
 * either, or it reads as "nothing wrong".
 */
export function ReadFailedRow({ children, action }: { children: ReactNode; action: ReactNode }) {
  return (
    <p className="flex items-center justify-between gap-3 rounded-md bg-surface-muted px-4 py-2.5 text-body text-ink-muted">
      {children}
      {action}
    </p>
  );
}
