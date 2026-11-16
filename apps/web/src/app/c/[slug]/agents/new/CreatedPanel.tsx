"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, PhoneIncoming, PhoneOutgoing } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useCreateInboundLine } from "@/lib/api/inboundLines";
import { useClientRealm, useClientSession } from "@/lib/api/session";

import { AGENT_PARAM } from "../../campaigns/NewCampaignScreen";
import { NEW_AGENT } from "../../_ui/copy";

/**
 * GIVE IT A JOB (founder, 16 Nov 2026). An agent is staff with no script of its own: what a
 * call says is written on an Inbound line or a campaign, in this agent's voice. So the end of
 * making an agent is one of those two, made with it:
 *
 * - **New Inbound line** makes a draft line in its voice at once and opens it (the line
 *   names itself, as the Inbound list's New line does);
 * - **New campaign** opens a new draft campaign with it as the agent (`?agent=`).
 */
export function GiveItAJob({ agentId, slug }: { agentId: string; slug: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const router = useRouter();
  const createLine = useCreateInboundLine(session);
  const lineFeedback = useActionFeedback(createLine, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "give this agent a job");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <ActionButton
          status={lineFeedback.status}
          pendingLabel="Making the line…"
          successLabel="Made"
          disabled={!write.allowed}
          title={write.reason ?? undefined}
          onClick={() =>
            createLine.mutate(
              { agent_id: agentId },
              { onSuccess: (line) => router.push(href(`/c/${slug}/inbound/${line.id}`)) },
            )
          }
        >
          <PhoneIncoming aria-hidden className="h-4 w-4" />
          New Inbound line
        </ActionButton>
        <Link href={href(`/c/${slug}/campaigns/new?${AGENT_PARAM}=${agentId}`)} className={SECONDARY_BUTTON}>
          <PhoneOutgoing aria-hidden className="h-4 w-4" />
          New campaign
        </Link>
      </div>
      {createLine.error ? <ProblemNotice error={createLine.error} /> : null}
    </div>
  );
}

/** The blank flow's finish: the agent exists, and the one next step is giving it a job. */
export function CreatedPanel({ agent, slug }: { agent: { id: string; name: string }; slug: string }) {
  const { href } = useClientRealm();
  return (
    <section aria-labelledby="agent-created-heading" className="settings-enter max-w-2xl py-6">
      <CheckCircle2 aria-hidden className="h-6 w-6 text-brand-strong" />
      <h2 id="agent-created-heading" className="mt-3 text-title text-ink">
        {agent.name} is created
      </h2>
      <p className="mt-1 max-w-prose text-body text-ink-muted">{NEW_AGENT.createdHint}</p>
      <div className="mt-6 space-y-4">
        <GiveItAJob agentId={agent.id} slug={slug} />
        <Link href={href(`/c/${slug}/agents/${agent.id}`)} className={TEXT_ACTION}>
          Open {agent.name}
        </Link>
      </div>
    </section>
  );
}
