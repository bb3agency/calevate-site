"use client";

import { Section } from "@/components/console/section";
import { useState } from "react";
import { CheckCircle2, Lock } from "lucide-react";

import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
  formatRupeeRate,
} from "@/components/ui";
import {
  useAttestCost,
  useAttestEngineMinutePrice,
  useEngineMinutePrices,
  type CostAttestation,
  type EngineMinutePrice,
  type EngineMinutePrices,
} from "@/lib/api/engineMinutePricing";
import { providerLabel } from "@/lib/api/llmModels";
import { lookup } from "@/lib/lookup";

type Access = { allowed: boolean; reason: string | null };

/** Rupees per minute: positive, at most six decimals. The server re-checks. */
const RUPEES_PER_MIN = "^(?:0*[1-9]\\d{0,5}(?:\\.\\d{1,6})?|0*\\.\\d{0,5}[1-9]\\d{0,5})$";

const KEY_LABELS: Record<string, string> = {
  platform: "Platform minute (telephony included)",
  standard: "Voice band: standard",
  premium: "Voice band: premium",
  studio: "Voice band: studio",
  carrier: "Carrier fee only (a call that ended before the agent spoke)",
  byok_voice: "Our voice, their model (Studio)",
  byok_llm_voice: "Our voice and our model (Studio on our model)",
};

/**
 * What a client is sold on this rate, from the server's `sold_as` (D-681). The platform
 * minute is never sold on its own, but it has to be recorded: it opens the platform at all.
 */
export function saleNote(row: EngineMinutePrice): string {
  if (row.sold_as) return `Sold to clients as ${row.sold_as}.`;
  if (row.rate_key === "platform") return "Not sold on its own — needed before any voice is offered.";
  return "Not sold to clients — recorded for cost only.";
}

/**
 * The wallet top-up fee the meter adds, from the server's attested figure (D-840), or the
 * plain statement that none is attested — never a number typed here.
 */
export function feeSentence(costs: EngineMinutePrices["costs"]): string {
  const fee = costs.find((cost) => cost.subject === "thinnest_topup_fee");
  return fee?.value ? `${fee.value}%` : "no fee recorded, so every minute is metered unpriced";
}

/** The all-in figure beside a posted rate: what a billed minute is metered at. */
export function allInNote(row: EngineMinutePrice): string | null {
  if (!row.inr_per_min_with_fee) return null;
  if (!row.topup_fee_percent || row.topup_fee_percent === "0") return null;
  return `${formatRupeeRate(row.inr_per_min_with_fee)} with the ${row.topup_fee_percent}% top-up fee`;
}

/** How a cost input reads beside its label: "2.36%", "₹349.00 a month", or not recorded. */
export function costValue(cost: CostAttestation): string {
  if (!cost.value) return "Not recorded";
  return cost.unit === "percent" ? `${cost.value}%` : `${formatRupeeRate(cost.value)} a month`;
}

function rowId(row: EngineMinutePrice): string {
  return `${row.engine}:${row.rate_key}`;
}

/**
 * The per-minute rates for a voice platform that reports no cost for a call (D-678).
 *
 * A minute on such a platform is metered only at a rate an operator read off their own
 * invoice (hard rule 7). The `platform` rate opens the platform at all; each voice band's
 * rate opens that band's voices. Each recording is a new dated row — a correction is a new
 * recording, never an edit.
 */
export function EngineMinutePricePanel({ access }: { access: Access }) {
  const prices = useEngineMinutePrices();
  const attest = useAttestEngineMinutePrice();
  const valid = useFormValidation();
  const [editing, setEditing] = useState<EngineMinutePrice | null>(null);
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("");

  if (isForbidden(prices.error)) {
    return (
      <WithheldPanel
        title="Per-minute rates"
        reason={
          forbiddenReason(prices.error) ??
          "The API refused this read: your admin account may not see platform prices."
        }
        subject="This panel would show the per-minute rate attested for each voice platform that reports no call cost."
      />
    );
  }

  const rows = prices.data ? prices.data.prices : null;
  const fees = prices.data ? feeSentence(prices.data.costs) : null;
  const platformUnpriced = Boolean(
    rows?.some((row) => row.rate_key === "platform" && !row.billable),
  );

  return (
    <Section title="Per-minute rates">
      <div className="space-y-4">
        <p className="text-body text-ink-muted">
          For a voice platform that reports no cost for a call: the voice platform&apos;s
          posted rate per billed minute, before its wallet top-up fee — we add the fee
          {fees ? ` (${fees})` : ""}. Calls are billed in 30-second steps. Type the figure
          from the platform&apos;s price page or your invoice.
        </p>

        {prices.isLoading ? (
          <Skeleton rows={3} />
        ) : prices.error || !rows ? (
          <ProblemNotice
            error={prices.error ?? new Error("The per-minute rates did not load.")}
            onRetry={() => prices.refetch()}
          />
        ) : null}

        {platformUnpriced && (
          <NoticeBox
            tone="warn"
            title="No platform rate recorded. No minute on it can be sold"
          >
            <p className="mt-1">
              Until the platform minute is recorded, no agent on that platform is offered and
              any call that runs is metered with no cost and raises an alarm.
            </p>
          </NoticeBox>
        )}

        {rows && rows.length > 0 && (
          <ul className="divide-y divide-line border-y border-line">
            {rows.map((row) => (
              <li key={rowId(row)} className="flex flex-wrap items-start gap-3 px-3 py-2.5 text-body">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-ink">
                    {providerLabel(row.engine)} ·{" "}
                    {lookup(KEY_LABELS, row.rate_key) ?? row.rate_key}
                  </p>
                  <p className="text-meta text-ink-muted">{saleNote(row)}</p>
                  {row.inr_per_min ? (
                    <p className="text-meta text-ink-muted">
                      {formatRupeeRate(row.inr_per_min)} per minute posted
                      {allInNote(row) ? ` · ${allInNote(row)}` : ""} ·{" "}
                      {row.source_note ?? "—"}
                      {row.attested_at ? ` · recorded ${formatIST(row.attested_at)}` : ""}
                    </p>
                  ) : (
                    <p className="text-meta font-medium text-warn">
                      Not recorded — not sold
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={!access.allowed || attest.isPending}
                  title={access.reason ?? undefined}
                  onClick={() => {
                    setEditing(row);
                    setAmount("");
                    setSource("");
                    valid.reset();
                  }}
                >
                  {row.inr_per_min ? "Record a new rate" : "Record a rate"}
                </button>
              </li>
            ))}
          </ul>
        )}

        {attest.error && <WriteFailure error={attest.error} actionLabel="Record the rate" />}
        {attest.isSuccess && !editing && (
          <p className="flex items-start gap-2 text-body text-ink-muted">
            <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
            <span>Recorded. Minutes from now on are metered at this rate.</span>
          </p>
        )}

        {!access.allowed && access.reason && (
          <p className="flex items-start gap-2 text-meta text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {access.reason}
          </p>
        )}

        {editing && (
          <form
            className="space-y-3 border-t border-line pt-4"
            noValidate
            onSubmit={valid.onSubmit(() => {
              attest.mutate(
                {
                  engine: editing.engine,
                  rateKey: editing.rate_key,
                  inrPerMin: amount.trim(),
                  sourceNote: source.trim(),
                },
                { onSuccess: () => setEditing(null) },
              );
            })}
          >
            <p className="text-body font-medium text-ink">
              {providerLabel(editing.engine)} ·{" "}
              {lookup(KEY_LABELS, editing.rate_key) ?? editing.rate_key}
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="block">
                <span className={FIELD_LABEL}>Rupees per billed minute</span>
                <input
                  {...valid.field("inr_per_min", "Enter rupees per minute, like 1.00 or 2.50.")}
                  required
                  inputMode="decimal"
                  pattern={RUPEES_PER_MIN}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  disabled={!access.allowed}
                  className={`${FIELD} font-mono`}
                />
                {valid.error("inr_per_min")}
                <span className={FIELD_HINT}>
                  The posted rate, before the top-up fee
                  {editing.topup_fee_percent && editing.topup_fee_percent !== "0"
                    ? `; we add ${editing.topup_fee_percent}%`
                    : ""}
                  .
                </span>
              </label>
              <label className="block sm:col-span-2">
                <span className={FIELD_LABEL}>Read from</span>
                <input
                  {...valid.field("source_note", "Name the invoice or plan page (at least 3 characters).")}
                  required
                  minLength={3}
                  maxLength={500}
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  disabled={!access.allowed}
                  placeholder="e.g. 'ThinnestAI invoice, Oct 2026'"
                  className={FIELD}
                />
                {valid.error("source_note")}
                <span className={FIELD_HINT}>The invoice or plan page, and its date.</span>
              </label>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                disabled={!access.allowed || attest.isPending}
                className={PRIMARY_BUTTON}
              >
                {attest.isPending ? "Recording…" : "Record the rate"}
              </button>
              <button
                type="button"
                disabled={attest.isPending}
                onClick={() => {
                  setEditing(null);
                  valid.reset();
                }}
                className={SECONDARY_BUTTON}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {prices.data && <CostInputs costs={prices.data.costs} access={access} />}
      </div>
    </Section>
  );
}

/** Rupees a month, or a percentage below 100 with up to four decimals. The server re-checks. */
const PERCENT = "^(?:\\d{1,2}(?:\\.\\d{1,4})?)$";

/**
 * The fees and the number rent beside the minute (D-840). The wallet top-up fee is added to
 * every metered minute and rented number; the gateway fee on a client's top-up is counted in
 * the rate card's cost floor; the rent prices each number rented in the platform's console.
 * Until one is recorded, what depends on it is metered unpriced or left out of the floor.
 */
function CostInputs({ costs, access }: { costs: CostAttestation[]; access: Access }) {
  const attest = useAttestCost();
  const valid = useFormValidation();
  const [editing, setEditing] = useState<CostAttestation | null>(null);
  const [value, setValue] = useState("");
  const [source, setSource] = useState("");

  return (
    <div className="space-y-3 border-t border-line pt-4">
      <p className="text-body font-medium text-ink">Fees and number rent</p>
      <ul className="divide-y divide-line border-y border-line">
        {costs.map((cost) => (
          <li key={cost.subject} className="flex flex-wrap items-start gap-3 px-3 py-2.5 text-body">
            <div className="min-w-0 flex-1">
              <p className="font-medium text-ink">{cost.label}</p>
              {cost.value ? (
                <p className="text-meta text-ink-muted">
                  {costValue(cost)} · {cost.source_note ?? "—"}
                  {cost.effective_from ? ` · from ${formatIST(cost.effective_from)}` : ""}
                </p>
              ) : (
                <p className="text-meta font-medium text-warn">Not recorded — left out of costs</p>
              )}
            </div>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!access.allowed || attest.isPending}
              title={access.reason ?? undefined}
              onClick={() => {
                setEditing(cost);
                setValue("");
                setSource("");
                valid.reset();
              }}
            >
              {cost.value ? "Record a new figure" : "Record a figure"}
            </button>
          </li>
        ))}
      </ul>

      {attest.error && <WriteFailure error={attest.error} actionLabel="Record the figure" />}

      {editing && (
        <form
          className="space-y-3"
          noValidate
          onSubmit={valid.onSubmit(() => {
            attest.mutate(
              { subject: editing.subject, value: value.trim(), sourceNote: source.trim() },
              { onSuccess: () => setEditing(null) },
            );
          })}
        >
          <p className="text-body font-medium text-ink">{editing.label}</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block">
              <span className={FIELD_LABEL}>
                {editing.unit === "percent" ? "Percent" : "Rupees a month"}
              </span>
              <input
                {...valid.field(
                  "cost_value",
                  editing.unit === "percent"
                    ? "Enter a percentage, like 2.36."
                    : "Enter rupees a month, like 349.00.",
                )}
                required
                inputMode="decimal"
                pattern={editing.unit === "percent" ? PERCENT : RUPEES_PER_MIN}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                disabled={!access.allowed}
                className={`${FIELD} font-mono`}
              />
              {valid.error("cost_value")}
            </label>
            <label className="block sm:col-span-2">
              <span className={FIELD_LABEL}>Read from</span>
              <input
                {...valid.field("cost_source", "Name the invoice or statement (at least 3 characters).")}
                required
                minLength={3}
                maxLength={500}
                value={source}
                onChange={(e) => setSource(e.target.value)}
                disabled={!access.allowed}
                className={FIELD}
              />
              {valid.error("cost_source")}
              <span className={FIELD_HINT}>The invoice or statement, and its date.</span>
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              disabled={!access.allowed || attest.isPending}
              className={PRIMARY_BUTTON}
            >
              {attest.isPending ? "Recording…" : "Record the figure"}
            </button>
            <button
              type="button"
              disabled={attest.isPending}
              onClick={() => {
                setEditing(null);
                valid.reset();
              }}
              className={SECONDARY_BUTTON}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
