"use client";

import { type ReactNode } from "react";
import { BadgeCheck, ShieldAlert } from "lucide-react";

import { ActionButton } from "@/components/arc/feedback";
import { RadioGroup } from "@/components/arc/radio-group";
import { FIELD_INLINE, ProblemNotice } from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { CONSENT_SOURCES, type ConsentSource, type ConsentStatus } from "@/lib/api/messagingConsent";

import { Verdict } from "./Verdict";
import { NO_STATUSES, STATUS_COPY } from "./statusCopy";
import { type ConsentForm } from "./consentForm";
import { CONSENT_COPY as COPY } from "./copy";

/**
 * Recording what a customer said — the append-only write behind this screen.
 *
 * Four things the schema encodes that a generic form would quietly break:
 *
 * 1. **The answer comes first, and it decides the rest of the form.** "They said yes" and
 *    "They said no" are not two values of one dropdown, because they have different rules:
 *    a yes must be evidenced and cannot come from your own staff, a no needs nothing at
 *    all and may come from anywhere. Asking the question first is what lets the form offer
 *    only the sources that can carry the answer given.
 * 2. **Evidence changes shape with the source**, because each source evidences itself
 *    differently (call → the call and the moment in it; web form → the form and the
 *    wording version; paper → the document; WhatsApp → the message id). One free-text
 *    "notes" box would satisfy the CHECK constraint and evidence nothing.
 * 3. **There is no "assumed" and no "implied".** Not in the source list, and not reachable
 *    by submitting a yes with the evidence fields left empty — the submit button says why
 *    it is disabled instead (`grantBlockReason`).
 * 4. **No delete control exists anywhere.** The ledger is append-only (hard rule 4) and a
 *    withdrawal is a new record that supersedes the grant before it.
 */
export function RecordConsent({ form }: { form: ConsentForm }) {
  /* Its own `useFormValidation` instance — see the note in `ConsentLookup`. */
  const valid = useFormValidation();
  const { record, spec } = form;

  return (
    <div>
      <p className="text-sm text-ink-muted">{COPY.recordIntro}</p>

      <form className="mt-4 space-y-4" noValidate onSubmit={valid.onSubmit(form.submit)}>
        <Field label={COPY.numberLabel} htmlFor="consent-phone">
          <input
            {...valid.field("phone", COPY.numberMissing)}
            id="consent-phone"
            required
            value={form.phone}
            onChange={(e) => {
              form.setPhone(e.target.value);
              record.reset();
            }}
            minLength={8}
            maxLength={20}
            inputMode="tel"
            autoComplete="off"
            placeholder="9876543210 or +919876543210"
            className={`${FIELD_INLINE} w-full max-w-md font-mono`}
          />
          {valid.error("phone")}
        </Field>

        {/* The answer first: it is what decides which sources may carry it. Native radios,
            so the focused answer is always visible (this record is the client's evidence
            that a real person agreed). */}
        <RadioGroup
          name="answer"
          label={COPY.saidLabel}
          value={form.answer}
          onChange={(next) => form.chooseAnswer(next === "yes" ? "yes" : "no")}
          options={[
            { value: "yes", label: COPY.saidYes, hint: STATUS_COPY.granted.hint },
            { value: "no", label: COPY.saidNo, hint: COPY.saidNoHint },
          ]}
        />

        {form.answer === "no" && (
          <Field label={COPY.whichNo} htmlFor="consent-status">
            <select
              id="consent-status"
              value={form.status}
              onChange={(e) => form.setStatus(e.target.value as ConsentStatus)}
              className={FIELD_INLINE}
            >
              {NO_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {STATUS_COPY[value].label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-ink-muted">{STATUS_COPY[form.status].hint}</p>
          </Field>
        )}

        <Field label={COPY.howKnow} htmlFor="consent-source">
          <select
            id="consent-source"
            value={form.source}
            onChange={(e) => form.chooseSource(e.target.value as ConsentSource)}
            className={`${FIELD_INLINE} w-full max-w-md`}
          >
            {form.sourceOptions.map((value) => (
              <option key={value} value={value}>
                {CONSENT_SOURCES[value].label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-ink-muted">{spec.hint}</p>
          {/* Said once, where someone would otherwise go looking for the missing
              option: your own staff cannot assert an opt-in on a customer's behalf. */}
          {form.answer === "yes" && (
            <p className="mt-1 text-xs text-ink-muted">{COPY.notOnBehalf}</p>
          )}
        </Field>

        {spec.requiresCallId && (
          <Field label={COPY.whichCall} htmlFor="consent-call">
            <input
              id="consent-call"
              value={form.callId}
              onChange={(e) => form.setCallId(e.target.value)}
              placeholder={COPY.callPlaceholder}
              className={`${FIELD_INLINE} w-full max-w-md font-mono`}
            />
            <p className="mt-1 text-xs text-ink-muted">
              {form.answer === "yes" ? COPY.callRequired : COPY.callOptional}
            </p>
          </Field>
        )}

        {spec.evidence.map((field) => (
          <Field key={field.key} label={field.label} htmlFor={`evidence-${field.key}`}>
            <input
              id={`evidence-${field.key}`}
              value={form.evidence[field.key] ?? ""}
              onChange={(e) =>
                form.setEvidence((prev) => ({ ...prev, [field.key]: e.target.value }))
              }
              placeholder={field.placeholder}
              className={`${FIELD_INLINE} w-full max-w-md`}
            />
            <p className="mt-1 text-xs text-ink-muted">
              {field.hint}
              {form.answer === "no" && COPY.optionalHere}
            </p>
          </Field>
        ))}

        <div className="flex flex-wrap items-center gap-3">
          {/* `blocked` holds the button: it is a rule about WHAT may be recorded, not an
              answer this form can point at. The length rule is answered at the field. */}
          <ActionButton
            type="submit"
            status={form.recordFeedback.status}
            disabled={form.blocked !== null}
            successLabel={COPY.recorded}
            className="max-sm:w-full max-sm:justify-center"
          >
            <BadgeCheck aria-hidden className="h-4 w-4" />
            {form.answer === "yes" ? COPY.recordYes : COPY.recordNo}
          </ActionButton>
          {/* The refusal, given before the click rather than as a 422 after it. */}
          {form.blocked && (
            <span className="flex items-start gap-1.5 text-xs text-warn">
              <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
              {form.blocked}
            </span>
          )}
        </div>
      </form>

      {/* `form.recordError`, not `record.error`: the module that FIRES the write is the
          one that hands its refusal on (see `consentForm.ts`). */}
      {form.recordError != null && (
        <div className="mt-3">
          <ProblemNotice error={form.recordError} />
        </div>
      )}
      {record.data && (
        <div className="mt-4">
          <p className="mb-2 text-sm font-medium text-ink">{COPY.nowStands}</p>
          <Verdict state={record.data} />
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
        {label}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

