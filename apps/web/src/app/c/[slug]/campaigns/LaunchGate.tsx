"use client";

import { CheckCircle2 } from "lucide-react";
import Link from "next/link";

import type { ActionFeedback } from "@/components/arc/feedback";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { Section } from "@/components/console/section";
import { NoticeBox, PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { shortDay, useCallingNumbers, type CallingNumberDeclaration } from "@/lib/api/autodialerNotice";
import { type useCampaignProgress, type useLaunchCheck } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { ConsentProvenanceAnswer, listSourceId } from "./ConsentProvenance";
import { LaunchConfirm } from "./LaunchConfirm";
import { Why } from "@/components/why";
import {
  BLOCKER_COPY,
  OWNER_BADGE,
  PROVENANCE_RULES,
  blockerDestination,
  blockerInPage,
} from "./blockerCopy";

/**
 * BEFORE YOU LAUNCH: the compliance gate as a checklist, and the launch it guards.
 *
 * **The launch button is disabled with its reasons on screen, not after a click**:
 * `/launch-check` returns named blockers so they can be listed as a to-do, each in
 * `BLOCKER_COPY`'s one line (the server's own `reason` for a rule this build does not know)
 * with the button that fixes it: a link to another screen, or a control on this page (add
 * people, answer where the list came from). There is no bypass to show, because
 * `POST /launch` re-runs the identical gate (hard rule 5).
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
  onAddPeople,
}: {
  slug: string;
  campaignId: string;
  status: string | null;
  check: ReturnType<typeof useLaunchCheck>;
  progress: ReturnType<typeof useCampaignProgress>;
  launch: ActionFeedback<void>;
  canWrite: boolean;
  /** The refusal sentence itself, or `null` while `/v1/me` has not answered. */
  writeReason: string | null;
  /** The same sentence as a control attribute, so a dead button explains itself. */
  refusal: string | undefined;
  /** Opens the add-people panel on this page. */
  onAddPeople: () => void;
}) {
  const { href, session } = useClientRealm();
  const declaration = useCallingNumbers(session);

  // A scheduled campaign has not launched either; the same gate runs when it fires.
  if (status !== "draft" && status !== "scheduled") return null;

  const blockers = check.data?.blockers ?? [];
  const provenanceRule = blockers.find((b) =>
    (PROVENANCE_RULES as readonly string[]).includes(b.rule),
  )?.rule;
  const at = (path: string) => href(`/c/${slug}${path}`);

  const jumpToListSource = () => {
    const form = document.getElementById(listSourceId(campaignId));
    form?.scrollIntoView({ block: "center", behavior: "smooth" });
    form?.querySelector<HTMLElement>("input")?.focus({ preventScroll: true });
  };

  const items: ChecklistItem[] = blockers.map((blocker) => {
    const note = lookup(BLOCKER_COPY, blocker.rule);
    const inPage = blockerInPage(blocker.rule);
    const action =
      inPage === "add-people" ? (
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canWrite} title={refusal} onClick={onAddPeople}>
          Add people
        </button>
      ) : inPage === "list-source" && provenanceRule ? (
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={jumpToListSource}>
          {blocker.rule === "consent_source_refused" ? "Correct answer" : "Answer"}
        </button>
      ) : undefined;
    const detail =
      note?.owner || note?.why ? (
        <>
          {note.owner ? <span className="mr-3">{OWNER_BADGE[note.owner]}</span> : null}
          {note.why ? <Why inline>{note.why}</Why> : null}
        </>
      ) : undefined;
    return {
      id: blocker.rule,
      label: note?.text ?? blocker.reason,
      // A rule we chase is a wait, not a task; the line under it says whose desk it is on.
      state: note?.owner === "calevate" ? "waiting" : "todo",
      detail,
      link: blockerDestination(blocker.rule, at, campaignId),
      action,
    };
  });
  const todo = items.filter((item) => item.state === "todo").length;

  return (
    <Section title={status === "scheduled" ? "Before it starts" : "Before you launch"}>
      <DeclarationDue declaration={declaration.data} href={`${at("/verify-business")}#calling-numbers`} />
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
            status={launch.status}
            onLaunch={() => launch.run()}
          />
          {!canWrite && writeReason && <p className="text-meta text-ink-muted">{writeReason}</p>}
        </div>
      ) : (
        <div className="space-y-4">
          {items.length === 0 ? (
            // Not ready with nothing itemised: say the true thing, that their side is done.
            <p className="text-body text-ink-muted">Everything on your side is ready.</p>
          ) : (
            <Checklist label="Still to do" items={items} emphasizeNext />
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
            <button type="button" disabled className={`${PRIMARY_BUTTON} w-full sm:w-auto`}>
              Launch campaign
            </button>
            {todo > 0 && (
              <p className="text-meta text-ink-muted">
                {todo === 1 ? "Fix 1 item first" : `Fix ${todo} items first`}
              </p>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}

/**
 * Before the calling-number rule is in force (D-941) the gate refuses nothing for it, so a
 * launch goes through; this says calls will stop on that date unless the numbers are
 * declared. From the date the gate's own blocker, with its link, takes over and this hides.
 */
function DeclarationDue({
  declaration,
  href,
}: {
  declaration: CallingNumberDeclaration | undefined;
  href: string;
}) {
  if (!declaration?.applies || !declaration.blocker || declaration.enforced) return null;
  if (declaration.blocker.rule === "a2p_declaration_not_yet_effective") return null;
  return (
    <NoticeBox
      tone="warn"
      title={`Declare your calling numbers before ${shortDay(declaration.enforced_from)}`}
      className="mb-4"
      action={
        <Link href={href} className={SECONDARY_BUTTON_SM}>
          Declare your calling numbers
        </Link>
      }
    >
      From that day, calls from undeclared numbers are refused.
    </NoticeBox>
  );
}
