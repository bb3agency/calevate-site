"use client";

import { useId, useState, type ReactNode } from "react";
import { Landmark } from "lucide-react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { MoneyInput, compareMoney } from "@/components/arc/money-input";
import { ChoiceCard } from "@/components/console/choiceCards";
import {
  FIELD_GROUP,
  FIELD_GROUP_INPUT,
  FIELD_HINT,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatINR,
} from "@/components/ui";
import {
  MAX_TOPUP_INR,
  MIN_TOPUP_INR,
  useConfirmTopUp,
  useCreditPacks,
  useTopUpCapability,
  useTopUpIntent,
  type CreditPack,
  type CreditPacks,
  type TopUpIntent,
} from "@/lib/api/billing";
import { useWriteAccess } from "@/lib/api/hooks";
import { formatAmountINR, formatRateINR } from "@/lib/api/rateCard";
import { CREDIT_WAIT_MS, useCreditLanding, type AwaitedCredit } from "@/lib/api/wallet";
import { openRazorpayCheckout, paymentFailedProblem } from "@/lib/razorpayCheckout";
import type { ApiProblem, Session } from "@/lib/api/client";

import {
  VOICE_TIERS,
  formatWhole,
  lapseDateFromToday,
  packForAmount,
  packMinutes,
  packRate,
  tierLabels,
  type TierLabels,
} from "./lots";

/**
 * Adding credit — a picker, then a completed payment.
 *
 * ## The picker
 *
 * One optional question first ("minutes you call in a month"), which selects the smallest
 * pack that covers it; then the packs as radio cards (one tab stop, arrow keys, "selected"
 * read aloud), each showing its amount and what it buys on each voice in one line; then
 * ONE button. The per-minute rates differ by pack, so they are stated once, for the
 * selection, rather than repeated on every card.
 *
 * Nothing is computed about money here: every amount, rate and minute count is the
 * server's, formatted by the shared formatters, and the pack a free amount buys at is the
 * server's rule (`packForAmount`). The server prices the intent and remains the authority.
 *
 * ## The four outcomes of a payment window, each with its own state
 *
 * - **paid** → the three fields go to `POST /v1/billing/topups/callback`, which verifies
 *   the signature SERVER-SIDE. We never assert a new balance: the webhook is the single
 *   writer, so the sentence is "received, updating" and the balance reads are invalidated.
 * - **dismissed** → not an error: the panel returns to where it was, with the order still
 *   live so "Pay now" reopens it rather than minting a second order.
 * - **failed** → OUR sentence through `ProblemNotice`, never the vendor's string.
 * - **not verified** → the one outcome that must not look like success, and the one where
 *   money may have moved. The server's words, then the fact that is ours: the webhook
 *   still credits a real payment without this page.
 *
 * The state machine is MONOTONIC: Checkout fires `ondismiss` after a successful payment
 * too, so `dismissed` and `failed` may only move a stage that is still `opening`/`open`.
 * Once a payment exists we are `verifying` and nothing walks that back.
 */
export function TopUp({ session }: { session: Session }) {
  const capability = useTopUpCapability(session);
  const intent = useTopUpIntent(session);
  const packs = useCreditPacks(session);
  const confirm = useConfirmTopUp(session);
  // Both outcomes are said on this panel, so neither is toasted.
  const intentFeedback = useActionFeedback(intent, { errorDisplay: "inline" });
  const confirmFeedback = useActionFeedback(confirm, { errorDisplay: "inline" });
  const [stage, setStage] = useState<Stage>({ at: "idle" });
  const creditLanded = useCreditLanding(
    session,
    stage.at === "verified" ? stage.awaited : null,
  );
  /** A pack id, `CUSTOM`, or "" before anything is chosen. */
  const [choice, setChoice] = useState("");
  const [amount, setAmount] = useState("");
  // `org:manage` is what the endpoint requires; staff see the prices and not a form that
  // will 403 them, and an operator viewing as the client cannot spend its money (D-22).
  const write = useWriteAccess(session, "org:manage", "add credit");
  /* What a client calls each voice quality, from the card and held nowhere else. A card
     without them prints no quality names and no per-minute rates: an unnamed pair of rupee
     figures is worse than none, because a reader assigns the cheaper one to whichever voice
     they had in mind. */
  const labels = tierLabels(packs.data);

  const startCheckout = (order: TopUpIntent & { provider_order_id: string }) => {
    setStage({ at: "opening" });
    // Every value handed over is the server's, copied and not computed — `amount_paise`
    // above all (hard rule 7). Nothing is prefilled: the intent carries no contact detail.
    void openRazorpayCheckout({
      keyId: order.key_id,
      orderId: order.provider_order_id,
      amountPaise: order.amount_paise,
      currency: order.currency,
      receipt: order.receipt,
      notes: order.notes,
      onSuccess: (response) => {
        // Unconditional, and above the guards below on purpose: a payment exists.
        setStage({ at: "verifying" });
        confirm.mutate(response, {
          onSuccess: () =>
            setStage({
              at: "verified",
              awaited: { receipt: order.receipt, until: Date.now() + CREDIT_WAIT_MS },
            }),
          onError: () => setStage({ at: "unverified" }),
        });
      },
      onDismissed: () => setStage(whileOpen({ at: "idle" })),
      onFailed: () => setStage(whileOpen({ at: "failed" })),
    })
      .then(() => setStage(whileOpening({ at: "open" })))
      .catch((error: unknown) => {
        // The script did not load; `openRazorpayCheckout` rejects with an `ApiProblem` so
        // this renders as a sentence with a way forward.
        setStage({ at: "blocked", problem: error as ApiProblem });
      });
  };

  const onIntent = (data: TopUpIntent) => {
    const orderId = data.provider_order_id;
    // No order means no checkout — the bank-transfer reference renders instead.
    if (orderId === null) return;
    startCheckout({ ...data, provider_order_id: orderId });
  };

  if (capability.isLoading) return <PickerSkeleton />;
  if (capability.error) {
    return <ProblemNotice error={capability.error} onRetry={() => void capability.refetch()} />;
  }
  if (!capability.data) return null;

  /* BANK TRANSFER ONLY: card and UPI are not on for this account. Not an error and not an
     empty state — and the prices still render, because nobody can decide what to transfer
     without knowing what it buys. The server's authored reason is not shown: a client
     cannot act on "no_webhook_secret", and naming our missing secret leaks internals. */
  const bankOnly = !capability.data.online_payments_available;
  /** A RENDERING HINT for the button's words; the intent route is the authority (D-75). */
  const payable = capability.data.provider_orders_available;
  const busy = intent.isPending || stage.at === "opening" || stage.at === "open";
  const order = intent.data ?? null;
  const card = packs.data;
  const selected = card ? selection(card.packs, choice, amount) : null;
  const continueStatus: FeedbackStatus =
    stage.at === "opening" || stage.at === "open" || stage.at === "verifying"
      ? "pending"
      : intentFeedback.status;
  const payNowStatus: FeedbackStatus =
    stage.at === "opening" || stage.at === "open" || stage.at === "verifying"
      ? "pending"
      : stage.at === "failed" || stage.at === "blocked"
        ? "error"
        : confirmFeedback.status;

  const choose = (next: string) => {
    setChoice(next);
    // A changed choice withdraws an order prepared for the old one, unless money moved.
    if (order && (stage.at === "idle" || stage.at === "failed" || stage.at === "blocked")) {
      intent.reset();
      setStage({ at: "idle" });
    }
  };

  const proceed = () => {
    if (!selected || busy) return;
    setStage({ at: "idle" });
    // A pack posts its id, never an amount, so the catalogue is the price.
    intent.mutate(
      selected.kind === "pack" ? { packId: selected.pack.pack_id } : { amountInr: selected.amount },
      { onSuccess: onIntent },
    );
  };

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex-1 space-y-5">
        <RestrictionNote reason={write.reason} />

        {/* THE OUTCOME OF THE LAST PAYMENT, above the controls that would start another. */}
        {stage.at === "verified" && (
          <NoticeBox tone="ok" title="Payment received">
            {creditLanded ? (
              <p role="status">The credit has been added to your balance.</p>
            ) : (
              <p>Your balance updates when the payment is confirmed, usually within a minute.</p>
            )}
          </NoticeBox>
        )}
        {stage.at === "unverified" && (
          <div className="space-y-2">
            {/* The server owns this wording: a compliance-shaped refusal about money. */}
            <ProblemNotice error={confirm.error} />
            <NoticeBox tone="warn" title="Do not pay again">
              <p>
                We could not confirm this payment here. If the money has left your account,
                the credit is added when the payment is confirmed. Send us the reference
                below if your balance does not move.
              </p>
            </NoticeBox>
          </div>
        )}
        {stage.at === "failed" && <ProblemNotice error={PAYMENT_FAILED} />}
        {stage.at === "blocked" && <ProblemNotice error={stage.problem} />}
        {intent.error && <ProblemNotice error={intent.error} />}

        {order && (
          <OrderPanel
            order={order}
            paid={stage.at === "verified"}
            payNow={
              order.provider_order_id === null || stage.at === "verified" ? null : (
                /* Reopens the SAME order, so a window closed by accident never becomes
                   two orders for one top-up. */
                <ActionButton
                  status={payNowStatus}
                  pendingLabel={
                    stage.at === "opening"
                      ? "Opening the payment window"
                      : stage.at === "open"
                        ? "Payment window is open"
                        : "Confirming your payment"
                  }
                  successLabel="Paid"
                  // Unverified means the money may have moved: the notice says not to pay again.
                  disabled={!write.allowed || stage.at === "unverified"}
                  onClick={() =>
                    startCheckout({ ...order, provider_order_id: order.provider_order_id as string })
                  }
                >
                  Pay {formatINR(order.amount_inr)} now
                </ActionButton>
              )
            }
          />
        )}

        {bankOnly && (
          <div
            role="note"
            className="flex gap-3 rounded-card border border-line bg-surface-muted px-4 py-3 text-body"
          >
            <Landmark aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" />
            <p className="text-ink-muted">
              <span className="font-medium text-ink">Pay by bank transfer.</span> Card and
              UPI payment isn&rsquo;t on for your account yet. Talk to us for our bank
              details; the credit appears here once the transfer lands.
            </p>
          </div>
        )}

        {packs.isLoading && <PickerSkeleton />}
        {packs.error && <ProblemNotice error={packs.error} onRetry={() => void packs.refetch()} />}
        {card && (
          <PackPicker
            card={card}
            labels={labels}
            choice={choice}
            onChoose={choose}
            amount={amount}
            onAmount={setAmount}
            disabled={!write.allowed || busy}
            selected={selected}
          />
        )}
      </div>

      {/* ONE BUTTON, pinned to the bottom of the drawer so it is in reach on a phone
          whatever was scrolled. Not offered where card and UPI are off: the bank transfer
          needs no order from us. */}
      {card && !bankOnly && (
        <div className="sticky bottom-0 -mx-4 -mb-4 mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] sm:-mx-5 sm:px-5 sm:pb-3">
          <p className="min-w-0 text-body text-ink-muted" aria-live="polite">
            {selected ? (
              <>
                You pay{" "}
                <strong className="font-semibold tabular-nums text-ink">
                  {formatAmountINR(selected.amount)}
                </strong>
              </>
            ) : (
              "Choose an amount"
            )}
          </p>
          <ActionButton
            status={continueStatus}
            successLabel={payable ? "Ready to pay" : "Details ready"}
            disabled={!write.allowed || selected === null || busy}
            onClick={proceed}
          >
            {payable ? "Continue" : "Get payment details"}
          </ActionButton>
        </div>
      )}
    </div>
  );
}

/** The value of `choice` that means "Other amount", distinct from any pack id. */
const CUSTOM = "__custom__";

type Selection =
  | { kind: "pack"; pack: CreditPack; amount: string }
  | { kind: "custom"; pack: CreditPack; amount: string };

/**
 * What the reader has chosen, and the pack whose rates it buys at — or `null` while the
 * choice is incomplete. A free amount takes the rates of the largest pack it reaches (the
 * server's rule, `billing/service.py::lot_rates_for_amount`), and states nothing until it
 * is an amount the server would accept, so a half-typed figure never flickers a rate.
 */
function selection(packs: CreditPack[], choice: string, amount: string): Selection | null {
  if (choice === CUSTOM) {
    if (amount === "") return null;
    if (
      compareMoney(amount, String(MIN_TOPUP_INR)) < 0 ||
      compareMoney(amount, String(MAX_TOPUP_INR)) > 0
    ) {
      return null;
    }
    const pack = packForAmount(packs, amount);
    return pack ? { kind: "custom", pack, amount } : null;
  }
  const pack = packs.find((candidate) => candidate.pack_id === choice);
  return pack ? { kind: "pack", pack, amount: pack.amount_inr } : null;
}

/** Where a payment attempt has got to. `blocked` (Checkout would not load) is not `failed`. */
type Stage =
  | { at: "idle" }
  | { at: "opening" }
  | { at: "open" }
  | { at: "verifying" }
  | { at: "verified"; awaited: AwaitedCredit }
  | { at: "unverified" }
  | { at: "failed" }
  | { at: "blocked"; problem: ApiProblem };

/** A transition the provider's window may make only while it is still the live attempt. */
function whileOpen(next: Stage): (current: Stage) => Stage {
  return (current) => (current.at === "opening" || current.at === "open" ? next : current);
}

/** The same guard for the load→open step, which a fast dismissal can already have passed. */
function whileOpening(next: Stage): (current: Stage) => Stage {
  return (current) => (current.at === "opening" ? next : current);
}

/** Built once: the same sentence every time, without the vendor's own description. */
const PAYMENT_FAILED: ApiProblem = paymentFailedProblem();

/**
 * The order the server priced: the amount as it sent it (the figure a bank transfer must
 * match to the paisa), how to pay, and the references to quote.
 */
function OrderPanel({
  order,
  paid,
  payNow,
}: {
  order: TopUpIntent;
  paid: boolean;
  payNow: ReactNode;
}) {
  return (
    <div className="settings-enter rounded-card border border-line px-4 py-3.5 text-body text-ink-muted">
      <p className="font-semibold text-ink">
        {formatINR(order.amount_inr)}
        {paid ? " — paid." : " — nothing has been charged yet."}
      </p>
      {order.provider_order_id === null ? (
        <p className="mt-1">
          Card and UPI payment isn&rsquo;t on for your account yet. Transfer{" "}
          <strong className="font-semibold text-ink">{formatINR(order.amount_inr)}</strong> to
          us by bank transfer quoting the reference below, and the credit is added once the
          payment lands. Your balance will not change until then.
        </p>
      ) : paid ? (
        <p className="mt-1">Quote the references below if you need to ask us about this payment.</p>
      ) : (
        <>
          <p className="mt-1">
            The payment window opens on this page; your balance changes once the payment is
            confirmed.
          </p>
          <div className="mt-3">{payNow}</div>
        </>
      )}
      <p className="mt-2 text-meta text-ink-faint">
        ref <MonoValue>{order.receipt}</MonoValue>
      </p>
      {order.provider_order_id !== null && (
        <p className="text-meta text-ink-faint">
          order <MonoValue>{order.provider_order_id}</MonoValue>
        </p>
      )}
    </div>
  );
}

/**
 * THE PACK PICKER — "how much calling do I need?", answered in that order.
 *
 * - **A minutes field instead of a compare table.** What a reader can answer is roughly
 *   how many minutes a month they call; the pack follows. Rejected: a slider (invents
 *   precision, poor touch target) and a per-card hover (unreachable on a phone). The field
 *   is optional and the picker is complete without it. **It matches on the DEARER
 *   quality's minutes**, the one direction that cannot mislead: a pack that covers a month
 *   of Studio calling covers it on Clear too, and the voice is chosen per agent, later.
 * - **Radio cards, not a button per card.** One selection and one button at the bottom: a
 *   grid of six "Pay" buttons was six competing primary actions.
 * - **The rate is stated once, for the selection.** Every pack has its own pair of rates
 *   (a bigger pack buys a cheaper minute, D-547); repeating both on all six cards was the
 *   noise the founder named. The card carries what a reader compares — the amount and the
 *   minutes — and the line under the grid carries the price of the one they chose.
 *
 * The catalogue is rendered as sent: no pack count or price is assumed here.
 */
function PackPicker({
  card,
  labels,
  choice,
  onChoose,
  amount,
  onAmount,
  disabled,
  selected,
}: {
  card: CreditPacks;
  labels: TierLabels | undefined;
  choice: string;
  onChoose: (choice: string) => void;
  amount: string;
  onAmount: (amount: string) => void;
  disabled: boolean;
  selected: Selection | null;
}) {
  const [monthly, setMonthly] = useState("");
  const fieldId = useId();
  const hintId = useId();
  const name = useId();
  const wanted = wantedMinutes(monthly);
  const match = wanted === null ? null : suggestPack(card.packs, wanted);
  const lapse = card.credit_expiry_months ? lapseDateFromToday(card.credit_expiry_months) : null;

  return (
    <div className="space-y-5">
      {/* Not a `<form>`: nothing is submitted. The answer is a rendering of the catalogue
          already on screen. */}
      <div>
        <label htmlFor={fieldId} className="block text-body font-medium text-ink">
          Minutes you call in a month
        </label>
        <span id={hintId} className={FIELD_HINT}>
          Optional — we&rsquo;ll pick the pack that covers it.
        </span>
        <div className={`${FIELD_GROUP} mt-2 w-full max-w-56`}>
          <input
            id={fieldId}
            aria-describedby={hintId}
            inputMode="numeric"
            autoComplete="off"
            value={monthly}
            placeholder="600"
            onChange={(event) => {
              const next = event.target.value;
              setMonthly(next);
              const minutes = wantedMinutes(next);
              const found = minutes === null ? null : suggestPack(card.packs, minutes);
              if (found) onChoose(found.pack.pack_id);
            }}
            className={`${FIELD_GROUP_INPUT} pl-3 tabular-nums`}
          />
          <span aria-hidden className="flex shrink-0 items-center pr-3 text-meta text-ink-muted">
            min a month
          </span>
        </div>
        {/* The live region EXISTS before it has anything to say: one inserted at the moment
            of the update is not reliably announced. */}
        <p
          role="status"
          aria-label="Which pack covers your month"
          className="answer-reveal mt-1.5 min-h-5 text-meta text-brand-strong dark:text-brand-bright"
          key={match ? `${match.pack.pack_id}-${match.short}` : monthly.trim() === "" ? "empty" : "bad"}
        >
          {monthly.trim() !== "" && wanted === null
            ? "Enter the minutes as digits, like 600."
            : match && wanted !== null
              ? matchSentence(match, wanted)
              : ""}
        </p>
      </div>

      <fieldset className="min-w-0" disabled={disabled}>
        <legend className="text-body font-medium text-ink">Amount to add</legend>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {card.packs.map((pack) => {
            const fits = match !== null && match.pack.pack_id === pack.pack_id;
            return (
              <ChoiceCard
                key={pack.pack_id}
                name={name}
                value={pack.pack_id}
                checked={choice === pack.pack_id}
                disabled={disabled}
                onChange={(on) => on && onChoose(pack.pack_id)}
              >
                <span className="flex items-baseline justify-between gap-2">
                  <span className="text-heading tabular-nums text-ink">
                    {formatAmountINR(pack.amount_inr)}
                  </span>
                  {fits ? (
                    <span className="text-meta font-semibold text-brand-strong dark:text-brand-bright">
                      Fits your month
                    </span>
                  ) : pack.best_value ? (
                    <span className="text-meta font-semibold text-brand-strong dark:text-brand-bright">
                      Best value
                    </span>
                  ) : null}
                </span>
                <span className="mt-0.5 block text-meta tabular-nums text-ink-muted">
                  {labels
                    ? VOICE_TIERS.map(
                        (tier) => `${formatCount(packMinutes(pack, tier))} min ${labels[tier]}`,
                      ).join(" · ")
                    : `${formatWhole(pack.total_credits)} credits of calling`}
                </span>
              </ChoiceCard>
            );
          })}
          <ChoiceCard
            name={name}
            value={CUSTOM}
            checked={choice === CUSTOM}
            disabled={disabled}
            onChange={(on) => on && onChoose(CUSTOM)}
            label="Other amount"
            hint={`${formatAmountINR(String(MIN_TOPUP_INR))} to ${formatAmountINR(String(MAX_TOPUP_INR))}`}
          />
        </div>
      </fieldset>

      {choice === CUSTOM && (
        <MoneyInput
          label="Other amount"
          value={amount}
          onChange={onAmount}
          min={String(MIN_TOPUP_INR)}
          max={String(MAX_TOPUP_INR)}
          disabled={disabled}
          className="settings-enter"
        />
      )}

      {/* THE RATE, ONCE, for what is chosen — before the button, because the rates a
          purchase freezes are fixed the moment it lands (D-547). Named for both qualities
          or not printed at all. */}
      <div className="space-y-1.5 text-body text-ink-muted">
        <p role="status" aria-label="What this amount buys" className="text-ink">
          {selected && labels ? <RatesSentence selected={selected} labels={labels} /> : null}
        </p>
        {labels && (
          /* The client sets the voice themselves (D-586): `PATCH /v1/agents/{id}/voice` is
             on `owner` and `staff`, with the picker on their own agent screen. */
          <p>
            Every pack buys both voice qualities, and the rate a call uses is set per agent —
            you choose that on each agent&rsquo;s own screen.
          </p>
        )}
        {lapse && (
          <p>
            Credit you buy now lasts {card.credit_expiry_months} months, until {lapse}. Credit
            you already hold keeps the terms it was bought on.
          </p>
        )}
      </div>
    </div>
  );
}

function RatesSentence({ selected, labels }: { selected: Selection; labels: TierLabels }) {
  return (
    <>
      {formatAmountINR(selected.amount)} buys calling at{" "}
      {VOICE_TIERS.map((tier, index) => (
        <span key={tier}>
          {index > 0 ? " and " : ""}
          <strong className="font-semibold tabular-nums">
            {formatRateINR(packRate(selected.pack, tier))}/min
          </strong>{" "}
          on {labels[tier]}
        </span>
      ))}
      {selected.kind === "custom" ? (
        <> — the {formatAmountINR(selected.pack.amount_inr)} pack&rsquo;s rates.</>
      ) : (
        "."
      )}{" "}
      <span className="text-ink-muted">They stay with this credit until it is spent.</span>
    </>
  );
}

/** Skeleton in the picker's own shape: a field, then a grid of cards. */
function PickerSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton rows={1} label="Loading credit packs" />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" aria-hidden>
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className="h-[4.25rem] animate-pulse rounded-card bg-ink/[0.05] motion-reduce:animate-none" />
        ))}
      </div>
    </div>
  );
}

/**
 * The minutes a reader typed, or `null` if they have not typed a usable number. Digits
 * only, deliberately not `parseInt` (`parseInt("600 or so")` is 600). A count of minutes is
 * not money, so `Number` is right here; capped so a pasted essay of digits cannot produce
 * an absurd sentence.
 */
function wantedMinutes(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d{1,7}$/.test(trimmed)) return null;
  const minutes = Number(trimmed);
  return minutes > 0 ? minutes : null;
}

/** The sentence the matcher speaks. The card it selected shows the minutes themselves. */
function matchSentence(match: { pack: CreditPack; short: boolean }, wanted: number): string {
  const amount = formatAmountINR(match.pack.amount_inr);
  if (match.short) {
    return `${formatCount(wanted)} minutes a month is more than one pack. The largest is ${amount} — add credit more than once, or turn on auto top-up.`;
  }
  return `${amount} covers ${formatCount(wanted)} minutes a month on either voice.`;
}

/**
 * The smallest pack whose talk time covers a month — or, when nothing does, the largest
 * and a flag saying so. Matched on the DEARER quality (see `PackPicker`); sorted here
 * because nothing in `CreditPacksOut` promises an order. Both figures are the server's own
 * floor of its own division, so this compares two numbers it sent and prices nothing.
 */
function suggestPack(
  packs: CreditPack[],
  minutes: number,
): { pack: CreditPack; short: boolean } | null {
  const ascending = [...packs].sort(
    (a, b) => packMinutes(a, "studio") - packMinutes(b, "studio"),
  );
  const largest = ascending[ascending.length - 1];
  if (largest === undefined) return null;
  const covering = ascending.find((pack) => packMinutes(pack, "studio") >= minutes);
  return covering ? { pack: covering, short: false } : { pack: largest, short: true };
}
