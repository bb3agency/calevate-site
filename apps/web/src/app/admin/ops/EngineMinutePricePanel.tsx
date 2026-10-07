"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert, Lock } from "lucide-react";

import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useFormValidation } from "@/components/formValidation";
import {
  Card,
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
  useAttestEngineMinutePrice,
  useEngineMinutePrices,
  type EngineMinutePrice,
} from "@/lib/api/engineMinutePricing";
import { lookup } from "@/lib/lookup";

type Access = { allowed: boolean; reason: string | null };

/** Rupees per minute: positive, at most six decimals. The server re-checks. */
const RUPEES_PER_MIN = "^(?:0*[1-9]\\d{0,5}(?:\\.\\d{1,6})?|0*\\.\\d{0,5}[1-9]\\d{0,5})$";

const ENGINE_LABELS: Record<string, string> = { thinnest: "ThinnestAI" };
const KEY_LABELS: Record<string, string> = {
  platform: "Platform minute (telephony included)",
  standard: "Voice band: standard",
  premium: "Voice band: premium",
  studio: "Voice band: studio",
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
  const platformUnpriced = Boolean(
    rows?.some((row) => row.rate_key === "platform" && !row.billable),
  );

  return (
    <Card title="Per-minute rates">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          What a billed minute costs this account on a voice platform that reports no cost
          for a call. Calls are billed in 30-second steps. Type the figure from your own
          invoice or plan page.
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
            icon={<CircleAlert aria-hidden className="h-5 w-5" />}
            title="No platform rate recorded — no minute on it can be sold"
          >
            <p className="mt-1">
              Until the platform minute is recorded, no agent on that platform is offered and
              any call that runs is metered with no cost and raises an alarm.
            </p>
          </NoticeBox>
        )}

        {rows && rows.length > 0 && (
          <ul className="divide-y divide-line rounded-card border border-line">
            {rows.map((row) => (
              <li key={rowId(row)} className="flex flex-wrap items-start gap-3 px-3 py-2.5 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-ink">
                    {lookup(ENGINE_LABELS, row.engine) ?? row.engine} ·{" "}
                    {lookup(KEY_LABELS, row.rate_key) ?? row.rate_key}
                  </p>
                  <p className="text-xs text-ink-muted">{saleNote(row)}</p>
                  {row.inr_per_min ? (
                    <p className="text-xs text-ink-muted">
                      {formatRupeeRate(row.inr_per_min)} per minute · {row.source_note ?? "—"}
                      {row.attested_at ? ` · recorded ${formatIST(row.attested_at)}` : ""}
                    </p>
                  ) : (
                    <p className="text-xs font-medium text-amber-700 dark:text-amber-400">
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
          <p className="flex items-start gap-2 text-sm text-ink-muted">
            <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
            <span>Recorded. Minutes from now on are metered at this rate.</span>
          </p>
        )}

        {!access.allowed && access.reason && (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
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
            <p className="text-sm font-medium text-ink">
              {lookup(ENGINE_LABELS, editing.engine) ?? editing.engine} ·{" "}
              {lookup(KEY_LABELS, editing.rate_key) ?? editing.rate_key}
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
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
      </div>
    </Card>
  );
}
