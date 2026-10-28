"use client";

import { useState } from "react";

import { DatePicker } from "@/components/arc/calendar";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { todayIST } from "@/components/arc/ist-dates";
import { ChoiceCards } from "@/components/console/choiceCards";
import { FieldMessage } from "@/components/formValidation";
import { FIELD_LABEL, ProblemNotice, RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  consentCollectedAt,
  useDeclareConsentProvenance,
  type ConsentSource,
} from "@/lib/api/campaigns";

import { CONSENT_SOURCES } from "./choices";
import { Why } from "./_ui/Why";

/** The answer form's element id, so the launch checklist's "Answer" button can jump to it. */
export function listSourceId(campaignId: string): string {
  return `list-source-${campaignId}`;
}

/**
 * WHERE THIS LIST CAME FROM — the consent-provenance question, and the two places that
 * ask it.
 *
 * Every sentence here is a compliance artefact (SEC-COMP §3): the client is stating on the
 * record where a list came from, and that statement is what a complaint would later be
 * answered with. "This goes on the record" stays visible; only the reason it matters sits
 * behind "Why?".
 *
 * The fields are shared rather than written twice because the two callers (the create
 * flow, and a blocked draft) must ask IDENTICALLY: two copies would drift, and the drift
 * would show up as two different records of the same declaration.
 */
export function ConsentProvenanceFields({
  idPrefix,
  source,
  collectedAt,
  onSource,
  onCollectedAt,
  sourceError,
  dateError,
}: {
  idPrefix: string;
  source: ConsentSource | "";
  collectedAt: string;
  onSource: (value: ConsentSource) => void;
  onCollectedAt: (value: string) => void;
  sourceError?: string | null;
  dateError?: string | null;
}) {
  return (
    <div className="space-y-4">
      <div>
        <ChoiceCards
          legend="Where did this list come from?"
          legendClassName={FIELD_LABEL}
          description={
            <>
              This goes on the record. Pick the true one.{" "}
              <Why>It is how we show, later, that these people agreed to hear from you.</Why>
            </>
          }
          name={`${idPrefix}-consent-source`}
          value={source}
          options={CONSENT_SOURCES}
          onChange={onSource}
          columns="sm:grid-cols-2"
        />
        {sourceError ? <FieldMessage id={`${idPrefix}-source-error`}>{sourceError}</FieldMessage> : null}
      </div>

      {/* Days after today are not offered: an agreement cannot have been given tomorrow. */}
      <DatePicker
        label="When did they agree?"
        hint="Date on the form, bill or enquiry. Use the newest one."
        value={collectedAt || null}
        onChange={(day) => onCollectedAt(day ?? "")}
        max={todayIST()}
        error={dateError}
      />
    </div>
  );
}

/**
 * The answer path for a draft that is already blocked: the form is rendered where the
 * blocker is read, so a client never has to rebuild a five-thousand-row list on the create
 * page just to record a date.
 *
 * Draft-only, matching the endpoint: this card only renders inside the `status === "draft"`
 * branch, and the server refuses anything else by name.
 */
export function ConsentProvenanceAnswer({
  campaignId,
  correcting,
}: {
  campaignId: string;
  /** True when a refused answer is already on file — the ask is "correct it", not "answer it". */
  correcting: boolean;
}) {
  const session = useClientSession();
  const write = useWriteAccess(
    session,
    "leads:dispatch",
    "record where a list came from",
  );
  const declare = useDeclareConsentProvenance(session, campaignId);
  // No success toast: the launch check is refetched on success and the blocker above
  // either disappears or is replaced by the refusal. That IS the answer, and it is more
  // honest than "Saved" over a campaign still unable to launch; the button's tick says the
  // record was taken.
  const feedback = useActionFeedback(declare, { errorDisplay: "inline" });
  const [source, setSource] = useState<ConsentSource | "">("");
  const [collectedAt, setCollectedAt] = useState("");
  const [tried, setTried] = useState(false);

  const iso = consentCollectedAt(collectedAt);

  return (
    <form
      id={listSourceId(campaignId)}
      className="scroll-mt-24 space-y-4 border-l-2 border-line pl-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setTried(true);
        if (!source || !iso) return;
        feedback.run({ source, collected_at: iso });
      }}
    >
      <p className="text-sm font-semibold text-ink">
        {correcting
          ? "Correct where this list came from"
          : "Record where this list came from"}
      </p>

      <ConsentProvenanceFields
        idPrefix={`answer-${campaignId}`}
        source={source}
        collectedAt={collectedAt}
        onSource={setSource}
        onCollectedAt={setCollectedAt}
        sourceError={tried && !source ? "Choose where the list came from." : null}
        dateError={tried && !iso ? "Choose the day they agreed." : null}
      />

      {/* Said before the click rather than discovered as a 403: `leads:dispatch` is a
          MUTATING permission, so an impersonating operator and a `staff` user are both
          refused it server-side. */}
      <RestrictionNote reason={write.reason} />
      {feedback.error != null && <ProblemNotice error={feedback.error} />}

      <ActionButton
        type="submit"
        title={write.allowed ? undefined : (write.reason ?? undefined)}
        disabled={!write.allowed}
        status={feedback.status}
        pendingLabel="Recording"
        successLabel="Recorded"
      >
        Record this
      </ActionButton>
    </form>
  );
}
