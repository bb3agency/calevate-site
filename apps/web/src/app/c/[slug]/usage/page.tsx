"use client";

import Link from "next/link";
import { useState } from "react";
import { Coins, Gauge, PhoneCall, Timer, Wallet } from "lucide-react";

import {
  Card,
  NOTICE_TONES,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
  formatRupeeRate,
} from "@/components/ui";
import {
  MAX_TOPUP_INR,
  MIN_TOPUP_INR,
  isPrepaid,
  useTopUpCapability,
  useTopUpIntent,
} from "@/lib/api/billing";
import { useCaps, useSetCaps } from "@/lib/api/caps";
import { useClientRealm } from "@/lib/api/session";
import { useMe, useUsage, useWriteAccess } from "@/lib/api/hooks";
import type { Session } from "@/lib/api/client";

/**
 * What this month costs (SURFACES §2b, `billing:read` — owners, not staff).
 *
 * Deliberately absent: our supplier cost. `unit_cost_paid` sits on every usage row so
 * per-client margin is a query (D-12), and it is commercially ours — the margin panel in
 * the admin console is where it belongs, and `UsagePanelOut` does not carry it here.
 *
 * ## Money
 *
 * Every money field on `UsagePanelOut` is an exact decimal STRING and stays one all the
 * way to the DOM. `formatINR` formats the DIGITS — it never parses them — because
 * `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998 on the screen a
 * client checks against their own books.
 *
 * The RATES are the exception, and the exception is the point: `overage_rate_inr` is
 * NUMERIC(12,4) and the server publishes it at full precision on purpose
 * (`billing/service.py::rate_to_display` — "a RATE is not a rupee amount and must not be
 * rounded like one"). `formatINR` keeps exactly two decimals, so putting ₹7.1250/min
 * through it would print ₹7.12 and break the only arithmetic a client ever does on an
 * invoice line: qty × unit = amount. Rates therefore render through `formatRupeeRate`
 * (components/ui.tsx), which prefixes the ₹ and touches nothing else.
 *
 * ## What changed in the design pass, beyond colour
 *
 * - The screen rendered its own `<h1>Usage</h1>` while the shell prints the page title
 *   from the nav list (layout.tsx).
 * - `Number(data.overage_minutes) > 0` parsed a server decimal to ask a yes/no question.
 *   It decided a hint rather than a figure, so nothing was visibly wrong — which is
 *   exactly how the habit survives to the line where it does matter. `hasNonZeroDigit`
 *   answers the same question without a float.
 * - Every panel sat behind `if (!usage.data) return null`, so a failed request rendered
 *   a blank screen: no numbers, and no notice either.
 * - The screen was not gated on the permission its own endpoint requires (below).
 */
export default function UsagePage() {
  const { session, href } = useClientRealm();
  const usage = useUsage(session);
  const me = useMe(session);

  /**
   * `GET /v1/usage` and `GET /v1/billing/caps` both require `billing:read` (crm/routes.py,
   * billing/cap_routes.py), which `staff` does not hold — spend is an owner's business
   * (SEC-COMP §5). The nav shows this screen to everyone, so a staff user reached it and
   * was answered with a red 403 alert that reads like an outage.
   *
   * Read off `/v1/me` rather than from a role list this build would have to keep in step
   * with `core/rbac.py`. Not `useWriteAccess`: that refuses EVERY permission to an
   * impersonating operator (D-22), which is right for a control that writes and wrong
   * here — `billing:read` is not a mutating permission, an operator holds it, and
   * blanking this screen for the person doing the support call would be a refusal the
   * server never made.
   *
   * While `/v1/me` is in flight `me.data` is undefined and nothing is refused, so the
   * screen never flashes an explanation it is about to withdraw. If `/v1/me` itself
   * failed we do not know, so the request goes out and the API's answer is what renders.
   */
  const refused = me.data !== undefined && !me.data.permissions.includes("billing:read");
  if (refused) {
    return (
      <RestrictionNote reason="Spending and usage are limited to the account owner. Ask them to share this month's figures, or to give you owner access." />
    );
  }

  const data = usage.data;

  return (
    <div className="space-y-5 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          {data ? `Billing month ${data.month} (Indian Standard Time).` : "This month's usage."}
        </p>
      </div>

      {usage.error && <ProblemNotice error={usage.error} onRetry={() => void usage.refetch()} />}

      {/* A skeleton is not a number and a failure is not a zero: when the request has
          not landed, the screen shows neither figures nor a reassuring blank. */}
      {!data ? (
        usage.error ? null : <Skeleton rows={6} />
      ) : (
        <>
          {data.capped && (
            <div role="alert" className={`rounded-card border p-3 text-sm ${NOTICE_TONES.warn}`}>
              {/* The cap is a safety rail the client chose; explaining it beats a silent
                  stop, which reads as an outage. Inbound is unaffected — the gate is
                  outbound-only — and saying so prevents a needless support call. */}
              Outgoing calls are paused for this month — you have reached your spending
              cap. People calling you still get through. Raise your own limit below, or
              talk to your account manager if the limit on your plan is the one you have
              reached.
            </div>
          )}

          {data.minutes_left !== null && (
            /* Runway framing: "about N minutes left" is what an owner plans around; a
               rupee balance makes them do the division at the counter. */
            <p className="rounded-card border border-line bg-surface px-4 py-3 text-sm text-ink-muted">
              About{" "}
              <strong className="font-semibold tabular-nums text-ink">
                {formatCount(data.minutes_left)} minutes
              </strong>{" "}
              of calling left this month.
            </p>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {/* The server's decimal string, printed as sent — minutes are metered to the
                same precision the invoice bills. */}
            <StatTile
              label="Minutes used"
              value={data.minutes_used}
              icon={<Timer className="h-5 w-5" />}
              hint={
                data.included_minutes > 0
                  ? `${formatCount(data.included_minutes)} included`
                  : "Pay as you go"
              }
            />
            <StatTile
              label="Calls"
              value={formatCount(data.calls)}
              icon={<PhoneCall className="h-5 w-5" />}
              hint="Billed calls this month"
            />
            <StatTile
              label="Extra minutes"
              value={data.overage_minutes}
              icon={<Gauge className="h-5 w-5" />}
              hint={
                hasNonZeroDigit(data.overage_minutes)
                  ? "Beyond your plan"
                  : "None — you are within your plan"
              }
            />
            {/* The rate, not just the total. Until the server published
                `overage_rate_inr` this tile showed a rupee figure with nothing to check
                it against — an owner could not tell how it was arrived at, nor what the
                next minute will cost them. */}
            <StatTile
              label="Extra charges"
              value={formatINR(data.overage_cost_inr)}
              icon={<Coins className="h-5 w-5" />}
              tone="strong"
              hint={
                /* Two rungs means two rates, and quoting only one of them would make the
                   invoice's arithmetic impossible to follow. `overage_rate_value_inr` is
                   null when the plan quotes a single rate — which is most plans — and the
                   hint reads exactly as it always did in that case. */
                data.overage_rate_value_inr === null
                  ? `${formatRupeeRate(data.overage_rate_inr)} per extra minute`
                  : `${formatRupeeRate(data.overage_rate_inr)}/min premium voice, ${formatRupeeRate(
                      data.overage_rate_value_inr,
                    )}/min value voice`
              }
            />
          </div>

          <Card title="This month">
            <dl className="space-y-2 text-sm">
              <Row label="Plan fee" value={formatINR(data.monthly_fee_inr)} />
              {data.overage_rate_value_inr === null ? (
                <Row
                  label={`Extra usage (${data.overage_minutes} min × ${formatRupeeRate(data.overage_rate_inr)})`}
                  value={formatINR(data.overage_cost_inr)}
                />
              ) : (
                /* The same two rungs the invoice prints, so the screen a client checks
                   and the document they are sent tell one story. The COST is one row,
                   because `overage_cost_inr` is one server-side number: splitting it here
                   would mean the browser dividing a bill, and a paisa of disagreement
                   with the invoice is a support ticket. */
                <>
                  <Row
                    label={`Extra usage, premium voice (${data.overage_minutes_premium} min × ${formatRupeeRate(data.overage_rate_inr)})`}
                    value={`${data.overage_minutes_premium} min`}
                  />
                  <Row
                    label={`Extra usage, value voice (${data.overage_minutes_value} min × ${formatRupeeRate(data.overage_rate_value_inr)})`}
                    value={`${data.overage_minutes_value} min`}
                  />
                  <Row label="Extra usage total" value={formatINR(data.overage_cost_inr)} />
                </>
              )}
              {/* THE MODEL UPGRADE (D-455), on the screen because it is on the invoice.
                  A client whose bill grew because they moved their agents onto a dearer
                  AI model has to be able to see WHICH decision did it — the line names
                  the model, exactly as `build_invoice` does, and multiplies out against
                  the rate beside it. Absent when the plan quotes no surcharge or nothing
                  was upgraded, which is every account today: a ₹0.00 row invites a
                  question about nothing, and is the same rule the overage rows follow. */}
              {hasNonZeroDigit(data.llm_surcharge_inr) && (
                <Row
                  label={`AI model upgrade${
                    data.llm_surcharge_models.length > 0
                      ? `, ${data.llm_surcharge_models.join(", ")}`
                      : ""
                  } (${data.llm_surcharge_minutes} min × ${formatRupeeRate(
                    data.llm_surcharge_rate_inr ?? "0",
                  )})`}
                  value={formatINR(data.llm_surcharge_inr)}
                />
              )}
              <Row
                label="Total so far"
                /* THE SERVER'S OWN TOTAL, not a sum taken here. It carries the retainer,
                   the overage and the model surcharge, and it is the same expression the
                   admin margin panel books as revenue — so "what this costs me" and "what
                   we earn" cannot disagree about one month. The browser added these three
                   in whole paise for a while, correctly; a total computed in a language
                   with one numeric type is still a second implementation of a bill, on the
                   screen a client checks against their own books. */
                value={formatINR(data.month_charges_inr)}
                emphasis
              />
              {data.cap_minutes !== null && (
                <Row label="Monthly cap" value={`${formatCount(data.cap_minutes)} minutes`} />
              )}
            </dl>
            {/* THE CONTROL THAT CAUSED THE CHARGE, FROM THE CHARGE. An owner reading a
                line they did not expect needs the setting that produced it, not a support
                ticket — and the model choice is theirs to change (D-454), which is what
                makes the link an answer rather than an explanation. Rendered only when the
                charge exists, on the same rule as the row above it: a pointer to a setting
                nobody is being charged for is a suggestion to spend money. */}
            {hasNonZeroDigit(data.llm_surcharge_inr) && (
              <p className="mt-3 text-xs text-ink-muted">
                The AI model upgrade is charged for the minutes your agents ran a model you
                chose. Change it on{" "}
                <Link
                  href={href(`/c/${session.orgSlug}/settings/models`)}
                  className="font-medium underline underline-offset-2 hover:text-ink"
                >
                  AI model
                </Link>
                , or on a single agent from Agents.
              </p>
            )}
            <p className="mt-3 text-xs text-ink-muted">
              Usage appears a couple of minutes after each call ends, once the recording
              and summary have been processed.
            </p>
          </Card>
        </>
      )}

      {/* Its own query and its own permission, so it is not hidden by a failed usage
          read: the limit is the control an owner reaches for when spend surprises them,
          and that is precisely the moment the panel above may be the thing that broke. */}
      <SpendLimit session={session} />

      {data && data.credit_balance_inr !== null && (
        <Card title="Calling credit">
          <p className="flex items-center gap-2 text-2xl font-bold tracking-tight tabular-nums text-ink">
            <Wallet className="h-5 w-5 text-brand" />
            {formatINR(data.credit_balance_inr)}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
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
 * Does this decimal STRING carry a value above zero?
 *
 * The question `Number(value) > 0` used to answer, without the parse. "0", "0.00" and
 * "0.0000" are all zero and no string comparison spots that; a single digit other than
 * zero anywhere in the string is exactly the condition, and it holds for every decimal
 * form the server can send. Not money-critical here — it picks a hint — but a `Number()`
 * on a server decimal is the habit hard rule 7 is about, and habits are what reach the
 * line that matters.
 */
function hasNonZeroDigit(value: string): boolean {
  return /[1-9]/.test(value);
}

/**
 * The client's own spending limit (D-34 R-11, SURFACES §2b).
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
  // `PUT /v1/billing/caps` requires `org:manage` — a MUTATING permission, so `staff` does
  // not hold it and an impersonating operator is refused it (D-22). Disabled with the
  // reason beside it, rather than a 403 after the click.
  const write = useWriteAccess(session, "org:manage", "change your spending limit");
  const [minutes, setMinutes] = useState<string | null>(null);
  const [spend, setSpend] = useState<string | null>(null);

  if (caps.isLoading) return <Skeleton rows={3} />;
  if (caps.error) return <ProblemNotice error={caps.error} onRetry={() => void caps.refetch()} />;
  if (!caps.data) return null;

  const current = caps.data;
  // `null` state means "not edited yet" — the input shows the server's value. Empty
  // string means the client cleared it, which is a real instruction (fall back to the
  // plan's limit) and must not be confused with "unchanged".
  const minutesField = minutes ?? (current.client_cap_minutes?.toString() ?? "");
  const spendField = spend ?? (current.client_cap_spend_inr ?? "");

  return (
    <Card title="Your spending limit">
      <p className="text-sm text-ink-muted">
        Set your own limit for this month. Outgoing calls stop when you reach it. Incoming
        calls are never affected.
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
        <Row
          label="Used so far"
          value={`${current.minutes_used} min · ${formatINR(current.spend_used_inr)}`}
        />
      </dl>

      <div className="mt-4 space-y-3 border-t border-line pt-4">
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
            className="rounded-md bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save limit"}
          </button>
        </form>

        <p className="text-xs text-ink-muted">
          Leave a box empty to remove your own limit and fall back on your plan&apos;s. A
          limit below what you have already spent this month takes effect immediately —
          outgoing calls stop for the rest of the month, and you can raise it again here
          at any time.
        </p>

        {save.data && (
          <div
            role="status"
            className={`rounded-card border p-3 text-sm ${
              save.data.capped ? NOTICE_TONES.warn : NOTICE_TONES.ok
            }`}
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

/** "no limit", "500 minutes", "₹5,000.00", or both — never an empty cell. */
function describeLimit(minutes: number | null, spend: string | null): string {
  const parts: string[] = [];
  if (minutes !== null) parts.push(`${formatCount(minutes)} minutes`);
  // The rupee figure never goes through a JS number: `formatINR` groups the digits the
  // server sent and keeps the paise it sent them with.
  if (spend !== null) parts.push(formatINR(spend));
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
      <label htmlFor={id} className="text-xs font-medium text-ink-muted">
        {label}
      </label>
      <input
        id={id}
        inputMode="decimal"
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-32 rounded-md border border-line bg-surface px-2 py-1 text-sm tabular-nums text-ink placeholder:text-ink-faint disabled:opacity-50"
      />
    </div>
  );
}

/**
 * Adding credit — as far as the server can actually take it, and no further.
 *
 * The symptom: a prepaid client whose wallet empties has outbound calling refused, and
 * there was nowhere in the product to add money. The fix is honest rather than complete,
 * because the backend is honest rather than complete.
 *
 * ## What the capability changed (D-98)
 *
 * This panel used to offer the form unconditionally — and `PAYMENT_PROVIDER` is unset by
 * default, so on every deployment the click could only ever return
 * `payments_not_configured`. A control whose single possible outcome is a red notice is
 * §52's defect one step earlier than §52 usually catches it: not a failure rendered as a
 * state, but a state offered that is really a failure. `GET /v1/billing/topups/capability`
 * answers it before the form exists, and the three renders are the §52 three:
 *
 * - **loading is a skeleton** — never a form, and never the "not available" sentence,
 *   which would be an explanation we are about to withdraw;
 * - **failure is a refusal** — the problem notice with a retry, and no form under it,
 *   because we do not know whether the form would work;
 * - **unavailable is a statement, not an empty state** — the bank-transfer path, which is
 *   the path that actually works today (runbooks/topup-payments.md §3).
 *
 * The hint is never the gate: the route asks the same selector server-side, so a stale
 * `true` here costs a refusal after the click and can never cost a payment.
 *
 * ## Why there is still no pay button
 *
 * There is no checkout in this build and the panel says so rather than implying one. A
 * "Pay ₹2,000" button that cannot charge anything is worse than no button: the client
 * believes they have paid, keeps not being able to dial, and calls support about a
 * payment that was never taken. When an order id DOES come back it is rendered as a
 * second reference to quote — Razorpay's own support and dashboard key on it — beside the
 * true statement that nothing has been charged.
 */
function TopUp({ session }: { session: Session }) {
  const [amount, setAmount] = useState("");
  const capability = useTopUpCapability(session);
  const intent = useTopUpIntent(session);
  // `org:manage` is what the endpoint requires — staff should see the balance and not a
  // form that will 403 them, and an operator in "view as client" cannot spend a client's
  // money from a client screen (D-22).
  const write = useWriteAccess(session, "org:manage", "add credit");

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

  return (
    <div className="mt-4 space-y-3 border-t border-line pt-4">
      <RestrictionNote reason={write.reason} />
      {intent.error && <ProblemNotice error={intent.error} />}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          intent.mutate(amount);
        }}
      >
        <label htmlFor="topup-amount" className="text-sm text-ink-muted">
          Add credit
        </label>
        <span className="text-sm text-ink-faint">₹</span>
        <input
          id="topup-amount"
          inputMode="decimal"
          value={amount}
          disabled={!write.allowed}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="2000"
          className="w-32 rounded-md border border-line bg-surface px-2 py-1 text-sm tabular-nums text-ink placeholder:text-ink-faint disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!write.allowed || !amount.trim() || intent.isPending}
          className="rounded-md bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
        >
          {intent.isPending ? "Working…" : "Get payment details"}
        </button>
        <span className="text-xs text-ink-faint">
          ₹{MIN_TOPUP_INR.toLocaleString("en-IN")} to ₹{MAX_TOPUP_INR.toLocaleString("en-IN")}
        </span>
      </form>

      {intent.data && (
        <div className="rounded-card border border-line bg-app p-3 text-sm text-ink-muted">
          {/* The amount the SERVER priced, as it sent it — this is the figure a bank
              transfer has to match to the paisa. */}
          <p className="font-semibold text-ink">
            {formatINR(intent.data.amount_inr)} — nothing has been charged yet.
          </p>
          {intent.data.provider_order_id === null ? (
            <p className="mt-1">
              We cannot take card or UPI payment on this account yet. Transfer{" "}
              <strong className="font-semibold text-ink">
                {formatINR(intent.data.amount_inr)}
              </strong>{" "}
              to us by bank transfer quoting the reference below, or send this reference to
              your account manager, and the credit is added once the payment lands. Your
              balance above will not change until then.
            </p>
          ) : (
            /* An order EXISTS with the payment provider. There is still no checkout in
               this build, so the order id is rendered as the thing to quote — it is what
               the provider's own support and dashboard key on — rather than dressed up as
               a payment in progress. */
            <p className="mt-1">
              A payment for{" "}
              <strong className="font-semibold text-ink">
                {formatINR(intent.data.amount_inr)}
              </strong>{" "}
              is set up and waiting. There is no online checkout in this version — send both
              references below to your account manager to complete it. Your balance will not
              change until the payment is confirmed.
            </p>
          )}
          <p className="mt-2 font-mono text-xs text-ink-faint">ref {intent.data.receipt}</p>
          {intent.data.provider_order_id !== null && (
            <p className="font-mono text-xs text-ink-faint">
              order {intent.data.provider_order_id}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-ink-muted">{label}</dt>
      <dd
        className={
          emphasis
            ? "shrink-0 font-semibold tabular-nums text-ink"
            : "shrink-0 tabular-nums text-ink-muted"
        }
      >
        {value}
      </dd>
    </div>
  );
}
