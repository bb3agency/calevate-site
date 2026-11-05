"use client";

import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { ActionFeedback } from "@/components/arc/feedback";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import {
  NoticeBox,
  PRIMARY_BUTTON_LG,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatPhone,
  formatCountOf,
} from "@/components/ui";
import { shortDay, useCallingNumbers, type CallingNumberDeclaration } from "@/lib/api/autodialerNotice";
import { type CampaignProgress, type useCampaignProgress, type useLaunchCheck } from "@/lib/api/campaigns";
import { useCampaignPurpose, type CampaignPurpose } from "@/lib/api/compliancePack";
import { useClientRealm } from "@/lib/api/session";
import { usePeRegistration } from "@/lib/api/dltRegistration";

import { AtOnceHint } from "./CampaignSettings";
import { ConsentProvenanceAnswer, listSourceId } from "./ConsentProvenance";
import { LaunchConfirm } from "./LaunchConfirm";
import { callingHoursText } from "./campaignProgress";
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
  // What kind of call the client's choices make this (D-943): said, never blocking by itself.
  const purpose = useCampaignPurpose(session, campaignId);
  const promotionalOpen = usePeRegistration(session).data?.calevate_tm_active === true;

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
    const note = blockerNote(blocker.rule, { promotionalOpen });
    const why = note?.why ?? (note?.whyFromServer ? blocker.reason : undefined);
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
      ) : inPage === "rewrite" ? (
        <AskAssistant
          label={`Ask ${ASSISTANT_NAME} to rewrite it`}
          prompt={rewritePrompt(progress.data?.agent_name ?? "this campaign's agent")}
        />
      ) : undefined;
    const link =
      blocker.rule === "script_promotional" && progress.data?.agent_id
        ? { href: at(`/agents/${progress.data.agent_id}`), label: "Open the agent" }
        : blockerDestination(blocker.rule, at, campaignId);
    const detail =
      note?.owner || why ? (
        <>
          {note?.owner ? <span className="mr-3">{OWNER_BADGE[note.owner]}</span> : null}
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
  const todo = items.filter((item) => item.state === "todo").length;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_19rem] lg:gap-10">
      <section aria-labelledby={`launch-${campaignId}`} className="min-w-0">
        <h2 id={`launch-${campaignId}`} className="text-heading text-ink">
          {status === "scheduled" ? "Before it starts" : "Before you launch"}
        </h2>
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
                <button type="button" disabled className={`${PRIMARY_BUTTON_LG} w-full justify-center sm:w-auto`}>
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
        </div>
      </section>
      {progress.data && <LaunchSummary progress={progress.data} purpose={purpose.data?.purpose} />}
    </div>
  );
}

/**
 * WHAT PRESSING CALL WILL DO, beside the button: how many people, how many at once, the
 * hours, the number, and the kind of call the campaign's own choices make it. A review
 * step restates the send before it happens; here it sits beside the button rather than
 * behind a second confirmation (founder, 4 Nov 2026: one press, pause is the way back).
 */
function LaunchSummary({
  progress,
  purpose,
}: {
  progress: CampaignProgress;
  purpose: CampaignPurpose["purpose"] | undefined;
}) {
  const source = CONSENT_SOURCES.find((choice) => choice.value === progress.consent_source)?.label;
  return (
    <dl
      role="group"
      aria-label="What launching does"
      className="grid h-fit grid-cols-2 gap-x-4 gap-y-4 rounded-card bg-surface-muted p-4 sm:grid-cols-4 lg:grid-cols-1 lg:p-5"
    >
      <SummaryFact label="People">{formatCountOf(progress.total, "person", "people")}</SummaryFact>
      <SummaryFact label="Calls at once">
        Up to {formatCount(progress.effective_concurrency)}
        <AtOnceHint progress={progress} />
      </SummaryFact>
      <SummaryFact label="Calling hours">{callingHoursText(progress)}</SummaryFact>
      <SummaryFact label="Calling from">
        {progress.number_e164 ? formatPhone(progress.number_e164) : "Your agent's number"}
      </SummaryFact>
      {purpose && purpose.purpose !== "unclear" && (
        <SummaryFact label="Kind of call" wide>
          {purpose.label}
          {/* The window is the regulation's, stated rather than enforced: a list carries
              one declared date, so the gate cannot check each person's (D-943). */}
          {purpose.window ? (
            <span className="block text-meta text-ink-muted">Permission lasts {purpose.window}.</span>
          ) : null}
          <span className="block text-meta text-ink-muted">
            <Why inline>
              {purpose.explanation}
              {source ? ` Your list: ${source}.` : ""}
              {purpose.window ? " We don't check each person's date for you." : ""}
            </Why>
          </span>
        </SummaryFact>
      )}
    </dl>
  );
}

function SummaryFact({ label, wide = false, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={`min-w-0 ${wide ? "col-span-2 sm:col-span-4 lg:col-span-1" : ""}`}>
      <dt className="text-meta text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-body font-medium text-ink [overflow-wrap:anywhere]">{children}</dd>
    </div>
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
