"use client";

import { useState } from "react";
import { Download, FileDown } from "lucide-react";

import { ActionButton, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import {
  FIELD,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  formatCountOf,
  formatIST,
  istDateStamp,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { downloadJson, useSubjectExport } from "@/lib/api/dataRights";
import { type Session } from "@/lib/api/client";

import { useSubjectExportAccess } from "./access";
import { WhyTip } from "../agreements/_ui/WhyTip";
import { CountChips } from "./_ui/CountChips";
import { DATA_RIGHTS_COPY as COPY, audioHeld, erasedOn } from "./copy";
import { Field } from "./fields";

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
  const exportFeedback = useActionFeedback(exportDocument, { errorDisplay: "inline" });
  const save = useAsyncAction(
    () =>
      downloadJson(
        exportDocument.data,
        // Named for the day, never for the number (hard rule 6): filenames end up in mail
        // clients, chat threads and shared folders. The IST day — `toISOString()` is still
        // on yesterday until 05:30 IST, and this is a statutory record whose date somebody
        // may later have to place.
        `subject-access-export-${istDateStamp()}.json`,
      ),
    { errorTitle: COPY.saveFailed },
  );
  const [phone, setPhone] = useState("");
  const valid = useFormValidation();

  return (
    <div>
      <p className="flex flex-wrap items-center gap-x-1 text-sm text-ink-muted">
        {COPY.exportIntro}
        <WhyTip about="the export file" label="What is in it?">
          <p>{COPY.exportWhy}</p>
        </WhyTip>
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
          label={COPY.exportField}
          hint={COPY.exportHint}
        >
          <input
            {...valid.field("phone", COPY.exportFieldMissing, "subject-export-phone-hint")}
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

        {/* `ready` (eight digits) is not repeated in `disabled`: the field answers it in a
            sentence, and a dead button said nothing. */}
        <ActionButton
          type="submit"
          status={exportFeedback.status}
          title={access.reason ?? undefined}
          disabled={!access.allowed}
          pendingLabel={COPY.building}
          successLabel={COPY.built}
          className="max-sm:w-full max-sm:justify-center"
        >
          <FileDown aria-hidden className="h-4 w-4" />
          {COPY.build}
        </ActionButton>
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
          <NoticeBox tone="ok" title={COPY.ready}>
            <p className="flex flex-wrap items-center gap-x-1">
              {COPY.readyBody}
              <WhyTip about="an empty export" label="Why?">
                <p>{COPY.readyWhy}</p>
              </WhyTip>
            </p>
            {/* Counts, and deliberately only counts: they let a client check the file
                is about the person they meant before handing it over, and they are the
                one part of the document that is not itself that person's data. */}
            <div className="mt-3">
              <CountChips
                counts={[
                  [COPY.calls, exportDocument.data.counts.calls],
                  [COPY.turns, exportDocument.data.counts.transcript_turns],
                  [COPY.leads, exportDocument.data.counts.leads],
                  [COPY.consents, exportDocument.data.counts.consent_records],
                ]}
              />
            </div>
            {/* An erasure empties every column that carries the number, so a subject who
                has already been erased gets a file of zeros — which reads as "we never
                had anything" and is not what happened. This says which of the two it is,
                and whether any audio is still lawfully held. It is a fact about our
                processing, not the person's data, so it belongs beside the counts. */}
            {exportDocument.data.erasure !== null && (
              <div className="mt-3 space-y-0.5 text-xs text-ink-muted">
                <p>{erasedOn(formatIST(exportDocument.data.erasure.completed_at))}</p>
                {exportDocument.data.erasure.recordings_pending_destruction > 0 &&
                  exportDocument.data.erasure.recordings_destroyed_by !== null && (
                    <p>
                      {audioHeld(
                        formatCountOf(exportDocument.data.erasure.recordings_pending_destruction, "recording"),
                        formatIST(exportDocument.data.erasure.recordings_destroyed_by),
                      )}
                    </p>
                  )}
              </div>
            )}
            <ActionButton
              variant="secondary-sm"
              status={save.status}
              onClick={() => save.run()}
              successLabel={COPY.saved}
              className="mt-3"
            >
              <Download aria-hidden className="h-4 w-4" />
              {COPY.save}
            </ActionButton>
          </NoticeBox>
        </div>
      )}
    </div>
  );
}
