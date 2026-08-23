"use client";

import { useState } from "react";

import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import { BadgeCheck, CircleHelp, Coins, Save, TriangleAlert } from "lucide-react";

import { lookup } from "@/lib/lookup";
import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { MonoValue, TypeToConfirm, confirmMatches } from "@/app/admin/ops/opsLanguage";
import {
  useAttestModelPrice,
  useModelPrices,
  type ModelPrice,
  type ModelPrices,
} from "@/lib/api/opsModelPricing";

/**
 * Vendor names as a person says them, from the machine value on the wire.
 *
 * `provider` arrives as `azure_openai` / `openai` / `google` — the catalogue's own leg
 * ids. The operator reads "Azure OpenAI", not a snake_case token. `lookup`, not a bare
 * index, so a value naming an `Object.prototype` member cannot resolve to a function
 * (the trap `StatusBadge` records); an unknown leg falls back to its own spelling with
 * the underscores opened out.
 */
const PROVIDER_LABELS: Record<string, string> = {
  azure_openai: "Azure OpenAI",
  openai: "OpenAI",
  google: "Google",
};

function providerLabel(provider: string): string {
  return lookup(PROVIDER_LABELS, provider) ?? provider.replace(/_/g, " ");
}

/**
 * Model prices — PLATFORM-CONFIG §5: the founder types the AUTHORITATIVE billing price for
 * each model, read off their own vendor console or invoice.
 *
 * ## Why this panel exists
 *
 * Hard rule 7 has no REPORTED tier: a price is the one vendor claim that reaches
 * `unit_cost_paid`, so the engine's catalogue refuses to make a model selectable on an
 * unverified price. Every OpenAI and Google pricing page is egress-blocked from this
 * deployment, so those two legs can never be VERIFIED in the tree — the only price true for
 * this account is the one the operator reads off their invoice and attests here. Azure is
 * the exception: D-410 read its price first-hand, so it is offerable with no attestation
 * (`reference_verified`), and this panel says so rather than demanding a redundant one.
 *
 * ## Money is a string, end to end
 *
 * Every price rendered here is the server's decimal STRING, printed verbatim — never
 * `Number()`d. A per-token price through a JS float is a rounding error four decimals deep
 * in every minute billed (hard rule 7). The reference figure is shown GREYED as a pre-fill
 * to confirm against the invoice, never as the value.
 *
 * ## The three states, and why there is no fourth (BUILD-LOG §52)
 *
 * loading is a skeleton, unreadable is a refusal with NO rows (a price table rendered from
 * a failed read would show invented figures an operator would act on), and read is the
 * server's own rows. forbidden is the fourth of the same family — the server answered "not
 * you" — rendered as a withheld panel.
 */

type PricingState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "forbidden"; said: string | null }
  | { status: "read"; list: ModelPrices };

export function modelPricingState(query: {
  data: ModelPrices | undefined;
  error: unknown;
  isLoading: boolean;
}): PricingState {
  if (isForbidden(query.error)) {
    return { status: "forbidden", said: forbiddenReason(query.error) };
  }
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", list: query.data };
}

export function ModelPricingPanel({
  access,
}: {
  access: { allowed: boolean; reason: string | null };
}) {
  const query = useModelPrices();
  const state = modelPricingState(query);

  if (state.status === "forbidden") {
    return (
      <WithheldPanel
        title="Model prices"
        reason={
          state.said ??
          "The API refused this read: your admin account may not manage platform configuration."
        }
        subject="This panel would list every model, its provider and the per-million-token price billing uses."
      />
    );
  }

  return (
    <Card title="Model prices">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          The price per million tokens that billing charges for each model, in US dollars.
          Enter what your own vendor invoice or dashboard says — that figure is the only one
          that&apos;s true for your account. A model becomes available to customers only once
          its vendor key is installed and its price is confirmed.
        </p>

        {query.error && <ProblemNotice error={query.error} onRetry={() => query.refetch()} />}
        {state.status === "loading" && <Skeleton rows={4} />}

        {state.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We could not read the model prices"
          >
            <p className="mt-1">
              This panel will not show invented figures when it could not read the real
              ones — billing from a guessed price is the mistake that would cause. The error
              above says what stopped the read.
            </p>
          </NoticeBox>
        )}

        {state.status === "read" && (
          <ul className="space-y-2">
            {state.list.prices.map((price) => (
              <li key={price.model}>
                <ModelPriceRow price={price} access={access} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

/** The one-line "can customers use this?" verdict, and the tone it renders in. */
function verdict(price: ModelPrice): { label: string; tone: "ok" | "warn" | "neutral" } {
  if (price.offerable) return { label: "Available to customers", tone: "ok" };
  const missing: string[] = [];
  if (!price.credential_installed) missing.push("a vendor key");
  // Billable == confirmed OR the catalogue figure is a first-hand vendor reading. So a model
  // that is not available and not confirmed needs a price ONLY when its recorded price is
  // not verified; when the recorded price IS verified the sole gap is the vendor key.
  if (!price.price_attested && !price.reference_verified) missing.push("a price");
  return { label: `Needs ${missing.join(" and ")}`, tone: "warn" };
}

function ModelPriceRow({
  price,
  access,
}: {
  price: ModelPrice;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  const v = verdict(price);
  const toneClass =
    v.tone === "ok" ? "text-brand" : v.tone === "warn" ? "text-amber-600" : "text-ink-faint";

  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm text-ink">
            <MonoValue>{price.model}</MonoValue>
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">{providerLabel(price.provider)}</p>
        </div>
        <span className={`inline-flex items-center gap-1 text-xs font-medium ${toneClass}`}>
          {price.offerable ? (
            <BadgeCheck aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
          )}
          {v.label}
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-ink-faint">Input price (US$ per million tokens)</dt>
        <dd className="text-ink">
          {/* The confirmed figure as an exact string; the recorded price greyed when
              there is no confirmed one yet. Never Number()d. */}
          {price.input_usd_per_mtok ? (
            <MonoValue>{price.input_usd_per_mtok}</MonoValue>
          ) : (
            <span className="text-ink-faint">
              <MonoValue>{price.reference_input_usd_per_mtok}</MonoValue> (recorded)
            </span>
          )}
        </dd>
        <dt className="text-ink-faint">Output price (US$ per million tokens)</dt>
        <dd className="text-ink">
          {price.output_usd_per_mtok ? (
            <MonoValue>{price.output_usd_per_mtok}</MonoValue>
          ) : (
            <span className="text-ink-faint">
              <MonoValue>{price.reference_output_usd_per_mtok}</MonoValue> (recorded)
            </span>
          )}
        </dd>
        {price.attested_at && (
          <>
            <dt className="text-ink-faint">Confirmed</dt>
            <dd className="text-ink">
              {formatIST(price.attested_at)}
              {price.attested_by ? ` · ${price.attested_by}` : ""}
            </dd>
          </>
        )}
        {price.source_note && (
          <>
            <dt className="text-ink-faint">Source</dt>
            <dd className="text-ink">{price.source_note}</dd>
          </>
        )}
      </dl>

      {!price.price_attested && (
        <p className="mt-2 text-xs text-ink-faint">
          {price.reference_verified
            ? "This model already has a recorded price from the vendor, so confirming it yourself is optional."
            : "This model becomes available to customers only once you confirm a price. The recorded price above is unverified — check it against your vendor invoice first."}
        </p>
      )}

      {access.allowed ? (
        <div className="mt-3">
          {open ? (
            <AttestForm price={price} onDone={() => setOpen(false)} />
          ) : (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(true)}>
              <Coins aria-hidden className="h-3.5 w-3.5" />
              {price.price_attested ? "Update price" : "Confirm price"}
            </button>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-faint">
          {access.reason ?? "Your admin account cannot change platform configuration."}
        </p>
      )}
    </div>
  );
}

function AttestForm({ price, onDone }: { price: ModelPrice; onDone: () => void }) {
  const [inputUsd, setInputUsd] = useState("");
  const [outputUsd, setOutputUsd] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [confirm, setConfirm] = useState("");

  const save = useAttestModelPrice();
  // The word the operator TYPES to arm the save — a clean, short word rather than the raw
  // step-up string the API checks. The real confirmation (`attest_model_price:<model>`)
  // still goes on the wire, set inside `useAttestModelPrice`; conflating the two is how a
  // copy change would quietly become an API change.
  const word = "CONFIRM";
  const ready =
    inputUsd.trim().length > 0 &&
    outputUsd.trim().length > 0 &&
    sourceNote.trim().length >= 3 &&
    confirmMatches(confirm, word);

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || save.isPending) return;
        save.mutate(
          {
            model: price.model,
            // The exact strings the operator typed — no Number(), no rounding (hard rule 7).
            inputUsdPerMtok: inputUsd.trim(),
            outputUsdPerMtok: outputUsd.trim(),
            sourceNote: sourceNote.trim(),
          },
          { onSuccess: onDone },
        );
      }}
    >
      {save.error && <WriteFailure error={save.error} />}

      <label className="block">
        <span className={FIELD_LABEL}>Input price (US$ per million tokens)</span>
        <input
          value={inputUsd}
          onChange={(e) => setInputUsd(e.target.value)}
          // `text`, not `number`: a number input hands JS a float, and money must reach the
          // server as the exact string that was typed.
          inputMode="decimal"
          placeholder={`${price.reference_input_usd_per_mtok} (recorded — check against your invoice)`}
          className={`${FIELD} font-mono`}
        />
        <span className={FIELD_HINT}>
          {price.reference_verified
            ? "This recorded price came directly from the vendor."
            : "This recorded price is unverified — the vendor's page can't be reached from here."}
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Output price (US$ per million tokens)</span>
        <input
          value={outputUsd}
          onChange={(e) => setOutputUsd(e.target.value)}
          inputMode="decimal"
          placeholder={`${price.reference_output_usd_per_mtok} (recorded — check against your invoice)`}
          className={`${FIELD} font-mono`}
        />
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Source</span>
        <input
          value={sourceNote}
          onChange={(e) => setSourceNote(e.target.value)}
          placeholder="e.g. Azure invoice 2026-08, or openai.com/api/pricing read today"
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          Where you read this figure. Saved with your confirmed price, so a later reader
          knows who read it and from where.
        </span>
      </label>

      <TypeToConfirm
        id={`confirm-price-${price.model}`}
        word={word}
        value={confirm}
        onChange={setConfirm}
        hint="A correction is added as a new entry — nothing is overwritten — so a re-issued invoice can always resolve the price that was live in its month."
      />

      <div className="flex gap-2">
        <button type="submit" disabled={!ready || save.isPending} className={PRIMARY_BUTTON_SM}>
          <Save aria-hidden className="h-3.5 w-3.5" />
          {save.isPending ? "Saving…" : "Confirm price"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
