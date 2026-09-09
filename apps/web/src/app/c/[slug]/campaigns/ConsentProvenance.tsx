"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  istDateStamp,
} from "@/components/ui";
import { useFormValidation, type FormValidation } from "@/components/formValidation";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  consentCollectedAt,
  useDeclareConsentProvenance,
  type ConsentSource,
} from "@/lib/api/campaigns";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON, CONSENT_SOURCES } from "./choices";

/**
 * WHERE THIS LIST CAME FROM — the consent-provenance question, and the two places that
 * ask it.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6: extract by SUBJECT). Every sentence here is
 * a compliance artefact (SEC-COMP §3): the client is stating on the record where a list
 * came from, and that statement is what a complaint would later be answered with. It is
 * never disclosed and never shortened.
 */
/**
 * The provenance question itself — one set of fields, two places that ask it.
 *
 * Shared rather than written twice because the two callers must ask IDENTICALLY: a
 * client answering on the create form and a client answering a blocker on a
 * five-thousand-row draft are making the same statement, and it is a statement that
 * gets audited. Two copies would drift, and the drift would show up as two different
 * records of the same declaration.
 */
export function ConsentProvenanceFields({
  idPrefix,
  source,
  collectedAt,
  onSource,
  onCollectedAt,
  validation,
}: {
  idPrefix: string;
  source: ConsentSource | "";
  collectedAt: string;
  onSource: (value: ConsentSource) => void;
  onCollectedAt: (value: string) => void;
  /** The campaign form's validation — this block is part of that form, not its own. */
  validation: FormValidation;
}) {
  return (
    <div className="space-y-4">
      <fieldset>
        <legend className={FIELD_LABEL}>Where did this list come from?</legend>
        <p className="mt-1 text-xs text-ink-faint">
          You&apos;re putting this on the record: it&apos;s how we can show,
          later, that the people on this list agreed to hear from you. Pick the
          one that&apos;s true.
        </p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {CONSENT_SOURCES.map((option) => (
            <label
              key={option.value}
              className={`${CHOICE_CARD} ${source === option.value ? CHOICE_ON : CHOICE_OFF}`}
            >
              <input
                type="radio"
                name={`${idPrefix}-consent-source`}
                className="sr-only"
                checked={source === option.value}
                onChange={() => onSource(option.value)}
              />
              {source === option.value && (
                <CheckCircle2
                  aria-hidden
                  className="absolute right-2 top-2 h-4 w-4 text-brand"
                />
              )}
              <span className="block pr-6 text-sm font-semibold text-ink">
                {option.label}
              </span>
              <span className="mt-0.5 block text-xs text-ink-faint">
                {option.hint}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="max-w-xs">
        <label className="block">
          <span className={FIELD_LABEL}>When did they agree?</span>
          <input
            {...validation.field("consentDate", "Choose the day they agreed.")}
            type="date"
            value={collectedAt}
            max={istDateStamp()}
            onChange={(e) => onCollectedAt(e.target.value)}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            The date on the form, bill or enquiry. If the list was built up over
            time, use the day the most recent person was added.
          </span>
        </label>
        {validation.error("consentDate")}
      </div>
    </div>
  );
}

/**
 * The answer path for a draft that is already blocked.
 *
 * SYMPTOM this fixes: a client opens a draft they built last month, the launch check
 * says "tell us where this list came from", and there is nowhere on the screen to tell
 * us — the only field that ever accepted the answer was on the create form, which is
 * behind them. Their options were to abandon the campaign or re-upload five thousand
 * rows into a new one. So the form is rendered where the blocker is read, not on a
 * different screen.
 *
 * Draft-only, matching the endpoint: this whole card only renders inside the
 * `status === "draft"` branch, and the server refuses anything else by name.
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
  const [source, setSource] = useState<ConsentSource | "">("");
  const [collectedAt, setCollectedAt] = useState("");
  const valid = useFormValidation();

  const iso = consentCollectedAt(collectedAt);

  return (
    <form
      className="space-y-4 rounded-card border border-line bg-app p-4"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (!source || !iso) return;
        declare.mutate({ source, collected_at: iso });
      })}
    >
      <p className="text-sm font-semibold text-ink">
        {correcting
          ? "Correct where this list came from"
          : "Record where this list came from"}
      </p>
      <p className="text-xs text-ink-faint">
        Your contacts stay as they are — this answers the question against this
        campaign.
      </p>

      <ConsentProvenanceFields
        validation={valid}
        idPrefix={`answer-${campaignId}`}
        source={source}
        collectedAt={collectedAt}
        onSource={setSource}
        onCollectedAt={setCollectedAt}
      />

      {/* Same gate as every other mutating control here, said before the click rather
          than discovered as a 403: `leads:dispatch` is a MUTATING permission, so an
          impersonating operator and a `staff` user are both refused it server-side. */}
      <RestrictionNote reason={write.reason} />
      {declare.error && <ProblemNotice error={declare.error} />}

      <button
        type="submit"
        title={write.allowed ? undefined : (write.reason ?? undefined)}
        disabled={!write.allowed || declare.isPending || !source || !iso}
        className={PRIMARY_BUTTON}
      >
        {declare.isPending ? "Recording…" : "Record this"}
      </button>
      {/* No success banner: the launch check is refetched on success and the blocker
          above either disappears or is replaced by the refusal. That IS the answer,
          and it is more honest than "Saved!" over a campaign still unable to launch. */}
    </form>
  );
}
