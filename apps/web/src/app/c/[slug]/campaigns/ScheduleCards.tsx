"use client";

import { CalendarClock, CircleAlert, Repeat } from "lucide-react";

import { Card, FIELD_HINT, SECONDARY_BUTTON, Skeleton, formatIST } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type {
  useCampaignProgress,
  useUnscheduleCampaign,
} from "@/lib/api/campaigns";

import { FireTimeRefusal, SKIP_COPY, describeRepeat, formatOccurrence } from "./scheduleCopy";

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
  unschedule: ReturnType<typeof useUnscheduleCampaign>;
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
            <Card title="Repeats">
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
                      className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                    />
                    <span>
                      We skipped the run due{" "}
                      {formatOccurrence(recurrence.last_skipped_at)} IST.{" "}
                      {lookup(SKIP_COPY, recurrence.last_skipped_reason) ??
                        "The next one is unaffected."}
                    </span>
                  </p>
                )}
                {/* Same wording the one-time card uses, because it is the same fact: the
                    gate refused the last attempt to start. */}
                {(progress.data?.schedule_blocked_rules?.length ?? 0) > 0 && (
                  <p className="flex gap-2.5 text-sm text-ink-muted">
                    <CircleAlert
                      aria-hidden
                      className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                    />
                    <span>
                      We tried to start this run and could not. The reasons are
                      listed below — fix them and it will start on the next
                      attempt.
                    </span>
                  </p>
                )}
                {/* …and the same fact BEFORE the first attempt, which is where this card
                    used to be silent: a repeat armed against a lapsed registration read
                    as a next occurrence and nothing else. */}
                {armedScheduleWouldRefuse && (
                  <FireTimeRefusal kind="repeat" when="armed" />
                )}
                <button
                  type="button"
                  title={refusal}
                  disabled={!canWrite || unschedule.isPending}
                  onClick={() => unschedule.mutate()}
                  className={SECONDARY_BUTTON}
                >
                  {unschedule.isPending ? "Stopping…" : "Stop repeating"}
                </button>
                <p className={FIELD_HINT}>
                  Stopping ends the repeat only. Calls already going out are not
                  affected — pause the campaign for that.
                </p>
              </div>
            </Card>
          )}

          {status === "scheduled" && !recurrence && (
            <Card title="Scheduled">
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
                        className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                      />
                      <span>
                        We tried to start this campaign and could not. The
                        reasons are listed below — fix them and it will start on
                        the next attempt. If they are still outstanding a day
                        after the start time, the campaign goes back to draft.
                      </span>
                    </p>
                  )}
                  {/* …and the same fact BEFORE the first attempt. Without it a start
                      armed against an outstanding blocker says only "Starts Monday,
                      10:00 IST" until the day it does not. */}
                  {armedScheduleWouldRefuse && (
                    <FireTimeRefusal kind="start" when="armed" />
                  )}
                  <button
                    type="button"
                    title={refusal}
                    disabled={!canWrite || unschedule.isPending}
                    onClick={() => unschedule.mutate()}
                    className={SECONDARY_BUTTON}
                  >
                    {unschedule.isPending
                      ? "Cancelling…"
                      : "Cancel scheduled start"}
                  </button>
                </div>
              )}
            </Card>
          )}
    </>
  );
}
