"use client";

import { useMemo, useState } from "react";

import {
  BellRing,
  CalendarClock,
  CircleHelp,
  Save,
  TriangleAlert,
  Undo2,
} from "lucide-react";

import { MonoValue, TypeToConfirm, confirmMatches } from "@/app/admin/ops/opsLanguage";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  formatINR,
  formatIST,
  formatWholeCount,
  formatRupeeRate,
} from "@/components/ui";
import {
  cardInstant,
  cardRefusal,
  cellVerdict,
  earliestPickableDate,
  noticeDays,
  noticeRecipients,
  pendingCards,
  rateDelta,
  rateOf,
  rungs,
  tierVendor,
  useCancelRateCard,
  useOpsRateCard,
  useRecordRateCard,
  type CartesiaVolume,
  type CellDraft,
  type PendingCard,
  type RateCard,
  type RateCardCell,
  type RateDelta,
} from "@/lib/api/opsRateCard";

/**
 * THE RATE CARD — the twelve cells in force, the cards already scheduled, and the form
 * that records the next one (D-547 for the read, D-550 for the write).
 *
 * ## What an operator is actually deciding
 *
 * Recording a rate card does not re-price anything already sold: a lot's rates were frozen
 * when the money arrived, so a new card prices only the purchases that come AFTER it
 * (`billing/list_rates.record_card`). That sentence is on the panel because it is the
 * difference between "I am about to change what everyone pays" and what is really
 * happening, and an operator who believes the first will not press the button at all.
 *
 * ## Two numbers go beside the button, and neither is guessed
 *
 * **How many clients get an email**, because "every affected client is notified" is the
 * founder's own condition on this feature and the size of that is something you learn
 * BEFORE sending it, not from the replies. It is the server's count over the prepaid book
 * (`RateCardOut.notice_recipients`) — an API that does not publish it says so rather than
 * showing a zero. **The earliest date this deployment will accept**, from
 * `earliest_effective_from`, which the server computes with the same function that refuses
 * — so the picker's floor and the write's floor cannot be two answers.
 *
 * ## Thin is shown, and it is shown as a WARNING
 *
 * The whole Sarvam column is under the 20% target and above cost, by the founder's own
 * decision. So this panel prints the margin of every cell, marks the thin ones amber, and
 * never disables anything because of one — `cellVerdict` has no refusal tone to give. The
 * refusals an operator CAN hit are below-cost, too-soon, already-scheduled and malformed,
 * and each arrives from the server with the server's own sentences (`cardRefusal`).
 *
 * ## A card is written WHOLE
 *
 * There is no per-cell write, here or on the wire: `card_refusals` scores a rate against
 * its voice's cost floor AND against the rung either side of it, so a one-cell PATCH could
 * only be validated against eleven cells read back from somewhere else. The form therefore
 * posts every cell it is showing, pre-filled from the card in force.
 */
export function RateCardPanel({
  access,
}: {
  access: { allowed: boolean; reason: string | null };
}) {
  const query = useOpsRateCard();
  // The generated type IS the validation now (`RateCardOut`, every field required), so the
  // read is used directly and the only remaining question is whether this deployment
  // answered at all — which is a read state, not a shape.
  const card = query.data ?? null;

  return (
    <section className="space-y-3 rounded-card border border-line bg-surface p-3">
      <div>
        <h3 className="text-sm font-semibold text-ink">Rate card — six packs, two voices</h3>
        <p className="text-xs text-ink-faint">
          What a minute sells for on each voice, per pack. A new card takes effect on a date
          you choose at least a month out, every client on a wallet is emailed when you
          record it, and credit already bought keeps the rates it was bought at.
        </p>
      </div>

      {/* A LINE, NOT A `Skeleton`. Every skeleton in this app is a `role="status"` live
          region, and this panel sits on a screen whose write receipts are also status
          regions — a second one would announce "reading the rate card" over the answer to
          the save an operator just made, and would make `getByRole("status")` ambiguous for
          anything reading the receipt. The panel is secondary; its loading state does not
          need to interrupt. */}
      {query.isLoading && <p className="text-xs text-ink-faint">Reading the rate card…</p>}

      {/* §52: no table of invented cells. A card that could not be read is said as itself —
          including the case that matters most while this is being built, which is a
          deployment whose API does not publish this read at all. */}
      {!query.isLoading && card === null && (
        <NoticeBox
          tone="warn"
          icon={<CircleHelp aria-hidden className="h-5 w-5" />}
          title="We could not read the rate card"
        >
          <p className="mt-1">
            No rates are shown because none were received — a table of guessed prices is the
            one thing this panel must never render. Either this deployment&apos;s API does not
            publish <MonoValue>/v1/ops/rate-card</MonoValue> yet, or the read failed. The
            card in force is unaffected by this panel failing to load, and no card can be
            recorded until it can be read.
          </p>
        </NoticeBox>
      )}

      {card !== null && (
        <>
          <RateCardTable card={card} />
          <ScheduledCards card={card} access={access} />
          <RecordCardSection card={card} access={access} />
        </>
      )}
    </section>
  );
}

function RateCardTable({ card }: { card: RateCard }) {
  const thin = card.cells.filter((cell) => cell.below_target);
  const under = card.cells.filter((cell) => cell.below_floor);
  // THE HONEST COUNT, beside the structural one. Struck at what the minute actually cost
  // this month rather than at the floor the write path refuses below, because on a
  // subscription-billed voice those are different numbers and the second is the one an
  // operator is being asked to judge (founder, 9 Sep 2026).
  const thinAtVolume = card.cells.filter(
    (cell) => cell.below_target_at_volume || cell.below_floor_at_volume,
  );
  const underAtVolume = card.cells.filter((cell) => cell.below_floor_at_volume);
  // `cartesia_volume` is REQUIRED on the wire, and this arm is not defensive padding: an
  // API older than 9 Sep 2026 sends no such field, and the one thing this panel must never
  // do is print a "costs us" column with no volume beside it — that IS the defect. So a
  // response without it is said as itself and the table is not rendered, exactly as the
  // whole-card failure above is. `?? null` rather than a non-null assertion because the
  // generated type cannot describe an older deployment.
  const volume: CartesiaVolume | null = card.cartesia_volume ?? null;
  if (volume === null) {
    return (
      <NoticeBox
        tone="warn"
        icon={<CircleHelp aria-hidden className="h-5 w-5" />}
        title="This deployment did not send the Studio volume, so no cost is shown"
      >
        <p className="mt-1">
          A Studio minute is billed as a monthly subscription, so what it costs us depends on
          how many minutes the platform spoke — and a cost printed without that volume is a
          guess, which is what this screen used to do. The rates themselves are unaffected;
          the API is older than the volume block and needs deploying.
        </p>
      </NoticeBox>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-faint">
        {card.effective_from
          ? `The card in force was dated ${formatIST(card.effective_from)}.`
          : "No card has been dated on this deployment yet."}{" "}
        Margins are the server&apos;s own, struck against the cost each minute carries.
      </p>

      <CartesiaVolumeNotice volume={volume} />

      <ScrollRegion label="The rate card, by pack and voice">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
              <th className="py-2 pr-4 font-semibold">Pack</th>
              <th className="py-2 pr-4 font-semibold">Voice</th>
              <th className="py-2 pr-4 text-right font-semibold">₹ / min</th>
              {/* ⚠ "COSTS US" USED TO BE ONE COLUMN AND IT PRINTED A BEST CASE (founder,
                  9 Sep 2026). Cartesia is a monthly subscription, so a per-minute cost is a
                  function of volume; the old single figure was the plan's cheapest possible
                  minute at a volume this platform has never run. There are now two, each
                  headed with what it is: the marginal cost of the NEXT minute, and what a
                  minute ACTUALLY cost at this month's measured volume. */}
              <th className="py-2 pr-4 text-right font-semibold">
                Next min costs
                <span className="block text-[10px] font-normal normal-case tracking-normal">
                  at the margin
                </span>
              </th>
              <th className="py-2 pr-4 text-right font-semibold">
                Cost at {formatWholeCount(volume.measured_call_minutes)} min/mo
                <span className="block text-[10px] font-normal normal-case tracking-normal">
                  this month, measured
                </span>
              </th>
              <th className="py-2 pr-4 text-right font-semibold">Margin</th>
              <th className="py-2 pr-4 text-right font-semibold">
                Break-even
                <span className="block text-[10px] font-normal normal-case tracking-normal">
                  platform min/mo
                </span>
              </th>
              <th className="py-2 font-semibold">Verdict</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rungs(card).map((rung) =>
              rung.cells.map((cell, index) => (
                <tr key={`${cell.pack_id}:${cell.voice_tier}`}>
                  <td className="py-2 pr-4">
                    {index === 0 ? (
                      <>
                        <span className="font-medium text-ink">{formatINR(rung.amount_inr)}</span>{" "}
                        <MonoValue className="text-ink-faint">{rung.pack_id}</MonoValue>
                      </>
                    ) : null}
                  </td>
                  {/* THE VENDOR IS NAMED, beside the name the client reads. An operator
                      installing a Cartesia key has to be able to tell which column that key
                      turns on; a client never sees this screen. */}
                  <td className="py-2 pr-4 text-ink-muted">
                    {tierVendor(cell.voice_tier)} · {cell.tier_label}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums text-ink">
                    {formatRupeeRate(cell.inr_per_min)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums text-ink-muted">
                    {formatRupeeRate(cell.cost_floor_inr_per_min)}
                  </td>
                  {/* WHAT THE MINUTE ACTUALLY COST THIS MONTH, and the margin struck against
                      THAT. A stated absence when nothing was spoken — never a zero, which
                      would read as "this voice is free". */}
                  <td
                    className={
                      "py-2 pr-4 text-right tabular-nums " +
                      (cell.below_floor_at_volume ? "font-semibold text-red-600" : "text-ink-muted")
                    }
                  >
                    {cell.cost_inr_per_min_at_volume === null
                      ? "—"
                      : formatRupeeRate(cell.cost_inr_per_min_at_volume)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums text-ink">
                    {/* The SERVER's percentage, printed. Never a division done here — see
                        the module header. `null` is a stated absence, not 0%. BOTH margins
                        are shown: the one struck at the structural floor, and — where it
                        differs — the one struck at what the month actually cost. */}
                    {cell.gross_margin_pct === null ? "—" : `${cell.gross_margin_pct}%`}
                    {cell.gross_margin_pct_at_volume !== null &&
                      cell.gross_margin_pct_at_volume !== cell.gross_margin_pct && (
                        <span
                          className={
                            "block text-[11px] " +
                            (cell.below_floor_at_volume
                              ? "font-semibold text-red-600"
                              : "text-ink-faint")
                          }
                        >
                          {cell.gross_margin_pct_at_volume}% at volume
                        </span>
                      )}
                  </td>
                  {/* HOW MANY PLATFORM MINUTES A MONTH THIS RUNG NEEDS BEFORE IT STOPS
                      LOSING MONEY. Blank on Sarvam, whose cost does not move with volume;
                      "never" where no volume rescues the rate, which is a different fact
                      from a big number and is said as itself. */}
                  <td className="py-2 pr-4 text-right tabular-nums text-ink-faint">
                    {cell.voice_tier !== "cartesia"
                      ? ""
                      : cell.breakeven_call_minutes === null
                        ? "never"
                        : formatWholeCount(cell.breakeven_call_minutes)}
                  </td>
                  <td className="py-2">
                    <CellBadge cell={cell} targetPct={card.target_gross_margin_pct} />
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </ScrollRegion>

      {/* THE THIN SUMMARY, AS A WARNING. Amber, never red, and it blocks nothing: this is
          the card that is on sale, and a screen that presented it as broken would be
          arguing with the founder's own decision every time it loaded. */}
      {thin.length > 0 && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title={
            thinAtVolume.length > thin.length
              ? `${thinAtVolume.length} of ${card.cells.length} rungs earn less than ` +
                `${card.target_gross_margin_pct}% at this month's volume ` +
                `(${thin.length} against the structural floor)`
              : `${thin.length} of ${card.cells.length} rungs earn less than ${card.target_gross_margin_pct}%`
          }
        >
          {/* ⚠ THE HEADLINE COUNT USED TO BE THE STRUCTURAL ONE ALONE, AND IT UNDERSTATED
              THE PROBLEM (founder, 9 Sep 2026). The structural floor is the cost of the
              next minute at the margin; at a low monthly volume the subscription has not
              amortised and the real cost is higher, so more rungs are thin than that count
              admits. Both numbers are shown — the honest one first — because the structural
              figure is still what the write path refuses on. */}
          <p className="mt-1">
            Every one of them is still above the structural floor, so the card can be
            recorded and is what we sell today. Read the numbers before you commit a new
            card — a thinner rung is a decision, not a fault, and nothing here is blocked by
            it.
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {thin.map((cell) => (
              <li key={`${cell.pack_id}:${cell.voice_tier}`}>
                {cell.pack_id} on {tierVendor(cell.voice_tier)} ({cell.tier_label}):{" "}
                {cell.gross_margin_pct === null ? "no margin struck" : `${cell.gross_margin_pct}%`}{" "}
                at {formatRupeeRate(cell.inr_per_min)}/min against{" "}
                {formatRupeeRate(cell.cost_floor_inr_per_min)}/min of cost.
              </li>
            ))}
          </ul>
        </NoticeBox>
      )}

      {/* UNDER WATER AT THIS MONTH'S VOLUME — the founder's actual complaint, rendered.
          These rungs clear the structural floor (so the server will record the card) and
          still sold a minute for less than the month cost us, because the subscription had
          not amortised. Amber and not red: it is a fact about a volume, not a broken card,
          and the answer is usually more minutes rather than a higher price. */}
      {underAtVolume.length > 0 && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title={
            `${underAtVolume.length} rung${underAtVolume.length === 1 ? "" : "s"} sold a minute ` +
            `for less than it cost at this month's volume`
          }
        >
          <p className="mt-1">
            Nothing is blocked — every one of these clears the floor the write path refuses
            below, which is the cost of the next minute at the margin. What they do not clear
            is what a minute ACTUALLY cost this month, because a monthly subscription spread
            over few minutes is dear. Each rung&apos;s break-even column says how many Studio
            minutes a month the platform needs before it stops losing money on that rung.
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {underAtVolume.map((cell) => (
              <li key={`${cell.pack_id}:${cell.voice_tier}`}>
                {cell.pack_id} on {tierVendor(cell.voice_tier)} ({cell.tier_label}):{" "}
                {formatRupeeRate(cell.inr_per_min)}/min against{" "}
                {cell.cost_inr_per_min_at_volume === null
                  ? "an unstated cost"
                  : `${formatRupeeRate(cell.cost_inr_per_min_at_volume)}/min of real cost`}
                {cell.breakeven_call_minutes === null
                  ? " — no volume makes this rung profitable"
                  : `, break-even ${formatWholeCount(cell.breakeven_call_minutes)} platform min/mo`}
                .
              </li>
            ))}
          </ul>
        </NoticeBox>
      )}

      {/* Below COST is the other thing entirely, and the server refuses the write. Shown
          here because a card already in this state must not first be discovered by a failed
          save three screens later. */}
      {under.length > 0 && (
        <NoticeBox
          tone="stop"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="Some rungs sell a minute for less than it costs"
        >
          <p className="mt-1">
            The server refuses to record a card in this state, so the form below will not
            save until these rungs are raised above what their minute costs.
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {under.map((cell) => (
              <li key={`${cell.pack_id}:${cell.voice_tier}`}>
                {cell.pack_id} on {tierVendor(cell.voice_tier)}:{" "}
                {formatRupeeRate(cell.inr_per_min)}/min against{" "}
                {formatRupeeRate(cell.cost_floor_inr_per_min)}/min of cost.
              </li>
            ))}
          </ul>
        </NoticeBox>
      )}
    </div>
  );
}

/**
 * **THE VOLUME EVERY CARTESIA COST FIGURE ON THIS SCREEN IS STRUCK AT.**
 *
 * THE DEFECT THIS EXISTS FOR. This panel printed ₹4.3639 for every Studio rung under a
 * column headed "COSTS US". That figure was the $49 Startup plan fee spread over the 2,315
 * call-minutes at which its allotment is exactly consumed — the cheapest a Cartesia minute
 * can ever be, at a volume this platform has never run — and nothing on the screen said so.
 * The founder read it on 9 Sep 2026 and said the Studio leg could not cost us that little.
 * The arithmetic was right; the SCREEN was lying.
 *
 * Cartesia is a monthly subscription with an included allotment and an overage past it, so
 * a per-minute cost is a function of volume and a screen that shows one without its volume
 * is showing a guess. Everything here is the SERVER's — no rupee is divided in the browser.
 */
function CartesiaVolumeNotice({ volume }: { volume: CartesiaVolume }) {
  const measured = volume.cost_inr_per_min;
  const fxIsFallback = volume.fx_as_of === null;
  return (
    <div className="space-y-2 rounded-card border border-line bg-surface-muted p-3 text-xs">
      <p className="text-ink">
        <span className="font-semibold">Studio (Cartesia) is a monthly subscription</span>, so
        what a minute costs us depends on how many we speak. This month the platform spoke{" "}
        <span className="font-semibold tabular-nums">
          {formatWholeCount(volume.measured_call_minutes)}
        </span>{" "}
        Studio call-minutes ({formatWholeCount(volume.measured_characters)} characters), on
        the <MonoValue>{volume.plan_id ?? "—"}</MonoValue> plan.{" "}
        {measured === null ? (
          <>
            Nothing was spoken, so there is no cost per minute to state — the subscription is
            still owed.
          </>
        ) : (
          <>
            That works out at{" "}
            <span className="font-semibold tabular-nums">{formatRupeeRate(measured)}</span> a
            minute, all in.
          </>
        )}
      </p>

      {/* THE FX PROVENANCE, ON THE FACE OF THE SCREEN. Cartesia bills in dollars and the
          floor converts at the live published rate (founder, 9 Sep 2026). A floor quietly
          struck at an operator's typed fallback is the same "best case as fact" defect,
          so WHICH rate and how old it is are stated, never implied. */}
      <p className={fxIsFallback ? "font-medium text-amber-700" : "text-ink-faint"}>
        Converted at <span className="tabular-nums">{formatRupeeRate(volume.fx_usd_inr)}</span>{" "}
        to the dollar
        {fxIsFallback ? (
          <>
            {" "}
            — the <MonoValue>{volume.fx_source}</MonoValue> fallback, because no published
            rate is current. These figures are as old as that setting.
          </>
        ) : (
          <>
            {" "}
            (<MonoValue>{volume.fx_source}</MonoValue>, published {volume.fx_as_of}).
          </>
        )}
      </p>

      <p className="text-ink-faint">
        The next Studio minute costs{" "}
        <span className="tabular-nums">{formatRupeeRate(volume.floor_inr_per_min)}</span> at the
        margin, falling to{" "}
        <span className="tabular-nums">
          {formatRupeeRate(volume.best_marginal_cost_inr_per_min)}
        </span>{" "}
        once volume passes {formatWholeCount(volume.plan_crossover_call_minutes)} min/mo and the{" "}
        {/* THE PLAN NAME IS READ, NOT TYPED. `plans` arrives in fee order, so the last is
            the one that wins at high volume; a literal "startup" here would be a second
            spelling of a fact the server already sent, and the wrong one the day a plan is
            added. */}
        <MonoValue>{volume.plans[volume.plans.length - 1]?.plan_id ?? "—"}</MonoValue> plan
        becomes the cheaper one. A card is refused below{" "}
        <span className="tabular-nums">{formatRupeeRate(volume.refusal_floor_inr_per_min)}</span>
        , which is deliberately frozen at ₹88 to the dollar so a currency tick can never make
        the card that is on sale un-recordable.
      </p>

      <ScrollRegion label="What a Studio minute costs at each monthly volume">
        <table className="w-full min-w-[420px] text-xs">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-ink-faint">
              <th className="py-1 pr-4 font-semibold">Platform min/mo</th>
              <th className="py-1 pr-4 font-semibold">Cheapest plan</th>
              <th className="py-1 text-right font-semibold">Costs us / min</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {volume.ladder.map((point: CartesiaVolume["ladder"][number]) => (
              <tr key={point.call_minutes}>
                <td className="py-1 pr-4 tabular-nums text-ink-muted">
                  {formatWholeCount(point.call_minutes)}
                </td>
                <td className="py-1 pr-4 text-ink-muted">
                  <MonoValue>{point.plan_id}</MonoValue>
                </td>
                <td className="py-1 text-right tabular-nums text-ink">
                  {formatRupeeRate(point.cost_inr_per_min)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>

      <p className="text-ink-faint">
        Modelled at {volume.assumed_chars_per_call_minute} characters a call-minute, the top of
        an unmeasured band. The measured figure above uses no such assumption — it divides the
        characters our meter counted by the minutes it billed.
      </p>
    </div>
  );
}

function CellBadge({ cell, targetPct }: { cell: RateCardCell; targetPct: string }) {
  const verdict = cellVerdict(cell, targetPct);
  return (
    <span
      className={
        verdict.tone === "thin"
          ? "inline-flex items-center gap-1 text-xs font-medium text-amber-600"
          : "inline-flex items-center gap-1 text-xs font-medium text-ink-faint"
      }
      title={verdict.sentence}
    >
      {verdict.tone === "thin" && <TriangleAlert aria-hidden className="h-3.5 w-3.5" />}
      {verdict.label}
    </span>
  );
}

/* -- the cards already scheduled, and the one act that can take one back -------------- */

/**
 * CARDS RECORDED WHOSE DATE HAS NOT ARRIVED.
 *
 * `pending` is the ordinary empty case, and an empty list is stated rather than left blank:
 * "nothing is scheduled" is a fact an operator checks before recording, and a blank space
 * answers it only by implication.
 *
 * WITHDRAWING IS THE COMPENSATING ENTRY, NOT A DELETE. Rate history is append-only, so the
 * API records the withdrawal as its own row and both facts stay readable — which is why
 * the button says Withdraw and the copy says the card stays in the history.
 */
function ScheduledCards({
  card,
  access,
}: {
  card: RateCard;
  access: { allowed: boolean; reason: string | null };
}) {
  const scheduled = pendingCards(card);
  return (
    <section className="space-y-2 border-t border-line pt-3">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
        Scheduled changes
      </h4>
      {scheduled.length === 0 ? (
        <p className="text-xs text-ink-faint">
          Nothing is scheduled. The card above is what every new purchase is priced at, and
          will stay so until a card recorded below takes effect.
        </p>
      ) : (
        <ul className="space-y-2">
          {scheduled.map((pending) => (
            <li key={pending.effective_from}>
              <ScheduledCard pending={pending} inForce={card} access={access} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ScheduledCard({
  pending,
  inForce,
  access,
}: {
  pending: PendingCard;
  inForce: RateCard;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm text-ink">
          <CalendarClock aria-hidden className="mr-1 inline h-3.5 w-3.5" />
          Starts {formatIST(pending.effective_from)}
        </p>
        {access.allowed && !open && (
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(true)}>
            <Undo2 aria-hidden className="h-3.5 w-3.5" />
            Withdraw
          </button>
        )}
      </div>

      <ul className="mt-2 space-y-1 text-xs text-ink-muted">
        {pending.cells.map((cell) => {
          const before = rateOf(inForce, cell.pack_id, cell.voice_tier);
          return (
            <li key={`${cell.pack_id}:${cell.voice_tier}`}>
              {cell.pack_id} on {tierVendor(cell.voice_tier)} ({cell.tier_label}):{" "}
              {formatRupeeRate(cell.inr_per_min)}/min{" "}
              {before !== null && <DeltaNote delta={rateDelta(before, cell.inr_per_min)} />}
            </li>
          );
        })}
      </ul>

      {open && <WithdrawForm pending={pending} onDone={() => setOpen(false)} />}
    </div>
  );
}

function WithdrawForm({ pending, onDone }: { pending: PendingCard; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const withdraw = useCancelRateCard();
  const valid = useFormValidation();
  const word = "WITHDRAW";
  const ready = confirmMatches(confirm, word);
  // The earliest date is not part of a withdrawal's refusals, so nothing is passed for it.
  const refusal = cardRefusal(withdraw.error, null);

  return (
    <form
      className="mt-3 space-y-3 border-t border-line pt-3"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (!ready || withdraw.isPending) return;
        withdraw.mutate(
          // THE SERVER'S OWN INSTANT, ECHOED. Re-deriving it here would be a second
          // spelling of one fact, and the step-up header is built from this string.
          { effectiveFrom: pending.effective_from, reason: reason.trim() },
          { onSuccess: onDone },
        );
      })}
    >
      {refusal ? (
        <CardRefusalNotice refusal={refusal} />
      ) : (
        withdraw.error && <WriteFailure error={withdraw.error} actionLabel="Withdraw" />
      )}

      <label className="block">
        <span className={FIELD_LABEL}>Why are you withdrawing it?</span>
        <input
          {...valid.field("withdrawReason", "Say why this card is being withdrawn.")}
          required
          minLength={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. superseded by the October card"
          className={FIELD}
        />
        {valid.error("withdrawReason")}
        <span className={FIELD_HINT}>
          Saved with the withdrawal and in the audit log. The card itself stays in the
          history — nothing is deleted — so both facts remain readable later.
        </span>
      </label>

      <TypeToConfirm
        id={`withdraw-card-${pending.effective_from}`}
        word={word}
        value={confirm}
        onChange={setConfirm}
        hint="Clients who were told about this change are not told again automatically. If it has already been announced, tell them yourself."
      />

      <div className="flex gap-2">
        <button type="submit" disabled={!ready || withdraw.isPending} className={PRIMARY_BUTTON_SM}>
          <Undo2 aria-hidden className="h-3.5 w-3.5" />
          {withdraw.isPending ? "Withdrawing…" : "Withdraw"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/* -- recording the next card ---------------------------------------------------------- */

/** The distinct voices this card carries, in the order the server sent them. */
function voicesOf(card: RateCard): RateCardCell[] {
  const seen: RateCardCell[] = [];
  for (const cell of card.cells) {
    if (!seen.some((held) => held.voice_tier === cell.voice_tier)) seen.push(cell);
  }
  return seen;
}

/** The draft's key for one cell. One spelling, so the grid and the POST cannot disagree. */
function cellKey(packId: string, voiceTier: string): string {
  return `${packId} ${voiceTier}`;
}

function RecordCardSection({
  card,
  access,
}: {
  card: RateCard;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  if (!access.allowed) {
    return (
      <p className="border-t border-line pt-3 text-xs text-ink-faint">
        {access.reason ?? "Your admin account cannot change platform configuration."}
      </p>
    );
  }
  return (
    <section className="space-y-2 border-t border-line pt-3">
      {open ? (
        <RecordCardForm card={card} onDone={() => setOpen(false)} />
      ) : (
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(true)}>
          <CalendarClock aria-hidden className="h-3.5 w-3.5" />
          Record a new card
        </button>
      )}
    </section>
  );
}

/**
 * THE FORM. Twelve boxes, a date, a reason and a typed confirmation.
 *
 * The boxes are `type="text"` with `inputMode="decimal"` and NOT `type="number"`: a number
 * input hands JavaScript a float, and the API refuses a JSON number outright with a
 * sentence saying why ("a JSON number is a binary float and cannot hold a rupee amount").
 * What the operator typed is what is sent, character for character.
 *
 * The date is a DAY, sent as midnight IST with the offset written in — see `cardInstant`,
 * which also explains why the step-up header cannot be built from `toISOString()`.
 */
function RecordCardForm({ card, onDone }: { card: RateCard; onDone: () => void }) {
  const voices = voicesOf(card);
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const seeded: Record<string, string> = {};
    // PRE-FILLED FROM THE CARD IN FORCE, so the act is "change these two rungs" rather than
    // "retype twelve figures" — the second is where a transcription error enters money.
    for (const cell of card.cells) seeded[cellKey(cell.pack_id, cell.voice_tier)] = cell.inr_per_min;
    return seeded;
  });
  const [day, setDay] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const save = useRecordRateCard();
  const valid = useFormValidation();
  const word = "RECORD";
  const ready = confirmMatches(confirm, word);

  const earliestDay = earliestPickableDate(card.earliest_effective_from);
  const days = noticeDays(card);
  const recipients = noticeRecipients(card);
  const refusal = cardRefusal(save.error, earliestDay);

  const cells: CellDraft[] = useMemo(
    () =>
      card.cells.map((cell) => ({
        pack_id: cell.pack_id,
        voice_tier: cell.voice_tier,
        inr_per_min: (draft[cellKey(cell.pack_id, cell.voice_tier)] ?? "").trim(),
      })),
    [card.cells, draft],
  );

  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (!ready || save.isPending) return;
        const effectiveFrom = cardInstant(day);
        // The date box is `required` and `type="date"`, so the browser has already refused
        // an empty one; this guards the shape the parser could not make sense of rather
        // than sending an instant nobody picked.
        if (effectiveFrom === null) return;
        save.mutate({ effectiveFrom, reason: reason.trim(), cells }, { onSuccess: onDone });
      })}
    >
      {refusal ? (
        <CardRefusalNotice refusal={refusal} />
      ) : (
        save.error && <WriteFailure error={save.error} actionLabel="Record card" />
      )}

      <ScrollRegion label="The new rate card, by pack and voice">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">
            The rate to sell a minute at, for every pack on every voice. Each box shows how
            it compares with the card in force.
          </caption>
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
              <th scope="col" className="py-2 pr-4 font-semibold">
                Pack
              </th>
              {voices.map((voice) => (
                <th key={voice.voice_tier} scope="col" className="py-2 pr-4 font-semibold">
                  {/* THE VENDOR, beside the name the client reads. An operator installing a
                      Cartesia key has to be able to tell which column that key turns on;
                      the client-facing label crosses the wire and is never spelled here. */}
                  {tierVendor(voice.voice_tier)} · {voice.tier_label} — ₹/min
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rungs(card).map((rung) => (
              <tr key={rung.pack_id}>
                <th scope="row" className="py-2 pr-4 text-left font-normal">
                  <span className="font-medium text-ink">{formatINR(rung.amount_inr)}</span>{" "}
                  <MonoValue className="text-ink-faint">{rung.pack_id}</MonoValue>
                </th>
                {voices.map((voice) => {
                  const key = cellKey(rung.pack_id, voice.voice_tier);
                  const before = rateOf(card, rung.pack_id, voice.voice_tier);
                  const typed = draft[key] ?? "";
                  return (
                    <td key={voice.voice_tier} className="py-2 pr-4">
                      <input
                        {...valid.field(
                          key,
                          `Enter the rate for the ${rung.pack_id} pack on the ${tierVendor(
                            voice.voice_tier,
                          )} voice.`,
                        )}
                        // The label is built from the two facts that identify the cell, so
                        // a screen reader hears which pack and which voice it is on — a
                        // grid of twelve identically-named boxes is unusable otherwise.
                        aria-label={`Rupees per minute, ${rung.pack_id} pack on ${tierVendor(
                          voice.voice_tier,
                        )} ${voice.tier_label}`}
                        required
                        value={typed}
                        onChange={(e) => setDraft((held) => ({ ...held, [key]: e.target.value }))}
                        // `text`, never `number`: money reaches the server as the exact
                        // string that was typed (hard rule 7).
                        inputMode="decimal"
                        className={`${FIELD} font-mono`}
                      />
                      {valid.error(key)}
                      {before !== null && (
                        <span className="mt-1 block text-xs">
                          <DeltaNote delta={rateDelta(before, typed)} />
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>

      <label className="block">
        <span className={FIELD_LABEL}>The day the new rates start (IST)</span>
        <input
          {...valid.field("effectiveFrom", "Pick the day these rates start.")}
          type="date"
          required
          value={day}
          min={earliestDay ?? undefined}
          onChange={(e) => setDay(e.target.value)}
          className={FIELD}
        />
        {valid.error("effectiveFrom")}
        <span className={FIELD_HINT}>
          {earliestDay === null
            ? "Clients are given notice before their rates move, so a card cannot start immediately. The server refuses a date that is too soon."
            : `Clients are given ${
                days === null ? "notice" : `${days} days' notice`
              } before their rates move, so the earliest day this deployment accepts is ${earliestDay}. Rates start at midnight IST on the day you pick.`}
        </span>
      </label>

      <label className="block">
        <span className={FIELD_LABEL}>Why are these rates changing?</span>
        <input
          {...valid.field("reason", "Say why the rates are changing.")}
          required
          minLength={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Cartesia raised its per-character price in September"
          className={FIELD}
        />
        {valid.error("reason")}
        <span className={FIELD_HINT}>
          Saved on the card and in the audit log, so whoever reads these rates next year
          knows what they were answering.
        </span>
      </label>

      {/* THE SIZE OF WHAT IS ABOUT TO BE SENT, before it is sent. The founder's condition on
          this whole feature is that every affected client is told; this is where an
          operator learns how many that is, rather than from the replies. */}
      <NoticeBox
        tone="warn"
        icon={<BellRing aria-hidden className="h-5 w-5" />}
        title={
          recipients === null
            ? "We do not know how many clients would be emailed"
            : `${recipients} client${
                recipients === 1 ? "" : "s"
              } will be emailed as soon as you record this`
        }
      >
        <p className="mt-1">
          {recipients === null
            ? "This deployment's API did not say how many clients are on a wallet, so no number is shown rather than a guessed one. Every client the new rates would price is still emailed when the card is recorded."
            : "Everyone on a wallet is told the new rates and the day they start, as soon as the card is recorded — not on the day itself. Clients on an invoiced plan are not emailed: this card does not price them."}
        </p>
        <p className="mt-2">
          Credit already bought is not repriced. Every top-up keeps the rates it was bought
          at, so this card only prices purchases made on or after the day you pick.
        </p>
      </NoticeBox>

      <TypeToConfirm
        id="record-rate-card"
        word={word}
        value={confirm}
        onChange={setConfirm}
        hint="Rate history is append-only. A recorded card can be withdrawn before its date, but it cannot be edited, and the email goes out straight away."
      />

      <div className="flex gap-2">
        <button type="submit" disabled={!ready || save.isPending} className={PRIMARY_BUTTON_SM}>
          <Save aria-hidden className="h-3.5 w-3.5" />
          {save.isPending ? "Recording…" : "Record card"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/**
 * The refusal, in the server's sentences under this console's advice.
 *
 * `role="alert"`, like every other refusal on these screens: it interrupts an operator
 * mid-task and the words after "nothing was saved" are the ones they act on.
 */
function CardRefusalNotice({
  refusal,
}: {
  refusal: { code: string; title: string; advice: string; sentences: string[] };
}) {
  return (
    <div role="alert">
      <NoticeBox
        tone="stop"
        icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
        title={refusal.title}
      >
        <p className="mt-1">{refusal.advice}</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {refusal.sentences.map((sentence) => (
            <li key={sentence}>{sentence}</li>
          ))}
        </ul>
      </NoticeBox>
    </div>
  );
}

/**
 * How far one rate moved, in rupees and as a percentage — or nothing at all.
 *
 * NOTHING, deliberately, while a box is empty or half-typed: "unchanged" and "we cannot
 * tell yet" are different statements, and the first would be a claim about a value nobody
 * has finished typing. The arrow is decoration beside the words and is hidden from
 * assistive technology, which reads "up 10.00%" rather than a glyph.
 */
function DeltaNote({ delta }: { delta: RateDelta | null }) {
  if (delta === null) return null;
  if (delta.direction === "same") return <span className="text-ink-faint">unchanged</span>;
  const up = delta.direction === "up";
  return (
    <span className={up ? "text-amber-600" : "text-ink-muted"}>
      <span aria-hidden>{up ? "↑" : "↓"}</span> {up ? "up" : "down"}{" "}
      {formatRupeeRate(delta.amount)}
      {delta.percent === null ? "" : ` (${delta.percent}%)`}
    </span>
  );
}
