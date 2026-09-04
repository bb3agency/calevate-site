"use client";

import Link from "next/link";
import { useState } from "react";
import { Coins, Gauge, PhoneCall, Timer } from "lucide-react";

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
  hasNonZeroDigit,
} from "@/components/ui";
import { useCaps, useSetCaps } from "@/lib/api/caps";
import { useClientRealm } from "@/lib/api/session";
import { useUsage, useWriteAccess } from "@/lib/api/hooks";
import type { Session } from "@/lib/api/client";

import { SpendPanel } from "./SpendPanel";

/**
 * USAGE — what this month has cost, which agent spent it, and the limit that stops it.
 *
 * The Usage tab of the billing hub (D-525). It is the old `/c/[slug]/usage` screen and the
 * old `/c/[slug]/spend` screen in one place, in the order the question is actually asked:
 * how much, then which agent, then which call, then the control that caps it. Those were
 * two sidebar entries, and a client had to already know that "Usage" answers the first and
 * "Spend" answers the second.
 *
 * ## Deliberately absent: our supplier cost
 *
 * `unit_cost_paid` sits on every usage row so per-client margin is a query (D-12), and it
 * is commercially ours — the margin panel in the admin console is where it belongs, and
 * `UsagePanelOut` does not carry it here.
 *
 * ## Money
 *
 * Every money field is an exact decimal STRING and stays one all the way to the DOM.
 * `formatINR` formats the DIGITS — it never parses them — because `Number("10159.00")` is
 * how ₹10,159.00 becomes ₹10,158.999999999998 on the screen a client checks against their
 * own books. RATES are the exception and go through `formatRupeeRate`, which keeps the
 * server's full NUMERIC(12,4) precision: rounding ₹7.1250/min to ₹7.12 breaks the only
 * arithmetic a client ever does on an invoice line (qty × unit = amount).
 *
 * ## THE PERMISSION IS THE TAB'S, NOT THE SCREEN'S
 *
 * `GET /v1/usage`, `GET /v1/billing/caps` and `GET /v1/billing/spend` all require
 * `billing:read`, which `staff` does not hold — spend is an owner's business
 * (SEC-COMP §5). The hub itself reads on `wallet:read`, which staff DO hold, so the
 * refusal moved in here: a staff member keeps the balance, the runway and the reason
 * their dialling stopped, and is told in a sentence why the month's figures are not
 * theirs to see. Before the hub existed they met a whole-screen refusal instead.
 *
 * `refused` is decided by the CALLER (the hub reads `/v1/me` once for all four tabs)
 * rather than re-read here, so the tabs cannot disagree about one session.
 */
export function UsageTab({
  session,
  slug,
  month,
  onMonthChange,
  refused,
}: {
  session: Session;
  slug: string;
  /** The IST billing month the per-agent breakdown is showing, `YYYY-MM`. */
  month: string;
  onMonthChange: (month: string) => void;
  /** True when this session does NOT hold `billing:read`. */
  refused: boolean;
}) {
  const usage = useUsage(session);

  if (refused) {
    return (
      <RestrictionNote reason="Spending and usage are limited to the account owner. Ask them to share this month's figures, or to give you owner access." />
    );
  }

  const data = usage.data;

  return (
    <div className="space-y-5">
      <p className="text-sm text-ink-muted">
        {data ? `Billing month ${data.month} (Indian Standard Time).` : "This month's usage."}
      </p>

      {usage.error && <ProblemNotice error={usage.error} onRetry={() => void usage.refetch()} />}

      {/* A skeleton is not a number and a failure is not a zero: when the request has
          not landed, the tab shows neither figures nor a reassuring blank. */}
      {!data ? (
        usage.error ? null : <Skeleton rows={6} label="Loading this month's usage" />
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
                next minute will cost them.

                THE RUNGS ARE NOT VOICES AND MUST NOT BE WORDED AS ONE. This hint used to
                read "premium voice" / "value voice", which is what `billing/invoice.py`'s
                `_RUNG_WORDING` called them. There is ONE voice quality on this platform —
                `billing/rates.py`'s header records that the premium/value VOICE ladder was
                deleted outright, along with `TtsTier`, `billable_tier` and `tier_of_voice`
                — and these two slots are a plan's standard and reduced overage RATES
                (`plans.overage_rate` / `overage_rate_value`, the second NULL on every plan
                today). Wording them as voices advertised a choice the client cannot make
                and nobody offers. */}
            <StatTile
              label="Extra charges"
              value={formatINR(data.overage_cost_inr)}
              icon={<Coins className="h-5 w-5" />}
              tone="strong"
              hint={
                data.overage_rate_value_inr === null
                  ? `${formatRupeeRate(data.overage_rate_inr)} per extra minute`
                  : `${formatRupeeRate(data.overage_rate_inr)}/min standard rate, ${formatRupeeRate(
                      data.overage_rate_value_inr,
                    )}/min reduced rate`
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
                /* The same two rungs the statement prints, so the screen a client checks
                   and the document they are sent tell one story. The COST is one row,
                   because `overage_cost_inr` is one server-side number: splitting it here
                   would mean the browser dividing a bill, and a paisa of disagreement with
                   the statement is a support ticket. */
                <>
                  <Row
                    label={`Extra usage, standard rate (${data.overage_minutes_premium} min × ${formatRupeeRate(data.overage_rate_inr)})`}
                    value={`${data.overage_minutes_premium} min`}
                  />
                  <Row
                    label={`Extra usage, reduced rate (${data.overage_minutes_value} min × ${formatRupeeRate(data.overage_rate_value_inr)})`}
                    value={`${data.overage_minutes_value} min`}
                  />
                  <Row label="Extra usage total" value={formatINR(data.overage_cost_inr)} />
                </>
              )}
              {/* THE MODEL UPGRADE (D-455), on the screen because it is on the statement.
                  A client whose bill grew because they moved their agents onto a dearer
                  AI model has to be able to see WHICH decision did it — the line names the
                  model, exactly as `build_invoice` does, and multiplies out against the
                  rate beside it. Absent when the plan quotes no surcharge or nothing was
                  upgraded, which is every account today: a ₹0.00 row invites a question
                  about nothing, and is the same rule the overage rows follow. */}
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
                   we earn" cannot disagree about one month. */
                value={formatINR(data.month_charges_inr)}
                emphasis
              />
              {data.cap_minutes !== null && (
                <Row label="Monthly cap" value={`${formatCount(data.cap_minutes)} minutes`} />
              )}
            </dl>
            {/* THE CONTROL THAT CAUSED THE CHARGE, FROM THE CHARGE. An owner reading a
                line they did not expect needs the setting that produced it, not a support
                ticket — and the model choice is theirs to change (D-454). Rendered only
                when the charge exists: a pointer to a setting nobody is being charged for
                is a suggestion to spend money. */}
            {hasNonZeroDigit(data.llm_surcharge_inr) && <ModelUpgradeLink slug={slug} />}
            <p className="mt-3 text-xs text-ink-muted">
              Usage appears a couple of minutes after each call ends, once the recording
              and summary have been processed.
            </p>
          </Card>
        </>
      )}

      {/* WHICH AGENT AND WHICH CALL. Its own month picker, because it is the only part of
          this tab that can look backwards — `GET /v1/usage` answers for the OPEN month
          only, and driving both from one picker would silently show a past month's
          breakdown under this month's totals. */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <p className="text-sm text-ink-muted">
          Every rupee of a month&rsquo;s calling charge, against the agent and the call
          that produced it.
        </p>
        <input
          type="month"
          value={month}
          onChange={(event) => onMonthChange(event.target.value)}
          className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
          aria-label="Billing month for the breakdown"
        />
      </div>
      <SpendPanel session={session} slug={slug} month={month} />

      {/* Its own query and its own permission, so it is not hidden by a failed usage read:
          the limit is the control an owner reaches for when spend surprises them, and that
          is precisely the moment the panel above may be the thing that broke. */}
      <SpendLimit session={session} />
    </div>
  );
}

/**
 * The link out to the account-wide model choice.
 *
 * Its own component so the hook that carries a "view as" session across the click is not
 * called from inside a conditional branch of the tab above.
 */
function ModelUpgradeLink({ slug }: { slug: string }) {
  const { href } = useClientRealm();
  return (
    <p className="mt-3 text-xs text-ink-muted">
      The AI model upgrade is charged for the minutes your agents ran a model you chose.
      Change it on{" "}
      <Link
        href={href(`/c/${slug}/settings/models`)}
        className="font-medium underline underline-offset-2 hover:text-ink"
      >
        AI model
      </Link>
      , or on a single agent from Agents.
    </p>
  );
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
          noValidate
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
