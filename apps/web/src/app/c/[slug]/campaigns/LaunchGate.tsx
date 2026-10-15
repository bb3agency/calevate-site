"use client";

import { CheckCircle2 } from "lucide-react";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { Section } from "@/components/console/section";
import { PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import {
  type useCampaignProgress,
  type useLaunchCampaign,
  type useLaunchCheck,
} from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { ConsentProvenanceAnswer } from "./ConsentProvenance";
import { LaunchConfirm } from "./LaunchConfirm";
import { BLOCKER_COPY, OWNER_BADGE, PROVENANCE_RULES, blockerDestination } from "./blockerCopy";

/**
 * BEFORE YOU LAUNCH: the compliance gate as a checklist, and the launch it guards.
 *
 * **The launch button is disabled with its reasons on screen, not after a click**:
 * `/launch-check` returns named blockers so they can be listed as a to-do, each in
 * `BLOCKER_COPY`'s words (the server's own `reason` for a rule this build does not know)
 * with where to fix it. There is no bypass to show, because `POST /launch` re-runs the
 * identical gate (hard rule 5). Only blockers are listed, because only blockers are what
 * the server returns.
 */
export function LaunchGate({
  slug,
  campaignId,
  status,
  check,
  progress,
  launch,
  canWrite,
  writeReason,
  refusal,
}: {
  slug: string;
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
  const { href } = useClientRealm();

  // A scheduled campaign has not launched either; the same gate runs when it fires.
  if (status !== "draft" && status !== "scheduled") return null;

  const blockers = check.data?.blockers ?? [];
  const provenanceRule = blockers.find((b) =>
    (PROVENANCE_RULES as readonly string[]).includes(b.rule),
  )?.rule;
  const at = (path: string) => href(`/c/${slug}${path}`);

  const items: ChecklistItem[] = blockers.map((blocker) => {
    const note = lookup(BLOCKER_COPY, blocker.rule);
    return {
      id: blocker.rule,
      label: note?.text ?? blocker.reason,
      // A rule we chase is a wait, not a task; the line under it says whose desk it is on.
      state: note?.owner === "calevate" ? "waiting" : "todo",
      detail: note?.owner ? OWNER_BADGE[note.owner] : undefined,
      link: blockerDestination(blocker.rule, at, campaignId),
    };
  });

  return (
    <Section
      title={status === "scheduled" ? "Before it starts" : "Before you launch"}
      description={
        check.data && !check.data.ready && items.length > 0
          ? "Nothing is called until every item here is done."
          : undefined
      }
    >
      {check.isLoading ? (
        <Skeleton rows={3} />
      ) : check.error || !check.data ? (
        <ProblemNotice
          error={check.error ?? new Error("The launch check did not load.")}
          onRetry={() => check.refetch()}
        />
      ) : check.data?.ready ? (
        <div className="space-y-3">
          <p className="flex items-center gap-2 text-body font-medium text-ink">
            <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
            Everything checks out.
          </p>
          {/* Launching dials real numbers and cannot be recalled: review, restatement,
              type-the-count (`LaunchConfirm`). */}
          <LaunchConfirm
            contacts={progress.data?.total}
            concurrency={progress.data?.effective_concurrency}
            callingHours={progress.data?.calling_hours}
            numberE164={progress.data?.number_e164}
            canWrite={canWrite}
            writeReason={refusal}
            pending={launch.isPending}
            onLaunch={() => launch.mutate()}
          />
          {!canWrite && writeReason && <p className="text-meta text-ink-muted">{writeReason}</p>}
        </div>
      ) : (
        <div className="space-y-4">
          {items.length === 0 ? (
            // Not ready with nothing itemised: say the true thing, that their side is done.
            <p className="text-body text-ink-muted">
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
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-4">
            <button type="button" disabled className={PRIMARY_BUTTON}>
              Launch campaign
            </button>
            {items.length > 0 && (
              <p className="text-meta text-ink-muted">
                Launch opens once {items.length === 1 ? "the item above is" : `the ${items.length} items above are`} done.
              </p>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}
