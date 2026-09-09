"use client";

import Link from "next/link";
import { useState } from "react";
import { TriangleAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  ProblemNotice,
  ScrollRegion,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
  formatRupeeRate,
} from "@/components/ui";
import { currentISTMonth } from "@/lib/api/invoice";
import {
  useFleetSpend,
  type FleetSpend,
  useTtsSpeakingRate,
  type FleetTenant,
  type SpeakingRatePoint,
  type TtsSpeakingRate,
} from "@/lib/api/spend";
import {
  vendorName,
  type SpeakingRateByProvider,
  type TtsPlanSpend,
} from "@/app/admin/spend/ttsCost";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * THE MONEY BOARD — every live client's month, worst margin first.
 *
 * It answers one question and is laid out around it: **which client is costing us money?**
 * The per-client margin card says whether ONE account is healthy; nothing said which of
 * them to open, so the answer lived in whoever happened to check.
 *
 * ## NOTHING TRUNCATES, AND THAT IS DELIBERATE
 *
 * The server walks every live client's month one `tenant_session` at a time (`usage_events`
 * is FORCE RLS'd, so a cross-tenant `SUM` is unaskable in app code and reaching for the
 * admin DB role to get one would break hard rule 1). It is therefore the slowest read in
 * this console, it is not polled, and it hides nobody — a money board that quietly dropped
 * the client at the bottom would defeat the board. The server logs and names a remedy when
 * its own walk goes over budget rather than cutting the list.
 *
 * ## MONEY
 *
 * Every figure is an exact decimal STRING from the server and goes through `formatINR`,
 * which formats the digits and never parses them. NOTHING on this page is summed in the
 * browser: `revenue_inr`, `cost_inr` and `margin_inr` at the top are the server's own sums
 * of the rows, and adding them here would be float arithmetic on money (hard rule 7) with a
 * second answer to a question already answered.
 *
 * The page carries no `<h1>` — the shell derives the title from the nav list it renders the
 * sidebar from (`app/admin/layout.tsx`), so a heading here would repeat it.
 */
export default function FleetSpendPage() {
  const [month, setMonth] = useState(currentISTMonth);
  const board = useFleetSpend(month);
  const data = board.data;

  /*
   * THE MONEY BOARD, DECLARED TO THE SCREEN ASSISTANT.
   *
   * FLEET TOTALS, NO CLIENT ROWS — the cross-tenant decision this screen forces, and the
   * reason it goes here rather than in a helper. Every row in the table below belongs to a
   * DIFFERENT client, so sending the table would drop one client's revenue into whatever
   * conversation the operator is having about another: hard rule 1's leak with no query to
   * blame for it. The four sums and the two counts are CALEVATE'S OWN margin, not any
   * tenant's data, so they go. An operator who wants to ask about one client opens that
   * client's `/admin/tenants/{id}/spend`, which declares its own surface with its own name
   * on it.
   *
   * The month is declared read-only. Changing it re-reads every live client one RLS
   * session at a time — the slowest read in this console — so it is not something to be
   * driven from a sentence; the model can still say which month is on screen.
   */
  useCopilotSurface({
    route: "/admin/spend",
    title: "Spend and margin, every client",
    realm: "admin",
    fields: [
      {
        id: "fleet-spend-month",
        label: "Billing month",
        type: "text",
        value: month,
        writable: false,
        help: "IST billing month as YYYY-MM. Changing it walks every live client again.",
      },
    ],
    facts: data
      ? [
          { key: "month", label: "Month shown", value: data.month },
          { key: "clients", label: "Live clients walked", value: String(data.clients) },
          { key: "revenue_inr", label: "Fleet revenue (₹)", value: data.revenue_inr },
          { key: "cost_inr", label: "What the fleet cost us (₹)", value: data.cost_inr },
          { key: "margin_inr", label: "Fleet margin (₹)", value: data.margin_inr },
          {
            key: "margin_pct",
            label: "Fleet margin (%)",
            value: data.margin_pct ?? "nothing billed this month",
          },
          {
            key: "loss_making",
            label: "Clients whose month is losing money",
            value: String(
              data.tenants.filter((row) => row.margin_inr.trim().startsWith("-")).length,
            ),
          },
        ]
      : [
          {
            key: "board",
            label: "The board",
            // Never "₹0": a read that did not arrive is not a month with no revenue in it,
            // and the assistant must not be the one surface that forgets that (§52).
            value: board.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          What every live client billed and cost us this month, worst margin first.
          Suspended and closed accounts are not included.
        </p>
        <input
          type="month"
          value={month}
          // No future months: an empty 2027 board reads like a failure (ux-audit F-9a).
          max={currentISTMonth()}
          onChange={(event) => setMonth(event.target.value)}
          className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
          aria-label="Billing month"
        />
      </div>

      {board.error && <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />}

      {/* §52: a skeleton is not a fleet total and a failed walk is not "we made ₹0". */}
      {!data ? (
        board.error ? null : (
          <Skeleton rows={6} label="Adding up every client's month" />
        )
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label={`Revenue · ${data.month}`} value={formatINR(data.revenue_inr)} />
            <StatTile label="Our cost" value={formatINR(data.cost_inr)} />
            <div className="rounded-card border border-line bg-surface p-5">
              <p className="text-[13px] font-medium text-ink-muted">Margin</p>
              <p
                className={
                  data.margin_inr.trim().startsWith("-")
                    ? "mt-1 text-2xl font-bold tracking-tight tabular-nums text-rose-600 dark:text-rose-400"
                    : "mt-1 text-2xl font-bold tracking-tight tabular-nums text-brand-strong dark:text-brand-bright"
                }
              >
                {/* Same sr-only prefix as the table rows below: colour is never the only
                    signal that a month is losing money (ux-audit F-18). */}
                {data.margin_inr.trim().startsWith("-") && (
                  <span className="sr-only">Losing money: </span>
                )}
                {formatINR(data.margin_inr)}
              </p>
            </div>
            {/* null, not 0%: "nothing billed across the fleet" and "we made nothing" are
                different facts. */}
            <StatTile
              label="Margin %"
              value={data.margin_pct === null ? "not billed yet" : `${data.margin_pct}%`}
              hint={`${formatCount(data.clients)} live ${data.clients === 1 ? "client" : "clients"} walked.`}
            />
          </div>

          <Card bodyClassName="p-0">
            {data.tenants.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  title="No live clients this month"
                  hint="Suspended and closed accounts are deliberately left out."
                />
              </div>
            ) : (
              <ScrollRegion label="Every live client's month">
                <table className="w-full min-w-[820px] text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                      <th className="px-4 py-3 font-semibold sm:px-6">Client</th>
                      <th className="px-4 py-3 font-semibold sm:px-6">Plan</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Calls</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Minutes</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Revenue</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Our cost</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Margin</th>
                      <th className="px-4 py-3 text-right font-semibold sm:px-6">Margin %</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.tenants.map((tenant) => (
                      <FleetRow key={tenant.tenant_id} tenant={tenant} />
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
            )}
          </Card>
        </>
      )}

      {/* WHAT THE VOICE VENDORS ACTUALLY BILLED, beside what the calls attributed. Inside
          the month, unlike the card below it, because a plan fee IS a month: it is paid
          whether or not anybody spoke. */}
      <TtsPlanCard board={data} />

      {/* Its own read, deliberately outside the month: the speaking rate is a property of
          the whole transcript archive, not of a billing month, and a failed fleet walk
          must not hide it (nor the reverse). */}
      <TtsSpeakingRateCard />
    </div>
  );
}

/**
 * A chars-per-minute figure as the server spelled it, with trailing zeros dropped so
 * "300.0000" reads as 300 — string surgery, never `Number()`, the digits are the server's.
 */
function trimRate(value: string): string {
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

function RatePoint({ point }: { point: SpeakingRatePoint }) {
  return (
    <>
      <span className="font-semibold tabular-nums text-ink">{trimRate(point.chars_per_minute)}</span>{" "}
      chars/min → {formatRupeeRate(point.tts_inr_per_minute)}/min
    </>
  );
}

/**
 * THE TTS SPEAKING RATE — MEASURED (pilot gate 12, TRD §10.1).
 *
 * TRD §10.1 prices the TTS leg from an ASSUMPTION — the agent speaks 40–60% of a call at
 * ~900 chars/min, so 360–540 TTS characters per call-minute — and says in its own words
 * that the ratio is unmeasured and is the single biggest lever on the TTS line. This card
 * is the measurement: characters in the AGENT's transcript turns ÷ call minutes, over every
 * live client, read one RLS session at a time by the server.
 *
 * BELOW THE THRESHOLD THERE IS NO FIGURE ON THIS CARD, and that is the point of it. A rate
 * from three calls printed under the word "measured" would be the exact hard-rule-11
 * failure the repository keeps correcting, so the server sends `measured: false` with the
 * sample size, and this card says how many calls it has and how many it needs — never a
 * placeholder, and never the assumed band dressed as a reading. The band is printed in
 * both states, labelled as what it is: the fallback, or the figure this replaced.
 */
function TtsSpeakingRateCard() {
  const query = useTtsSpeakingRate();
  const rate = query.data;
  return (
    <Card title="TTS speaking rate — measured">
      {query.error ? (
        <ProblemNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : !rate ? (
        <Skeleton rows={3} label="Reading every client's transcripts" />
      ) : rate.measured && rate.p50 && rate.p95 && rate.pooled ? (
        <div className="space-y-3 text-sm text-ink-muted">
          <p>
            <span className="font-semibold text-ink">{formatCount(rate.calls)}</span> calls with a
            transcript across{" "}
            <span className="font-semibold text-ink">{formatCount(rate.clients)}</span>{" "}
            {rate.clients === 1 ? "client" : "clients"}, priced at {formatRupeeRate(rate.tts_inr_per_10k_chars)}{" "}
            per 10,000 characters.
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
            {formatRupeeRate(rate.assumed_high.tts_inr_per_minute)}/min) in TRD §10.1. ⚠ This
            paragraph used to end &ldquo;re-derive the cost floor from it, not from the
            band&rdquo; — an instruction to a person that nothing carried out. It is code now,
            and what it produced is below.
          </p>
          <FleetFloorLine rate={rate} />
        </div>
      ) : (
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
          {/* The per-vendor prices still render below the threshold: whether a voice has a
              confirmed price at all is not a measurement and does not wait on one. */}
          <SpeakingRateByVendor rate={rate} />
          <p>
            Until then the cost floor rests on TRD §10.1&apos;s assumed{" "}
            {trimRate(rate.assumed_low.chars_per_minute)}–
            {trimRate(rate.assumed_high.chars_per_minute)} chars/min (
            {formatRupeeRate(rate.assumed_low.tts_inr_per_minute)}–
            {formatRupeeRate(rate.assumed_high.tts_inr_per_minute)}/min), which is an
            assumption and not a reading.
          </p>
          <FleetFloorLine rate={rate} />
        </div>
      )}
    </Card>
  );
}

/**
 * **THE FIGURE THE COST MODEL ACTUALLY DIVIDES BY, AND THE FLOOR IT PRODUCED (D-557).**
 *
 * Everything above this line is the archive, walked one client at a time so a distribution
 * can be drawn. This is the platform counter the post-call meter moves — the same pooled
 * question, answered in one row — and it is the only speaking rate any rupee in this product
 * is struck at. Both are shown because if they disagree, one of them is wrong.
 *
 * The refusal figure beside it is the bound a rate card is refused below, and it does NOT
 * move with the measurement: a veto that did would refuse tomorrow the card it accepted
 * today, because twenty more calls were answered.
 */
function FleetFloorLine({ rate }: { rate: TtsSpeakingRate }) {
  // `?? null`: the block is REQUIRED on the wire, and an API older than 9 Sep 2026 sends
  // none — which the generated type cannot describe.
  const fleet = rate.fleet ?? null;
  if (fleet === null) return null;
  return (
    <p>
      <span className="font-semibold text-ink">What the cost model uses:</span> {fleet.basis}.
      A Clear call-minute costs {formatRupeeRate(fleet.cost_floor_inr_per_min)} at that rate;
      a rate card is refused below{" "}
      {formatRupeeRate(fleet.refusal_floor_inr_per_min)}, which stays where it is whatever
      this measurement says.{" "}
      {fleet.floor_above_refusal ? (
        <span className="font-semibold text-red-600">
          The measured cost is ABOVE that bound — some rungs may be under water and still
          recordable. That is a pricing decision.
        </span>
      ) : null}
    </p>
  );
}

/**
 * One client's row, linking to the screen that says WHERE that margin came from.
 *
 * A losing month is marked rather than only coloured: colour is the one signal the a11y
 * sweep cannot check and the one a colour-blind operator may not have, so the warning
 * triangle carries a text alternative of its own.
 */
function FleetRow({ tenant }: { tenant: FleetTenant }) {
  const negative = tenant.margin_inr.trim().startsWith("-");
  return (
    <tr className={negative ? NOTICE_TONES.stop : undefined}>
      <td className="px-4 py-3 sm:px-6">
        <Link
          href={`/admin/tenants/${tenant.tenant_id}/spend`}
          className="font-medium text-ink underline underline-offset-2 hover:text-brand-strong"
        >
          {tenant.name}
        </Link>
        <span className="ml-2 text-xs text-ink-faint">/c/{tenant.slug}</span>
      </td>
      <td className="px-4 py-3 text-ink-muted sm:px-6">{tenant.plan_tier}</td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">{formatCount(tenant.calls)}</td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {tenant.minutes_used}
      </td>
      <td className="px-4 py-3 text-right tabular-nums sm:px-6">
        {formatINR(tenant.revenue_inr)}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {formatINR(tenant.cost_inr)}
      </td>
      <td className="px-4 py-3 text-right font-semibold tabular-nums sm:px-6">
        {negative && (
          <>
            <TriangleAlert aria-hidden className="mr-1 inline h-3.5 w-3.5" />
            <span className="sr-only">Losing money: </span>
          </>
        )}
        {formatINR(tenant.margin_inr)}
      </td>
      <td className="px-4 py-3 text-right tabular-nums text-ink-muted sm:px-6">
        {tenant.margin_pct === null ? "not billed yet" : `${tenant.margin_pct}%`}
      </td>
    </tr>
  );
}

/**
 * PLAN SPEND vs ATTRIBUTED — the two voice-cost figures, kept apart on purpose.
 *
 * Under BYOK we pay the voice vendor directly and the call platform charges nothing for the
 * synthesizer leg, so a Cartesia call's cost is not something the engine reports: it is the
 * attested rupees-per-1,000-characters times the characters our own transcripts say the
 * agent spoke. That is the ATTRIBUTED figure, and it is the one the fleet table above is
 * built from.
 *
 * The vendor, meanwhile, bills a monthly plan whether or not anybody speaks. That is PLAN
 * SPEND, and it belongs to the platform rather than to any client — folding it into the
 * fleet margin would add cost with no matching revenue and break the partition the board
 * rests on (`AbsorbedAiSpendOut` makes the identical argument one ledger over).
 *
 * The gap between them is the allotment nobody used. It is the server's own subtraction:
 * this card renders `unused_inr` and never computes it, because a difference worked out in
 * a browser is float arithmetic on money and would be a second answer to what we paid.
 */
function TtsPlanCard({ board }: { board: FleetSpend | undefined }) {
  if (board === undefined) return null;
  // An empty list and a missing month are ONE absence: the API omits a vendor's row rather
  // than sending a zero fee, so there is nothing here to tell apart. The optional read is
  // deliberate over a REQUIRED field — an API older than Phase D.3 sends no `tts_plan` at
  // all, and the whole money board dying on a card about one vendor's invoice is a worse
  // answer than the card saying it has nothing to show.
  const rows = board.tts_plan?.length ? board.tts_plan : null;

  return (
    <Card title="Voice vendors — plan spend against attributed">
      {rows === null ? (
        // §52: "no plan spend was published" is not "the voices cost us nothing". A ₹0 plan
        // fee on this board would show a fleet margin that does not exist.
        <p className="text-sm text-ink-muted">
          This deployment did not publish what the voice vendors billed, so nothing is shown
          rather than a zero. The client figures above are unaffected — they are what the
          calls were charged; this card is what we paid the vendor for the month.
        </p>
      ) : (
        <ul className="space-y-3">
          {rows.map((row) => (
            <li key={row.provider}>
              <TtsPlanRow row={row} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function TtsPlanRow({ row }: { row: TtsPlanSpend }) {
  return (
    <div className="rounded-md border border-line p-3">
      {/* VENDOR FIRST, then the name the client reads. An operator reconciling this against
          an invoice is holding a document with the vendor's name at the top of it. */}
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
          {/* The SERVER's subtraction. "—" where it did not send one: a blank is honest,
              and a difference computed here would be a second answer to what we paid. */}
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

/**
 * THE MEASURED RATE, PER VENDOR — the same characters, priced at each vendor's own figure.
 *
 * The card above this one measures how many characters a call-minute really uses. For a
 * BYOK vendor that count is not a check on an assumption: it IS the billed quantity, so
 * this strip says what a minute costs on each voice at the price an operator attested, and
 * says plainly when there is no price to apply.
 */
function SpeakingRateByVendor({ rate }: { rate: TtsSpeakingRate }) {
  // `by_provider` is generated and REQUIRED, so the hand validator that stood in for it is
  // gone. An empty list is still skipped: a heading over no rows says nothing twice.
  const rows = rate.by_provider;
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 border-t border-line pt-3">
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
        <span className="font-semibold text-ink">{vendor}</span>: no confirmed price, so the
        characters above meter at nothing and this voice cannot be sold. Confirm it on the
        ops model-prices panel.
      </>
    );
  }
  return (
    <>
      <span className="font-semibold text-ink">{vendor}</span>: {formatRupeeRate(row.inr_per_1k_chars)}{" "}
      per 1,000 characters
      {/* The server's own multiplication or nothing at all. The browser does not multiply a
          chars/min figure by a price to invent a per-minute cost. */}
      {row.pooled_inr_per_minute !== null
        ? ` → ${formatRupeeRate(row.pooled_inr_per_minute)}/min at the pooled rate above.`
        : "."}
    </>
  );
}
