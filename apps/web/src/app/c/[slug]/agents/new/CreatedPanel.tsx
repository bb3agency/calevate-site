"use client";

/**
 * WHAT WAS JUST BUILT, AND WHAT HAS TO HAPPEN NEXT.
 *
 * Split out of `new/page.tsx` (UX-DOCTRINE §6).
 */

import Link from "next/link";
import { ArrowRight, CheckCircle2, MessageSquareQuote } from "lucide-react";

import { Card, NOTICE_TONES, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";

/**
 * Created — and the gap between "created" and "taking calls", stated.
 *
 * The browser is deliberately not bounced to the new agent: a draft agent's screen is
 * mostly absences, and arriving on it with no explanation reads as a broken creation. This
 * says what exists now, what has to happen next, and offers both destinations.
 */
export function CreatedPanel({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  return (
    <Card title={`${agent.name} is ready to be written`}>
      <div className="space-y-4">
        <p className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES.ok}`}>
          <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The agent exists on your account as a draft. It is not on the calling system, so
            it is not answering or dialling anyone.
          </span>
        </p>

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            What happens next
          </p>
          <ol className="mt-2 space-y-2 text-sm text-ink-muted">
            {/* ⚠ THIS SUPERSEDES THE OLD "your account manager writes it with you" COPY,
                on the founder's approved decision that the structured builder is the
                PRIMARY client authoring surface. The old sentence sent an owner to wait
                for someone else for the one thing they can now do themselves — and it was
                the same stale claim that kept the script a footnote on the agent's own
                screen (UX-DOCTRINE §1). */}
            <li>
              <span className="font-medium text-ink">1. You write its script.</span> What it
              says, what it does when a caller asks for something you do not offer, how it
              books. Build it as an opening line, steps and questions, or let AI draft it
              from a description of your business.
            </li>
            <li>
              <span className="font-medium text-ink">2. You teach it what it knows.</span>{" "}
              Opening hours, prices, the questions callers actually ask — you can start
              adding those on its screen right now.
            </li>
            <li>
              <span className="font-medium text-ink">3. You switch it on.</span> That puts it
              on the calling system and it starts taking calls.
            </li>
          </ol>
        </div>

        {/* ONE primary, and it is step 1 — the next thing that has to happen to this
            agent is that somebody writes what it says, and an agent with no script cannot
            be switched on at all (`agent_has_no_script`). The workspace is the secondary,
            because it is where you go when you are NOT doing that (UX-DOCTRINE §4). */}
        <div className="flex flex-wrap gap-3">
          <Link
            href={href(`/c/${slug}/agents/${agent.id}/script`)}
            className={PRIMARY_BUTTON}
          >
            <MessageSquareQuote aria-hidden className="h-4 w-4" />
            Write its script
          </Link>
          <Link href={href(`/c/${slug}/agents/${agent.id}`)} className={SECONDARY_BUTTON}>
            Open {agent.name}
            <ArrowRight aria-hidden className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </Card>
  );
}
