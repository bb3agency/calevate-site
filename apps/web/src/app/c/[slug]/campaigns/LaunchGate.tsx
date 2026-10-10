"use client";

import { CheckCircle2, Rocket } from "lucide-react";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { Card, ProblemNotice, Skeleton } from "@/components/ui";
import { FIRST_CAMPAIGN_BLOCKERS } from "@/lib/api/firstCampaign";
import {
  type useCampaignProgress,
  type useLaunchCampaign,
  type useLaunchCheck,
} from "@/lib/api/campaigns";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { ConsentProvenanceAnswer } from "./ConsentProvenance";
import { LaunchConfirm } from "./LaunchConfirm";
import {
  AUTODIALER_NOTICE_BLOCKERS,
  BLOCKER_COPY,
  FIRST_CAMPAIGN_REVIEW_LABEL,
  KYC_BLOCKERS,
  OWNER_BADGE,
  PLATFORM_BLOCKER,
  PlatformOutageNotice,
} from "./blockerCopy";

/**
 * BEFORE YOU LAUNCH: the compliance gate as a checklist, and the launch it guards.
 *
 * PRIMARY JOB of a draft's screen. **The launch button is disabled with its reasons on
 * screen, not after a click**: `/launch-check` returns named blockers so they can be listed
 * as a to-do, each in `BLOCKER_COPY`'s words (the server's own `reason` for a rule this
 * build does not know, never dropped) with where to go to fix it. There is no bypass to
 * show, because `POST /launch` re-runs the identical gate (hard rule 5). Nothing here is
 * disclosed: UX-DOCTRINE §3 forbids putting a compliance control or the sentence that
 * qualifies it behind one.
 *
 * Only blockers are listed, because only blockers are what the server returns. A checklist
 * padded with "done" rows we inferred would be the screen stating facts it was never told.
 */
export function LaunchGate({
  campaignId,
  status,
  check,
  progress,
  launch,
  canWrite,
  writeReason,
  refusal,
}: {
  campaignId: string;
  status: string | null;
  check: ReturnType<typeof useLaunchCheck>;
  progress: ReturnType<typeof useCampaignProgress>;
  launch: ReturnType<typeof useLaunchCampaign>;
  canWrite: boolean;
  /** The refusal sentence itself, or `null` while `/v1/me` has not answered. */
  writeReason: string | null;
  /** The same sentence as a control attribute, so a dead button explains itself. */
  refusal: string | undefined;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();

  // A scheduled campaign has not launched either; the same gate runs when it fires.
  if (status !== "draft" && status !== "scheduled") return null;

  // Our own outage is split off before anything is counted: it is never one of the
  // client's to-dos.
  const all = check.data?.blockers ?? [];
  const outage = all.find((b) => b.rule === PLATFORM_BLOCKER);
  const blockers = all.filter((b) => b.rule !== PLATFORM_BLOCKER);
  const provenanceRule = blockers.find(
    (b) => b.rule === "consent_provenance_missing" || b.rule === "consent_source_refused",
  )?.rule;

  /** Where a client goes to clear a rule, for the rules whose fix lives on another screen. */
  const destination = (rule: string): { href: string; label: string } | undefined => {
    const at = (path: string) => href(`/c/${session.orgSlug}${path}`);
    if (rule === "trial_campaigns_unavailable")
      return { href: at("/billing?tab=credits"), label: "Add credit to go live" };
    if (rule === "no_credits") return { href: at("/billing?tab=credits"), label: "Add calling credit" };
    if (rule === "spend_cap")
      return { href: at("/billing?tab=usage"), label: "See your monthly spending limit" };
    if (KYC_BLOCKERS.includes(rule))
      return { href: at("/verify-business"), label: "Go to Verify your business" };
    if (AUTODIALER_NOTICE_BLOCKERS.includes(rule))
      return { href: at("/agreements"), label: "Record your autodialler notice" };
    if (FIRST_CAMPAIGN_BLOCKERS.includes(rule))
      return { href: at("/campaign-review"), label: FIRST_CAMPAIGN_REVIEW_LABEL };
    return undefined;
  };

  const items: ChecklistItem[] = blockers.map((blocker) => {
    const note = lookup(BLOCKER_COPY, blocker.rule);
    const to = destination(blocker.rule);
    return {
      id: blocker.rule,
      label: note?.text ?? blocker.reason,
      // A rule we chase is a wait, not a task; the badge says whose desk it is on.
      state: note?.owner === "calevate" ? "waiting" : "todo",
      // Whose desk it is on, under the sentence; the way to the fix is the row's action,
      // which `Checklist` drops below long sentences rather than squeezing them.
      detail: note?.owner ? OWNER_BADGE[note.owner] : undefined,
      link: to,
    };
  });

  return (
    <Card title={status === "scheduled" ? "Before it starts" : "Before you launch"}>
      {check.isLoading ? (
        <Skeleton rows={3} />
      ) : check.error ? (
        // Without this the card would sit over a dead button saying nothing.
        <ProblemNotice error={check.error} onRetry={() => check.refetch()} />
      ) : check.data?.ready ? (
        <div className="space-y-3">
          <p className="flex items-center gap-2 text-sm font-medium text-brand-strong">
            <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0" />
            Everything checks out.
          </p>
          {/* Launching dials real numbers and cannot be recalled: review, restatement,
              type-the-count. `LaunchConfirm` carries the argument. */}
          <LaunchConfirm
            contacts={progress.data?.total}
            concurrency={progress.data?.concurrency}
            callingHours={progress.data?.calling_hours}
            numberE164={progress.data?.number_e164}
            canWrite={canWrite}
            writeReason={refusal}
            pending={launch.isPending}
            onLaunch={() => launch.mutate()}
          />
          {/* Repeated here only: this is the one branch where the line above a dead
              control says everything is fine. */}
          {!canWrite && writeReason && <p className="text-xs text-ink-muted">{writeReason}</p>}
        </div>
      ) : (
        <div className="space-y-4">
          {outage && <PlatformOutageNotice reason={outage.reason} />}
          {items.length === 0 ? (
            // Blocked only by our outage: say the true thing, that their side is done.
            <p className="text-sm text-ink-muted">
              Everything on your side is ready. There is nothing else to do here.
            </p>
          ) : (
            <Checklist label="Still to do" items={items} />
          )}
          {/* The one blocker with a control: answered here, against this draft, so a
              client never has to rebuild a list to record a date. */}
          {provenanceRule && (
            <ConsentProvenanceAnswer
              campaignId={campaignId}
              correcting={provenanceRule === "consent_source_refused"}
            />
          )}
          <button
            type="button"
            disabled
            className="inline-flex cursor-not-allowed items-center gap-2 rounded-md border border-line bg-surface-muted px-4 py-2 text-sm font-semibold text-ink-faint touch:min-h-11"
          >
            <Rocket aria-hidden className="h-4 w-4" />
            Launch campaign
          </button>
        </div>
      )}
    </Card>
  );
}
