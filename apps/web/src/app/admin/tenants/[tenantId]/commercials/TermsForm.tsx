"use client";

import { useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  RestrictionNote,
  istInputToInstant,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { FieldMessage, wholeNumberProblem } from "@/components/formValidation";
import { WriteFailure } from "@/app/admin/writeFailure";
import type { useAdminAccess } from "@/app/admin/access";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { flatDraftSurface, type FlatFieldSpec } from "@/lib/copilot/screens/flatDraft";
import {
  loosenedCeilings,
  type CommercialTermsIn,
  type PlanRow,
  type useRecordTerms,
} from "@/lib/api/commercials";

import { secondOverageRate } from "./termsFormat";

/** The draft, as strings — exactly what crosses the wire (hard rule 7). */
interface Draft {
  setup_fee_inr: string;
  monthly_fee_inr: string;
  included_minutes: string;
  overage_rate_inr: string;
  overage_rate_second_inr: string;
  llm_model_surcharge_inr: string;
  hard_cap_minutes: string;
  hard_cap_spend_inr: string;
  concurrency_ceiling: string;
  effective_from: string;
  effective_to: string;
}

/**
 * What the screen assistant may fill in — the eleven controls the form renders, keyed by
 * the ids they carry. Written out rather than derived from `Draft`'s keys because a key
 * cannot say what a control MEANS: "empty means no ceiling" is the difference between an
 * unlimited account and a free one.
 */
const COPILOT_FIELDS: readonly FlatFieldSpec<keyof Draft & string>[] = [
  { id: "terms-setup", key: "setup_fee_inr", label: "Setup fee (₹, one-time)", type: "text", help: "Billed once, on the onboarding month's statement. Empty means none." },
  { id: "terms-monthly", key: "monthly_fee_inr", label: "Monthly retainer (₹)", type: "text", help: "Empty means no retainer." },
  { id: "terms-included", key: "included_minutes", label: "Included minutes", type: "number", help: "The monthly allowance before overage. Empty means none included." },
  { id: "terms-overage", key: "overage_rate_inr", label: "Base overage rate (₹ / minute)", type: "text", help: "Four decimal places, published unrounded." },
  { id: "terms-value", key: "overage_rate_second_inr", label: "Second overage rate (₹ / minute)", type: "text", help: "A second agreed rate for this plan, not a different voice. Leave EMPTY unless a rate has actually been decided — an unset rate bills everything at the rate above." },
  { id: "terms-llm-surcharge", key: "llm_model_surcharge_inr", label: "AI model surcharge (₹ / minute)", type: "text", help: "Applies only to a model the client picked. Leave EMPTY unless a number has been decided." },
  { id: "terms-concurrency", key: "concurrency_ceiling", label: "Concurrent calls", type: "number", help: "Engine capacity for this account." },
  { id: "terms-cap-spend", key: "hard_cap_spend_inr", label: "Spend ceiling (₹ / month)", type: "text", help: "OUR ceiling. Empty means no ceiling — their dialling is unlimited." },
  { id: "terms-cap-min", key: "hard_cap_minutes", label: "Minute ceiling (/ month)", type: "number", help: "OUR ceiling. Empty means no ceiling." },
  { id: "terms-from", key: "effective_from", label: "In effect from (IST)", type: "date", help: "A `datetime-local` value (YYYY-MM-DDTHH:MM) read as Indian Standard Time, never as the viewer's clock. Empty = now." },
  { id: "terms-to", key: "effective_to", label: "Until (IST)", type: "date", help: "A `datetime-local` value (YYYY-MM-DDTHH:MM) read as Indian Standard Time. Empty = until further notice." },
];

function initialDraft(row: PlanRow | null): Draft {
  return {
    setup_fee_inr: row?.setup_fee_inr ?? "",
    monthly_fee_inr: row?.monthly_fee_inr ?? "",
    included_minutes: row?.included_minutes === null || row === null ? "" : String(row.included_minutes),
    overage_rate_inr: row?.overage_rate_inr ?? "",
    overage_rate_second_inr: secondOverageRate(row) ?? "",
    llm_model_surcharge_inr: row?.llm_model_surcharge_inr ?? "",
    hard_cap_minutes: row?.hard_cap_minutes === null || row === null ? "" : String(row.hard_cap_minutes),
    hard_cap_spend_inr: row?.hard_cap_spend_inr ?? "",
    concurrency_ceiling: String(row?.concurrency_ceiling ?? 10),
    effective_from: "",
    effective_to: "",
  };
}

function text(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * The whole-number fields. Their empty value MEANS something ("none included", "no
 * ceiling"), so an unreadable one is refused on the form rather than sent: `Number()` of it
 * is NaN, which JSON sends as that same `null`.
 */
const COUNT_FIELDS = ["included_minutes", "hard_cap_minutes", "concurrency_ceiling"] as const;
type CountField = (typeof COUNT_FIELDS)[number];

function count(value: string): number | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : Number(trimmed);
}

/**
 * `datetime-local` is a wall clock with no zone; the API takes an instant. It is read as
 * IST (`istInputToInstant`), never as the browser's clock — an operator on a laptop set to
 * a US zone typing "09:00" meant IST, and the old `new Date()` recorded a billing boundary
 * eleven and a half hours away. The labels say IST because an unlabelled field meaning
 * something other than the machine's clock is worse than the bug.
 */
function toPayload(draft: Draft): CommercialTermsIn {
  return {
    setup_fee_inr: text(draft.setup_fee_inr),
    monthly_fee_inr: text(draft.monthly_fee_inr),
    included_minutes: count(draft.included_minutes),
    overage_rate_inr: text(draft.overage_rate_inr),
    // WRITTEN UNDER THE NEW NAME ONLY: the server refuses a request that sends both names
    // with different figures, so sending both would invent a conflict to keep in step.
    overage_rate_second_inr: text(draft.overage_rate_second_inr),
    llm_model_surcharge_inr: text(draft.llm_model_surcharge_inr),
    hard_cap_minutes: count(draft.hard_cap_minutes),
    hard_cap_spend_inr: text(draft.hard_cap_spend_inr),
    concurrency_ceiling: Number(draft.concurrency_ceiling || "10"),
    effective_from: istInputToInstant(draft.effective_from),
    effective_to: istInputToInstant(draft.effective_to),
  };
}

/**
 * THE WRITE — always a NEW dated agreement; there is no edit control anywhere, because an
 * invoice is re-derived from these rows and editing the one that priced July would rewrite a
 * bill already paid. Prefilled from the agreement in effect, because a change is almost
 * always "the same terms with one number moved" and a blank form invites a plan that
 * silently drops the ceiling the operator meant to keep.
 */
export function TermsForm({
  save,
  inEffect,
  confirmation,
  write,
}: {
  save: ReturnType<typeof useRecordTerms>;
  inEffect: PlanRow | null;
  confirmation: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [draft, setDraft] = useState<Draft>(() => initialDraft(inEffect));
  // Whole-number problems show once a submit has been tried, then stay live so a fix
  // clears them.
  const [attempted, setAttempted] = useState(false);
  const set = (key: keyof Draft, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    save.reset();
  };

  // One flat draft of strings, so a fill is one `setDraft` — never the DOM — and it leaves
  // the server's refusal on screen (a keystroke clears it; a fill should not).
  useCopilotSurface(
    flatDraftSurface(
      { route: "/admin/tenants/{id}/commercials", title: "Commercial terms", realm: "admin" },
      draft,
      COPILOT_FIELDS,
      setDraft,
      [],
    ),
  );

  const payload = toPayload(draft);
  const loosened = loosenedCeilings(inEffect, payload);
  const countProblems: Partial<Record<CountField, string>> = {};
  for (const key of COUNT_FIELDS) {
    const problem = wholeNumberProblem(draft[key]);
    if (attempted && problem !== null) countProblems[key] = problem;
  }
  const countProps = (key: CountField) => {
    const problem = countProblems[key];
    return problem
      ? { "aria-invalid": true as const, "aria-describedby": `terms-${key}-problem` }
      : {};
  };
  const countMessage = (key: CountField) => {
    const problem = countProblems[key];
    return problem ? <FieldMessage id={`terms-${key}-problem`}>{problem}</FieldMessage> : null;
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-ink-muted">
        This records a NEW dated agreement. Leave the dates empty for terms that apply now
        and until further notice; set a start date to prepare a change that takes effect
        then and not before. A date inside a closed billing month is refused — that
        statement has already been rendered.
      </p>

      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setAttempted(true);
          if (COUNT_FIELDS.some((key) => wholeNumberProblem(draft[key]) !== null)) return;
          save.mutate({
            terms: payload,
            // Sent only for the dangerous direction, and bound to this tenant. The server
            // refuses it if this preview was wrong, so nothing rests on it.
            confirm: loosened.length > 0 ? confirmation : null,
          });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Setup fee (₹, one-time)" id="terms-setup" hint="Billed once, on the onboarding month's statement. Empty means none.">
            <input id="terms-setup" value={draft.setup_fee_inr} disabled={!write.allowed} onChange={(event) => set("setup_fee_inr", event.target.value)} inputMode="decimal" placeholder="5000.00" className={FIELD} />
          </Field>
          <Field label="Monthly retainer (₹)" id="terms-monthly" hint="Empty means no retainer.">
            <input id="terms-monthly" value={draft.monthly_fee_inr} disabled={!write.allowed} onChange={(event) => set("monthly_fee_inr", event.target.value)} inputMode="decimal" placeholder="9999.00" className={FIELD} />
          </Field>
          <Field label="Included minutes" id="terms-included" hint="The monthly allowance before overage. Empty means none included.">
            <input id="terms-included" value={draft.included_minutes} disabled={!write.allowed} onChange={(event) => set("included_minutes", event.target.value)} inputMode="numeric" className={FIELD} {...countProps("included_minutes")} />
            {countMessage("included_minutes")}
          </Field>
          <Field label="Base overage rate (₹ / minute)" id="terms-overage" hint="Four decimal places, published unrounded — the invoice multiplies by it.">
            <input id="terms-overage" value={draft.overage_rate_inr} disabled={!write.allowed} onChange={(event) => set("overage_rate_inr", event.target.value)} inputMode="decimal" placeholder="8.0000" className={FIELD} />
          </Field>
          <Field label="Second overage rate (₹ / minute)" id="terms-value" hint="A second agreed rate, not a different voice. Leave empty unless one has been decided — an unset rate bills everything at the base rate.">
            <input id="terms-value" value={draft.overage_rate_second_inr} disabled={!write.allowed} onChange={(event) => set("overage_rate_second_inr", event.target.value)} inputMode="decimal" className={FIELD} />
          </Field>
          <Field label="AI model surcharge (₹ / minute)" id="terms-llm-surcharge" hint="Added only for minutes this client's own model choice upgraded, never for the platform default. Leave empty unless a number has been decided.">
            <input id="terms-llm-surcharge" value={draft.llm_model_surcharge_inr} disabled={!write.allowed} onChange={(event) => set("llm_model_surcharge_inr", event.target.value)} inputMode="decimal" className={FIELD} />
          </Field>
          <Field label="Concurrent calls" id="terms-concurrency" hint="Engine capacity for this account.">
            <input id="terms-concurrency" value={draft.concurrency_ceiling} disabled={!write.allowed} onChange={(event) => set("concurrency_ceiling", event.target.value)} inputMode="numeric" className={FIELD} {...countProps("concurrency_ceiling")} />
            {countMessage("concurrency_ceiling")}
          </Field>
          <Field label="Spend ceiling (₹ / month)" id="terms-cap-spend" hint="OUR ceiling. Empty means no ceiling — their dialling is unlimited.">
            <input id="terms-cap-spend" value={draft.hard_cap_spend_inr} disabled={!write.allowed} onChange={(event) => set("hard_cap_spend_inr", event.target.value)} inputMode="decimal" className={FIELD} />
          </Field>
          <Field label="Minute ceiling (/ month)" id="terms-cap-min" hint="OUR ceiling. Empty means no ceiling.">
            <input id="terms-cap-min" value={draft.hard_cap_minutes} disabled={!write.allowed} onChange={(event) => set("hard_cap_minutes", event.target.value)} inputMode="numeric" className={FIELD} {...countProps("hard_cap_minutes")} />
            {countMessage("hard_cap_minutes")}
          </Field>
          <Field label="In effect from (IST)" id="terms-from" hint="Indian Standard Time, whatever this machine's clock is set to. Empty = now, and since forever for anything already billed.">
            <input id="terms-from" type="datetime-local" value={draft.effective_from} disabled={!write.allowed} onChange={(event) => set("effective_from", event.target.value)} className={FIELD} />
          </Field>
          <Field label="Until (IST)" id="terms-to" hint="Indian Standard Time, whatever this machine's clock is set to. Empty = until further notice. An end date with no successor leaves the account with no rate and no ceiling from that instant.">
            <input id="terms-to" type="datetime-local" value={draft.effective_to} disabled={!write.allowed} onChange={(event) => set("effective_to", event.target.value)} className={FIELD} />
          </Field>
        </div>

        {loosened.length > 0 && (
          /* The dangerous direction, called out where it is decided: the API requires a
             superadmin AND the confirmation header for this write. */
          <NoticeBox tone="warn" icon={<AlertTriangle className="h-4 w-4" />}>
            <p className="text-xs">
              This raises or removes the <span className="font-medium">{loosened.join(" and ")}</span>.
              That is a superadmin action and it is confirmed explicitly — this console
              sends the confirmation with the request. Tightening a ceiling, or setting a
              first one, needs neither.
            </p>
          </NoticeBox>
        )}

        {inEffect && (
          <p className="text-xs text-ink-muted">
            The client&apos;s own spend cap does not carry over: a new agreement is terms
            they have not seen, so the limit they set against the old one stays on the old
            row. They can set it again from their own screen.
          </p>
        )}

        {save.error != null && <WriteFailure error={save.error} actionLabel="Record new terms" />}
        {save.data && (
          <NoticeBox tone={save.data.changed ? "ok" : "neutral"} icon={<CheckCircle2 className="h-5 w-5" />}>
            <p className="text-xs">
              {save.data.changed
                ? "Recorded as a new dated agreement. Nothing already billed was altered."
                : "These are already the terms in effect — nothing was written, and no audit row was added."}
            </p>
          </NoticeBox>
        )}

        <ActionButton type="submit" loading={save.isPending} disabled={!write.allowed}>
          Record new terms
        </ActionButton>
      </form>
    </div>
  );
}

function Field({
  label,
  id,
  hint,
  children,
}: {
  label: string;
  id: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <div className="mt-1">{children}</div>
      <span className={FIELD_HINT}>{hint}</span>
    </div>
  );
}
