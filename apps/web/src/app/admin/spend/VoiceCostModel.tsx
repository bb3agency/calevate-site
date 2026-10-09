"use client";

import {
  Disclosure,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatINR,
  formatRupeeRate,
} from "@/components/ui";
import {
  useTtsSpeakingRate,
  type FleetSpend,
  type SpeakingRatePoint,
  type TtsSpeakingRate,
} from "@/lib/api/spend";

import { vendorName, type SpeakingRateByProvider, type TtsPlanSpend } from "./ttsCost";

/**
 * THE PLATFORM'S VOICE COST MODEL — a different question from the client table above
 * ("what does a minute of speech cost us" rather than "which client is losing money"), so it
 * is disclosed beneath the board with its headline fact in the closed state.
 *
 * Two reads, kept apart: the vendors' monthly bills (inside the board's month, because a plan
 * fee IS a month) and the measured speaking rate (the whole transcript archive, its own read,
 * so a failed fleet walk does not hide it nor the reverse).
 */
export function VoiceCostModel({ board }: { board: FleetSpend | undefined }) {
  const query = useTtsSpeakingRate();
  const rate = query.data;
  const subtitle = query.error
    ? "The speaking rate could not be read."
    : !rate
      ? "Reading every client's transcripts…"
      : rate.measured
        ? `Speaking rate measured from ${formatCount(rate.calls)} calls across ${formatCount(rate.clients)} ${rate.clients === 1 ? "client" : "clients"}.`
        : `Speaking rate not measured yet: ${formatCount(rate.calls)} of ${formatCount(rate.minimum_calls)} calls needed.`;

  return (
    <Disclosure title="Voice cost model" subtitle={subtitle}>
      <div className="space-y-6">
        <TtsPlanSection board={board} />
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-ink">TTS speaking rate — measured</h3>
          {query.error ? (
            <ProblemNotice error={query.error} onRetry={() => void query.refetch()} />
          ) : !rate ? (
            <Skeleton rows={3} label="Reading every client's transcripts" />
          ) : (
            <SpeakingRate rate={rate} />
          )}
        </section>
      </div>
    </Disclosure>
  );
}

/**
 * PLAN SPEND vs ATTRIBUTED. Under BYOK a Cartesia call's cost is the attested ₹ per 1,000
 * characters times the characters our transcripts say the agent spoke — ATTRIBUTED, the
 * figure the client table is built from. The vendor meanwhile bills a monthly PLAN whether
 * or not anybody speaks; it belongs to the platform, and folding it into the fleet margin
 * would add cost with no matching revenue. The gap is the SERVER's subtraction.
 */
function TtsPlanSection({ board }: { board: FleetSpend | undefined }) {
  if (board === undefined) return null;
  // An empty list and a missing field are ONE absence: the API omits a vendor's row rather
  // than sending a zero fee, and an API older than Phase D.3 sends no `tts_plan` at all.
  const rows = board.tts_plan?.length ? board.tts_plan : null;
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-ink">
        Voice vendors — plan spend against attributed
      </h3>
      {rows === null ? (
        // "No plan spend was published" is not "the voices cost us nothing".
        <p className="text-sm text-ink-muted">
          This deployment did not publish what the voice vendors billed, so
          nothing is shown rather than a zero. The client figures above are
          unaffected — they are what the calls were charged; this card is what
          we paid the vendor for the month.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li key={row.provider} className="py-3 first:pt-0 last:pb-0">
              <TtsPlanRow row={row} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TtsPlanRow({ row }: { row: TtsPlanSpend }) {
  return (
    <div>
      {/* VENDOR FIRST: an operator reconciling this holds an invoice with the vendor's name
          at the top of it. */}
      <p className="text-sm font-medium text-ink">
        {vendorName(row.provider)} · {row.tier_label} · {row.month}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-ink-faint">Plan spend</dt>
          <dd className="tabular-nums text-ink">{formatINR(row.plan_inr)}</dd>
        </div>
        <div>
          <dt className="text-ink-faint">Attributed to calls</dt>
          <dd className="tabular-nums text-ink">{formatINR(row.attributed_inr)}</dd>
        </div>
        <div>
          <dt className="text-ink-faint">Allotment unused</dt>
          {/* The SERVER's subtraction; "—" where it sent none. */}
          <dd className="tabular-nums text-ink-muted">
            {row.unused_inr === null ? "—" : formatINR(row.unused_inr)}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">Characters spoken</dt>
          <dd className="tabular-nums text-ink-muted">{row.chars}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-ink-faint">
        {row.inr_per_1k_chars
          ? `Attributed at the confirmed ${formatRupeeRate(row.inr_per_1k_chars)} per 1,000 characters, counted from our own transcripts.`
          : "No price is confirmed for this vendor, so its calls attribute no cost at all — confirm the price on the ops model-prices panel before reading this row as a margin."}
      </p>
    </div>
  );
}

/** A chars-per-minute figure as the server spelled it, trailing zeros dropped — string
 * surgery, never `Number()`, the digits are the server's. */
function trimRate(value: string): string {
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

function RatePoint({ point }: { point: SpeakingRatePoint }) {
  return (
    <>
      <span className="font-semibold tabular-nums text-ink">
        {trimRate(point.chars_per_minute)}
      </span>{" "}
      chars/min → {formatRupeeRate(point.tts_inr_per_minute)}/min
    </>
  );
}

/**
 * THE TTS SPEAKING RATE (pilot gate 12, TRD §10.1). TRD §10.1 prices the TTS leg from an
 * ASSUMED 360–540 chars per call-minute; this is the measurement. BELOW THE THRESHOLD THERE
 * IS NO FIGURE: the server sends `measured: false` with the sample size, and a rate from
 * three calls printed as "measured" would be a hard-rule-11 failure. The assumed band is
 * printed in both states, labelled as what it is.
 */
function SpeakingRate({ rate }: { rate: TtsSpeakingRate }) {
  if (rate.measured && rate.p50 && rate.p95 && rate.pooled) {
    return (
      <div className="space-y-3 text-sm text-ink-muted">
        <p>
          <span className="font-semibold text-ink">{formatCount(rate.calls)}</span> calls with a
          transcript across{" "}
          <span className="font-semibold text-ink">{formatCount(rate.clients)}</span>{" "}
          {rate.clients === 1 ? "client" : "clients"}, priced at{" "}
          {formatRupeeRate(rate.tts_inr_per_10k_chars)} per 10,000 characters.
        </p>
        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-3">
          <div>
            <dt className="text-[13px] font-medium">Pooled (Σ chars ÷ Σ minutes)</dt>
            <dd>
              <RatePoint point={rate.pooled} />
            </dd>
          </div>
          <div>
            <dt className="text-[13px] font-medium">Typical call (p50)</dt>
            <dd>
              <RatePoint point={rate.p50} />
            </dd>
          </div>
          <div>
            <dt className="text-[13px] font-medium">Talkative tail (p95)</dt>
            <dd>
              <RatePoint point={rate.p95} />
            </dd>
          </div>
        </dl>
        <SpeakingRateByVendor rate={rate} />
        <p>
          Replaces the assumed {trimRate(rate.assumed_low.chars_per_minute)}–
          {trimRate(rate.assumed_high.chars_per_minute)} chars/min (
          {formatRupeeRate(rate.assumed_low.tts_inr_per_minute)}–
          {formatRupeeRate(rate.assumed_high.tts_inr_per_minute)}/min) used in the cost model.
        </p>
        <FleetFloorLine rate={rate} />
      </div>
    );
  }
  return (
    <div className="space-y-3 text-sm text-ink-muted">
      <p>
        <span className="font-semibold text-ink">Not enough calls to measure yet:</span>{" "}
        {formatCount(rate.calls)} of {formatCount(rate.minimum_calls)} needed
        {rate.clients > 0
          ? ` (across ${formatCount(rate.clients)} ${rate.clients === 1 ? "client" : "clients"})`
          : ""}
        .
      </p>
      {rate.reason && <p>{rate.reason}</p>}
      {/* Whether a voice has a confirmed price is not a measurement and does not wait on one. */}
      <SpeakingRateByVendor rate={rate} />
      <p>
        Until then the cost floor rests on the assumed{" "}
        {trimRate(rate.assumed_low.chars_per_minute)}–
        {trimRate(rate.assumed_high.chars_per_minute)} chars/min (
        {formatRupeeRate(rate.assumed_low.tts_inr_per_minute)}–
        {formatRupeeRate(rate.assumed_high.tts_inr_per_minute)}/min), which
        is an assumption and not a reading.
      </p>
      <FleetFloorLine rate={rate} />
    </div>
  );
}

/**
 * THE FIGURE THE COST MODEL ACTUALLY DIVIDES BY, AND THE FLOOR IT PRODUCED (D-557): the
 * platform counter the post-call meter moves, the only speaking rate any rupee is struck at.
 * The refusal floor does NOT move with the measurement — a veto that did would refuse
 * tomorrow the card it accepted today.
 */
function FleetFloorLine({ rate }: { rate: TtsSpeakingRate }) {
  // `?? null`: an API older than 9 Sep 2026 sends no block.
  const fleet = rate.fleet ?? null;
  if (fleet === null) return null;
  return (
    <p>
      <span className="font-semibold text-ink">What the cost model uses:</span>{" "}
      {fleet.basis}. A Clear call-minute costs{" "}
      {formatRupeeRate(fleet.cost_floor_inr_per_min)} at that rate; a rate card
      is refused below {formatRupeeRate(fleet.refusal_floor_inr_per_min)}, which
      stays where it is whatever this measurement says.{" "}
      {fleet.floor_above_refusal ? (
        <span className="font-semibold text-danger">
          The measured cost is ABOVE that bound — some rungs may be under water
          and still recordable. That is a pricing decision.
        </span>
      ) : null}
    </p>
  );
}

/** The same characters, priced at each vendor's attested figure — or plainly unpriced. */
function SpeakingRateByVendor({ rate }: { rate: TtsSpeakingRate }) {
  const rows = rate.by_provider;
  if (rows.length === 0) return null;
  return (
    <div className="border-t border-line pt-3">
      <p className="text-[13px] font-medium text-ink">What that rate costs on each voice</p>
      <ul className="mt-1 space-y-1 text-sm text-ink-muted">
        {rows.map((row) => (
          <li key={row.provider}>
            <VendorRateLine row={row} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function VendorRateLine({ row }: { row: SpeakingRateByProvider }) {
  const vendor = `${vendorName(row.provider)} (${row.tier_label})`;
  if (!row.price_attested || row.inr_per_1k_chars === null) {
    return (
      <>
        <span className="font-semibold text-ink">{vendor}</span>: no confirmed
        price, so the characters above meter at nothing and this voice cannot be
        sold. Confirm it on the ops model-prices panel.
      </>
    );
  }
  return (
    <>
      <span className="font-semibold text-ink">{vendor}</span>:{" "}
      {formatRupeeRate(row.inr_per_1k_chars)} per 1,000 characters
      {/* The server's own multiplication or nothing: the browser does not multiply money. */}
      {row.pooled_inr_per_minute !== null
        ? ` → ${formatRupeeRate(row.pooled_inr_per_minute)}/min at the pooled rate above.`
        : "."}
    </>
  );
}
