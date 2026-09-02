"use client";

import { useState } from "react";

import {
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  ScrollRegion,
  Skeleton,
  formatCount,
  formatINR,
  formatRupeeRate,
  hasNonZeroDigit,
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
       internals leak. */
    return (
      <div className="mt-4 border-t border-line pt-4 text-sm text-ink-muted">
        <p>
          We cannot take card or UPI payment on this account. To add credit, transfer the
          amount to us by bank — talk to your account manager for the details — and the
          credit appears here once the payment lands.
        </p>
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

      {/* The pack rate card — the productized way to add credit. A bigger pack buys
          proportionally more calling because it grants bonus credits; the effective rate
          and talk time are the server's own figures, priced at the live list rate. */}
      {packs.isLoading && <Skeleton rows={4} />}
      {packs.error && <ProblemNotice error={packs.error} onRetry={() => void packs.refetch()} />}
      {packs.data && (
        <PacksTable
          packs={packs.data.packs}
          payable={payable}
          disabled={!write.allowed || busy}
          pendingPackId={intent.isPending ? pending : null}
          onSelect={(packId) => {
            setPending(packId);
            setStage({ at: "idle" });
            intent.mutate({ packId }, { onSuccess: onIntent });
          }}
        />
      )}

      {/* An "other amount" for a client who wants a figure that is not a pack. Same route,
          no bonus — packs are where the volume bonus lives. */}
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
 * The credit-pack rate card, Outpero-style: You pay / Credits / Free / Effective rate /
 * Talk time / the action. Every figure is the SERVER's — priced at the live list rate —
 * and rendered as sent (hard rule 7 reaches the browser: no decimal arithmetic on money
 * here).
 *
 * Scrolls inside its own container on narrow screens rather than forcing the page body to
 * scroll sideways. The "best value" pack is badged and row-highlighted.
 */
function PacksTable({
  packs,
  payable,
  disabled,
  pendingPackId,
  onSelect,
}: {
  packs: CreditPack[];
  payable: boolean;
  disabled: boolean;
  pendingPackId: string | null;
  onSelect: (packId: string) => void;
}) {
  return (
    <ScrollRegion label="Prepaid credit packs">
      <table className="w-full min-w-[36rem] border-collapse text-sm">
        <caption className="sr-only">Prepaid credit packs</caption>
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-muted">
            <th scope="col" className="py-2 pr-3 font-medium">
              You pay
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Credits
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Free
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Effective rate
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Talk time
            </th>
            <th scope="col" className="py-2 font-medium">
              <span className="sr-only">{payable ? "Pay" : "Select"}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {packs.map((pack) => (
            <tr
              key={pack.pack_id}
              className={`border-b border-line/60 ${pack.best_value ? "bg-brand-soft" : ""}`}
            >
              <td className="py-3 pr-3 font-semibold tabular-nums text-ink">
                {formatINR(pack.amount_inr)}
                {pack.best_value && (
                  <span className="ml-2 rounded-full bg-brand-strong px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
                    Best value
                  </span>
                )}
              </td>
              <td className="py-3 pr-3 tabular-nums text-ink-muted">
                {formatCredits(pack.total_credits)}
              </td>
              <td className="py-3 pr-3 tabular-nums text-ink-muted">
                {hasNonZeroDigit(pack.bonus_pct) ? (
                  <span className="font-medium text-brand">
                    +{formatCredits(pack.bonus_credits)} ({pack.bonus_pct}%)
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="py-3 pr-3 tabular-nums text-ink-muted">
                {formatRupeeRate(pack.effective_rate_inr_per_min)}/min
              </td>
              <td className="py-3 pr-3 tabular-nums text-ink-muted">
                ~{formatCount(pack.talk_time_minutes)} min
              </td>
              <td className="py-3">
                {/* The accessible name carries the AMOUNT, because six buttons all reading
                    "Pay" are six identically-named controls in a screen reader's list and
                    the one thing that tells them apart is the row's price. */}
                <button
                  type="button"
                  disabled={disabled}
                  aria-label={`${payable ? "Pay" : "Select"} ${formatINR(pack.amount_inr)}`}
                  onClick={() => onSelect(pack.pack_id)}
                  className={PRIMARY_BUTTON_SM}
                >
                  {pendingPackId === pack.pack_id ? "Working…" : payable ? "Pay" : "Select"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/**
 * A credit COUNT (1 credit = ₹1) formatted with grouping. Only the integer part is shown —
 * credits are whole rupees to a client — and it is parsed off the STRING (never the whole
 * decimal through `Number`), so no money value is put through a binary float. The integer
 * part of a NUMERIC(12,4) string is a safe `parseInt`; the fraction is dropped on purpose.
 */
function formatCredits(value: string): string {
  const whole = value.split(".")[0];
  return parseInt(whole, 10).toLocaleString("en-IN");
}
