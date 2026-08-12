"use client";

import { useState } from "react";

import { Card, ProblemNotice, RestrictionNote, Skeleton, StatTile } from "@/components/ui";
import {
  MAX_TOPUP_INR,
  MIN_TOPUP_INR,
  isPrepaid,
  useTopUpIntent,
} from "@/lib/api/billing";
import { useCaps, useSetCaps } from "@/lib/api/caps";
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
          People calling you still get through. Raise your own limit below, or talk to
          your account manager if the limit on your plan is the one you have reached.
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
          hint={
            /* Two rungs means two rates, and quoting only one of them would make the
               invoice's arithmetic impossible to follow. `overage_rate_value_inr` is
               null when the plan quotes a single rate — which is most plans — and the
               hint reads exactly as it always did in that case. */
            data.overage_rate_value_inr === null
              ? `₹${data.overage_rate_inr} per extra minute`
              : `₹${data.overage_rate_inr}/min premium voice, ₹${data.overage_rate_value_inr}/min value voice`
          }
        />
      </div>

      <Card title="This month">
        <dl className="space-y-2 text-sm">
          <Row label="Plan fee" value={data.monthly_fee_inr ? `₹${data.monthly_fee_inr}` : "—"} />
          {data.overage_rate_value_inr === null ? (
            <Row
              label={`Extra usage (${data.overage_minutes} min × ₹${data.overage_rate_inr})`}
              value={`₹${data.overage_cost_inr}`}
            />
          ) : (
            /* The same two rungs the invoice prints, so the screen a client checks and
               the document they are sent tell one story. The COST is one row, because
               `overage_cost_inr` is one server-side number: splitting it here would mean
               the browser dividing a bill, and a paisa of disagreement with the invoice
               is a support ticket. */
            <>
              <Row
                label={`Extra usage, premium voice (${data.overage_minutes_premium} min × ₹${data.overage_rate_inr})`}
                value={`${data.overage_minutes_premium} min`}
              />
              <Row
                label={`Extra usage, value voice (${data.overage_minutes_value} min × ₹${data.overage_rate_value_inr})`}
                value={`${data.overage_minutes_value} min`}
              />
              <Row label="Extra usage total" value={`₹${data.overage_cost_inr}`} />
            </>
          )}
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

      <SpendLimit session={session} />

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
 * The client's own spending limit (D-34 R-11, SURFACES §2b) — the control that was
 * missing entirely.
 *
 * Three things the screen has to get right, and each of them is a sentence on it:
 *
 * 1. **What is in force is not necessarily what they set.** The plan carries a limit
 *    too, and the stricter of the two wins. Showing only "your limit" would leave a
 *    client staring at a stopped account with a limit they have not reached.
 * 2. **Lowering below what they have already spent stops outbound calling NOW.** That
 *    is the server's deliberate behaviour (`billing/caps.py`), so the form says so
 *    before the click rather than letting it be discovered from an empty call list.
 * 3. **Incoming calls are never affected.** It is the reason an immediate stop is a
 *    safe control to hand over, and it is the first thing an owner worries about.
 *
 * No client-side validation of the ceiling. A limit looser than the plan's is refused
 * server-side with its own problem+json message, and a second copy of that rule in the
 * browser is a rule that drifts.
 */
function SpendLimit({ session }: { session: Session }) {
  const caps = useCaps(session);
  const save = useSetCaps(session);
  const write = useWriteAccess(session, "org:manage", "change your spending limit");
  const [minutes, setMinutes] = useState<string | null>(null);
  const [spend, setSpend] = useState<string | null>(null);

  if (caps.isLoading) return <Skeleton rows={3} />;
  if (caps.error) return <ProblemNotice error={caps.error} onRetry={() => caps.refetch()} />;
  if (!caps.data) return null;

  const current = caps.data;
  // `null` state means "not edited yet" — the input shows the server's value. Empty
  // string means the client cleared it, which is a real instruction (fall back to the
  // plan's limit) and must not be confused with "unchanged".
  const minutesField = minutes ?? (current.client_cap_minutes?.toString() ?? "");
  const spendField = spend ?? (current.client_cap_spend_inr ?? "");

  return (
    <Card title="Your spending limit">
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Set your own limit for this month. Outgoing calls stop when you reach it.
        Incoming calls are never affected.
      </p>

      <dl className="mt-3 space-y-2 text-sm">
        <Row
          label="In force this month"
          value={describeLimit(current.effective_cap_minutes, current.effective_cap_spend_inr)}
          emphasis
        />
        <Row
          label="Limit on your plan"
          value={describeLimit(current.plan_cap_minutes, current.plan_cap_spend_inr)}
        />
        <Row label="Used so far" value={`${current.minutes_used} min · ₹${current.spend_used_inr}`} />
      </dl>

      <div className="mt-4 space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
        <RestrictionNote reason={write.reason} />
        {save.error && <ProblemNotice error={save.error} />}

        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({
              capMinutes: minutesField.trim() === "" ? null : Number(minutesField),
              // A STRING all the way to the server (hard rule 7): `Number()` here would
              // put a rupee amount through a binary float on the way out.
              capSpendInr: spendField.trim() === "" ? null : spendField.trim(),
            });
          }}
        >
          <Field
            id="cap-minutes"
            label="Minutes"
            value={minutesField}
            disabled={!write.allowed}
            onChange={setMinutes}
            placeholder="no limit"
          />
          <Field
            id="cap-spend"
            label="Spend (₹)"
            value={spendField}
            disabled={!write.allowed}
            onChange={setSpend}
            placeholder="no limit"
          />
          <button
            type="submit"
            disabled={!write.allowed || save.isPending}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {save.isPending ? "Saving…" : "Save limit"}
          </button>
        </form>

        <p className="text-xs text-slate-500">
          Leave a box empty to remove your own limit and fall back on your plan&apos;s.
          A limit below what you have already spent this month takes effect immediately
          — outgoing calls stop for the rest of the month, and you can raise it again
          here at any time.
        </p>

        {save.data && (
          <div
            role="status"
            className={
              save.data.capped
                ? "rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
                : "rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
            }
          >
            {save.data.capped
              ? "Saved. Outgoing calls are stopped for the rest of this month. Incoming calls still get through."
              : `Saved. In force this month: ${describeLimit(save.data.effective_cap_minutes, save.data.effective_cap_spend_inr)}.`}
          </div>
        )}
      </div>
    </Card>
  );
}

/** "no limit", "500 minutes", "₹5,000", or both — never an empty cell. */
function describeLimit(minutes: number | null, spend: string | null): string {
  const parts: string[] = [];
  if (minutes !== null) parts.push(`${minutes} minutes`);
  // The rupee figure stays a string: the server sends an exact NUMERIC and formatting
  // it through a JS number is how ₹10,159.00 becomes ₹10,158.999999999998.
  if (spend !== null) parts.push(`₹${spend}`);
  return parts.length > 0 ? parts.join(" or ") : "no limit";
}

function Field({
  id,
  label,
  value,
  disabled,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs text-slate-600 dark:text-slate-400">
        {label}
      </label>
      <input
        id={id}
        inputMode="decimal"
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-32 rounded-md border border-slate-300 px-2 py-1 text-sm tabular-nums dark:border-slate-700 dark:bg-slate-950"
      />
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
