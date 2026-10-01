"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, MessageSquareQuote } from "lucide-react";

import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";

/**
 * The step flow's done state: what was made, and the one next thing.
 *
 * "Created" and "able to take calls" are different facts, so the line under the heading
 * says which one this is. The primary is writing the script, because an agent with none
 * cannot be switched on (`agent_has_no_script`); the agent's own screen is the secondary,
 * where its checklist says what else is left.
 */
export function CreatedPanel({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  return (
    <section
      aria-labelledby="agent-created-heading"
      className="settings-enter rounded-card border border-line bg-surface p-6 shadow-card"
    >
      <CheckCircle2 aria-hidden className="h-6 w-6 text-brand-strong" />
      <h2 id="agent-created-heading" className="mt-3 text-lg font-semibold text-ink">
        {agent.name} is created
      </h2>
      <p className="mt-1 max-w-prose text-sm text-ink-muted">
        It is a draft and switched off, so it is not answering or dialling anyone. Next, write
        what it says.
      </p>
      <div className="mt-5 flex flex-wrap gap-3">
        <Link href={href(`/c/${slug}/agents/${agent.id}/script`)} className={PRIMARY_BUTTON}>
          <MessageSquareQuote aria-hidden className="h-4 w-4" />
          Write its script
        </Link>
        <Link href={href(`/c/${slug}/agents/${agent.id}`)} className={SECONDARY_BUTTON}>
          Open {agent.name}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
      </div>
    </section>
  );
}
