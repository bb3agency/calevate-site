"use client";

import { CheckCircle2 } from "lucide-react";
import Link from "next/link";

import type { ActionFeedback } from "@/components/arc/feedback";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { ScriptFixActions } from "@/components/scriptChecks/ScriptNeedsFix";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import {
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { shortDay, useCallingNumbers, type CallingNumberDeclaration } from "@/lib/api/autodialerNotice";
import { type CampaignProgress, type useCampaignProgress, type useLaunchCheck } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { usePeRegistration } from "@/lib/api/dltRegistration";

import { ConsentProvenanceAnswer, ConsentProvenanceFields } from "./ConsentProvenance";
import { FoldSection } from "./FoldSection";
import { complianceCardId } from "./campaignSections";
import { LaunchConfirm } from "./LaunchConfirm";
import { SLOTS_FULL_RULE, SlotHolders, SlotsFullProblem, isSlotsFull } from "./SlotHolders";
import { CONSENT_SOURCES } from "./choices";
import { Why } from "@/components/why";
import {
  blockerNote,
  OWNER_BADGE,
  PROVENANCE_RULES,
  blockerDestination,
  blockerInPage,
  rewritePrompt,
} from "./blockerCopy";

/** The compliance card's name, in the owner's words (redesign plan §6). */
export const CHECKS_TITLE = "Before it can call";

type Blocker = NonNullable<ReturnType<typeof useLaunchCheck>["data"]>["blockers"][number];

/**
 * Which blockers the compliance card lists, and the one count of checks left that the card
 * header, the Checks tab and the Start hint all show (defect C12-b: two counts disagreed).
 *
 * Three blockers are not rows (founder, 15 Nov 2026): where the list came from is asked as a
 * question under the list (it still counts as one check), adding people is the People tab's
 * job, and putting the agent live is the agent's own. A rule we chase ourselves is a wait,
 * not a check for the owner, so it is listed but not counted.
 */
export function checksOf(
  blockers: readonly Blocker[],
  promotionalOpen: boolean | null,
): { listed: Blocker[]; provenanceRule: string | undefined; todo: number } {
  const provenanceRule = blockers.find((b) => (PROVENANCE_RULES as readonly string[]).includes(b.rule))?.rule;
  const listed = blockers.filter(
    (b) =>
      b.rule !== "no_contacts" &&
      b.rule !== "agent_not_live" &&
      !(PROVENANCE_RULES as readonly string[]).includes(b.rule),
  );
  const todo =
    listed.filter((b) => blockerNote(b.rule, { promotionalOpen })?.owner !== "calevate").length +
    (provenanceRule ? 1 : 0);
  return { listed, provenanceRule, todo };
}

/** The checks still to answer on a campaign not yet launched, or `null` while unknown. */
export function useChecksLeft(check: ReturnType<typeof useLaunchCheck>): number | null {
  const { session } = useClientRealm();
  const registration = usePeRegistration(session).data;
  const promotionalOpen = registration ? registration.calevate_tm_active === true : null;
  if (!check.data) return null;
  return check.data.ready ? 0 : checksOf(check.data.blockers, promotionalOpen).todo;
}

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
  // Unknown (null) until the registration read lands: the rule's own copy stands meanwhile.
  const registration = usePeRegistration(session).data;
  const promotionalOpen = registration ? registration.calevate_tm_active === true : null;

  // A scheduled campaign has not launched either; the same gate runs when it fires.
  // Started: the same section, showing what was answered before it went out.
  if (status !== "draft" && status !== "scheduled") {
    return <ComplianceRecord campaignId={campaignId} progress={progress.data} />;
  }

  const blockers = check.data?.blockers ?? [];
  const { listed, provenanceRule, todo } = checksOf(blockers, promotionalOpen);
  const at = (path: string) => href(`/c/${slug}${path}`);

  const noPeople = blockers.some((b) => b.rule === "no_contacts");
  const agentNotLive = blockers.some((b) => b.rule === "agent_not_live");
  const provenanceBlocker = blockers.find((b) => b.rule === provenanceRule);
  const provenanceProblem =
    provenanceBlocker && provenanceRule !== "consent_provenance_missing"
      ? (blockerNote(provenanceBlocker.rule, { promotionalOpen })?.text ?? provenanceBlocker.reason)
      : undefined;
  const items: ChecklistItem[] = listed.map((blocker) => {
    const note = blockerNote(blocker.rule, { promotionalOpen });
    const why = note?.why ?? (note?.whyFromServer ? blocker.reason : undefined);
    const inPage = blockerInPage(blocker.rule);
    const action =
      inPage === "add-people" ? (
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canWrite} title={refusal} onClick={onAddPeople}>
          Add people
        </button>
      ) : inPage === "fix-script" ? (
        <ScriptFixActions holder={{ kind: "campaign", id: campaignId }} canWrite={canWrite} refusal={refusal} />
      ) : inPage === "rewrite" ? (
        <AskAssistant
          label={`Ask ${ASSISTANT_NAME} to rewrite it`}
          prompt={rewritePrompt(progress.data?.agent_name ?? "this campaign's agent")}
        />
      ) : undefined;
    const link = blockerDestination(blocker.rule, at, campaignId, progress.data?.agent_id);
    const detail =
      blocker.rule === SLOTS_FULL_RULE ? (
        <SlotHolders slug={slug} holders={blocker.holders ?? []} />
      ) : note?.owner === "calevate" || why ? (
        <>
          {note?.owner === "calevate" ? <span className="mr-3">{OWNER_BADGE[note.owner]}</span> : null}
          {why ? <Why inline>{why}</Why> : null}
        </>
      ) : undefined;
    return {
      id: blocker.rule,
      label: note?.text ?? blocker.reason,
      // A rule we chase is a wait, not a task; the line under it says whose desk it is on.
      state: note?.owner === "calevate" ? "waiting" : "todo",
      detail,
      link,
      action,
    };
  });

  return (
    // The compliance checks (founder, 15 Nov 2026): foldable, open by default. Launch stays
    // disabled here until every check is answered, and the server's compliance gate refuses
    // a launch that skips one (hard rule 5), whatever this shows.
    <FoldSection
      id={complianceCardId(campaignId)}
      title={CHECKS_TITLE}
      tone="compliance"
      aside={
        check.data?.ready ? (
          <span className="font-medium text-brand-strong">All checks done</span>
        ) : todo > 0 ? (
          <span className="font-medium text-warn">{todo === 1 ? "1 check to answer" : `${todo} checks to answer`}</span>
        ) : undefined
      }
    >
        <div>
        <div className="min-w-0">
        <p className="text-meta text-ink-muted">Required by law before any call goes out.</p>
        <p className="text-meta text-ink-muted">It cannot start until each one is answered.</p>
        <DeclarationDue declaration={declaration.data} href={`${at("/verify-business")}#calling-numbers`} />
        <div className="mt-3">
          {check.isLoading ? (
            <Skeleton rows={3} />
          ) : check.error || !check.data ? (
            <ProblemNotice
              error={check.error ?? new Error("The launch check did not load.")}
              onRetry={() => check.refetch()}
            />
          ) : check.data.ready ? (
            <div className="space-y-5">
              <p className="flex items-center gap-2 text-body font-medium text-ink">
                <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
                Everything checks out.
              </p>
              <LaunchConfirm
                contacts={progress.data?.total}
                canWrite={canWrite}
                writeReason={refusal}
                status={launch.status}
                onLaunch={() => launch.run()}
                waiting={check.isRefetching && launch.status !== "pending" ? "Checking your campaign again" : null}
              />
              {/* The launch's feedback is inline, so a refusal of this button is said here. */}
              {launch.error != null &&
                (isSlotsFull(launch.error) ? (
                  <SlotsFullProblem slug={slug} error={launch.error} />
                ) : (
                  <ProblemNotice error={launch.error} />
                ))}
              {!canWrite && writeReason && <p className="text-meta text-ink-muted">{writeReason}</p>}
            </div>
          ) : (
            <div className="space-y-4">
              {/* The card's header carries the one count (`todo`, which includes the
                  where-the-list-came-from question below the list), so the list adds none. */}
              {items.length > 0 && <Checklist label="Checks to answer" items={items} emphasizeNext counted={false} />}
              {items.length === 0 && !provenanceRule && !noPeople && !agentNotLive && (
                // Not ready with nothing itemised: say the true thing, that their side is done.
                <p className="text-body text-ink-muted">Everything on your side is ready.</p>
              )}
              {/* The one blocker with a control: answered here, against this draft, so a
                  client never has to rebuild a list to record a date. */}
              {provenanceRule && (
                <ConsentProvenanceAnswer campaignId={campaignId} problem={provenanceProblem} />
              )}
            </div>
          )}
        </div>
        </div>
        </div>
    </FoldSection>
  );
}

/**
 * A started campaign's checks, shown exactly as they were answered during set-up (founder,
 * 16 Nov 2026: "nothing changes here even after the campaign has started"). The server
 * refuses a new answer once it has dialled, so the question is shown answered and fixed.
 */
function ComplianceRecord({
  campaignId,
  progress,
}: {
  campaignId: string;
  progress: CampaignProgress | undefined;
}) {
  const source = CONSENT_SOURCES.find((choice) => choice.value === progress?.consent_source)?.value ?? "";
  const collectedAt = progress?.consent_collected_at
    ? new Date(progress.consent_collected_at).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })
    : "";
  return (
    <FoldSection
      id={complianceCardId(campaignId)}
      title={CHECKS_TITLE}
      tone="compliance"
      aside={<span className="font-medium text-brand-strong">All checks done</span>}
    >
      <p className="text-meta text-ink-muted">Required by law before any call goes out.</p>
      <div className="mt-3">
        <ConsentProvenanceFields
          idPrefix={`record-${campaignId}`}
          source={source}
          collectedAt={collectedAt}
          onSource={() => undefined}
          onCollectedAt={() => undefined}
          mandatory
          disabled
        />
      </div>
    </FoldSection>
  );
}

/**
 * Before the calling-number rule is in force (D-941) the gate refuses nothing for it, so a
 * launch goes through; this says calls will stop on that date unless the numbers are
 * confirmed. From the date the gate's own blocker, with its link, takes over and this hides.
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
      title={`Confirm your calling numbers before ${shortDay(declaration.enforced_from)}`}
      className="mb-4"
      action={
        <Link href={href} className={SECONDARY_BUTTON_SM}>
          Confirm numbers
        </Link>
      }
    >
      From that day, calls from numbers you have not confirmed are refused.
    </NoticeBox>
  );
}
