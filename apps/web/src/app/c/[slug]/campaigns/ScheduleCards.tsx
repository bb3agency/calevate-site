"use client";

import { CalendarClock, CircleAlert, Repeat } from "lucide-react";

import { ActionButton, type ActionFeedback } from "@/components/arc/feedback";
import { Section } from "@/components/console/section";
import { FIELD_HINT, Skeleton, formatIST } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type { useCampaignProgress } from "@/lib/api/campaigns";

import { Why } from "./_ui/Why";
import { FireTimeRefusal, SKIP_COPY, START_GIVES_UP, describeRepeat, formatOccurrence } from "./scheduleCopy";

/**
 * WHEN THIS CAMPAIGN DIALS NEXT — the two armed-schedule cards.
 *
 * Extracted from `CampaignDetail.tsx` (UX-DOCTRINE §6). One subject: a schedule that is
 * already ON the campaign, and the way out of it. Every sentence here is either the
 * server's own record of a refused attempt or `FireTimeRefusal` saying in advance what
 * the fire-time check will do — the discovery-by-silence this pair exists to prevent —
 * so none of it is disclosed and none of it was reworded in the move.
 */
export function ScheduleCards({
  status,
  progress,
  unschedule,
  armedScheduleWouldRefuse,
  canWrite,
  refusal,
}: {
  status: string | null;
  progress: ReturnType<typeof useCampaignProgress>;
  /** The cancel's feedback; one DELETE ends a one-time start and a repeat alike. */
  unschedule: ActionFeedback<void>;
  /** Would an already-armed schedule be refused if it came due right now? */
  armedScheduleWouldRefuse: boolean;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const recurrence = progress.data?.recurrence ?? null;
  return (
    <>
          {/* THE REPEAT, at any status.
              A one-time start is spent the moment it fires, so its card is keyed on
              `scheduled`. A repeat is not: a campaign dialling right now still repeats
              next Tuesday, and the client needs both that fact and the button that stops
              it wherever they are looking. Rendered only from a response that arrived —
              the loading and failure states are the skeleton and the notice above, and
              "this campaign does not repeat" is a claim neither of them supports. */}
          {recurrence && (
            <Section title="Repeats">
              <div className="space-y-3">
                <p className="flex items-center gap-2 text-sm font-medium text-ink">
                  <Repeat aria-hidden className="h-4 w-4 shrink-0" />
                  Calls {describeRepeat(recurrence)} IST
                </p>
                {/* The sentence this whole card exists for: a schedule a client cannot
                    read against their own calendar is a schedule they cannot trust. */}
                <p className="text-sm text-ink-muted">
                  Next: {formatOccurrence(recurrence.next_occurrence_at)} IST
                  {recurrence.until &&
                    ` · stops repeating after ${formatIST(recurrence.until)}`}
                </p>
                {/* An occurrence that did not run, and why. Without this the campaign
                    simply says "scheduled" on a week it never dialled, which is the
                    silence §52 is about. */}
                {recurrence.last_skipped_at && (
                  <p className="flex gap-2.5 text-sm text-ink-muted">
                    <CircleAlert
                      aria-hidden
                      className="mt-0.5 h-4 w-4 shrink-0 text-warn"
                    />
                    <span>
                      Skipped {formatOccurrence(recurrence.last_skipped_at)} IST.{" "}
                      {lookup(SKIP_COPY, recurrence.last_skipped_reason) ? (
                        <Why>{lookup(SKIP_COPY, recurrence.last_skipped_reason)}</Why>
                      ) : (
                        "The next one is unaffected."
                      )}
                    </span>
                  </p>
                )}
                {/* Same wording the one-time card uses, because it is the same fact: the
                    gate refused the last attempt to start. */}
                {(progress.data?.schedule_blocked_rules?.length ?? 0) > 0 && (
                  <p className="flex gap-2.5 text-sm text-ink-muted">
                    <CircleAlert
                      aria-hidden
                      className="mt-0.5 h-4 w-4 shrink-0 text-warn"
                    />
                    <span>
                      <span className="block text-ink">Couldn&rsquo;t start. Fix the items below.</span>
                      <span className="block">Once fixed, it starts on the next attempt.</span>
                    </span>
                  </p>
                )}
                {/* …and the same fact BEFORE the first attempt, which is where this card
                    used to be silent: a repeat armed against a lapsed registration read
                    as a next occurrence and nothing else. */}
                {armedScheduleWouldRefuse && (
                  <FireTimeRefusal kind="repeat" when="armed" />
                )}
                <ActionButton
                  variant="secondary"
                  title={refusal}
                  disabled={!canWrite}
                  status={unschedule.status}
                  pendingLabel="Stopping"
                  successLabel="Stopped"
                  onClick={() => unschedule.run()}
                >
                  Stop repeating
                </ActionButton>
                <p className={FIELD_HINT}>Ends the repeat only. Pause to stop today&rsquo;s calls.</p>
              </div>
            </Section>
          )}

          {status === "scheduled" && !recurrence && (
            <Section title="Scheduled">
              {/* §52: loading is a skeleton, failure is the notice above — neither is a
                  date and neither is the word "scheduled" on its own. */}
              {progress.isLoading ? (
                <Skeleton rows={2} />
              ) : (
                <div className="space-y-3">
                  <p className="flex items-center gap-2 text-sm font-medium text-ink">
                    <CalendarClock aria-hidden className="h-4 w-4 shrink-0" />
                    Starts {formatIST(progress.data?.scheduled_start_at)} IST
                  </p>
                  {/* The gate refused the last attempt to start it. Without this the
                      campaign sits here saying "scheduled" for a day and then quietly
                      becomes a draft again — a start that never happened and never said
                      so. The rules are the launch gate's own names, so the list above
                      already explains each one in the client's words. */}
                  {(progress.data?.schedule_blocked_rules?.length ?? 0) > 0 && (
                    <p className="flex gap-2.5 text-sm text-ink-muted">
                      <CircleAlert
                        aria-hidden
                        className="mt-0.5 h-4 w-4 shrink-0 text-warn"
                      />
                      <span>
                        <span className="block text-ink">Couldn&rsquo;t start. Fix the items below.</span>
                        <span className="block">{START_GIVES_UP}</span>
                      </span>
                    </p>
                  )}
                  {/* …and the same fact BEFORE the first attempt. Without it a start
                      armed against an outstanding blocker says only "Starts Monday,
                      10:00 IST" until the day it does not. */}
                  {armedScheduleWouldRefuse && (
                    <FireTimeRefusal kind="start" when="armed" />
                  )}
                  <ActionButton
                    variant="secondary"
                    title={refusal}
                    disabled={!canWrite}
                    status={unschedule.status}
                    pendingLabel="Cancelling"
                    successLabel="Cancelled"
                    onClick={() => unschedule.run()}
                  >
                    Cancel scheduled start
                  </ActionButton>
                </div>
              )}
            </Section>
          )}
    </>
  );
}
