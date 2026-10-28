"use client";

import { useId, useState } from "react";
import Link from "next/link";

import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { ChoiceCards } from "@/components/console/choiceCards";
import { FIELD, MonoValue, ProblemNotice, Skeleton, formatIST, formatPhone } from "@/components/ui";
import { type Session } from "@/lib/api/client";
import {
  RESTORE_NOTE_MAX,
  RESTORE_NOTE_MIN,
  useDncEvidence,
  useRestoreDncEntry,
  type DncEntry,
  type DncEvidenceRecord,
  type DncRestoreGround,
} from "@/lib/api/dnc";
import { useClientRealm } from "@/lib/api/session";

import { DNC_COPY as COPY, DNC_KEPT as KEPT, charsLeft } from "./copy";

const GROUNDS: { value: DncRestoreGround; label: string; hint: string }[] = [
  {
    value: "never_asked",
    label: "They never asked to stop",
    hint: "Recorded by mistake, e.g. they only said “not interested”.",
  },
  {
    value: "asked_to_be_called",
    label: "They have since asked to be called",
    hint: "They got in touch and asked for a call.",
  },
];

/** Who noticed the request, in words. The agent heard it, or the call's transcript showed it. */
function heardBy(record: DncEvidenceRecord): string {
  if (record.detected_by === "post_call_transcript") return "Found in the call's transcript";
  if (record.detected_by === "in_call_tool" || record.detected_by === "engine_platform") {
    return "The agent recorded it on the call";
  }
  return "Recorded on a call";
}

/**
 * Restoring a person's opt-out: the evidence first, then a stated reason.
 *
 * An opt-out a person made is theirs, and this account cannot simply delete it. One that
 * was recorded by MISTAKE is not their request at all, and one they have since withdrawn
 * is no longer their wish, so either may be restored — with the reason chosen here and
 * kept in the account's audit record under the name of whoever chose it. The dialog shows
 * what was recorded (when, on which call, the words if any) before it asks, because the
 * person restoring is attesting to something and should see what they are attesting about.
 *
 * The newest record's id goes back with the request: if the person opted out again while
 * this was open, the server refuses instead of undoing a request nobody here has seen.
 */
export function RestoreDialog({
  session,
  entry,
  onClose,
}: {
  session: Session;
  entry: DncEntry;
  onClose: () => void;
}) {
  const { href } = useClientRealm();
  const evidence = useDncEvidence(session, entry.id);
  const restore = useRestoreDncEntry(session);
  // A refusal stays inside the dialog; the toast says it happened once the dialog closes.
  const restoreFeedback = useActionFeedback(restore, {
    errorDisplay: "inline",
    successToast: COPY.restoredToast,
    successDescription: COPY.restoredToastBody,
  });
  const [ground, setGround] = useState<DncRestoreGround | null>(null);
  const [note, setNote] = useState("");
  const noteId = useId();
  const groupId = useId();

  const records = evidence.data?.records;
  const noteShort = ground === "asked_to_be_called" && note.trim().length < RESTORE_NOTE_MIN;
  const ready = records !== undefined && ground !== null && !noteShort;

  return (
    <ConfirmDialog
      title={COPY.restoreTitle}
      confirmLabel={COPY.restoreConfirm}
      pendingLabel={COPY.restoring}
      cancelLabel={COPY.restoreKeep}
      status={restoreFeedback.status}
      confirmDisabled={!ready}
      error={restore.error}
      onCancel={() => {
        restore.reset();
        onClose();
      }}
      onConfirm={() => {
        if (!ready) return;
        restore.mutate(
          {
            entryId: entry.id,
            ground,
            note: ground === "asked_to_be_called" ? note.trim() : null,
            latestEvidenceId: records[0]?.id ?? null,
          },
          { onSuccess: onClose },
        );
      }}
    >
      <p>
        <MonoValue className="tabular-nums text-ink">{formatPhone(entry.phone_e164)}</MonoValue>{" "}
        {KEPT.onYourList}
      </p>

      <section aria-label={COPY.recorded} className="space-y-2">
        <h3 className="text-meta font-semibold text-ink">{COPY.recorded}</h3>
        {evidence.isLoading ? (
          <Skeleton rows={2} />
        ) : evidence.error != null ? (
          <ProblemNotice error={evidence.error} onRetry={() => evidence.refetch()} />
        ) : records && records.length ? (
          <ul className="space-y-2">
            {records.map((record) => (
              <li key={record.id} className="rounded-card border border-line bg-surface p-3 text-meta">
                <p className="text-ink">
                  {heardBy(record)} · {formatIST(record.recorded_at)}
                </p>
                {record.matched_redacted ? (
                  <p className="mt-1 text-ink-muted">
                    They said: <q className="italic">{record.matched_redacted}</q>
                  </p>
                ) : (
                  <p className="mt-1 text-ink-faint">{COPY.noWords}</p>
                )}
                {record.call_id && (
                  <Link
                    href={href(`/c/${session.orgSlug}/calls/${record.call_id}`)}
                    className="mt-1 inline-block font-medium text-brand underline-offset-2 hover:underline"
                  >
                    {COPY.openCall}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-meta text-ink-faint">{COPY.noCall}</p>
        )}
      </section>

      <ChoiceCards
        legend={COPY.restoreWhyHeading}
        description={COPY.restoreWhyNote}
        name={`${groupId}-ground`}
        value={ground}
        options={GROUNDS}
        onChange={setGround}
      />

      {ground === "asked_to_be_called" && (
        <div>
          <label htmlFor={noteId} className="text-meta font-medium text-ink">
            {COPY.restoreNoteLabel}
          </label>
          <textarea
            id={noteId}
            value={note}
            rows={2}
            maxLength={RESTORE_NOTE_MAX}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Rang the office on 3 October asking for a call back"
            aria-describedby={`${noteId}-hint`}
            className={`${FIELD} mt-1 resize-none`}
          />
          <p id={`${noteId}-hint`} className="mt-1 text-meta text-ink-faint">
            {charsLeft(RESTORE_NOTE_MAX - note.length)}
          </p>
        </div>
      )}

      <p>
        <strong className="font-semibold text-ink">{KEPT.breaksLaw}</strong>{" "}
        {COPY.restoreEffect}
      </p>
    </ConfirmDialog>
  );
}
