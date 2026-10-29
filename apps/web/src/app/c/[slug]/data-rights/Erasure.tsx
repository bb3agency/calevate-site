"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD, NoticeBox, ProblemNotice, RestrictionNote } from "@/components/ui";
import { TypedConfirmation } from "@/components/typedConfirmation";
import { useFormValidation } from "@/components/formValidation";
import { useFileErasure, useSubjectExport } from "@/lib/api/dataRights";
import { useActAccess } from "@/lib/api/hooks";
import { type Session } from "@/lib/api/client";

import { useSubjectExportAccess } from "./access";
import { CountChips } from "./_ui/CountChips";
import { WhyTip } from "../agreements/_ui/WhyTip";
import { DATA_RIGHTS_COPY as COPY, DATA_RIGHTS_KEPT as KEPT } from "./copy";
import { Field } from "./fields";

/** Typed to arm the erasure. Uppercase and unambiguous — nobody types this by accident. */
const ERASE_CONFIRMATION = "ERASE";

/**
 * Erasure (DPDP §12) — irreversible, so the control is shaped like one.
 *
 * A typed confirmation plus the consequences stated ABOVE the button, which is the ops
 * console's big-red-switch idiom (`admin/ops/page.tsx`) and the right shape for the same
 * reason: the decision has to be made before the click, not discovered after it.
 */
export function Erasure({
  session,
  onFiled,
}: {
  session: Session;
  /** Called once a NEW request is filed, with its id; the register shows it from there. */
  onFiled?: (requestId: string) => void;
}) {
  // `org:manage` AND the named act, because since D-587 the permission is no longer the
  // whole answer: `org:manage` is writable in a view-as session, and filing an erasure is
  // refused inside it by name (`compliance/deletion_routes.py:294`,
  // `rbac.VIEW_AS_WITHHELD_ACTS["compliance.erasure_request"]`) — it destroys this
  // account's records of a person irreversibly, which is the account's decision about
  // their own customer. `useWriteAccess` alone would have armed the button for an
  // operator and let the typed ERASE end in a 403.
  const access = useActAccess(
    session,
    "org:manage",
    "compliance.erasure_request",
    "file an erasure request",
  );
  const file = useFileErasure(session);
  const fileFeedback = useActionFeedback(file, { errorDisplay: "inline" });
  // The TARGET check (ux-audit DR-1 🔒): the typed ERASE confirms intent, but a
  // transposed digit in a ten-digit mobile passes every check on this form and erases a
  // different real customer, irreversibly. This reuses the subject-export read — the
  // same POST the card above makes — and renders ONLY its counts, so the owner sees
  // whose record is about to be destroyed before arming it. Gated on the export
  // permission; a session without it keeps the typed confirmation alone.
  const previewAccess = useSubjectExportAccess(session);
  const preview = useSubjectExport(session);
  const previewFeedback = useActionFeedback(preview, { errorDisplay: "inline" });

  const [phone, setPhone] = useState("");
  const valid = useFormValidation();
  const [confirmation, setConfirmation] = useState("");

  const armed = phone.trim().length >= 8 && confirmation === ERASE_CONFIRMATION;

  return (
    <div>
      {/* The consequences stay ABOVE the control and in the open (UX-DOCTRINE §3: high
          consequence never discloses), one claim per line so they scan. Only the itemised
          list of what survives is behind the tap; the line that says things survive is not. */}
      <NoticeBox tone="stop" title={COPY.eraseTitle}>
        <ul className="mt-1 list-disc space-y-1 pl-4">
          <li>{KEPT.erased}</li>
          <li className="font-medium text-ink">{KEPT.noRestore}</li>
          <li>{KEPT.ownRecord}</li>
          <li>
            {KEPT.kept}{" "}
            <WhyTip about="what an erasure keeps" label={COPY.whatIsKept} className="-my-2 align-middle">
              <p>{KEPT.keptList}</p>
            </WhyTip>
          </li>
        </ul>
      </NoticeBox>

      <div className="mt-3">
        <RestrictionNote reason={access.reason} />
      </div>

      <form
        className="mt-3 space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          file.mutate(phone.trim(), {
            onSuccess: (result) => {
              // The filed request arrives from the register, which the mutation
              // invalidates — nothing is remembered here.
              setPhone("");
              setConfirmation("");
              preview.reset();
              // An erasure that was already running files nothing new; the form stays
              // open to say so rather than closing as if it had.
              if (!result.already_open) onFiled?.(result.request_id);
            },
          });
        })}
      >
        {/* Not "Their phone number", which is the export field's name: the two forms must
            never be confusable, by eye or by screen reader, when one of them is erasure. */}
        <Field
          id="erasure-phone"
          label={COPY.eraseField}
          hint={COPY.eraseHint}
        >
          <input
            {...valid.field("phone", COPY.eraseFieldMissing, "erasure-phone-hint")}
            required
            id="erasure-phone"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value);
              // A count fetched for the previous number, standing beside a changed
              // one, is the wrong person's record vouching for this one.
              preview.reset();
            }}
            minLength={8}
            maxLength={20}
            inputMode="tel"
            autoComplete="off"
            disabled={!access.allowed}
            className={`${FIELD} font-mono`}
          />
          {valid.error("phone")}
        </Field>

        {previewAccess.allowed && phone.trim().length >= 8 && (
          <div>
            {preview.data === undefined && (
              <ActionButton
                variant="secondary-sm"
                status={previewFeedback.status}
                onClick={() => previewFeedback.run(phone.trim())}
                pendingLabel={COPY.checking}
                successLabel={COPY.checked}
              >
                {COPY.checkWhose}
              </ActionButton>
            )}
            {preview.error != null && <ProblemNotice error={preview.error} />}
            {preview.data !== undefined && preview.error == null && (
              <div className="text-sm text-ink" aria-live="polite">
                {preview.data.counts.calls +
                  preview.data.counts.leads +
                  preview.data.counts.transcript_turns +
                  preview.data.counts.consent_records ===
                0 ? (
                  <>
                    <p className="font-semibold">{COPY.holdNothing}</p>
                    <p className="text-ink-muted">{COPY.holdNothingHint}</p>
                  </>
                ) : (
                  <>
                    {/* The four counts as figures, so the owner can see at a glance whose
                        record this is before arming the erasure. */}
                    <CountChips
                      counts={[
                        [COPY.calls, preview.data.counts.calls],
                        [COPY.turns, preview.data.counts.transcript_turns],
                        [COPY.leads, preview.data.counts.leads],
                        [COPY.consents, preview.data.counts.consent_records],
                      ]}
                    />
                    <p className="mt-2 font-semibold">{COPY.allErased}</p>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        <TypedConfirmation
          id="erasure-confirmation"
          match="exact"
          phrase={ERASE_CONFIRMATION}
          value={confirmation}
          onChange={setConfirmation}
          disabled={!access.allowed}
        />

        <ActionButton
          type="submit"
          variant="danger"
          status={fileFeedback.status}
          title={access.reason ?? undefined}
          disabled={!access.allowed || !armed}
          pendingLabel={COPY.filing}
          successLabel={COPY.filed}
          className="max-sm:w-full max-sm:justify-center"
        >
          <Trash2 aria-hidden className="h-4 w-4" />
          {COPY.eraseSubmit}
        </ActionButton>
      </form>

      {file.error != null && (
        <div className="mt-3">
          <ProblemNotice error={file.error} />
        </div>
      )}

      {/* `already_open` is on the body precisely so this sentence does not have to be
          inferred from a status line: a second ask for someone already being erased is
          not an error, and telling the client it was would send them chasing a fault
          that does not exist. */}
      {file.data?.already_open === true && (
        <p className="mt-3 text-sm text-ink-muted">{COPY.alreadyOpen}</p>
      )}
    </div>
  );
}
