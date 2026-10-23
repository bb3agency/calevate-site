/**
 * "What's new": release notes as a dated list. Adapted from uiarc's `changelog-feed` (MIT,
 * see ./LICENSE) without its image hero and avatar row: an entry here is a sentence about
 * what changed for the client and where to find it, and a stock photo says neither.
 *
 * Data comes from props. Dates are instants from the server, shown as the IST day
 * (`formatISTDay`, D-709), with a machine-readable `<time>` beside the words.
 */

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import clsx from "clsx";

import { formatISTDay } from "@/components/ui";

export type ChangelogEntry = {
  id: string;
  /** ISO instant the change shipped. */
  date: string;
  title: string;
  body: ReactNode;
  /** One or two words: "Calls", "Billing". */
  tags?: string[];
  href?: string;
  hrefLabel?: string;
};

export function ChangelogFeed({
  entries,
  label = "What's new",
  emptyMessage = "Nothing new yet.",
  headingLevel = 3,
  className,
}: {
  entries: ChangelogEntry[];
  label?: string;
  emptyMessage?: string;
  headingLevel?: 2 | 3;
  className?: string;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  if (entries.length === 0) return <p className={clsx("text-body text-ink-muted", className)}>{emptyMessage}</p>;
  return (
    <ol aria-label={label} className={clsx("space-y-6", className)}>
      {entries.map((entry) => (
        <li key={entry.id} className="grid grid-cols-1 gap-1 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-4">
          <time dateTime={entry.date} className="text-meta tabular-nums text-ink-faint">
            {formatISTDay(entry.date) ?? entry.date}
          </time>
          <article className="min-w-0 space-y-1.5">
            <Heading className="text-body font-semibold text-ink">{entry.title}</Heading>
            {entry.tags?.length ? (
              <p className="flex flex-wrap gap-1.5">
                {entry.tags.map((tag) => (
                  <span key={tag} className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[12px] font-medium text-ink-muted">
                    {tag}
                  </span>
                ))}
              </p>
            ) : null}
            <div className="text-body text-ink-muted">{entry.body}</div>
            {entry.href ? (
              <Link
                href={entry.href}
                className="inline-flex min-h-7 items-center gap-1 rounded-sm text-meta font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              >
                {entry.hrefLabel ?? "Open"}
                <ArrowRight aria-hidden className="h-3.5 w-3.5" />
              </Link>
            ) : null}
          </article>
        </li>
      ))}
    </ol>
  );
}
