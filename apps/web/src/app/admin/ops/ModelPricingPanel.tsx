"use client";

import { useState } from "react";

import {
  WithheldPanel,
  forbiddenReason,
  isForbidden,
} from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import {
  BadgeCheck,
  CircleHelp,
  Coins,
  Save,
  TriangleAlert,
} from "lucide-react";

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
import { useFormValidation } from "@/components/formValidation";
import {
  MonoValue,
  TypeToConfirm,
  confirmMatches,
} from "@/app/admin/ops/opsLanguage";
import {
  useAttestTtsPrice,
  type TtsPrice,
} from "@/lib/api/opsTtsPricing";
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
  // The two VOICE vendors. Same table, because the question a reader has is the same one
  // ("whose invoice is this?") and two tables would be two spellings of "Cartesia".
  sarvam: "Sarvam",
  cartesia: "Cartesia",
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
          The price per million tokens that billing charges for each model, in
          US dollars. Enter what your own vendor invoice or dashboard says —
          that figure is the only one that&apos;s true for your account. A model
          becomes available to customers only once its vendor key is installed
          and its price is confirmed.
        </p>

        {query.error && (
          <ProblemNotice error={query.error} onRetry={() => query.refetch()} />
        )}
        {state.status === "loading" && <Skeleton rows={4} />}

        {state.status === "unreadable" && (
          <NoticeBox
            tone="warn"
            icon={<CircleHelp aria-hidden className="h-5 w-5" />}
            title="We could not read the model prices"
          >
            <p className="mt-1">
              This panel will not show invented figures when it could not read
              the real ones — billing from a guessed price is the mistake that
              would cause. The error above says what stopped the read.
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

        {/* THE VOICE LEG, on the same panel and for the same reason (D-547): a price an
            operator reads off their own invoice is one act whichever vendor sold it, and
            splitting the two would leave the newer one somewhere nobody looks. It is read
            from the SAME payload — an API that does not publish it yet renders a stated
            absence, never an empty table that reads as "no voices are priced". */}
        {state.status === "read" && (
          <TtsPricesSection rows={state.list.tts_prices} access={access} />
        )}
      </div>
    </Card>
  );
}

/** The one-line "can customers use this?" verdict, and the tone it renders in. */
function verdict(price: ModelPrice): {
  label: string;
  tone: "ok" | "warn" | "neutral";
} {
  if (price.offerable) return { label: "Available to customers", tone: "ok" };
  // MERIT FIRST. "Needs a vendor key and a price" is a to-do list, and printing one for a
  // model this repository refuses on merit reads as three steps from available when it is
  // not reachable at all. `neutral`, not `warn`: nothing here is wrong or waiting on
  // anybody — the decision was taken, and the row below carries its ground.
  if (price.withheld_reason != null)
    return { label: "Not offered", tone: "neutral" };
  const missing: string[] = [];
  if (!price.credential_installed) missing.push("a vendor key");
  // Billable == confirmed OR the catalogue figure is a first-hand vendor reading. So a model
  // that is not available and not confirmed needs a price ONLY when its recorded price is
  // not verified; when the recorded price IS verified the sole gap is the vendor key.
  if (!price.price_attested && !price.reference_verified)
    missing.push("a price");
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
    v.tone === "ok"
      ? "text-brand"
      : v.tone === "warn"
        ? "text-amber-600"
        : "text-ink-faint";

  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm text-ink">
            <MonoValue>{price.model}</MonoValue>
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">
            {providerLabel(price.provider)}
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1 text-xs font-medium ${toneClass}`}
        >
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
              <MonoValue>{price.reference_input_usd_per_mtok}</MonoValue>{" "}
              (recorded)
            </span>
          )}
        </dd>
        <dt className="text-ink-faint">
          Output price (US$ per million tokens)
        </dt>
        <dd className="text-ink">
          {price.output_usd_per_mtok ? (
            <MonoValue>{price.output_usd_per_mtok}</MonoValue>
          ) : (
            <span className="text-ink-faint">
              <MonoValue>{price.reference_output_usd_per_mtok}</MonoValue>{" "}
              (recorded)
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

      {/* WITHHELD ON MERIT COMES FIRST, and it replaces the price sentence rather than
          joining it. Without this the screen told the founder that `gemini-3.1-flash-lite`
          "becomes available to customers only once you confirm a price" — which is false
          however carefully the price is attested, because `LlmModelSpec.selectable` refuses
          it regardless. It invited work that cannot succeed AND hid the reason it cannot:
          on that family, thinking tokens draw on the reply budget with no knob to set, and
          the engine's terminal branch yields nothing — silence, mid-call.

          The catalogue's own words, not a paraphrase: these grounds cite vendor enums and
          engine line numbers, and a screen that summarised them would be the version people
          argue with. */}
      {price.withheld_reason != null ? (
        <div className="mt-2 rounded-lg border border-line bg-app px-3 py-2">
          <p className="text-xs font-medium text-ink">
            Not offered on this platform — a price will not change that
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-muted">
            {price.withheld_reason}
          </p>
        </div>
      ) : (
        !price.price_attested && (
          <p className="mt-2 text-xs text-ink-faint">
            {price.reference_verified
              ? "This model already has a recorded price from the vendor, so confirming it yourself is optional."
              : "This model becomes available to customers only once you confirm a price. The recorded price above is unverified — check it against your vendor invoice first."}
          </p>
        )
      )}

      {access.allowed ? (
        <div className="mt-3">
          {open ? (
            <AttestForm price={price} onDone={() => setOpen(false)} />
          ) : (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setOpen(true)}
            >
              <Coins aria-hidden className="h-3.5 w-3.5" />
              {price.price_attested ? "Update price" : "Confirm price"}
            </button>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-faint">
          {access.reason ??
            "Your admin account cannot change platform configuration."}
        </p>
      )}
    </div>
  );
}

function AttestForm({
  price,
  onDone,
}: {
  price: ModelPrice;
  onDone: () => void;
}) {
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
  const valid = useFormValidation();
  // The three answers moved OUT of `ready` and onto the controls, where a press can say
  // which one is missing. A button that goes dead because a box three rows up is empty is
  // a refusal with no words in it. What stays is the typed confirmation — a gate, not an
  // answer on the form.
  const ready = confirmMatches(confirm, word);

  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={valid.onSubmit(() => {
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
      })}
    >
      {save.error && <WriteFailure error={save.error} actionLabel="Confirm price" />}

      <label className="block">
        <span className={FIELD_LABEL}>
          Input price (US$ per million tokens)
        </span>
        <input
          {...valid.field("inputUsd", "Enter the input price you were billed.")}
          required
          value={inputUsd}
          onChange={(e) => setInputUsd(e.target.value)}
          // `text`, not `number`: a number input hands JS a float, and money must reach the
          // server as the exact string that was typed.
          inputMode="decimal"
          placeholder={`${price.reference_input_usd_per_mtok} (recorded — check against your invoice)`}
          className={`${FIELD} font-mono`}
        />
        {valid.error("inputUsd")}
        <span className={FIELD_HINT}>
          {price.reference_verified
            ? "This recorded price came directly from the vendor."
            : "This recorded price is unverified — the vendor's page can't be reached from here."}
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>
          Output price (US$ per million tokens)
        </span>
        <input
          {...valid.field("outputUsd", "Enter the output price you were billed.")}
          required
          value={outputUsd}
          onChange={(e) => setOutputUsd(e.target.value)}
          inputMode="decimal"
          placeholder={`${price.reference_output_usd_per_mtok} (recorded — check against your invoice)`}
          className={`${FIELD} font-mono`}
        />
        {valid.error("outputUsd")}
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Source</span>
        <input
          {...valid.field("sourceNote", "Say where you read this figure.")}
          required
          minLength={3}
          value={sourceNote}
          onChange={(e) => setSourceNote(e.target.value)}
          placeholder="e.g. Azure invoice 2026-08, or openai.com/api/pricing read today"
          className={FIELD}
        />
        {valid.error("sourceNote")}
        <span className={FIELD_HINT}>
          Where you read this figure. Saved with your confirmed price, so a
          later reader knows who read it and from where.
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
        <button
          type="submit"
          disabled={!ready || save.isPending}
          className={PRIMARY_BUTTON_SM}
        >
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

/**
 * VOICE (TTS) PRICES — the leg where an unattested price BLOCKS A TIER rather than merely
 * looking empty.
 *
 * ## Why this section says something stronger than the model rows above it
 *
 * A language model with no attested price is one model a client cannot choose. A VOICE with
 * no attested price is a whole product tier that cannot be sold — and the failure mode if
 * we shipped it anyway is worse than an unavailable option, because the vendor bills us
 * directly under BYOK and the engine reports the synthesizer leg as ₹0. Every Cartesia
 * minute would then meter as free and the margin board would show a profit that does not
 * exist (`ops/model_pricing.tts_price_is_billable` is the one door; hard rule 7).
 *
 * ## The vendor is named, deliberately
 *
 * No client-facing surface names a vendor as a product tier — they read "Clear" and
 * "Studio". THIS SCREEN IS THE EXCEPTION and it must be: an operator typing a figure off a
 * Cartesia invoice, or installing a Cartesia key next door, needs to know which of the two
 * names on the row is the one their invoice is headed with. Both are printed, and the tier
 * label crosses the wire rather than being spelled again here.
 */
function TtsPricesSection({
  rows,
  access,
}: {
  rows: readonly TtsPrice[];
  access: { allowed: boolean; reason: string | null };
}) {
  return (
    <section className="space-y-2 border-t border-line pt-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Voice prices</h3>
        <p className="text-xs text-ink-faint">
          What 1,000 spoken characters cost us on each voice, in rupees. On a monthly plan
          this is the plan&apos;s marginal rate — the committed spend divided by the
          characters it buys — which only you, holding the invoice, can work out.
        </p>
      </div>

      {rows.length === 0 ? (
        // NOT a zero, and this branch is KEPT rather than deleted with the validator it
        // used to serve. `ModelPricesOut.tts_prices` is required now, so a well-behaved
        // server always sends both voices and this is unreachable through it — but an
        // empty list is a cheap net against a server regression, and the thing it prevents
        // is a section that renders as a confident nothing. "We do not know" and "no voice
        // costs anything" are opposite claims (§52, hard rule 11), and the second is the
        // one that gets a Cartesia minute metered as free.
        <NoticeBox
          tone="warn"
          icon={<CircleHelp aria-hidden className="h-5 w-5" />}
          title="This deployment did not send any voice prices"
        >
          <p className="mt-1">
            Nothing is shown rather than a table of guessed figures. A voice whose price is
            not confirmed cannot be sold at all — every minute on it would meter as costing
            nothing — so treat this as unknown, not as free.
          </p>
        </NoticeBox>
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => (
            <li key={row.provider}>
              <TtsPriceRow price={row} access={access} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The one-line verdict for a voice, and why it is not the model row's verdict. */
export function ttsVerdict(price: TtsPrice): { label: string; tone: "ok" | "warn" } {
  if (price.offerable) return { label: "On sale to customers", tone: "ok" };
  const missing: string[] = [];
  if (!price.credential_installed) missing.push("a vendor key");
  if (!price.price_billable) missing.push("a confirmed price");
  if (missing.length === 0) return { label: "Not on sale", tone: "warn" };
  return { label: `Blocked — needs ${missing.join(" and ")}`, tone: "warn" };
}

function TtsPriceRow({
  price,
  access,
}: {
  price: TtsPrice;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  const v = ttsVerdict(price);

  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          {/* VENDOR, then the tier the client reads, then the synthesizer model. Three
              facts an operator needs together: whose invoice, which product, which model
              id the engine is actually asked for. */}
          <p className="text-sm text-ink">
            {providerLabel(price.provider)} · {price.tier_label}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">
            <MonoValue>{price.tts_model}</MonoValue>
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1 text-xs font-medium ${
            v.tone === "ok" ? "text-brand" : "text-amber-600"
          }`}
        >
          {v.tone === "ok" ? (
            <BadgeCheck aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
          )}
          {v.label}
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-ink-faint">Price (₹ per 1,000 characters)</dt>
        <dd className="text-ink">
          {price.inr_per_1k_chars ? (
            <MonoValue>{price.inr_per_1k_chars}</MonoValue>
          ) : (
            <span className="text-ink-faint">not confirmed</span>
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

      {/* THE CONSEQUENCE, NOT THE GAP. "No price yet" is a blank; this is what the blank
          does — the voice cannot be offered, and if it somehow were, its minutes would
          meter at nothing. A leg that needs no attestation says WHY in the server's words
          rather than looking like an oversight. */}
      {price.billable_without_attestation_reason ? (
        <p className="mt-2 text-xs text-ink-faint">
          {price.billable_without_attestation_reason}
        </p>
      ) : !price.price_attested ? (
        <div className="mt-2 rounded-lg border border-line bg-app px-3 py-2">
          <p className="text-xs font-medium text-ink">
            This voice cannot be sold until its price is confirmed
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-muted">
            We pay {providerLabel(price.provider)} directly for this voice, so the call
            platform reports its cost as ₹0. Without your figure every minute on it would be
            metered as free and the margin board would show a profit that is not there —
            which is why the voice picker refuses the tier by name instead.
          </p>
        </div>
      ) : null}

      {access.allowed ? (
        <div className="mt-3">
          {open ? (
            <AttestTtsForm price={price} onDone={() => setOpen(false)} />
          ) : (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setOpen(true)}
            >
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

function AttestTtsForm({ price, onDone }: { price: TtsPrice; onDone: () => void }) {
  const [inr, setInr] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [confirm, setConfirm] = useState("");

  const save = useAttestTtsPrice();
  const word = "CONFIRM";
  const valid = useFormValidation();
  const ready = confirmMatches(confirm, word);

  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (!ready || save.isPending) return;
        save.mutate(
          {
            provider: price.provider,
            // The exact string typed — no Number(), no rounding (hard rule 7). ₹3.4496 is
            // four decimals of a division somebody did against an invoice.
            inrPer1kChars: inr.trim(),
            sourceNote: sourceNote.trim(),
          },
          { onSuccess: onDone },
        );
      })}
    >
      {save.error && <WriteFailure error={save.error} actionLabel="Confirm price" />}

      <label className="block">
        <span className={FIELD_LABEL}>Price (₹ per 1,000 characters)</span>
        <input
          {...valid.field("inrPer1k", "Enter the rate your plan works out to.")}
          required
          value={inr}
          onChange={(e) => setInr(e.target.value)}
          inputMode="decimal"
          className={`${FIELD} font-mono`}
        />
        {valid.error("inrPer1k")}
        <span className={FIELD_HINT}>
          On a monthly plan: the committed spend divided by the characters it buys. Characters
          beyond the allotment cost whatever the vendor&apos;s overage rate is, which we have
          not read anywhere — so name the plan and the period below.
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Source</span>
        <input
          {...valid.field("ttsSourceNote", "Say where this figure came from.")}
          required
          minLength={3}
          value={sourceNote}
          onChange={(e) => setSourceNote(e.target.value)}
          placeholder="e.g. Cartesia Startup plan, Sep 2026 invoice: ₹4,312 ÷ 1.25M chars"
          className={FIELD}
        />
        {valid.error("ttsSourceNote")}
      </label>

      <TypeToConfirm
        id={`confirm-tts-price-${price.provider}`}
        word={word}
        value={confirm}
        onChange={setConfirm}
        hint="A correction is added as a new entry — nothing is overwritten — so a past month still resolves the price that was live in it."
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
