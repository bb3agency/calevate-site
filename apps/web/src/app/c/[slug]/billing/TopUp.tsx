"use client";

import { useId, useState } from "react";

import {
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  formatCount,
  formatINR,
  formatRupeeRate,
} from "@/components/ui";
import {
  MAX_TOPUP_INR,
  MIN_TOPUP_INR,
  useConfirmTopUp,
  useCreditPacks,
  useTopUpCapability,
  useTopUpIntent,
  type CreditPack,
  type TopUpIntent,
} from "@/lib/api/billing";
import { useWriteAccess } from "@/lib/api/hooks";
import { openRazorpayCheckout, paymentFailedProblem } from "@/lib/razorpayCheckout";
import type { ApiProblem, Session } from "@/lib/api/client";

import {
  VOICE_TIERS,
  formatWhole,
  packForAmount,
  packMinutes,
  packRate,
  readTierLabels,
  type TierLabels,
} from "./lots";

/**
 * Adding credit — all the way to a completed payment.
 *
 * The symptom this closed: the server minted a real Razorpay order and the browser
 * dead-ended on it. `POST /v1/billing/topups/intent` returned `key_id`,
 * `provider_order_id` and `amount_paise` — everything Checkout needs — and the screen
 * printed the order id as a reference to email somebody. A prepaid client whose wallet
 * emptied could not pay, on a product whose outbound calling stops when it does.
 *
 * ## The four outcomes, and why each has its own state
 *
 * A payment window has more ways to end than a request does, and three of the four are
 * not failures of ours:
 *
 * - **paid** → the three fields go to `POST /v1/billing/topups/callback`, which verifies
 *   the signature with the key secret SERVER-SIDE. We never assert a new balance: the
 *   callback carries no amount, the webhook is the single writer, and `credit_pending` is
 *   `true` on every successful response by construction. So the sentence is "received,
 *   updating" and the balance reads are invalidated (`useConfirmTopUp`).
 * - **dismissed** → the client closed the window. Not an error, not a failure notice, and
 *   emphatically not a spinner left running: the panel returns to exactly the state it was
 *   in, with the order still live so the same "Pay" button reopens it rather than minting
 *   a second order.
 * - **failed** → the provider reported a failed attempt. Rendered as OUR problem sentence
 *   through `ProblemNotice`, never the vendor's string (`paymentFailedProblem`).
 * - **not verified** → the callback was refused. This is the one outcome that must not
 *   look like success, and it is also the one where the client's money may genuinely have
 *   moved. The server's own words are rendered (it owns that wording), and beneath them
 *   the one fact that is ours to state: the wallet is credited by the webhook, so a real
 *   payment still lands without this page.
 *
 * ## The state machine is MONOTONIC, deliberately
 *
 * `lib/razorpayCheckout.ts` forwards the provider's three callbacks raw, because Checkout
 * fires `ondismiss` when it closes — including after a successful payment, and possibly
 * after a failed attempt the client then retries inside the window. A "first callback
 * wins" rule at that seam gets one of those two wrong. Here, `dismissed` and `failed` may
 * only move a stage that is still `opening`/`open`; once a payment exists we are
 * `verifying` and nothing walks that back. Money moving is the one transition that must
 * not be undone by a window closing.
 */
export function TopUp({ session }: { session: Session }) {
  const [amount, setAmount] = useState("");
  const capability = useTopUpCapability(session);
  const intent = useTopUpIntent(session);
  const packs = useCreditPacks(session);
  const confirm = useConfirmTopUp(session);
  const [stage, setStage] = useState<Stage>({ at: "idle" });
  // Which control the in-flight intent belongs to, so only the pack the client clicked
  // (or the custom row) shows its spinner — never every button at once.
  const [pending, setPending] = useState<string | null>(null);
  // `org:manage` is what the endpoint requires — staff should see the balance and not a
  // form that will 403 them, and an operator in "view as client" cannot spend a client's
  // money from a client screen (D-22).
  const write = useWriteAccess(session, "org:manage", "add credit");
  /* WHAT A CLIENT CALLS EACH VOICE QUALITY, read from the card the server sent and held
     nowhere else. No client-facing surface names a vendor as a tier (founder, 7 Sep 2026),
     so a build whose card carries no labels prints no quality names and no per-minute
     rates — an unnamed pair of rupee figures beside one another is worse than silence,
     because a reader assigns the cheaper one to whichever voice they were thinking of. */
  const labels = readTierLabels(packs.data);

  /**
   * Open the provider's window for an order the SERVER created.
   *
   * Every value handed over is the server's, copied and not computed — `amount_paise` in
   * particular is the integer the order itself was created with (hard rule 7: a second
   * rupee-to-paise conversion in the browser would be a second source of the number, and
   * its failure mode is charging a different amount than the one agreed).
   *
   * Nothing is prefilled. The intent carries no email and no phone, and inventing one
   * from the session would put a contact detail into a third party's form that nobody
   * asked us to send (hard rule 6's neighbour).
   */
  const startCheckout = (order: TopUpIntent & { provider_order_id: string }) => {
    setStage({ at: "opening" });
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
          onSuccess: () => setStage({ at: "verified" }),
          onError: () => setStage({ at: "unverified" }),
        });
      },
      onDismissed: () => setStage(whileOpen({ at: "idle" })),
      onFailed: () => setStage(whileOpen({ at: "failed" })),
    })
      .then(() => setStage(whileOpening({ at: "open" })))
      .catch((error: unknown) => {
        // The script did not load, or left no constructor behind. `openRazorpayCheckout`
        // rejects with an `ApiProblem` precisely so this renders as a sentence with a way
        // forward rather than as "Something went wrong".
        setStage({ at: "blocked", problem: error as ApiProblem });
      });
  };

  const onIntent = (data: TopUpIntent) => {
    const orderId = data.provider_order_id;
    // No order means no checkout — the manual reference path, unchanged. The capability
    // hint said the same thing before the click; this is the authority saying it after.
    if (orderId === null) return;
    startCheckout({ ...data, provider_order_id: orderId });
  };

  if (capability.isLoading) return <Skeleton rows={2} />;
  if (capability.error) {
    return (
      <div className="mt-4 border-t border-line pt-4">
        <ProblemNotice error={capability.error} onRetry={() => void capability.refetch()} />
      </div>
    );
  }
  if (!capability.data) return null;

  if (!capability.data.online_payments_available) {
    /* Not an empty state and not an error: a true statement about this deployment, with
       the path that works. The server's authored reason is deliberately NOT shown — a
       client cannot act on "no_webhook_secret" and naming our missing secret is an
       internals leak.

       THE PRICES STILL RENDER, AND THAT IS THE POINT OF THIS BRANCH RATHER THAN AN
       ADDITION TO IT. This used to `return` here, before the rate card — so on every
       deployment that cannot take a card (which is all of them until a provider account
       exists) a client opened "Add credit" and found one sentence: no packs, no prices,
       no idea what any of it costs. They cannot decide what to transfer without knowing
       what a pack buys, so the branch that removes the BUTTON must not also remove the
       PRICE LIST. `read_credit_packs` reads no tenant state and no provider state — the
       catalogue is the same for everyone and is as true on a bank-transfer deployment as
       on a card one. */
    return (
      <div className="mt-4 space-y-4 border-t border-line pt-4">
        <p className="text-sm text-ink-muted">
          We cannot take card or UPI payment on this account yet. To add credit, transfer
          the amount to us by bank — talk to your account manager for the details — and
          the credit appears here once the payment lands. The packs below are what each
          amount buys.
        </p>
        {packs.isLoading && <Skeleton rows={4} />}
        {packs.error && (
          <ProblemNotice error={packs.error} onRetry={() => void packs.refetch()} />
        )}
        {packs.data && (
          <PackChooser
            packs={packs.data.packs}
            labels={labels}
            payable={false}
            disabled
            pendingPackId={null}
            onSelect={() => undefined}
          />
        )}
      </div>
    );
  }

  /**
   * Will a click on these controls end in a payment window?
   *
   * A RENDERING HINT and never the check — the intent route asks the same selector
   * server-side and remains the authority (D-75), so a stale `true` costs a reference
   * panel instead of a checkout and can never cost a payment. What it decides is the
   * BUTTON LABEL, and that is worth deciding: "Pay" on a deployment that can only mint a
   * reference is a promise the click cannot keep, and "Get payment details" on one that
   * opens a card form is the opposite mistake.
   */
  const payable = capability.data.provider_orders_available;
  const busy = intent.isPending || stage.at === "opening" || stage.at === "open";
  const order = intent.data ?? null;

  return (
    <div className="mt-4 space-y-4 border-t border-line pt-4">
      <RestrictionNote reason={write.reason} />

      {/* THE OUTCOME OF THE LAST PAYMENT, above the controls that would start another —
          UX-DOCTRINE §4. A client who has just paid must not have to look past a rate
          card to find out whether it worked. */}
      {stage.at === "verified" && (
        <NoticeBox tone="ok" title="Payment received">
          <p>
            We have confirmed this payment with the provider. Your balance updates as soon
            as the payment provider confirms it to us — usually within a minute. Nothing
            else is needed from you.
          </p>
        </NoticeBox>
      )}

      {stage.at === "unverified" && (
        <div className="space-y-2">
          {/* The server owns this wording — it is a compliance-shaped refusal about
              money, and a paraphrase would be a second implementation of it. */}
          <ProblemNotice error={confirm.error} />
          <NoticeBox tone="warn" title="What happens next">
            <p>
              We could not verify this payment here, so we are not treating it as
              successful. If the amount has left your account, your credit is still added
              automatically when the payment provider confirms the payment to us — that
              confirmation does not come through this page. Do not pay again; send us the
              reference below if the balance has not moved.
            </p>
          </NoticeBox>
        </div>
      )}

      {stage.at === "failed" && <ProblemNotice error={PAYMENT_FAILED} />}
      {stage.at === "blocked" && <ProblemNotice error={stage.problem} />}
      {stage.at === "verifying" && (
        <p role="status" className="text-sm text-ink-muted">
          Confirming your payment…
        </p>
      )}

      {intent.error && <ProblemNotice error={intent.error} />}

      {/* The pack rate card — the productized way to add credit. A bigger pack buys a
          cheaper minute on both voice qualities (D-547); the rates and the talk times are
          the server's own figures, and the pack a client picks freezes its two rates on
          the credit it opens. */}
      {packs.isLoading && <Skeleton rows={4} />}
      {packs.error && <ProblemNotice error={packs.error} onRetry={() => void packs.refetch()} />}
      {packs.data && (
        <>
          <PackChooser
            packs={packs.data.packs}
            labels={labels}
            payable={payable}
            disabled={!write.allowed || busy}
            pendingPackId={intent.isPending ? pending : null}
            onSelect={(packId) => {
              setPending(packId);
              setStage({ at: "idle" });
              intent.mutate({ packId }, { onSuccess: onIntent });
            }}
          />
          {/* ONE LINE UNDER THE PRICES. It used to say every pack buys the same voice, which
              was true of a one-quality catalogue and is now false: a pack quotes TWO rates
              and which one prices a call depends on the voice the agent that took it speaks
              with. What survives is the sentence that has to be read next to the numbers —
              the price you buy at is fixed on the purchase, so a rate change later leaves
              credit you already own alone. `WhatCallsCost` argues both properly on the same
              screen. Only rendered with the names, for `labels`' reason above. */}
          {labels && (
            <p className="text-sm text-ink-muted">
              Every pack buys both voice qualities — you choose which one each agent speaks
              with. A bigger pack makes each minute cheaper, and the rates on the pack you
              buy stay with that credit until you have spent it.
            </p>
          )}
        </>
      )}

      {/* An "other amount" for a client who wants a figure that is not a pack. Same route,
          and it is NOT rateless: a free amount takes the rates of the largest pack whose
          price it reaches (plan §0 Q3), so somebody typing ₹4,999 is not punished for
          missing a rung by a rupee. */}
      <form
        className="flex flex-wrap items-center gap-2"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          setPending(CUSTOM);
          setStage({ at: "idle" });
          intent.mutate({ amountInr: amount }, { onSuccess: onIntent });
        }}
      >
        <label htmlFor="topup-amount" className="text-sm text-ink-muted">
          Other amount
        </label>
        <span className="text-sm text-ink-faint">₹</span>
        <input
          id="topup-amount"
          inputMode="decimal"
          value={amount}
          disabled={!write.allowed}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="2000"
          className="w-32 rounded-md border border-line bg-surface px-2 py-1 text-sm tabular-nums text-ink placeholder:text-ink-faint disabled:opacity-50 touch:min-h-11"
        />
        <button
          type="submit"
          disabled={!write.allowed || !amount.trim() || busy}
          className={SECONDARY_BUTTON}
        >
          {intent.isPending && pending === CUSTOM
            ? "Working…"
            : payable
              ? "Pay this amount"
              : "Get payment details"}
        </button>
        <span className="text-xs text-ink-faint">
          ₹{MIN_TOPUP_INR.toLocaleString("en-IN")} to ₹{MAX_TOPUP_INR.toLocaleString("en-IN")}
        </span>
        {/* WHAT THIS AMOUNT BUYS AT, BEFORE THE BUTTON. A free amount is priced by the
            server at the largest pack it reaches, and a client who cannot see that before
            paying discovers their rates afterwards — on a purchase whose terms are then
            frozen and cannot be corrected. It is a full-width row of the same form so it
            sits under the field on a phone rather than beside it. */}
        {packs.data && labels && (
          <p
            role="status"
            aria-label="What this amount buys"
            className="w-full text-sm text-brand-strong"
          >
            <AmountRates packs={packs.data.packs} labels={labels} amount={amount} />
          </p>
        )}
      </form>

      {order && (
        <div className="rounded-card border border-line bg-app p-3 text-sm text-ink-muted">
          {/* The amount the SERVER priced, as it sent it — this is the figure a bank
              transfer has to match to the paisa, and the figure the provider's window is
              opened with. */}
          <p className="font-semibold text-ink">
            {formatINR(order.amount_inr)}
            {stage.at === "verified" ? " — paid." : " — nothing has been charged yet."}
          </p>
          {order.provider_order_id === null ? (
            <p className="mt-1">
              We cannot take card or UPI payment on this account yet. Transfer{" "}
              <strong className="font-semibold text-ink">{formatINR(order.amount_inr)}</strong>{" "}
              to us by bank transfer quoting the reference below, or send this reference to
              your account manager, and the credit is added once the payment lands. Your
              balance above will not change until then.
            </p>
          ) : stage.at === "verified" ? (
            <p className="mt-1">
              Quote the references below if you need to ask us about this payment.
            </p>
          ) : (
            <>
              <p className="mt-1">
                A payment for{" "}
                <strong className="font-semibold text-ink">{formatINR(order.amount_inr)}</strong>{" "}
                is ready. The payment window opens on this page; your balance changes once
                the payment is confirmed.
              </p>
              {/* Reopening uses the SAME order rather than starting a new intent, which is
                  the whole reason a dismissal keeps the panel: a client who closed the
                  window by accident should not end up with two orders against one
                  top-up. */}
              <button
                type="button"
                disabled={!write.allowed || busy || stage.at === "verifying"}
                onClick={() =>
                  startCheckout({ ...order, provider_order_id: order.provider_order_id as string })
                }
                className={`${PRIMARY_BUTTON} mt-3`}
              >
                {stage.at === "opening"
                  ? "Opening…"
                  : stage.at === "open"
                    ? "Payment window is open"
                    : `Pay ${formatINR(order.amount_inr)} now`}
              </button>
            </>
          )}
          <p className="mt-2 text-xs text-ink-faint">
            ref <MonoValue>{order.receipt}</MonoValue>
          </p>
          {order.provider_order_id !== null && (
            <p className="text-xs text-ink-faint">
              order <MonoValue>{order.provider_order_id}</MonoValue>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** The custom-amount row's spinner key, distinct from any pack id the catalogue can hold. */
const CUSTOM = "__custom__";

/**
 * Where a payment attempt has got to.
 *
 * `blocked` (Checkout would not load) is separate from `failed` (Checkout ran and the
 * payment did not go through) because they are different sentences with different ways
 * out — one is about this browser, the other is about a card.
 */
type Stage =
  | { at: "idle" }
  | { at: "opening" }
  | { at: "open" }
  | { at: "verifying" }
  | { at: "verified" }
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

/**
 * The authored "it did not go through" sentence, built once.
 *
 * `paymentFailedProblem()` takes no arguments and produces the same sentence every time,
 * so a fresh object per render would hand `ProblemNotice` a new identity to re-render on
 * and nothing else. The vendor's own description is deliberately not in it — see
 * `lib/razorpayCheckout.ts` for why a third party's string is not shown to a client.
 */
const PAYMENT_FAILED: ApiProblem = paymentFailedProblem();

/**
 * THE PACK CHOOSER — "how much calling do I need?", answered in that order.
 *
 * ## What this replaced, and why a table was the wrong shape
 *
 * It was a six-column table: You pay / Credits / Free / Effective rate / Talk time / the
 * button, one row per pack, borrowed wholesale from the competitor the founder had
 * benchmarked. Two things were wrong with it and only one of them is taste.
 *
 * The taste half: it was somebody else's table, and it looked it.
 *
 * The half that matters: **a table answers "what do these six packs cost?" and nobody
 * arrives with that question.** They arrive with "how much calling do I need, and what
 * does that come to?" — and a table makes the reader do the division themselves, across
 * six columns, on a phone, before they can act. ₹4.6296/min is the unit an accountant
 * thinks in; "about 10,800 minutes" is the unit somebody running a phone line thinks in.
 * Both are here. The talk time leads and the rupees follow.
 *
 * ## TWO RATES AND TWO TALK TIMES, AND THE "EXTRA CREDIT" COLUMN IS GONE (D-547)
 *
 * A pack no longer grants bonus credits; a bigger pack buys a CHEAPER MINUTE, on each of
 * the two voice qualities, and the rates it quotes are frozen on the purchase. So the card
 * carries a pair of everything and the bonus line was DELETED rather than emptied —
 * `bonus_pct` and `bonus_credits` are still on the wire at zero for one release (plan §10)
 * and rendering "no bonus credit" off them would keep a retired idea on the screen a client
 * buys from. What replaced it is the fact that actually differs between the rungs.
 *
 * The two qualities are named by the SERVER (`CreditPacksOut.*_tier_label`). Without those
 * names this renders no rate and no talk time at all: two unnamed rupee figures side by
 * side are worse than none, because a reader assigns the cheaper one to whichever voice
 * they had in mind, and no client-facing surface may fall back to the vendor's word.
 *
 * ## What was chosen, and what was rejected
 *
 * - **Cards, not rows.** A row's cells are only legible beside their header, which is why
 *   the table needed `min-w-[36rem]` and a sideways scroll on the phone this is read on.
 *   A card carries its own labels, so it reads at 320px and wraps instead of scrolling.
 * - **The recommendation is CARRIED by the card**, not bolted on: the best-value pack has
 *   the brand border, the tinted ground and a full-width band across its top.
 * - **A minutes matcher instead of a "compare" toggle.** REJECTED: a slider (invents
 *   precision the reader does not have and is a poor touch target), and a per-card "how
 *   many minutes is this?" hover (unreachable on a phone, invisible to a screen reader).
 *   What the reader can actually answer is roughly how many minutes a month they call, and
 *   from that the pack follows — so that is the one input, it is optional, and the panel
 *   is complete without it. **It matches on the DEARER quality's minutes**, which is the
 *   one direction that cannot mislead: a pack that covers a month of Studio calling covers
 *   it on Clear too, and the reverse recommendation would fall short for anybody who picks
 *   the dearer voice after buying.
 *
 * ## The rules this stayed inside
 *
 * Every figure is the SERVER's, rendered from its digits — `formatINR` for amounts,
 * `formatRupeeRate` for the rates (a rate is not a rupee amount and must not be rounded
 * like one), `formatWhole` for the credit counts. No money is put through `Number` here
 * (hard rule 7 reaches the browser). Nothing is hardcoded about how many packs exist or
 * what they cost: the catalogue is whatever `GET /v1/billing/topups/packs` sent, in the
 * order it sent it.
 *
 * The accessible name of every buy control still carries its AMOUNT, because a grid of
 * buttons all reading "Pay" is a list of identical controls in a screen reader and the
 * price is the only thing that tells them apart.
 */
function PackChooser({
  packs,
  labels,
  payable,
  disabled,
  pendingPackId,
  onSelect,
}: {
  packs: CreditPack[];
  /** What a client calls each quality, from the card. Absent = no names, so no prices. */
  labels: TierLabels | undefined;
  payable: boolean;
  disabled: boolean;
  pendingPackId: string | null;
  onSelect: (packId: string) => void;
}) {
  const [monthly, setMonthly] = useState("");
  // `useId` rather than a literal: this panel renders on two tabs of one hub, and two
  // inputs sharing an id would make the second label point at the first field.
  const fieldId = useId();
  const wanted = wantedMinutes(monthly);
  const match = wanted === null ? null : suggestPack(packs, wanted);

  return (
    <div className="space-y-3">
      {/* Not a `<form>`: there is nothing to submit and no request behind it. The answer
          is a rendering of the catalogue already on screen, so an Enter key that appeared
          to "search" would be a promise of a round trip that never happens. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-card border border-line bg-app px-3 py-2">
        <label htmlFor={fieldId} className="text-sm text-ink">
          Roughly how many minutes do you call in a month?
        </label>
        <input
          id={fieldId}
          inputMode="numeric"
          value={monthly}
          onChange={(event) => setMonthly(event.target.value)}
          placeholder="600"
          className="w-20 rounded-md border border-line bg-surface px-2 py-1 text-sm tabular-nums text-ink placeholder:text-ink-faint touch:min-h-11"
        />
        <span className="text-sm text-ink-muted">minutes</span>
      </div>

      {/* The live region EXISTS before it has anything to say — a `role="status"` element
          inserted at the moment of the update is not reliably announced, because assistive
          technology subscribes to the region rather than to the insertion. */}
      <p
        role="status"
        /* NAMED, because this panel now holds a second live region — the one under the
           free-amount field — and two unnamed status regions are two controls a screen
           reader (and a test) cannot tell apart. */
        aria-label="Which pack covers your month"
        className="min-h-5 text-sm text-brand-strong"
      >
        {monthly.trim() !== "" && wanted === null
          ? "Enter the number of minutes as digits — 600, say."
          : match
            ? matchSentence(match, wanted as number, labels)
            : ""}
      </p>

      {/* A LIST, because that is what it is: a screen reader announces how many packs
          there are before the reader commits to walking them. */}
      <ul aria-label="Prepaid credit packs" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {packs.map((pack) => {
          const covers = match !== null && match.pack.pack_id === pack.pack_id;
          return (
            <li
              key={pack.pack_id}
              className={`flex flex-col overflow-hidden rounded-card border p-4 ${
                pack.best_value ? "border-brand bg-brand-soft" : "border-line bg-surface"
              } ${covers ? "ring-2 ring-brand" : ""}`}
            >
              {pack.best_value && (
                <p className="-mx-4 -mt-4 mb-3 bg-brand-strong px-4 py-1 text-[11px] font-bold uppercase tracking-wide text-white">
                  Best value
                </p>
              )}
              {covers && (
                <p className="mb-1 text-xs font-semibold text-brand-strong">
                  Covers your month
                </p>
              )}
              <p className="text-2xl font-semibold tabular-nums text-ink">
                {formatINR(pack.amount_inr)}
              </p>
              <p className="text-sm text-ink-muted">
                {formatWhole(pack.total_credits)} credits of calling
              </p>
              {labels && (
                /* THE PAIR, one row per quality: what a minute costs on it and how long
                   the credits last at that price. A `<dl>` rather than two sentences
                   because it is two labelled values and a screen reader reads it as
                   such. Both figures are the server's — the minutes are ITS floor of the
                   division, not one taken here. */
                <dl className="mt-3 space-y-1 text-sm">
                  {VOICE_TIERS.map((tier) => (
                    <div key={tier} className="flex items-baseline justify-between gap-2">
                      <dt className="text-ink-muted">{labels[tier]}</dt>
                      <dd className="tabular-nums text-ink">
                        <strong className="font-semibold">
                          {formatRupeeRate(packRate(pack, tier))}
                        </strong>
                        /min · {formatCount(packMinutes(pack, tier))} min
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              {/* `mt-auto` on the WRAPPER so every button sits on the same line whatever
                  the card above it says — a grid whose actions are at four different
                  heights reads as four unrelated things. */}
              <div className="mt-auto pt-4">
                {/* THE AMOUNT IS IN THE VISIBLE LABEL, which is why there is no
                    `aria-label` here any more and why removing it is not a regression of
                    the property the table had. The table's cells carried the price and the
                    button said only "Pay", so the accessible name had to be repaired with
                    an `aria-label` — six identically-named controls in a screen reader's
                    list otherwise. A card's button has room for the price itself, so the
                    name is now the same string a sighted reader sees, which also keeps
                    WCAG 2.5.3 (Label in Name) honest for voice control: "click Pay fifty
                    thousand" hits the right one. An `aria-label` fixed at the amount while
                    the visible text said "Working…" would break exactly that. */}
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onSelect(pack.pack_id)}
                  className={`${PRIMARY_BUTTON} w-full justify-center`}
                >
                  {pendingPackId === pack.pack_id
                    ? "Working…"
                    : payable
                      ? `Pay ${formatINR(pack.amount_inr)}`
                      : `Select ${formatINR(pack.amount_inr)}`}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * WHAT A TYPED AMOUNT BUYS AT, in words, before the payment button.
 *
 * A free amount is priced by the server at the largest pack it reaches, and the smallest
 * pack's rates below the first rung (`billing/service.py::lot_rates_for_amount`). Those
 * rates are FROZEN on the purchase the moment it lands, so a client who only learns them
 * from the wallet afterwards has bought terms they never saw. This says them first.
 *
 * It states no rate until the amount is a figure the server would accept — a half-typed
 * "34" is not an amount, and quoting the smallest pack's rates against it would flicker a
 * different answer with every keystroke. Nothing is computed: the rates are the catalogue's
 * own digits and the pack is chosen by comparing them.
 */
function AmountRates({
  packs,
  labels,
  amount,
}: {
  packs: CreditPack[];
  labels: TierLabels;
  amount: string;
}) {
  const typed = amount.trim();
  if (typed === "") return null;
  const pack = packForAmount(packs, typed);
  if (pack === undefined) return null;
  return (
    <>
      {formatINR(typed)} buys calling at{" "}
      {VOICE_TIERS.map((tier, index) => (
        <span key={tier}>
          {index > 0 ? " and " : ""}
          <strong className="font-semibold tabular-nums">
            {formatRupeeRate(packRate(pack, tier))}
          </strong>
          /min on {labels[tier]}
        </span>
      ))}
      {" — the "}
      {formatINR(pack.amount_inr)} pack&rsquo;s rates. They stay with this credit until you
      have spent it.
    </>
  );
}

/**
 * The minutes a reader typed, or `null` if they have not typed a usable number.
 *
 * Digits only, and deliberately not `parseInt`: `parseInt("600 or so")` is 600, which
 * would answer a question the reader did not ask. A count of minutes is not money, so
 * `Number` is the right instrument here and hard rule 7 is not in play — but the guard
 * still refuses anything that is not a plain positive integer, and caps it so a pasted
 * essay of digits cannot produce an absurd sentence.
 */
function wantedMinutes(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d{1,7}$/.test(trimmed)) return null;
  const minutes = Number(trimmed);
  return minutes > 0 ? minutes : null;
}

/**
 * The sentence the matcher speaks, and the reason it names BOTH figures.
 *
 * A pack's talk time is now a pair, and which one applies is decided later, on a different
 * screen, by whoever picks each agent's voice. So the recommendation is made on the DEARER
 * quality (see `suggestPack`) and the sentence says both numbers: "₹5,000 covers it — about
 * 714 minutes on Studio and 1,000 on Clear" is a fact a reader can act on, while a single
 * figure would be a promise that holds for only one of the two choices in front of them.
 *
 * Without the server's names for the qualities it says only what it can: the pack, and that
 * it covers the month whichever voice they choose.
 */
function matchSentence(
  match: { pack: CreditPack; short: boolean },
  wanted: number,
  labels: TierLabels | undefined,
): string {
  const amount = formatINR(match.pack.amount_inr);
  const dear = formatCount(packMinutes(match.pack, "cartesia"));
  const cheap = formatCount(packMinutes(match.pack, "sarvam"));
  const spread = labels
    ? ` — about ${dear} minutes on ${labels.cartesia} and ${cheap} on ${labels.sarvam}`
    : "";
  if (match.short) {
    return `About ${formatCount(wanted)} minutes a month is more than one pack. The largest is ${amount}${spread} — add credit more than once, or talk to us about a monthly plan.`;
  }
  return `About ${formatCount(wanted)} minutes a month? ${amount} covers it whichever voice you choose${spread}.`;
}

/**
 * The smallest pack whose talk time covers a month — or, when nothing does, the largest
 * one and a flag saying so.
 *
 * **MATCHED ON THE DEARER QUALITY**, which is the change D-547 forced and the only
 * direction that cannot mislead: a pack that covers a month of Studio calling covers the
 * same month on Clear, while matching on the cheaper voice would recommend a pack that
 * falls short for anybody who picks the dearer one after buying — and the voice is chosen
 * per agent, later, on a screen this one does not control. The old single
 * `talk_time_minutes` is deprecated on the wire and holds the CHEAPER figure, so reading it
 * would have made exactly that mistake silently.
 *
 * The catalogue is sorted here rather than assumed to arrive in order: nothing in
 * `CreditPacksOut` promises an ordering, and a chooser that silently depends on one would
 * recommend the wrong pack the day the server sorts by anything else. Both figures are the
 * server's own floor of its own division, so this compares two numbers it sent and computes
 * no price.
 */
function suggestPack(
  packs: CreditPack[],
  minutes: number,
): { pack: CreditPack; short: boolean } | null {
  const ascending = [...packs].sort(
    (a, b) => packMinutes(a, "cartesia") - packMinutes(b, "cartesia"),
  );
  const largest = ascending[ascending.length - 1];
  if (largest === undefined) return null;
  const covering = ascending.find((pack) => packMinutes(pack, "cartesia") >= minutes);
  return covering ? { pack: covering, short: false } : { pack: largest, short: true };
}
