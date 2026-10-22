"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PipMark } from "@/components/illustration/pip";
import { PRIMARY_BUTTON } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

/**
 * THE WAY IN TO THE FIRST AGENT (D-854), on the dashboard while the account has none.
 *
 * New accounts are no longer given a ready agent (D-853), so the dashboard's first job is to
 * send the owner to build one. Rendered by the caller only when the agents list answered
 * empty and this person may create an agent; a failed read says nothing here.
 */
export function FirstAgentInvite({ href }: { href: (path: string) => string }) {
  return (
    <section
      aria-labelledby="first-agent-invite"
      className="flex flex-col gap-4 rounded-card border border-brand/40 bg-surface p-5 shadow-card sm:flex-row sm:items-center"
    >
      <PipMark size={40} className="shrink-0" />
      <div className="min-w-0 flex-1">
        <h2 id="first-agent-invite" className="text-heading text-ink">
          Build your first agent
        </h2>
        <p className="mt-0.5 text-body text-ink-muted">
          {ASSISTANT_NAME} asks a few questions and builds it with you, in about five minutes. At the
          end, it rings your phone.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link href={href("/agents/first?with=pip")} className={PRIMARY_BUTTON}>
          Build it with {ASSISTANT_NAME}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
        <Link href={href("/agents/first?with=manual")} className={TEXT_ACTION}>
          Set it up myself
        </Link>
      </div>
    </section>
  );
}
