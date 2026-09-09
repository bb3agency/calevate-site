"use client";

import { useState } from "react";
import { CheckCircle2, Download, FileDown } from "lucide-react";

import {
  Card,
  FIELD,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  formatCount,
  formatIST,
  istDateStamp,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { downloadJson, useSubjectExport } from "@/lib/api/dataRights";
import { type Session } from "@/lib/api/client";

import { useSubjectExportAccess } from "./access";
import { Fact, Field } from "./fields";

/**
 * Subject access (DPDP §11) — the file a client hands to the person who asked.
 *
 * ## What this refuses to do
 *
 * - **It does not render the document.** The export is that person's whole record — every
 *   call, the redacted transcripts, the lead row and the consent history. Painting it into
 *   a console that is screen-shared on support calls and left open on a reception desk
 *   adds a copy nobody asked for, and the document already travels by a channel the client
 *   chooses. So this produces the file and says so, and the file is the only place the
 *   contents exist.
 * - **It states the document's COUNTS and nothing else about it.** Counts are the part a
 *   client needs before handing the file over ("does this look like the right person?")
 *   and the part that is not itself personal data.
 * - **It never echoes the number back.** It appears in the input the user typed it into
 *   and in the POST body, and nowhere else — not in a URL, not in a heading, not in a
 *   filename (hard rule 6).
 */
export function SubjectExport({ session }: { session: Session }) {
  const access = useSubjectExportAccess(session);
  const exportDocument = useSubjectExport(session);
  const [phone, setPhone] = useState("");
  const valid = useFormValidation();

  return (
    <Card title="What we hold about a person">
      <p className="text-sm text-ink-muted">
        Builds one file containing everything this account holds against a phone number:
        their calls, the redacted transcripts, their record in your CRM and their consent
        history. Hand that file to the person who asked for it.
      </p>

      <div className="mt-3">
        <RestrictionNote reason={access.reason} />
      </div>

      <form
        className="mt-3 space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          exportDocument.mutate(phone.trim());
        })}
      >
        <Field
          id="subject-export-phone"
          label="Their phone number"
          hint="Ten digits, or the full number starting with +. We send it privately — it never appears in the web address at the top of your browser, and never in your history."
        >
          <input
            {...valid.field(
              "phone",
              "Enter their phone number.",
              "subject-export-phone-hint",
            )}
            required
            id="subject-export-phone"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value);
              // A file prepared for the previous number, sitting beside a changed one, is
              // how the wrong person's record gets handed over.
              exportDocument.reset();
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

        <button
          type="submit"
          title={access.reason ?? undefined}
          /* `ready` (eight digits) is not repeated here: the field answers it in a
             sentence, and a dead button said nothing. */
          disabled={!access.allowed || exportDocument.isPending}
          className={PRIMARY_BUTTON_SM}
        >
          <FileDown aria-hidden className="h-4 w-4" />
          {exportDocument.isPending ? "Building…" : "Build the export"}
        </button>
      </form>

      {exportDocument.error != null && (
        <div className="mt-3">
          <ProblemNotice error={exportDocument.error} />
        </div>
      )}

      {/* The document is held here and NOT rendered — see the module note. `data` is the
          narrowed success value, so nothing on this branch is a stand-in for an answer we
          do not have. */}
      {exportDocument.data !== undefined && exportDocument.error == null && (
        <div className="mt-4">
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="The export is ready"
          >
            <p className="mt-1">
              Save it and send it to the person who asked. We do not show it on screen:
              it is their whole record with us, and the fewer copies of it exist, the
              better. If we hold nothing about that number the file says exactly that,
              which is a complete answer to their request.
            </p>
            {/* Counts, and deliberately only counts: they let a client check the file
                is about the person they meant before handing it over, and they are the
                one part of the document that is not itself that person's data. */}
            <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
              <Fact label="Calls" value={formatCount(exportDocument.data.counts.calls)} />
              <Fact
                label="Transcript turns"
                value={formatCount(exportDocument.data.counts.transcript_turns)}
              />
              <Fact
                label="CRM records"
                value={formatCount(exportDocument.data.counts.leads)}
              />
              <Fact
                label="Consent records"
                value={formatCount(exportDocument.data.counts.consent_records)}
              />
            </dl>
            {/* An erasure empties every column that carries the number, so a subject who
                has already been erased gets a file of zeros — which reads as "we never
                had anything" and is not what happened. This says which of the two it is,
                and whether any audio is still lawfully held. It is a fact about our
                processing, not the person's data, so it belongs beside the counts. */}
            {exportDocument.data.erasure !== null && (
              <p className="mt-3 text-xs text-ink-muted">
                An erasure for this number completed on{" "}
                {formatIST(exportDocument.data.erasure.completed_at)}, which is why the
                counts above are what they are.
                {exportDocument.data.erasure.recordings_pending_destruction > 0 &&
                  exportDocument.data.erasure.recordings_destroyed_by !== null &&
                  ` ${formatCount(exportDocument.data.erasure.recordings_pending_destruction)} recording(s) are still held under the mandatory retention period and are destroyed by ${formatIST(exportDocument.data.erasure.recordings_destroyed_by)}.`}
              </p>
            )}
            <button
              type="button"
              onClick={() =>
                downloadJson(
                  exportDocument.data,
                  // Named for the day, never for the number (hard rule 6): filenames end
                  // up in mail clients, chat threads and shared folders. The IST day —
                  // `toISOString()` is still on yesterday until 05:30 IST, and this is a
                  // statutory record whose date somebody may later have to place.
                  `subject-access-export-${istDateStamp()}.json`,
                )
              }
              className={`${SECONDARY_BUTTON_SM} mt-3`}
            >
              <Download aria-hidden className="h-4 w-4" />
              Save the file
            </button>
          </NoticeBox>
        </div>
      )}
    </Card>
  );
}
