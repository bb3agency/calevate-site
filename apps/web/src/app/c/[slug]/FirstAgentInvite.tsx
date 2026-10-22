"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PRIMARY_BUTTON } from "@/components/ui";

/**
 * THE WAY IN TO THE FIRST AGENT (D-854, D-855), on the dashboard while the account has none.
 *
 * New accounts are not given a ready agent (D-853), so the dashboard's first job is to send
 * the owner to "Meet your agent". Rendered by the caller only when the agents list answered
 * empty and this person may create an agent; a failed read says nothing here.
 */
export function FirstAgentInvite({ href }: { href: (path: string) => string }) {
  return (
    <section
      aria-labelledby="first-agent-invite"
      className="flex flex-col gap-4 rounded-card border border-brand/40 bg-surface p-5 shadow-card sm:flex-row sm:items-center"
    >
      <div className="min-w-0 flex-1">
        <h2 id="first-agent-invite" className="text-heading text-ink">
          Meet your agent
        </h2>
        <p className="mt-0.5 text-body text-ink-muted">
          Tell it its job in your own words and it is built while you watch. Then it rings your phone so
          you hear it.
        </p>
      </div>
      <Link href={href("/agents/first")} className={PRIMARY_BUTTON}>
        Start
        <ArrowRight aria-hidden className="h-4 w-4" />
      </Link>
    </section>
  );
}
