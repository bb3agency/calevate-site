"use client";

/**
 * WHAT TO TRY THE AGENT ON (founder, 16 Nov 2026; rememory 298ad6cb). An agent has no script
 * of its own, so the owner picks:
 *
 * - **Just the business** (the default): the chat and the call below try the agent with the
 *   company training and the business's knowledge and no job's script, which tests its
 *   voice, language, style, business answers and actions.
 * - **One of its jobs**, an Inbound line or a campaign in its voice: each has its own Test
 *   call on its own page, ringing it exactly as callers hear it, so this links there rather
 *   than repeating it.
 */

import Link from "next/link";

import { RadioGroup, type RadioOption } from "@/components/arc/radio-group";
import { ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { jobTestPath, useAgentJobs, type AgentJob } from "@/lib/api/agentJobs";
import { useClientRealm, useClientSession } from "@/lib/api/session";

/** The choice that tries the agent on the business alone. */
export const BUSINESS = "business";

const KIND_WORD: Record<AgentJob["kind"], string> = { inbound_line: "Inbound line", campaign: "Campaign" };

export function TryItOn({
  agentId,
  slug,
  value,
  onChange,
}: {
  agentId: string;
  slug: string;
  value: string;
  onChange: (next: string) => void;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const jobs = useAgentJobs(session, agentId);
  const list = jobs.data?.jobs ?? [];
  const options: RadioOption[] = [
    { value: BUSINESS, label: "Just the business", hint: "What your business knows. No script." },
    ...list.map((job) => ({ value: job.id, label: job.name, hint: KIND_WORD[job.kind] })),
  ];
  const chosen = list.find((job) => job.id === value) ?? null;
  const started = chosen?.kind === "campaign" && chosen.status !== "draft";

  return (
    <div className="mt-2 space-y-3">
      <RadioGroup label="Try it on" options={options} value={value} onChange={onChange} />
      {jobs.isPending ? <Skeleton rows={1} label="Finding its Inbound lines and campaigns" /> : null}
      {jobs.isError ? <ProblemNotice error={jobs.error} onRetry={() => void jobs.refetch()} /> : null}
      {jobs.data && list.length === 0 ? (
        <p className="text-meta text-ink-muted">No Inbound line or campaign uses it yet.</p>
      ) : null}
      {chosen ? (
        <div className="flex flex-wrap items-center gap-3 rounded-card border border-line p-4">
          <p className="text-body text-ink-muted">
            {started ? "This campaign has started. Its calls are on its page." : "It has its own test call."}
          </p>
          <Link href={href(jobTestPath(slug, chosen))} className={SECONDARY_BUTTON}>
            {started ? "Open the campaign" : "Open its test call"}
          </Link>
        </div>
      ) : null}
    </div>
  );
}
