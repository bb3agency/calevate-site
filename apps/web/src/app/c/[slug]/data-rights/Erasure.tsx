"use client";

import { useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import {
  Card,
  DANGER_BUTTON,
  FIELD,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  formatCount,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { useFileErasure, useSubjectExport } from "@/lib/api/dataRights";
import { useActAccess } from "@/lib/api/hooks";
import { type Session } from "@/lib/api/client";

import { useSubjectExportAccess } from "./access";
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
export function Erasure({ session }: { session: Session }) {
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
  // The TARGET check (ux-audit DR-1 🔒): the typed ERASE confirms intent, but a
  // transposed digit in a ten-digit mobile passes every check on this form and erases a
  // different real customer, irreversibly. This reuses the subject-export read — the
  // same POST the card above makes — and renders ONLY its counts, so the owner sees
  // whose record is about to be destroyed before arming it. Gated on the export
  // permission; a session without it keeps the typed confirmation alone.
  const previewAccess = useSubjectExportAccess(session);
  const preview = useSubjectExport(session);

  const [phone, setPhone] = useState("");
  const valid = useFormValidation();
  const [confirmation, setConfirmation] = useState("");

  const armed = phone.trim().length >= 8 && confirmation === ERASE_CONFIRMATION;

  return (
    <Card title="Erase a person's data">
      <NoticeBox
        tone="stop"
        icon={<AlertTriangle aria-hidden className="h-5 w-5" />}
        title="This cannot be undone"
      >
        <p className="mt-1">
          Every call, transcript, extracted field and CRM record we hold for this number
          is erased, and the calls themselves survive only as rows with the personal
          details stripped out. Nothing restores them. If this person is still a
          customer, you are erasing your own record of them too.
        </p>
        <p className="mt-1">
          Some things are kept, and the certificate names each one with the rule that
          required it — the consent ledger that proves the calls were lawful, the
          billing ledger, any do-not-call entry, and the call audio, which Indian
          telecom rules require to be retained.
        </p>
      </NoticeBox>

      <div className="mt-3">
        <RestrictionNote reason={access.reason} />
      </div>

      <form
        className="mt-3 space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          file.mutate(phone.trim(), {
            onSuccess: () => {
              // The filed request arrives from the register, which the mutation
              // invalidates — nothing is remembered here.
              setPhone("");
              setConfirmation("");
              preview.reset();
            },
          });
        })}
      >
        {/* Not "Their phone number", which the export field above already carries: two
            controls with one accessible name is a screen reader announcing the erasure
            field as the export field, on the one screen where confusing the two is
            unrecoverable. */}
        <Field
          id="erasure-phone"
          label="Number to erase permanently"
          hint="Check it twice. We erase whoever this number belongs to, and there is no undo."
        >
          <input
            {...valid.field("phone", "Enter the number to erase.", "erasure-phone-hint")}
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
              <button
                type="button"
                onClick={() => preview.mutate(phone.trim())}
                disabled={preview.isPending}
                className={SECONDARY_BUTTON_SM}
              >
                {preview.isPending ? "Checking…" : "Check whose record this is first"}
              </button>
            )}
            {preview.error != null && <ProblemNotice error={preview.error} />}
            {preview.data !== undefined && preview.error == null && (
              <p className="text-sm text-ink" aria-live="polite">
                {preview.data.counts.calls +
                  preview.data.counts.leads +
                  preview.data.counts.transcript_turns +
                  preview.data.counts.consent_records ===
                0 ? (
                  <>
                    We hold <span className="font-semibold">nothing</span> for this
                    number. If you expected a record, check the digits — this is the
                    strongest sign they are wrong.
                  </>
                ) : (
                  <>
                    We hold{" "}
                    <span className="font-semibold tabular-nums">
                      {formatCount(preview.data.counts.calls)}
                    </span>{" "}
                    call(s),{" "}
                    <span className="font-semibold tabular-nums">
                      {formatCount(preview.data.counts.transcript_turns)}
                    </span>{" "}
                    transcript turn(s),{" "}
                    <span className="font-semibold tabular-nums">
                      {formatCount(preview.data.counts.leads)}
                    </span>{" "}
                    CRM record(s) and{" "}
                    <span className="font-semibold tabular-nums">
                      {formatCount(preview.data.counts.consent_records)}
                    </span>{" "}
                    consent record(s) for this number. All of it will be erased.
                  </>
                )}
              </p>
            )}
          </div>
        )}

        <Field id="erasure-confirmation" label={`Type ${ERASE_CONFIRMATION} to confirm`}>
          <input
            id="erasure-confirmation"
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            autoComplete="off"
            disabled={!access.allowed}
            className={`${FIELD} font-mono`}
          />
        </Field>

        <button
          type="submit"
          title={access.reason ?? undefined}
          disabled={!access.allowed || !armed || file.isPending}
          className={DANGER_BUTTON}
        >
          <Trash2 aria-hidden className="h-4 w-4" />
          {file.isPending ? "Filing…" : "Erase this person's data"}
        </button>
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
        <p className="mt-3 text-sm text-ink-muted">
          An erasure for this person was already running, so nothing new was filed. Its
          progress is below.
        </p>
      )}
    </Card>
  );
}
