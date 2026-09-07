"use client";

import { CircleHelp, TriangleAlert } from "lucide-react";

import { MonoValue } from "@/app/admin/ops/opsLanguage";
import {
  NoticeBox,
  ScrollRegion,
  formatINR,
  formatIST,
  formatRupeeRate,
} from "@/components/ui";
import {
  asRateCard,
  cellVerdict,
  rungs,
  tierVendor,
  useOpsRateCard,
  type RateCard,
  type RateCardCell,
} from "@/app/admin/ops/rateCard";

/**
 * THE CARD THE NEXT WRITE WILL DATE — twelve cells, six rungs x two voices.
 *
 * ## What an operator is actually deciding
 *
 * Recording a rate card does not re-price anything already sold: a lot's rates were frozen
 * when the money arrived, so a new card prices only the purchases that come AFTER it
 * (`billing/list_rates.record_card`, D-492 extended by D-547). That sentence is on the
 * panel because it is the difference between "I am about to change what everyone pays" and
 * what is really happening, and an operator who believes the first will not press the
 * button at all.
 *
 * ## Thin is shown, and it is shown as a WARNING
 *
 * The whole Sarvam column is under the 20% target and above cost, by the founder's own
 * decision. So this panel prints the margin of every cell, marks the thin ones amber, and
 * never disables anything because of one — `cellVerdict` has no refusal tone to give. The
 * refusal an operator CAN hit is below-cost or non-monotone, and that arrives from the
 * server on the write, in the server's own sentences (`ConfigPanel`'s form renders them).
 *
 * ## A card is written WHOLE
 *
 * There is no per-cell control here, and its absence is stated rather than left to be
 * discovered: the card is a committed constant (`billing/credit_packs.PACK_CATALOGUE`) and
 * the wire has one act — dating the whole card — so a cell input would be a box whose value
 * had nowhere to go. §52's rule, applied to a control instead of to a state.
 */
export function RateCardPanel() {
  const query = useOpsRateCard();
  const card = asRateCard(query.data);

  return (
    <section className="space-y-3 rounded-card border border-line bg-surface p-3">
      <div>
        <h3 className="text-sm font-semibold text-ink">Rate card — six packs, two voices</h3>
        <p className="text-xs text-ink-faint">
          What a minute sells for on each voice, per pack. Saving the self-serve price below
          dates this whole card; it prices credit bought AFTER that moment and never
          re-prices credit already sold.
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
            card in force is unaffected by this panel failing to load, and the write below
            is still checked against it by the server.
          </p>
        </NoticeBox>
      )}

      {card !== null && <RateCardTable card={card} />}
    </section>
  );
}

function RateCardTable({ card }: { card: RateCard }) {
  const thin = card.cells.filter((cell) => cell.below_target);
  const under = card.cells.filter((cell) => cell.below_floor);
  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-faint">
        {card.effective_from
          ? `The card in force was dated ${formatIST(card.effective_from)}.`
          : "No card has been dated on this deployment yet."}{" "}
        Margins are the server&apos;s own, struck against the cost each minute carries.
      </p>

      <ScrollRegion label="The rate card, by pack and voice">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
              <th className="py-2 pr-4 font-semibold">Pack</th>
              <th className="py-2 pr-4 font-semibold">Voice</th>
              <th className="py-2 pr-4 text-right font-semibold">₹ / min</th>
              <th className="py-2 pr-4 text-right font-semibold">Costs us</th>
              <th className="py-2 pr-4 text-right font-semibold">Margin</th>
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
                  <td className="py-2 pr-4 text-right tabular-nums text-ink">
                    {/* The SERVER's percentage, printed. Never a division done here — see
                        the module header. `null` is a stated absence, not 0%. */}
                    {cell.gross_margin_pct === null ? "—" : `${cell.gross_margin_pct}%`}
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
          title={`${thin.length} of ${card.cells.length} rungs earn less than ${card.target_gross_margin_pct}%`}
        >
          <p className="mt-1">
            Every one of them is still above what the minute costs us, so the card can be
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
            The server refuses to record a card in this state, so no write below will land
            until it is corrected in the catalogue and deployed.
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
