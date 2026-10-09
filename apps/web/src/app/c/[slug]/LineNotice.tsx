"use client";

import Link from "next/link";
import { ArrowRight, LifeBuoy } from "lucide-react";

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
      <p className="rounded-card border border-line bg-surface-muted px-4 py-3 text-sm text-ink-muted">
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
      className="flex items-start justify-between gap-3 rounded-card border border-warn-line bg-warn-soft px-4 py-3 text-sm text-warn transition-colors duration-(--duration-fast) ease-out hover:bg-[color-mix(in_srgb,var(--warn-soft),var(--warn-line)_40%)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warn focus-visible:ring-offset-2"
    >
      <span className="flex min-w-0 items-start gap-2">
        <LifeBuoy aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <span className="min-w-0">
          <span className="block font-semibold">{first.headline}</span>
          <span className="block">{first.what_we_did}</span>
          {more > 0 && (
            <span className="block">
              {more === 1 ? "One more line needs a look." : `${more} more lines need a look.`}
            </span>
          )}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-1 font-medium">
        Details
        <ArrowRight aria-hidden className="h-3.5 w-3.5" />
      </span>
    </Link>
  );
}
