"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2 } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { adminSession, useTenant } from "@/lib/api/admin";
import {
  loosenedCeilings,
  termsStateCopy,
  useCommercialTerms,
  useRecordTerms,
  type CommercialTermsIn,
  type PlanRow,
} from "@/lib/api/commercials";

import { useAdminAccess } from "@/app/admin/access";

/**
 * Commercials — what this client pays, and every dated agreement behind it.
 *
 * `plans` has carried the whole commercial relationship since the first migration and
 * NOTHING in this product ever wrote a row: the invoice, the margin panel, the dispatch
 * ceiling and the setup-fee cron all resolved a row an operator had to INSERT by hand
 * against production. This is the surface SURFACES §1 has promised since v1.0.
 *
 * THE ONE RULE THIS SCREEN EXISTS TO KEEP. **A price change is a NEW DATED ROW.** An
 * invoice here is a derived statement — re-rendering July reads `plans` again — so
 * editing the row that priced July would silently rewrite a bill the client has already
 * paid. There is deliberately no "edit" control anywhere on this page: the form always
 * records a new agreement, the history below is append-only in practice, and the API
 * refuses a row dated into a closed billing month outright.
 *
 * §52, on every branch: loading is a skeleton, failure is a refusal, and neither is a
 * number, a state or an empty state. A read that fails must never render as "no terms" —
 * that is the one wrong answer here, because it is also a real and actionable state.
 */
export default function CommercialsPage({
  params,
}: {
  // Next 15: `params` is a Promise, unwrapped with React's `use()` in a client component.
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const terms = useCommercialTerms(adminSession(), tenantId);
  // The mutation lives here rather than in the form: a successful write invalidates the
  // read, and a mutation held inside a form remounted by that read would lose its own
  // confirmation at the moment the write landed.
  const save = useRecordTerms(adminSession(), tenantId);
  // `POST .../commercial-terms` is `admin:tenants` — see `@/app/admin/access` for why
  // the client realm's `useWriteAccess` is the wrong instrument on an admin screen.
  const write = useAdminAccess("admin:tenants", "record commercial terms");

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenantQuery.data) return <EmptyState title="Client not found" />;

  const tenant = tenantQuery.data;

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {tenant.name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Commercials</h1>
        <p className="text-sm text-ink-muted">
          What this account is charged, and from when. Every change is a new dated
          agreement — the row that priced a month they have already been billed for is
          never edited.
        </p>
      </div>

      {terms.error && <ProblemNotice error={terms.error} onRetry={() => terms.refetch()} />}

      {terms.isLoading ? (
        <Skeleton rows={5} />
      ) : !terms.data ? (
        /* The form is WITHHELD, not merely unpopulated. Recording terms while the
           current agreement is unreadable means writing a ceiling and a rate without
           knowing what they supersede — and the one thing this screen must never do is
           report "no terms" over a read that failed, because that is also a real state
           an operator would act on. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot record terms while the current agreement is unreadable"
        >
          <p className="mt-1 text-xs opacity-90">
            We could not read what is in effect for this client. Recording new terms now
            would supersede an agreement nobody can see — including, possibly, a spend
            ceiling. Retry the read above; the form comes back with it.
          </p>
        </NoticeBox>
      ) : (
        <>
          <StateBanner state={terms.data.state} />
          <InEffect row={terms.data.in_effect} />
          <RecordForm
            key={terms.data.in_effect?.id ?? "none"}
            save={save}
            inEffect={terms.data.in_effect}
            confirmation={terms.data.loosening_confirmation}
            write={write}
          />
          {save.error != null && <ProblemNotice error={save.error} />}
          {save.data && (
            <NoticeBox tone={save.data.changed ? "ok" : "neutral"} icon={<CheckCircle2 className="h-5 w-5" />}>
              <p className="text-xs">
                {save.data.changed
                  ? "Recorded as a new dated agreement. Nothing already billed was altered."
                  : "These are already the terms in effect — nothing was written, and no audit row was added."}
              </p>
            </NoticeBox>
          )}
          <History rows={terms.data.history} inEffectId={terms.data.in_effect?.id ?? null} />
        </>
      )}
    </div>
  );
}

function StateBanner({ state }: { state: string }) {
  const copy = termsStateCopy(state);
  return (
    <NoticeBox tone={copy.tone} icon={<AlertTriangle className="h-5 w-5" />} title={copy.label}>
      <p className="mt-1 text-xs opacity-90">{copy.detail}</p>
    </NoticeBox>
  );
}

/**
 * Fees go through `formatINR`, which formats the DIGITS of the API's string and never
 * parses them. A RATE does not: `overage_rate` is NUMERIC(12,4) published unrounded so
 * `qty x unit = amount` holds, and rounding ₹7.1250 to ₹7.12 on screen would break the
 * invoice's arithmetic in our favour (BUILD-LOG §52).
 */
function money(value: string | null): string | null {
  return value === null ? null : formatINR(value);
}

function rate(value: string | null): string | null {
  return value === null ? null : `₹${value}`;
}

function InEffect({ row }: { row: PlanRow | null }) {
  if (!row) return null;
  const rows: { label: string; value: string | null }[] = [
    { label: "Setup fee (one-time)", value: money(row.setup_fee_inr) },
    { label: "Monthly retainer", value: money(row.monthly_fee_inr) },
    {
      label: "Included minutes",
      // No `?? 0`: an absent allowance and an allowance of zero are different terms.
      value: row.included_minutes === null ? null : String(row.included_minutes),
    },
    { label: "Overage rate / min", value: rate(row.overage_rate_inr) },
    { label: "Value-tier rate / min", value: rate(row.overage_rate_value_inr) },
    {
      label: "Spend ceiling (ours)",
      value: money(row.hard_cap_spend_inr),
    },
    {
      label: "Minute ceiling (ours)",
      value: row.hard_cap_minutes === null ? null : String(row.hard_cap_minutes),
    },
    {
      label: "Client's own spend cap",
      value: money(row.client_cap_spend_inr),
    },
    { label: "Concurrent calls", value: String(row.concurrency_ceiling) },
    { label: "In effect from", value: row.effective_from ? formatIST(row.effective_from) : "always" },
    { label: "Until", value: row.effective_to ? formatIST(row.effective_to) : "further notice" },
  ].filter((entry) => entry.value !== null);

  return (
    <Card title="In effect now">
      <dl className="grid gap-2 sm:grid-cols-2">
        {rows.map((entry) => (
          <div key={entry.label} className="text-xs">
            <dt className="text-ink-muted">{entry.label}</dt>
            <dd className="mt-0.5 font-medium text-ink">{entry.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-ink-muted">
        Unset fields are absent rather than zero: a rate of ₹0 is free minutes, an unset
        rate is a plan that quotes none.
      </p>
    </Card>
  );
}

/** The draft, as strings — exactly what crosses the wire (hard rule 7). */
interface Draft {
  setup_fee_inr: string;
  monthly_fee_inr: string;
  included_minutes: string;
  overage_rate_inr: string;
  overage_rate_value_inr: string;
  hard_cap_minutes: string;
  hard_cap_spend_inr: string;
  concurrency_ceiling: string;
  effective_from: string;
  effective_to: string;
}

function initialDraft(row: PlanRow | null): Draft {
  return {
    setup_fee_inr: row?.setup_fee_inr ?? "",
    monthly_fee_inr: row?.monthly_fee_inr ?? "",
    included_minutes: row?.included_minutes === null || row === null ? "" : String(row.included_minutes),
    overage_rate_inr: row?.overage_rate_inr ?? "",
    overage_rate_value_inr: row?.overage_rate_value_inr ?? "",
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

function count(value: string): number | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : Number(trimmed);
}

/** `datetime-local` gives a local wall-clock string; the API takes an instant. */
function instant(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function toPayload(draft: Draft): CommercialTermsIn {
  return {
    setup_fee_inr: text(draft.setup_fee_inr),
    monthly_fee_inr: text(draft.monthly_fee_inr),
    included_minutes: count(draft.included_minutes),
    overage_rate_inr: text(draft.overage_rate_inr),
    overage_rate_value_inr: text(draft.overage_rate_value_inr),
    hard_cap_minutes: count(draft.hard_cap_minutes),
    hard_cap_spend_inr: text(draft.hard_cap_spend_inr),
    concurrency_ceiling: Number(draft.concurrency_ceiling || "10"),
    effective_from: instant(draft.effective_from),
    effective_to: instant(draft.effective_to),
  };
}

/**
 * The write. Prefilled from the agreement in effect, because a change is almost always
 * "the same terms with one number moved" — and because a blank form invites an operator
 * to record a plan that silently drops the ceiling they meant to keep.
 */
function RecordForm({
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
  const set = (key: keyof Draft, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    save.reset();
  };

  const payload = toPayload(draft);
  const loosened = loosenedCeilings(inEffect, payload);

  return (
    <Card title="Agree new terms">
      <p className="-mt-2 text-xs text-ink-muted">
        This records a NEW dated agreement. Leave the dates empty for terms that apply now
        and until further notice; set a start date to prepare a change that takes effect
        then and not before. A date inside a closed billing month is refused — that
        statement has already been rendered.
      </p>

      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({
            terms: payload,
            // Sent only for the dangerous direction, and bound to this tenant. The
            // server refuses it if this preview was wrong, so nothing rests on it.
            confirm: loosened.length > 0 ? confirmation : null,
          });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Setup fee (₹, one-time)"
            id="terms-setup"
            hint="Billed once, on the onboarding month's statement. Empty means none."
          >
            <input
              id="terms-setup"
              value={draft.setup_fee_inr}
              disabled={!write.allowed}
              onChange={(event) => set("setup_fee_inr", event.target.value)}
              inputMode="decimal"
              placeholder="5000.00"
              className={FIELD}
            />
          </Field>
          <Field label="Monthly retainer (₹)" id="terms-monthly" hint="Empty means no retainer.">
            <input
              id="terms-monthly"
              value={draft.monthly_fee_inr}
              disabled={!write.allowed}
              onChange={(event) => set("monthly_fee_inr", event.target.value)}
              inputMode="decimal"
              placeholder="9999.00"
              className={FIELD}
            />
          </Field>
          <Field
            label="Included minutes"
            id="terms-included"
            hint="The monthly allowance before overage. Empty means none included."
          >
            <input
              id="terms-included"
              value={draft.included_minutes}
              disabled={!write.allowed}
              onChange={(event) => set("included_minutes", event.target.value)}
              inputMode="numeric"
              className={FIELD}
            />
          </Field>
          <Field
            label="Overage rate (₹ / minute)"
            id="terms-overage"
            hint="Four decimal places, published unrounded — the invoice multiplies by it."
          >
            <input
              id="terms-overage"
              value={draft.overage_rate_inr}
              disabled={!write.allowed}
              onChange={(event) => set("overage_rate_inr", event.target.value)}
              inputMode="decimal"
              placeholder="8.0000"
              className={FIELD}
            />
          </Field>
          <Field
            label="Value-tier rate (₹ / minute)"
            id="terms-value"
            hint="The cheaper voice, priced separately. Leave EMPTY unless a rate has actually been decided — an unset rate bills everything at the rate above, and no default exists to fall back on."
          >
            <input
              id="terms-value"
              value={draft.overage_rate_value_inr}
              disabled={!write.allowed}
              onChange={(event) => set("overage_rate_value_inr", event.target.value)}
              inputMode="decimal"
              className={FIELD}
            />
          </Field>
          <Field
            label="Concurrent calls"
            id="terms-concurrency"
            hint="Engine capacity for this account."
          >
            <input
              id="terms-concurrency"
              value={draft.concurrency_ceiling}
              disabled={!write.allowed}
              onChange={(event) => set("concurrency_ceiling", event.target.value)}
              inputMode="numeric"
              className={FIELD}
            />
          </Field>
          <Field
            label="Spend ceiling (₹ / month)"
            id="terms-cap-spend"
            hint="OUR ceiling. Empty means no ceiling — their dialling is unlimited."
          >
            <input
              id="terms-cap-spend"
              value={draft.hard_cap_spend_inr}
              disabled={!write.allowed}
              onChange={(event) => set("hard_cap_spend_inr", event.target.value)}
              inputMode="decimal"
              className={FIELD}
            />
          </Field>
          <Field
            label="Minute ceiling (/ month)"
            id="terms-cap-min"
            hint="OUR ceiling. Empty means no ceiling."
          >
            <input
              id="terms-cap-min"
              value={draft.hard_cap_minutes}
              disabled={!write.allowed}
              onChange={(event) => set("hard_cap_minutes", event.target.value)}
              inputMode="numeric"
              className={FIELD}
            />
          </Field>
          <Field
            label="In effect from"
            id="terms-from"
            hint="Empty = now, and since forever for anything already billed."
          >
            <input
              id="terms-from"
              type="datetime-local"
              value={draft.effective_from}
              disabled={!write.allowed}
              onChange={(event) => set("effective_from", event.target.value)}
              className={FIELD}
            />
          </Field>
          <Field
            label="Until"
            id="terms-to"
            hint="Empty = until further notice. An end date with no successor leaves the account with no rate and no ceiling from that instant."
          >
            <input
              id="terms-to"
              type="datetime-local"
              value={draft.effective_to}
              disabled={!write.allowed}
              onChange={(event) => set("effective_to", event.target.value)}
              className={FIELD}
            />
          </Field>
        </div>

        {loosened.length > 0 && (
          /* The dangerous direction, called out where it is decided. The API requires a
             superadmin AND the confirmation header for this write; an operator finding
             that out as a 403 after filling the form in is the worst moment to learn it. */
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

        <button
          type="submit"
          disabled={save.isPending || !write.allowed}
          className={PRIMARY_BUTTON}
        >
          {save.isPending ? "Recording…" : "Record new terms"}
        </button>
      </form>
    </Card>
  );
}

function History({ rows, inEffectId }: { rows: PlanRow[]; inEffectId: string | null }) {
  if (rows.length === 0) return null;
  return (
    <Card title="Every agreement, newest first">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-ink-muted">
            <tr>
              <th className="py-1 pr-3 font-medium">From</th>
              <th className="py-1 pr-3 font-medium">Until</th>
              <th className="py-1 pr-3 font-medium">Retainer</th>
              <th className="py-1 pr-3 font-medium">Included</th>
              <th className="py-1 pr-3 font-medium">Rate / min</th>
              <th className="py-1 pr-3 font-medium">Recorded</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-line">
                <td className="py-1.5 pr-3">
                  {row.effective_from ? formatIST(row.effective_from) : "always"}
                  {row.id === inEffectId && (
                    <span className="ml-2 rounded-full bg-brand-soft px-2 py-0.5 text-brand-strong">
                      in effect
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-3">
                  {row.effective_to ? formatIST(row.effective_to) : "—"}
                </td>
                <td className="py-1.5 pr-3">{money(row.monthly_fee_inr) ?? "—"}</td>
                <td className="py-1.5 pr-3">
                  {row.included_minutes === null ? "—" : row.included_minutes}
                </td>
                <td className="py-1.5 pr-3">{rate(row.overage_rate_inr) ?? "—"}</td>
                <td className="py-1.5 pr-3">{formatIST(row.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-ink-muted">
        Nothing here is editable, and that is the point: an invoice is re-derived from
        these rows every time anyone opens it, so a change to one would rewrite a
        statement the client has already paid.
      </p>
    </Card>
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
  children: React.ReactNode;
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
