"use client";

import { Card, ProblemNotice, Skeleton, StatTile } from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { useUsage } from "@/lib/api/hooks";

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
  const usage = useUsage(useClientSession());

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
        <StatTile
          label="Extra charges"
          value={`₹${data.overage_cost_inr}`}
          hint="added to this month's invoice"
        />
      </div>

      <Card title="This month">
        <dl className="space-y-2 text-sm">
          <Row label="Plan fee" value={data.monthly_fee_inr ? `₹${data.monthly_fee_inr}` : "—"} />
          <Row label="Extra usage" value={`₹${data.overage_cost_inr}`} />
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
        </Card>
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
