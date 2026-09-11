"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";

import {
  FIELD,
  NoticeBox,
  RestrictionNote,
  SECONDARY_BUTTON,
  formatIST,
} from "@/components/ui";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useAdminAccess } from "@/app/admin/access";
import { useEndTrial, type TrialOutcome } from "@/lib/api/trials";

import { Field, describedBy } from "./fields";

/**
 * ENDING a trial — converted (they bought) or stopped (we ended it).
 *
 * Its own file rather than a section of `TrialPanel.tsx`, by subject (UX-DOCTRINE §6):
 * this act and its opposite carry deliberately different ceremony, and splitting them by
 * subject is what keeps that difference legible rather than buried in one long component.
 */

interface EndDraft {
  outcome: TrialOutcome | "";
  reason: string;
}

const NO_END: EndDraft = { outcome: "", reason: "" };

/**
 * End the open trial.
 *
 * NO typed confirmation and no step-up header, because the route asks for neither: this
 * is the direction that STOPS us spending money, it is what an operator does the minute a
 * client converts, and a second factor in front of the safe act while the expensive one
 * is one call away teaches people to click through ceremony. What the panel DOES insist
 * on is naming which ending it is, because the two decide whether this client's leads,
 * calls and transcripts survive.
 */
export function EndTrialForm({
  clientName,
  end,
  write,
}: {
  clientName: string;
  end: ReturnType<typeof useEndTrial>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<EndDraft>(NO_END);
  const set = (key: keyof EndDraft, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }) as EndDraft);
    end.reset();
  };
  const reason = draft.reason.trim();
  const ready = write.allowed && draft.outcome !== "" && reason.length >= 3 && !end.isPending;

  return (
    <form
      className="mt-5 space-y-4 border-t border-line pt-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (draft.outcome === "") return;
        end.mutate({ outcome: draft.outcome, reason }, { onSuccess: () => setDraft(NO_END) });
      }}
    >
      <Field
        label="How it ended"
        id="trial-outcome"
        hint="“Expired” is not on this list: that is the clock's own verdict, and recording a trial we stopped as one that ran its course is a different fact about the same client."
        error={null}
      >
        <select
          id="trial-outcome"
          value={draft.outcome}
          disabled={!write.allowed}
          onChange={(event) => set("outcome", event.target.value)}
          aria-describedby={describedBy("trial-outcome", false)}
          className={FIELD}
        >
          <option value="">Choose how this trial ended…</option>
          <option value="converted">They bought — converted</option>
          <option value="stopped">We ended it — stopped</option>
        </select>
      </Field>

      <Field
        label="Why this trial is ending (required)"
        id="trial-end-reason"
        hint="Stored on the trial row and on the audit record, in your words."
        error={
          draft.reason.trim() !== "" && reason.length < 3
            ? "Say why in at least a few words."
            : null
        }
      >
        <input
          id="trial-end-reason"
          value={draft.reason}
          disabled={!write.allowed}
          onChange={(event) => set("reason", event.target.value)}
          maxLength={500}
          aria-describedby={describedBy(
            "trial-end-reason",
            draft.reason.trim() !== "" && reason.length < 3,
          )}
          className={FIELD}
        />
      </Field>

      <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
        <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
        <div className="min-w-0">
          <p className="font-semibold text-ink">
            This ends {clientName}&apos;s trial now and starts a fresh counting period
          </p>
          <p className="mt-1 text-ink-muted">
            From this instant their own usage figures count from zero, exactly as they do
            on the 1st of a month. Nothing is deleted — every ledger keeps every row; what
            moves is the window their screens count over. If their wallet is empty, their
            outgoing calls stop and their agents stop answering incoming ones from the next
            call onwards, so record the payment above first if there is one.
          </p>
          <p className="mt-1 text-ink-muted">
            <span className="font-semibold">Converted</span> keeps this client&apos;s
            leads, calls and transcripts for good.{" "}
            <span className="font-semibold">Stopped</span> schedules a tenant erasure for
            the end of the grace period agreed when the trial was opened.
          </p>
        </div>
      </div>

      {end.error != null && <WriteFailure error={end.error} actionLabel="End this trial" />}
      {end.data && (
        <NoticeBox
          tone="ok"
          icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
          title={`Trial ended — ${end.data.status}`}
        >
          <p className="mt-1 text-xs">
            {end.data.erase_after
              ? `They did not convert, so their data becomes erasable on ${formatIST(end.data.erase_after)}.`
              : "They bought, so their leads, calls and transcripts are kept."}
          </p>
        </NoticeBox>
      )}

      <button type="submit" title={write.reason ?? undefined} disabled={!ready} className={SECONDARY_BUTTON}>
        {end.isPending ? "Ending…" : "End this trial"}
      </button>

      <RestrictionNote reason={write.reason} />
    </form>
  );
}
