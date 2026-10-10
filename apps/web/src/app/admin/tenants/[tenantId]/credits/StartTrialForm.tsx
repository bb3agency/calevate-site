"use client";

import { useState } from "react";
import { CheckCircle2, TriangleAlert } from "lucide-react";

import {
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON,
  RestrictionNote,
  formatCountOf,
  formatIST,
} from "@/components/ui";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useAdminAccess } from "@/app/admin/access";
import { Term } from "@/lib/glossary";
import {
  DEFAULT_ERASURE_GRACE_DAYS,
  MAX_ERASURE_GRACE_DAYS,
  MAX_FREE_MINUTES,
  MAX_TRIAL_DAYS,
  MIN_ERASURE_GRACE_DAYS,
  MIN_FREE_MINUTES,
  MIN_TRIAL_DAYS,
  useStartTrial,
} from "@/lib/api/trials";

import { Field, describedBy } from "./fields";

/**
 * OPENING a trial — the expensive direction, and the one the confirmation is for.
 *
 * Its own file rather than a third section of `TrialPanel.tsx`, by subject (UX-DOCTRINE
 * §6): starting and ending a trial are different acts with different ceremony, and the
 * whole point of the difference is that it stays visible.
 *
 * What this control has to say before it is pressed, and why: `TrialPanel.tsx`.
 */

/** The draft, as strings — the day counts because a half-typed number is not a number. */
interface StartDraft {
  days: string;
  /** Typed a second time. Double keying, on the field that is the only bound this
   * arrangement has. */
  confirm: string;
  reason: string;
  grace: string;
  minutes: string;
}

const NO_START: StartDraft = {
  days: "",
  confirm: "",
  reason: "",
  grace: String(DEFAULT_ERASURE_GRACE_DAYS),
  minutes: "",
};

/** Whole days only, inside the bounds the route and the table both enforce. Parsed as an
 * INTEGER COUNT, not money — hard rule 7 is about rupees, and a day count that reached the
 * API as a string would be refused by a `Field(ge=…, le=…)` typed `int`. */
function dayProblem(raw: string, low: number, high: number, what: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  if (!/^\d{1,3}$/.test(trimmed)) return `${what} is a whole number of days.`;
  const value = Number(trimmed);
  if (value < low || value > high) return `${what} is between ${low} and ${high} days.`;
  return null;
}

export function StartTrialForm({
  clientName,
  start,
  write,
}: {
  clientName: string;
  start: ReturnType<typeof useStartTrial>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<StartDraft>(NO_START);
  const set = (key: keyof StartDraft, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    // The last result described a trial that is no longer the one in the form.
    start.reset();
  };

  const daysProblem = dayProblem(draft.days, MIN_TRIAL_DAYS, MAX_TRIAL_DAYS, "A trial");
  const daysReady = draft.days.trim() !== "" && daysProblem === null;
  const confirmed = daysReady && draft.confirm.trim() === draft.days.trim();
  const graceProblem = dayProblem(
    draft.grace,
    MIN_ERASURE_GRACE_DAYS,
    MAX_ERASURE_GRACE_DAYS,
    "The grace period",
  );
  const graceReady = draft.grace.trim() !== "" && graceProblem === null;
  const minutesRaw = draft.minutes.trim();
  const minutesProblem =
    minutesRaw === ""
      ? null
      : !/^\d{1,4}$/.test(minutesRaw) ||
          Number(minutesRaw) < MIN_FREE_MINUTES ||
          Number(minutesRaw) > MAX_FREE_MINUTES
        ? `Free minutes are a whole number between ${MIN_FREE_MINUTES} and ${MAX_FREE_MINUTES}.`
        : null;
  const minutesReady = minutesRaw !== "" && minutesProblem === null;
  const reason = draft.reason.trim();
  const reasonReady = reason.length >= 3;
  const ready =
    write.allowed && confirmed && graceReady && minutesReady && reasonReady && !start.isPending;
  const days = daysReady ? Number(draft.days.trim()) : null;

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (days === null) return;
        start.mutate(
          {
            days,
            reason,
            erasureGraceDays: Number(draft.grace.trim()),
            freeMinutes: Number(minutesRaw),
          },
          { onSuccess: () => setDraft(NO_START) },
        );
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Days on us"
          id="trial-days"
          hint={`Between ${MIN_TRIAL_DAYS} and ${MAX_TRIAL_DAYS}. There is no spend ceiling on a trial, so this number is the only bound on what it can cost us.`}
          error={daysProblem}
        >
          <input
            id="trial-days"
            value={draft.days}
            disabled={!write.allowed}
            onChange={(event) => set("days", event.target.value)}
            inputMode="numeric"
            autoComplete="off"
            aria-describedby={describedBy("trial-days", daysProblem !== null)}
            aria-invalid={daysProblem !== null}
            className={FIELD}
          />
        </Field>

        <Field
          label="Type the number of days again"
          id="trial-days-confirm"
          hint="Typed twice because it is the whole bound on this arrangement, and it travels in the confirmation the API demands. 14 and 140 are one keystroke apart."
          error={
            draft.confirm.trim() !== "" && daysReady && !confirmed
              ? "These two do not match. Read the number off the agreement rather than pasting one into the other."
              : null
          }
        >
          <input
            id="trial-days-confirm"
            value={draft.confirm}
            disabled={!write.allowed}
            onChange={(event) => set("confirm", event.target.value)}
            inputMode="numeric"
            autoComplete="off"
            aria-describedby={describedBy(
              "trial-days-confirm",
              draft.confirm.trim() !== "" && daysReady && !confirmed,
            )}
            className={FIELD}
          />
        </Field>
      </div>

      <Field
        label="Free test-call minutes"
        id="trial-minutes"
        hint={`Between ${MIN_FREE_MINUTES} and ${MAX_FREE_MINUTES}. The trial ends when these are used or on its last day, whichever comes first, and at once when the client adds credit.`}
        error={minutesProblem}
      >
        <input
          id="trial-minutes"
          value={draft.minutes}
          disabled={!write.allowed}
          onChange={(event) => set("minutes", event.target.value)}
          inputMode="numeric"
          autoComplete="off"
          aria-describedby={describedBy("trial-minutes", minutesProblem !== null)}
          aria-invalid={minutesProblem !== null}
          className={FIELD}
        />
      </Field>

      <Field
        label="Why this client is being carried (required)"
        id="trial-reason"
        hint="Stored on the audit record in your words. “Who agreed to carry this account for a month, and why” is the question this answers months later."
        error={
          draft.reason.trim() !== "" && !reasonReady ? "Say why in at least a few words." : null
        }
      >
        <input
          id="trial-reason"
          value={draft.reason}
          disabled={!write.allowed}
          onChange={(event) => set("reason", event.target.value)}
          maxLength={500}
          aria-describedby={describedBy("trial-reason", draft.reason.trim() !== "" && !reasonReady)}
          aria-invalid={draft.reason.trim() !== "" && !reasonReady}
          className={FIELD}
        />
      </Field>

      <Field
        label="If they do not buy, erase their data after (days)"
        id="trial-grace"
        hint={`Counted from the day the trial ends. Frozen onto this trial when you press the button, so a change to the platform default of ${DEFAULT_ERASURE_GRACE_DAYS} days later cannot move the date for a client already inside their window. A client who CONVERTS keeps everything, for good.`}
        error={graceProblem}
      >
        <input
          id="trial-grace"
          value={draft.grace}
          disabled={!write.allowed}
          onChange={(event) => set("grace", event.target.value)}
          inputMode="numeric"
          autoComplete="off"
          aria-describedby={describedBy("trial-grace", graceProblem !== null)}
          aria-invalid={graceProblem !== null}
          className={FIELD}
        />
      </Field>

      {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON — the act, for how long, what it does NOT
          suspend, then that it is recorded. An operator who reads only the first line has
          read the part that matters. */}
      <div className="flex gap-3 border-l-2 border-danger py-1 pl-4 text-body">
        <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
        <div className="min-w-0">
          <p className="font-semibold text-ink">
            {days === null
              ? `This puts ${clientName} on a trial — their calling is on us for the days you enter`
              : `This carries ${clientName} for ${formatCountOf(days, "day")}, starting the moment you press it`}
          </p>
          <p className="mt-1 text-ink-muted">
            A client that has not paid builds agents and places outbound test calls from the
            shared trial number, nothing else: no inbound, campaigns, numbers,{" "}
            <Term id="kyc" audience="operator" /> or live calling until their first top-up,
            which also ends the trial. The trial ends on its last day or when the free
            minutes are used, whichever comes first. Every minute is still metered at what
            it costs US; the days are typed twice because they and the minutes are the only
            bounds. What it has cost appears above while it runs.
          </p>
          <p className="mt-1 text-ink-muted">
            <span className="font-semibold">A trial is a billing state, not a licence.</span>{" "}
            The no-cold-calls pledge, the signed agreements, this client&apos;s own spend
            cap, calling hours, do-not-call, consent and the AI disclosure still apply to
            every test call. A client that has already paid keeps everything it had, and a
            trial only puts its calls on us.
          </p>
          <p className="mt-1 text-meta text-ink-muted">
            Recorded in the audit log against your admin account with the reason you type
            above, in the same transaction as the trial. Their agents are told straight
            away, so a client whose line stopped for an empty wallet starts answering again
            without anyone republishing anything.
          </p>
        </div>
      </div>

      {start.error != null && (
        <WriteFailure error={start.error} actionLabel="Start this trial" />
      )}
      {start.data && (
        <NoticeBox
          tone="ok"
          icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
          title={`On us for ${formatCountOf(start.data.days, "day")} — until ${formatIST(start.data.ends_at)}`}
        >
          <p className="mt-1">
            Nothing was credited to their wallet and no ledger entry was written: a trial is
            not money, it is a period we agreed to fund.
          </p>
        </NoticeBox>
      )}

      <button type="submit" title={write.reason ?? undefined} disabled={!ready} className={PRIMARY_BUTTON}>
        {start.isPending
          ? "Starting…"
          : days === null
            ? "Start a trial"
            : `Carry ${clientName} for ${formatCountOf(days, "day")}`}
      </button>

      <RestrictionNote reason={write.reason} />

      {write.allowed && (
        <p className="text-meta text-ink-muted">
          {!daysReady
            ? "Enter how many days this client was promised."
            : !confirmed
              ? "Type the number of days a second time to confirm. The two have to match exactly."
              : !reasonReady
                ? "Say why. It is stored on the audit record."
                : !graceReady
                  ? "Enter how long to keep their data if they do not buy."
                  : !minutesReady
                    ? "Enter the free test-call minutes this client was promised."
                    : "Ready. Their test calls are on us from the moment you press this."}
        </p>
      )}
    </form>
  );
}
