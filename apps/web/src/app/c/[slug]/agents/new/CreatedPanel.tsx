"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { wholeRequestFor } from "../[agentId]/script/PipAsk";

/**
 * THE AGENT EXISTS, AND WHAT TO DO NEXT. A plain success state rather than a card: one
 * sentence of state, then the one next step (write what it says) and the quicker route
 * (Pip drafts it, which the owner asks for and which uses their AI help allowance; the draft
 * waits on the Script page for review, D-820).
 */
export function CreatedPanel({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const script = href(`/c/${slug}/agents/${agent.id}?section=script`);
  return (
    <section aria-labelledby="agent-created-heading" className="settings-enter max-w-2xl py-6">
      <CheckCircle2 aria-hidden className="h-6 w-6 text-brand-strong" />
      <h2 id="agent-created-heading" className="mt-3 text-title text-ink">
        {agent.name} is created
      </h2>
      <p className="mt-1 max-w-prose text-body text-ink-muted">
        It is a draft and switched off, so it is not answering or dialling anyone. Next, write
        what it says.
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link href={script} className={PRIMARY_BUTTON}>
          Write its script
        </Link>
        <AskAssistant label={`Let ${ASSISTANT_NAME} draft it`} prompt={wholeRequestFor(agent.name)} size="md" />
        <Link href={href(`/c/${slug}/agents/${agent.id}`)} className={SECONDARY_BUTTON}>
          Open {agent.name}
        </Link>
      </div>
    </section>
  );
}
