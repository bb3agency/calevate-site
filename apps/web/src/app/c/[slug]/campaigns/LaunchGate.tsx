"use client";

import Link from "next/link";
import { CheckCircle2, CircleAlert, Rocket } from "lucide-react";

import { Card, ProblemNotice, Skeleton } from "@/components/ui";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { FIRST_CAMPAIGN_BLOCKERS } from "@/lib/api/firstCampaign";
import {
  type useCampaignProgress,
  type useLaunchCheck,
  type useLaunchCampaign,
  type useScheduleCampaign,
  type useSetRecurrence,
} from "@/lib/api/campaigns";

import { ArmingForms } from "./ArmingForms";
import { LaunchConfirm } from "./LaunchConfirm";
import { ConsentProvenanceAnswer } from "./ConsentProvenance";
import {
  BLOCKER_COPY,
  FIRST_CAMPAIGN_REVIEW_LABEL,
  KYC_BLOCKERS,
  OWNER_BADGE,
  PLATFORM_BLOCKER,
  PlatformOutageNotice,
} from "./blockerCopy";
import type { ScheduleFormState } from "./campaignForm";

/**
 * BEFORE YOU LAUNCH — the compliance gate, its to-do list, and the two ways to arm it
 * for later.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). One subject, and it is the screen's whole
 * reason for existing: **the launch button is disabled with its reasons on screen, not
 * after a click.** Nothing in here is disclosed and nothing is shortened — UX-DOCTRINE §3
 * forbids putting a compliance control or the sentence that qualifies it behind a
 * `<Disclosure>`, and hard rule 5 forbids a bypass. The client never sees one, because
 * there isn't one: `POST /launch` re-runs the identical gate server-side.
 *
 * The SCHEDULE and REPEAT forms render on both verdicts, and that exception is the
 * SERVER's rather than this screen's: arming a schedule runs no compliance gate — the
 * gate runs when it FIRES, on every occurrence (D-79, `campaigns/scheduling.py`
 * decision 3). The blocker list stays above them and `FireTimeRefusal` states the
 * fire-time consequence beside them; the full argument is at their call site below.
 */
export function LaunchGate({
  campaignId,
  status,
  check,
  progress,
  launch,
  schedule,
  repeat,
  scheduleForm,
  canWrite,
  writeReason,
  refusal,
}: {
  campaignId: string;
  status: string | null;
  check: ReturnType<typeof useLaunchCheck>;
  progress: ReturnType<typeof useCampaignProgress>;
  launch: ReturnType<typeof useLaunchCampaign>;
  schedule: ReturnType<typeof useScheduleCampaign>;
  repeat: ReturnType<typeof useSetRecurrence>;
  scheduleForm: ScheduleFormState;
  canWrite: boolean;
  /** The refusal sentence itself, or `null` while `/v1/me` has not answered. */
  writeReason: string | null;
  /** The same sentence as a control attribute, so a dead button explains itself. */
  refusal: string | undefined;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();

  // Our outage is split off from the client's list BEFORE anything is rendered, so it
  // can never be counted, bulleted or badged alongside things this business can
  // actually do. See PLATFORM_BLOCKER.
  const allBlockers = check.data?.blockers ?? [];
  const platformOutage = allBlockers.find((b) => b.rule === PLATFORM_BLOCKER);
  const clientBlockers = allBlockers.filter((b) => b.rule !== PLATFORM_BLOCKER);
  // Which of the two provenance blockers is on this campaign, if either — the answer
  // form is the same either way, but the question it asks is not ("record" vs
  // "correct"), and neither should appear when the launch check is clean.
  const provenanceBlocker = clientBlockers.find(
    (b) =>
      b.rule === "consent_provenance_missing" ||
      b.rule === "consent_source_refused",
  )?.rule;
  const blockedOnKyc = clientBlockers.some((b) => KYC_BLOCKERS.includes(b.rule));
  const blockedOnFirstCampaign = clientBlockers.some((b) =>
    FIRST_CAMPAIGN_BLOCKERS.includes(b.rule),
  );
  /* THE TWO MONEY GATES, each with a screen behind it — the same shape as the KYC and
     first-campaign links below: the bullet says WHY, the link says WHERE. They are
     separate booleans and separate links because they end differently: an empty wallet is
     fixed in two minutes with a card, and a monthly limit is a number the account owner
     chose and may not want to move. */
  const blockedOnCredits = clientBlockers.some((b) => b.rule === "no_credits");
  const blockedOnSpendCap = clientBlockers.some((b) => b.rule === "spend_cap");

  return (
    <>
          {/* `scheduled` shares this card with `draft`: a campaign waiting for Monday
              has not launched, its blockers are still the launch gate's, and the server
              re-runs exactly this check when the schedule fires. Rendering it only for
              `draft` would leave a scheduled campaign with no card at all — a status and
              nothing else, which §52 says a screen may not stop at. */}
          {(status === "draft" || status === "scheduled") && (
            <Card
              title={
                status === "scheduled"
                  ? "Before it starts"
                  : "Before you launch"
              }
            >
              {check.isLoading ? (
                <Skeleton rows={3} />
              ) : check.error ? (
                /* Without this the card renders an empty blocker list under a
                   dead button: "you cannot launch, and we will not say why". */
                <ProblemNotice
                  error={check.error}
                  onRetry={() => check.refetch()}
                />
              ) : check.data?.ready ? (
                <div className="space-y-3">
                  <p className="flex items-center gap-2 text-sm font-medium text-brand-strong dark:text-brand-bright">
                    <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0" />
                    Everything checks out.
                  </p>
                  {/* NOT a bare button. Launching dials real Indian phone numbers under
                      TRAI and a placed call cannot be recalled, so it gets the same
                      three-beat gate as every other irreversible control in this product
                      — review, restatement, type-the-count — rather than being the one
                      with none. `LaunchConfirm` carries the full argument, including why
                      it has no size threshold where `BulkActionBar` has one. */}
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

                  {/* THE ONE PLACE THE TOP-OF-SCREEN RESTRICTION NOTE IS REPEATED, and
                      the exception is earned: this is the only branch where the sentence
                      immediately above a dead control says everything is fine. A `staff`
                      user — no longer a view-as operator, who since D-587 holds
                      `leads:dispatch` and may press it — reads "Everything checks
                      out", presses nothing, and has to scroll past the tiles and the
                      contact list to find out why — which is how a working compliance
                      gate gets reported as a broken button. The other three controls
                      keep the single note; they sit under a reason of their own. */}
                  {!canWrite && writeReason && (
                    <p className="text-xs text-ink-muted">{writeReason}</p>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Above the list, in its own shape, and never inside it. */}
                  {platformOutage && (
                    <PlatformOutageNotice reason={platformOutage.reason} />
                  )}

                  {/* A campaign blocked ONLY by our outage has an empty to-do list, and
                      an empty list under "Before you launch" reads as "we will not say
                      why". Say the true thing: your side is done. */}
                  {clientBlockers.length === 0 ? (
                    <p className="text-sm text-ink-muted">
                      Everything on your side is ready. There is nothing else to
                      do here.
                    </p>
                  ) : (
                    <ul className="space-y-2.5">
                      {clientBlockers.map((blocker) => {
                        // The server's own `reason` is the fallback, never dropped: a
                        // blocker this build has no copy for is still a blocker, and an
                        // unnamed one would read as "you cannot launch, and we will not
                        // say why" — the exact failure this card exists to prevent.
                        const note = lookup(BLOCKER_COPY, blocker.rule);
                        return (
                          <li
                            key={blocker.rule}
                            className="flex gap-2.5 text-sm"
                          >
                            <CircleAlert
                              aria-hidden
                              className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                            />
                            <span className="text-ink-muted">
                              {note?.text ?? blocker.reason}
                              {note?.owner && (
                                <span className="ml-2 whitespace-nowrap rounded-full border border-line px-1.5 py-0.5 text-[11px] font-medium text-ink-faint">
                                  {OWNER_BADGE[note.owner]}
                                </span>
                              )}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  {/* The reason above says WHY; this says where to go. Carries the
                      view-as marker like every other in-realm link, so an operator
                      following it from a "view as client" session does not drop back
                      to a client token two pages in (lib/api/session.tsx). */}
                  {/* THE WALLET, one click away. The bullet above says what stopped —
                      since D-551 that is the dialling AND the answering; this is the
                      two-minute fix, and without it a client whose phone has gone quiet is
                      left hunting for "Calling credit" at the bottom of a settings menu. */}
                  {blockedOnCredits && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/billing?tab=credits`)}
                        className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                      >
                        Add calling credit
                      </Link>{" "}
                      <span className="text-ink-muted">
                        — it takes a minute, and your campaigns and your agents&apos;
                        answering both start again as soon as it lands.
                      </span>
                    </p>
                  )}

                  {/* The monthly limit is the client's OWN and lives on Usage (D-34 R-11),
                      so this is a destination and not an account-manager queue. */}
                  {blockedOnSpendCap && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/billing?tab=usage`)}
                        className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                      >
                        See your monthly spending limit
                      </Link>{" "}
                      <span className="text-ink-muted">
                        — it is your own setting, and you can raise it there.
                      </span>
                    </p>
                  )}

                  {blockedOnKyc && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/verification`)}
                        className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                      >
                        See what we need to verify your business
                      </Link>{" "}
                      <span className="text-ink-muted">
                        — incoming calls are unaffected while this is
                        outstanding.
                      </span>
                    </p>
                  )}

                  {/* Same shape as the KYC link above, and for the same reason: the
                      bullet says WHY, this says where to go. The trailing sentence is
                      the one thing the server's per-campaign reason structurally cannot
                      say — the hold is on the ACCOUNT, so it is not a gate this client
                      will meet again on their next campaign. */}
                  {blockedOnFirstCampaign && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/campaign-review`)}
                        className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                      >
                        {FIRST_CAMPAIGN_REVIEW_LABEL}
                      </Link>{" "}
                      <span className="text-ink-muted">
                        — it is a one-off check on your account, not on each
                        campaign, and incoming calls are unaffected.
                      </span>
                    </p>
                  )}

                  {/* The one blocker with a control attached, rendered under the
                      sentence that asks for it. `consent_source_refused` gets the form
                      too — a client who mis-answered must be able to correct the record
                      without rebuilding the campaign, and a client who answered truly
                      simply leaves it and the refusal stands. */}
                  {provenanceBlocker && (
                    <ConsentProvenanceAnswer
                      campaignId={campaignId}
                      correcting={
                        provenanceBlocker === "consent_source_refused"
                      }
                    />
                  )}

                  {/* Disabled WITH the reasons above it — SURFACES §2b. A blocked
                      feature that is merely missing teaches the client nothing. */}
                  <button
                    type="button"
                    disabled
                    className="inline-flex cursor-not-allowed items-center gap-2 rounded-md border border-line bg-app px-4 py-2 text-sm font-semibold text-ink-faint"
                  >
                    <Rocket aria-hidden className="h-4 w-4" />
                    Launch campaign
                  </button>
                </div>
              )}

              <ArmingForms
                status={status}
                check={check}
                schedule={schedule}
                repeat={repeat}
                scheduleForm={scheduleForm}
                canWrite={canWrite}
                refusal={refusal}
              />
            </Card>
          )}
    </>
  );
}
