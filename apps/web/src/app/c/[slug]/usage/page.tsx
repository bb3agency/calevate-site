"use client";

import { useState } from "react";

import { Card, ProblemNotice, RestrictionNote, Skeleton, StatTile } from "@/components/ui";
import {
  MAX_TOPUP_INR,
  MIN_TOPUP_INR,
  isPrepaid,
  useTopUpIntent,
} from "@/lib/api/billing";
import { useClientSession } from "@/lib/api/session";
import { useUsage, useWriteAccess } from "@/lib/api/hooks";
import type { Session } from "@/lib/api/client";

/**
 * What this month costs (SURFACES §2b, `billing:read` — owners, not staff).
 *
 * Deliberately absent: our supplier cost. `unit_cost_paid` sits on every usage row so
 * per-client margin is a query (D-12), and it is commercially ours — the margin panel
 * in the admin console is where it belongs.
 *
 * Money arrives as strings and stays strings all the way to the screen. Parsing INR
 * into a JS number to format it is how ₹10,159.00 becomes ₹10,158.999999999998.
 */
export default function UsagePage() {
  const session = useClientSession();
  const usage = useUsage(session);

  if (usage.isLoading) return <Skeleton rows={5} />;
  if (usage.error) return <ProblemNotice error={usage.error} onRetry={() => usage.refetch()} />;
  if (!usage.data) return null;

  const data = usage.data;
  const overage = Number(data.overage_minutes) > 0;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Usage</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Billing month {data.month} (Indian Standard Time).
        </p>
      </div>

      {data.capped && (
        <div
          role="alert"
          className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
        >
          {/* The cap is a safety rail the client chose; explaining it beats a silent
              stop, which reads as an outage. Inbound is unaffected — the gate is
              outbound-only — and saying so prevents a needless support call. */}
          Outgoing calls are paused for this month — you have reached your spending cap.
          People calling you still get through. Talk to your account manager to raise it.
        </div>
      )}

      {data.minutes_left !== null && (
        /* Runway framing: "about N minutes left" is what an owner plans around;
           a rupee balance makes them do the division at the counter. */
        <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200">
          About <strong>{data.minutes_left} minutes</strong> of calling left this month.
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-4">
        <StatTile
          label="Minutes used"
          value={data.minutes_used}
          hint={
            data.included_minutes > 0 ? `${data.included_minutes} included` : "pay as you go"
          }
        />
        <StatTile label="Calls" value={data.calls} />
        <StatTile
          label="Extra minutes"
          value={data.overage_minutes}
          hint={overage ? "beyond your plan" : "none — you are within your plan"}
        />
        {/* The rate, not just the total. Until the server published
            `overage_rate_inr` this tile showed a rupee figure with nothing to check
            it against — an owner could not tell how it was arrived at, nor what the
            next minute will cost them. It is a string at full precision on purpose:
            the invoice's overage line multiplies by exactly this number. */}
        <StatTile
          label="Extra charges"
          value={`₹${data.overage_cost_inr}`}
          hint={`₹${data.overage_rate_inr} per extra minute`}
        />
      </div>

      <Card title="This month">
        <dl className="space-y-2 text-sm">
          <Row label="Plan fee" value={data.monthly_fee_inr ? `₹${data.monthly_fee_inr}` : "—"} />
          <Row
            label={`Extra usage (${data.overage_minutes} min × ₹${data.overage_rate_inr})`}
            value={`₹${data.overage_cost_inr}`}
          />
          <Row
            label="Total so far"
            value={`₹${addRupees(data.monthly_fee_inr, data.overage_cost_inr)}`}
            emphasis
          />
          {data.cap_minutes !== null && (
            <Row label="Monthly cap" value={`${data.cap_minutes} minutes`} />
          )}
        </dl>
        <p className="mt-3 text-xs text-slate-500">
          Usage appears a couple of minutes after each call ends, once the recording and
          summary have been processed.
        </p>
      </Card>

      {data.credit_balance_inr !== null && (
        <Card title="Calling credit">
          <p className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-50">
            ₹{data.credit_balance_inr}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Outgoing calls stop when this reaches zero. Incoming calls are unaffected.
          </p>
          {/* Offered on the tier the server says has a wallet, not on "the balance is
              not null": an invoiced account would get `topup_not_available` after the
              click, which is a refusal we can see coming and therefore should not
              deliver as an error. */}
          {isPrepaid(data.plan_tier) && <TopUp session={session} />}
        </Card>
      )}
    </div>
  );
}

/**
 * Adding credit — as far as the server can actually take it, and no further.
 *
 * The symptom: a prepaid client whose wallet empties has outbound calling refused, and
 * there was nowhere in the product to add money. The fix is honest rather than
 * complete, because the backend is honest rather than complete: `POST
 * /v1/billing/topups/intent` prices the top-up and mints a receipt, but returns
 * `provider_order_id: null` / `provider_order_pending: true` — creating the provider
 * order needs credentials this deployment does not hold.
 *
 * So this renders NO pay button, no checkout, no spinner waiting on a payment window.
 * A "Pay ₹2,000" button that cannot charge anything is worse than no button: the
 * client believes they have paid, keeps not being able to dial, and calls support
 * about a payment that was never taken. What they get instead is a real reference for
 * a real amount, with the true statement that nothing has been charged and how to
 * actually pay. When the server starts returning an order id, the checkout opens from
 * exactly here.
 */
function TopUp({ session }: { session: Session }) {
  const [amount, setAmount] = useState("");
  const intent = useTopUpIntent(session);
  // `org:manage` is what the endpoint requires — staff should see the balance and not
  // a form that will 403 them, and an operator in "view as client" cannot spend a
  // client's money from a client screen (D-22).
  const write = useWriteAccess(session, "org:manage", "add credit");

  return (
    <div className="mt-4 space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
      <RestrictionNote reason={write.reason} />
      {intent.error && <ProblemNotice error={intent.error} />}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          intent.mutate(amount);
        }}
      >
        <label htmlFor="topup-amount" className="text-sm text-slate-600 dark:text-slate-400">
          Add credit
        </label>
        <span className="text-sm text-slate-500">₹</span>
        <input
          id="topup-amount"
          inputMode="decimal"
          value={amount}
          disabled={!write.allowed}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="2000"
          className="w-32 rounded-md border border-slate-300 px-2 py-1 text-sm tabular-nums dark:border-slate-700 dark:bg-slate-950"
        />
        <button
          type="submit"
          disabled={!write.allowed || !amount.trim() || intent.isPending}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {intent.isPending ? "Working…" : "Get payment details"}
        </button>
        <span className="text-xs text-slate-500">
          ₹{MIN_TOPUP_INR.toLocaleString("en-IN")} to ₹{MAX_TOPUP_INR.toLocaleString("en-IN")}
        </span>
      </form>

      {intent.data && (
        <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200">
          <p className="font-medium">
            ₹{intent.data.amount_inr} — nothing has been charged yet.
          </p>
          {intent.data.provider_order_id === null || intent.data.provider_order_pending ? (
            <p className="mt-1">
              We cannot take card or UPI payment on this account yet. Transfer{" "}
              <strong>₹{intent.data.amount_inr}</strong> to us by bank transfer quoting the
              reference below, or send this reference to your account manager, and the
              credit is added once the payment lands. Your balance above will not change
              until then.
            </p>
          ) : (
            /* The server has started creating provider orders. There is still no
               checkout in this build, so it says so instead of implying one. */
            <p className="mt-1">
              A payment order is ready. Online checkout is not available in this version —
              send this reference to your account manager to complete it.
            </p>
          )}
          <p className="mt-2 font-mono text-xs">ref {intent.data.receipt}</p>
        </div>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="flex justify-between">
      <dt className="text-slate-600 dark:text-slate-400">{label}</dt>
      <dd
        className={
          emphasis
            ? "font-semibold tabular-nums text-slate-900 dark:text-slate-50"
            : "tabular-nums text-slate-700 dark:text-slate-300"
        }
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * Adds two INR strings in whole paise.
 *
 * The server sends exact NUMERIC values as strings precisely so nothing downstream
 * rounds them; `Number(a) + Number(b)` would undo that at the very last step, which is
 * the most embarrassing possible place for it to happen. Integers are exact in a JS
 * number up to 2^53 — about ₹90 trillion in paise — so the arithmetic below is
 * float-free in the way that matters, without needing BigInt.
 */
function addRupees(a: string | null, b: string): string {
  const toPaise = (value: string) => {
    const negative = value.trim().startsWith("-");
    const [rupees, decimals = ""] = value.replace("-", "").split(".");
    const paise = Number(rupees || "0") * 100 + Number((decimals + "00").slice(0, 2));
    return negative ? -paise : paise;
  };
  const total = (a ? toPaise(a) : 0) + toPaise(b);
  const sign = total < 0 ? "-" : "";
  const abs = Math.abs(total);
  return `${sign}${Math.trunc(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}
