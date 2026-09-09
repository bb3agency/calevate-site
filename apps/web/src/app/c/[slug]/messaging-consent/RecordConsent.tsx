"use client";

import { type ReactNode } from "react";
import { BadgeCheck, ShieldAlert } from "lucide-react";

import {
  Card,
  FIELD_INLINE,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { CONSENT_SOURCES, type ConsentSource, type ConsentStatus } from "@/lib/api/messagingConsent";

import { Verdict } from "./Verdict";
import { NO_STATUSES, STATUS_COPY } from "./statusCopy";
import { type ConsentForm } from "./consentForm";

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
    <Card title="Record what a customer said">
      <p className="text-sm text-ink-muted">
        Every record is kept — nothing here is edited or deleted. If someone changes
        their mind, record the new answer and it replaces the old one from that
        moment.
      </p>

      <form className="mt-4 space-y-4" noValidate onSubmit={valid.onSubmit(form.submit)}>
        <Field label="Their number" htmlFor="consent-phone">
          <input
            {...valid.field("phone", "Enter their number.")}
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
            className={`${FIELD_INLINE} w-64 font-mono`}
          />
          {valid.error("phone")}
        </Field>

        {/* The answer first: it is what decides which sources may carry it. */}
        <fieldset>
          <legend className="text-sm font-medium text-ink">What did they say?</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            <Choice
              name="answer"
              checked={form.answer === "yes"}
              onChange={() => form.chooseAnswer("yes")}
              label="They agreed to be messaged"
            />
            <Choice
              name="answer"
              checked={form.answer === "no"}
              onChange={() => form.chooseAnswer("no")}
              label="They do not want messages"
            />
          </div>
          <p className="mt-2 text-xs text-ink-muted">
            {form.answer === "yes"
              ? STATUS_COPY.granted.hint
              : "A refusal is never held up: it needs no evidence and can be recorded by anyone here."}
          </p>
        </fieldset>

        {form.answer === "no" && (
          <Field label="Which kind of no?" htmlFor="consent-status">
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

        <Field label="How do you know?" htmlFor="consent-source">
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
            <p className="mt-1 text-xs text-ink-muted">
              Recording it on a customer&apos;s behalf is not on this list — an
              opt-in has to come from the customer.
            </p>
          )}
        </Field>

        {spec.requiresCallId && (
          <Field label="Which call?" htmlFor="consent-call">
            <input
              id="consent-call"
              value={form.callId}
              onChange={(e) => form.setCallId(e.target.value)}
              placeholder="Call ID from the Calls page"
              className={`${FIELD_INLINE} w-full max-w-md font-mono`}
            />
            <p className="mt-1 text-xs text-ink-muted">
              {form.answer === "yes"
                ? "Required: a spoken opt-in has to name the call it was spoken on."
                : "Optional for a refusal."}
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
              {form.answer === "no" && " Optional here."}
            </p>
          </Field>
        ))}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            /* `blocked` stays: it is a rule about WHAT may be recorded, not about
               an answer this form can point at. The length rule is answered at the
               field now. */
            disabled={record.isPending || form.blocked !== null}
            className={PRIMARY_BUTTON_SM}
          >
            <BadgeCheck className="h-4 w-4" />
            {record.isPending
              ? "Recording…"
              : form.answer === "yes"
                ? "Record their opt-in"
                : "Record their refusal"}
          </button>
          {/* The refusal, given before the click rather than as a 422 after it. */}
          {form.blocked && (
            <span className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
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
          <p className="mb-2 text-sm font-medium text-ink">
            Recorded. This is where that number now stands:
          </p>
          <Verdict state={record.data} />
        </div>
      )}
    </Card>
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

function Choice({
  name,
  checked,
  onChange,
  label,
}: {
  name: string;
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  /*
   * WCAG 2.4.7 Focus Visible (AA), failure technique F78 — the same fix, and the same
   * reasoning, as `components/llmModelPicker.tsx`'s model rows, which is where it is
   * written out in full. The input below is `sr-only`, so the browser's own ring is gone
   * and the label styled only `checked` and `hover`: a keyboard user could not see which
   * of "Agreed" / "Refused" they were on.
   *
   * This one is 🔒 compliance-visible. The record this radio produces is the client's
   * evidence under TCCCPR that a person agreed to be messaged — the screen says so — so a
   * keyboard user unable to see which answer is focused is a keyboard user who can record
   * the wrong one about a real person.
   */
  const FOCUS_RING =
    "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app";
  return (
    <label
      className={
        checked
          ? `cursor-pointer rounded-md border border-brand-strong bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white ${FOCUS_RING}`
          : `cursor-pointer rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5 ${FOCUS_RING}`
      }
    >
      <input type="radio" name={name} checked={checked} onChange={onChange} className="sr-only" />
      {label}
    </label>
  );
}
