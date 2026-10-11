"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { NOTICE_BAR, NOTICE_BASE } from "@/components/ui";

import type { Session } from "@/lib/api/client";
import { useLineIncidents } from "@/lib/api/healer";

/**
 * A problem with one of the client's lines, at the top of the dashboard, while it lasts.
 *
 * The sentence is the server's (the same one the email carries). Nothing renders when no
 * problem is open; a failed read says so in one quiet line rather than reading as "all
 * your lines are fine".
 */
export function LineNotice({ session, href }: { session: Session; href: string }) {
  const incidents = useLineIncidents(session);
  if (incidents.isError) {
    return (
      <p className="rounded-md bg-surface-muted px-4 py-3 text-body text-ink-muted">
        We could not check whether your lines are working.{" "}
        <Link href={href} className="font-medium text-brand-strong underline">
          See line protection
        </Link>
      </p>
    );
  }
  if (!incidents.data) return null;
  const open = incidents.data.items.filter((item) => item.state === "open");
  if (open.length === 0) return null;
  const first = open[0];
  const more = open.length - 1;
  return (
    <Link
      href={href}
      className={`${NOTICE_BASE} ${NOTICE_BAR.warn} flex items-start justify-between gap-3 transition-colors duration-(--duration-fast) ease-out hover:bg-ink/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2`}
    >
      <span className="flex min-w-0 items-start gap-2">
        <span className="min-w-0">
          <span className="block font-medium">{first.headline}</span>
          <span className="block text-ink-muted">{first.what_we_did}</span>
          {more > 0 && (
            <span className="block text-ink-muted">
              {more === 1 ? "One more line needs a look." : `${more} more lines need a look.`}
            </span>
          )}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-1 font-medium text-brand-strong">
        Details
        <ChevronRight aria-hidden className="h-3.5 w-3.5" />
      </span>
    </Link>
  );
}
