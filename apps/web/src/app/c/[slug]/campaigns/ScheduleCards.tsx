"use client";

import type { ReactNode } from "react";
import { CalendarClock, CircleAlert, Repeat } from "lucide-react";

import { ActionButton, type ActionFeedback } from "@/components/arc/feedback";
import { FIELD_HINT, Skeleton, formatIST } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type { useCampaignProgress } from "@/lib/api/campaigns";

import { Why } from "@/components/why";
import { FireTimeRefusal, SKIP_COPY, START_GIVES_UP, describeRepeat, formatOccurrence } from "./scheduleCopy";

/**
 * WHEN THIS CAMPAIGN DIALS NEXT — the schedule already ON the campaign, and the way out of
 * it: a one-time start while it is `scheduled`, and a weekly repeat at any status.
 *
 * Every warning here is either the server's own record of a refused attempt or
 * `FireTimeRefusal` saying in advance what the fire-time check will do, so a schedule
 * armed against an outstanding blocker never reads as a plain date until the day it does
 * not start. The cancel controls sit here, outside the launch verdict, because
 * `DELETE /schedule` runs no gate: a client must be able to stop a start they no longer
 * want however blocked the campaign has become.
 */
export function ScheduleCards({
  status,
  progress,
  unschedule,
  armedScheduleWouldRefuse,
  canWrite,
  refusal,
  className = "",
}: {
  status: string | null;
  progress: ReturnType<typeof useCampaignProgress>;
  /** The cancel's feedback; one DELETE ends a one-time start and a repeat alike. */
  unschedule: ActionFeedback<void>;
  /** Would an already-armed schedule be refused if it came due right now? */
  armedScheduleWouldRefuse: boolean;
  canWrite: boolean;
  refusal: string | undefined;
  className?: string;
}) {
  const recurrence = progress.data?.recurrence ?? null;
  const refused = (progress.data?.schedule_blocked_rules?.length ?? 0) > 0;

  // A one-time start is spent the moment it fires, so its card is keyed on `scheduled`;
  // a repeat is not, so a campaign dialling today still shows next Tuesday's run and the
  // button that stops it. Each renders only from a response that arrived.
  if (recurrence) {
    return (
      <ArmedCard
        className={className}
        icon={<Repeat aria-hidden className="h-4 w-4" />}
        title="Repeats"
        action={
          <>
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
          </>
        }
      >
        <p className="text-body font-medium text-ink">Calls {describeRepeat(recurrence)} IST</p>
        <p className="text-meta text-ink-muted">
          Next: {formatOccurrence(recurrence.next_occurrence_at)} IST
          {recurrence.until && ` · stops repeating after ${formatIST(recurrence.until)}`}
        </p>
        {recurrence.last_skipped_at && (
          <Warning>
            Skipped {formatOccurrence(recurrence.last_skipped_at)} IST.{" "}
            {lookup(SKIP_COPY, recurrence.last_skipped_reason) ? (
              <Why inline>{lookup(SKIP_COPY, recurrence.last_skipped_reason)}</Why>
            ) : (
              "The next one is unaffected."
            )}
          </Warning>
        )}
        {refused && (
          <Warning>
            <span className="block text-ink">Couldn&rsquo;t start. Fix the items below.</span>
            <span className="block">Once fixed, it starts on the next attempt.</span>
          </Warning>
        )}
        {armedScheduleWouldRefuse && <FireTimeRefusal kind="repeat" when="armed" />}
      </ArmedCard>
    );
  }

  if (status !== "scheduled") return null;
  return (
    <ArmedCard
      className={className}
      icon={<CalendarClock aria-hidden className="h-4 w-4" />}
      title="Scheduled"
      action={
        progress.isLoading ? undefined : (
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
        )
      }
    >
      {/* Loading is a skeleton, never a date or the bare word "scheduled". */}
      {progress.isLoading ? (
        <Skeleton rows={2} />
      ) : (
        <>
          <p className="text-body font-medium text-ink">Starts {formatIST(progress.data?.scheduled_start_at)} IST</p>
          {refused && (
            <Warning>
              <span className="block text-ink">Couldn&rsquo;t start. Fix the items below.</span>
              <span className="block">{START_GIVES_UP}</span>
            </Warning>
          )}
          {armedScheduleWouldRefuse && <FireTimeRefusal kind="start" when="armed" />}
        </>
      )}
    </ArmedCard>
  );
}

function ArmedCard({
  icon,
  title,
  action,
  children,
  className,
}: {
  icon: ReactNode;
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className: string;
}) {
  return (
    <section className={`flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between ${className}`}>
      <div className="min-w-0 space-y-1.5">
        <h2 className="flex items-center gap-2 text-heading text-ink">
          <span className="text-brand-strong">{icon}</span>
          {title}
        </h2>
        {children}
      </div>
      {action ? <div className="shrink-0 space-y-1.5 sm:max-w-[16rem] sm:text-right">{action}</div> : null}
    </section>
  );
}

function Warning({ children }: { children: ReactNode }) {
  return (
    <p className="flex gap-2.5 text-meta text-ink-muted">
      <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
      <span>{children}</span>
    </p>
  );
}
