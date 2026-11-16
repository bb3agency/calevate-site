"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";

import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";

import { scriptsHome } from "../[agentId]/sections/agentSections";
import { NEW_AGENT } from "../../_ui/copy";

/**
 * THE AGENT EXISTS, AND WHAT TO DO NEXT. A plain success state rather than a card: one
 * sentence of state, then the one next step, writing what it says. That is written on an
 * inbound line or a campaign, not on the agent (D-997), so the step opens the one that
 * matches the way its calls go.
 */
export function CreatedPanel({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  return (
    <section aria-labelledby="agent-created-heading" className="settings-enter max-w-2xl py-6">
      <CheckCircle2 aria-hidden className="h-6 w-6 text-brand-strong" />
      <h2 id="agent-created-heading" className="mt-3 text-title text-ink">
        {agent.name} is created
      </h2>
      <p className="mt-1 max-w-prose text-body text-ink-muted">{NEW_AGENT.createdHint}</p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link href={href(scriptsHome(slug, agent.direction))} className={PRIMARY_BUTTON}>
          Write what it says
        </Link>
        <Link href={href(`/c/${slug}/agents/${agent.id}`)} className={SECONDARY_BUTTON}>
          Open {agent.name}
        </Link>
      </div>
    </section>
  );
}
