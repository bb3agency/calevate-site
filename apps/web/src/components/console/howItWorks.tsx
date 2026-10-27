import type { ReactNode } from "react";

import { Disclosure } from "@/components/ui";

/**
 * "How it works" — the details behind a settings section, as 2-4 short bullets.
 *
 * A settings surface shows a title, at most one line, and the control (founder, 27 Oct
 * 2026); everything a reader needs only once lives here. It is the kit's `Disclosure` at
 * strip size, not a second mechanism. Never put a required notice (AI disclosure,
 * recording, consent, do-not-call, calling hours, money) only in here: those stay visible.
 */
export function HowItWorks({
  items,
  headingLevel = 4,
  title = "How it works",
  className = "mt-3",
}: {
  items: ReactNode[];
  headingLevel?: 3 | 4;
  title?: string;
  className?: string;
}) {
  return (
    <Disclosure variant="inline" headingLevel={headingLevel} title={title} className={className}>
      <ul className="list-disc space-y-1 pl-5 text-sm text-ink-muted">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </Disclosure>
  );
}
