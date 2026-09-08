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
