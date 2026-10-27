"use client";

import Link from "next/link";
import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { MoneyInput } from "@/components/arc/money-input";
import { NumberField } from "@/components/arc/number-field";
import { StatsBand } from "@/components/arc/stats-band";
import { UsageMeter } from "@/components/arc/usage-meter";
import { Section } from "@/components/console/section";
import {
  Disclosure,
  FIELD,
  NOTICE_BAR,
  NOTICE_BASE,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatDecimal,
  formatINR,
  hasNonZeroDigit,
} from "@/components/ui";
import { isPrepaid } from "@/lib/api/billing";
import { useCaps, useSetCaps } from "@/lib/api/caps";
import { useClientRealm } from "@/lib/api/session";
import { useUsage, useWriteAccess } from "@/lib/api/hooks";
import { formatBillingMonth } from "@/lib/billingMonth";
import type { Session } from "@/lib/api/client";

import { SpendPanel } from "./SpendPanel";
import { voiceUsage } from "./lots";

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
 * own books. Amounts and rates alike read under the client display rule (at most one
 * decimal, `lib/numberDisplay.ts`); the paisa-exact figures are on the statement, which is
 * the tax document.
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
  /* THE TWO VOICE QUALITIES' SHARE OF THE MONTH, off the typed read: the six fields are
     generated and required on `UsagePanelOut`. Named by the SERVER — a client reads the
     quality's name, never the vendor's. */
  const voices = voiceUsage(usage.data);

  if (refused) {
    return (
      <RestrictionNote reason="Spending and usage are limited to the account owner. Ask them to share this month's figures, or to give you owner access." />
    );
  }

  const data = usage.data;

  return (
    <div className="space-y-5">
      <p className="text-body text-ink-muted">
        {data ? `${formatBillingMonth(data.month)} so far, in Indian Standard Time.` : "This month's usage."}
      </p>

      {usage.error && <ProblemNotice error={usage.error} onRetry={() => void usage.refetch()} />}

      {/* A skeleton is not a number and a failure is not a zero: when the request has
          not landed, the tab shows neither figures nor a reassuring blank. */}
      {!data ? (
        usage.error ? null : <Skeleton rows={6} label="Loading this month's usage" />
      ) : (
        <>
          {data.capped && (
            <div role="alert" className={`${NOTICE_BASE} ${NOTICE_BAR.warn}`}>
              {/* The cap is a safety rail the client chose; explaining it beats a silent
                  stop, which reads as an outage. Inbound is unaffected — the gate is
                  outbound-only — and saying so prevents a needless support call. */}
              Outgoing calls are paused for this month — you have reached your spending
              cap. People calling you still get through. Raise your own limit below, or
              talk to us if the limit on your plan is the one you have
              reached.
            </div>
          )}

          {data.minutes_left !== null && !isPrepaid(data.plan_tier) && (
            /* Runway framing: "about N minutes left" is what an owner plans around; a
               rupee balance makes them do the division at the counter.

               NOT FOR A PREPAID ACCOUNT, and that is a correction rather than a
               restriction. `UsagePanelOut.minutes_left` is one field with two meanings
               (`billing/service.py::usage_summary`): what is left of a monthly CAP for a
               plan that has one, and — for a prepaid wallet — `prepaid_minutes_left`,
               which divides the balance by the LIST rate. Under D-547 that second figure
               is not true of anybody: credit is spent at the rates frozen on each
               purchase and the answer differs by voice quality besides. The honest pair
               is on the Overview tab, from the lot queue; here a prepaid account gets
               nothing rather than a minute count nobody is charged at. */
            <p className="text-body text-ink-muted">
              About{" "}
              <strong className="font-semibold tabular-nums text-ink">
                {formatCount(data.minutes_left)} minutes
              </strong>{" "}
              of calling left this month.
            </p>
          )}

          {/* Minutes are the server's decimal strings, printed as sent — metered to the
              same precision the invoice bills. The extra-charges figure carries its rate,
              so an owner can check how it was arrived at and what the next minute costs. */}
          <StatsBand
            label="This month so far"
            items={[
              {
                label: "Minutes used",
                value: data.minutes_used,
                hint: data.included_minutes > 0 ? `${formatCount(data.included_minutes)} included` : "Pay as you go",
              },
              { label: "Calls", value: formatCount(data.calls), hint: "Billed calls this month" },
              {
                label: "Extra minutes",
                value: data.overage_minutes,
                hint: hasNonZeroDigit(data.overage_minutes) ? "Beyond your plan" : "None — you are within your plan",
              },
              {
                label: "Extra charges",
                value: formatINR(data.overage_cost_inr),
                hint: `${formatINR(data.overage_rate_inr)} per extra minute`,
              },
            ]}
          />

          {/* `Number()` sizes the bars only; every figure read is the server's string. */}
          {data.included_minutes > 0 || data.cap_minutes !== null ? (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              {data.included_minutes > 0 ? (
                <UsageMeter
                  label="Minutes in your plan"
                  used={Number(data.minutes_used)}
                  limit={data.included_minutes}
                  usedText={`${formatDecimal(data.minutes_used)} min`}
                  limitText={`${formatCount(data.included_minutes)} min`}
                  overTone="warn"
                  hint={
                    hasNonZeroDigit(data.overage_minutes)
                      ? `Minutes past your plan are charged at ${formatINR(data.overage_rate_inr)} each.`
                      : undefined
                  }
                />
              ) : null}
              {data.cap_minutes !== null ? (
                <UsageMeter
                  label="Monthly cap"
                  used={Number(data.minutes_used)}
                  limit={data.cap_minutes}
                  usedText={`${formatDecimal(data.minutes_used)} min`}
                  limitText={`${formatCount(data.cap_minutes)} min`}
                  overTone="danger"
                  hint="Outgoing calls pause at the cap. People calling you still get through."
                />
              ) : null}
            </div>
          ) : null}

          {/* The breakdown behind the four figures above, closed: the closed state states the
              total, and the rows are the working (UX-DOCTRINE §3 — a disclosure carries the
              fact, the click buys the detail). */}
          <Disclosure
            title="This month's charges"
            subtitle={`Total so far ${formatINR(data.month_charges_inr)}`}
          >
            <dl className="divide-y divide-line text-body">
              <Row label="Plan fee" value={formatINR(data.monthly_fee_inr)} />
              <Row
                label={`Extra usage (${formatDecimal(data.overage_minutes)} min × ${formatINR(data.overage_rate_inr)})`}
                value={formatINR(data.overage_cost_inr)}
              />
              {/* WHAT EACH VOICE QUALITY COST THIS MONTH (D-547), replacing the plan's
                  "standard rate / reduced rate" pair that was NULL on every plan and
                  therefore never rendered for anybody. These two are real: the minutes are
                  a part of `minutes_used` and the charges are the rupees the LOT SPLITS
                  took off the wallet, so this panel and the credit history cannot disagree
                  about a month. NO TOTAL IS TAKEN HERE (D-458) — "Total so far" below is
                  the server's own `month_charges_inr`, and adding two rupee strings in a
                  browser is the arithmetic that ends with the screen and the statement a
                  paisa apart.

                  A QUALITY WITH NO MINUTES GETS NO ROW. The six fields are required on the
                  wire now, so every month carries both qualities and a quiet one arrives as
                  `"0.0000"` — and a ₹0.00 row invites a question about nothing, which is
                  the rule the overage and surcharge rows above already follow. What is NOT
                  done is hiding a row for want of a CHARGE: minutes a trial absorbed are
                  minutes the client spoke, and they belong on the screen at ₹0.00. */}
              {voices?.map((voice) =>
                hasNonZeroDigit(voice.minutes) ? (
                  <Row
                    key={voice.provider}
                    label={`${voice.label} voice (${formatDecimal(voice.minutes)} min)`}
                    value={formatINR(voice.charges_inr)}
                  />
                ) : null,
              )}
              {/* THE MODEL UPGRADE (D-455), on the screen because it is on the statement.
                  A client whose bill grew because they moved their agents onto a dearer
                  AI model has to be able to see WHICH decision did it — the line names the
                  tier (never the model behind it, D-680), exactly as `build_invoice` does, and multiplies out against the
                  rate beside it. Absent when the plan quotes no surcharge or nothing was
                  upgraded, which is every account today: a ₹0.00 row invites a question
                  about nothing, and is the same rule the overage rows follow. */}
              {hasNonZeroDigit(data.llm_surcharge_inr) && (
                <Row
                  label={`AI model upgrade${
                    data.llm_surcharge_tiers.length > 0
                      ? `, ${data.llm_surcharge_tiers.join(", ")}`
                      : ""
                  }${
                    /* ⚠ THIS WAS `formatINR(data.llm_surcharge_rate_inr ?? "0")`,
                       WHICH PRINTED A RATE OF ₹0.00 BESIDE A NON-ZERO CHARGE. `?? "0"` is
                       a manufactured money figure: `llm_surcharge_rate_inr` is `string |
                       null` on the wire and the null means the plan quotes NO surcharge
                       rate (`billing/service.py:2883`), not a rate of zero. Rendered
                       inside this branch — which only runs on a non-zero charge — it
                       produced the one line a client cannot reconcile: "40.00 min × ₹0.00"
                       beside a real rupee amount, on the screen they check their statement
                       against.

                       `billing/invoice.py:515` is the standard this now matches: the
                       invoice omits the multiplication unless `surcharge_rate is not
                       None`. The minutes and the amount are both still shown, so nothing
                       checkable is withheld — what is dropped is the arithmetic we cannot
                       state. */
                    data.llm_surcharge_rate_inr === null
                      ? ` (${formatDecimal(data.llm_surcharge_minutes)} min)`
                      : ` (${formatDecimal(data.llm_surcharge_minutes)} min × ${formatINR(
                          data.llm_surcharge_rate_inr,
                        )})`
                  }`}
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
            </dl>
            {/* THE CONTROL THAT CAUSED THE CHARGE, FROM THE CHARGE. An owner reading a
                line they did not expect needs the setting that produced it, not a support
                ticket — and the model choice is theirs to change (D-454). Rendered only
                when the charge exists: a pointer to a setting nobody is being charged for
                is a suggestion to spend money. */}
            {hasNonZeroDigit(data.llm_surcharge_inr) && <ModelUpgradeLink slug={slug} />}
            <p className="mt-3 text-meta text-ink-muted">
              Usage appears a couple of minutes after each call ends, once the recording
              and summary have been processed.
            </p>
          </Disclosure>
        </>
      )}

      {/* WHICH AGENT AND WHICH CALL. Its own month picker, because it is the only part of
          this tab that can look backwards — `GET /v1/usage` answers for the OPEN month
          only, and driving both from one picker would silently show a past month's
          breakdown under this month's totals. */}
      <Disclosure
        title="By agent and by call"
        subtitle="Every rupee of a month’s calling charge, against the agent and the call that produced it."
      >
        <div className="space-y-5">
          <input
            type="month"
            value={month}
            onChange={(event) => onMonthChange(event.target.value)}
            className={`${FIELD} mt-0 w-auto`}
            aria-label="Billing month for the breakdown"
          />
          <SpendPanel session={session} slug={slug} month={month} />
        </div>
      </Disclosure>

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
    <p className="mt-3 text-meta text-ink-muted">
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
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  // `PUT /v1/billing/caps` requires `org:manage` — a MUTATING permission, so `staff` does
  // not hold it and an impersonating operator is refused it (D-22). Disabled with the
  // reason beside it, rather than a 403 after the click.
  const write = useWriteAccess(session, "org:manage", "change your spending limit");
  // `undefined` = not edited, so the box shows the server's value; `null` / `""` = the
  // owner cleared it, which is a real instruction (fall back to the plan's limit).
  const [minutes, setMinutes] = useState<number | null | undefined>(undefined);
  const [spend, setSpend] = useState<string | undefined>(undefined);

  if (caps.isLoading) return <Skeleton rows={3} />;
  if (caps.error) return <ProblemNotice error={caps.error} onRetry={() => void caps.refetch()} />;
  if (!caps.data) return null;

  const current = caps.data;
  const minutesField = minutes === undefined ? current.client_cap_minutes : minutes;
  const spendField = spend ?? current.client_cap_spend_inr ?? "";

  return (
    <Section
      title="Your spending limit"
      description="Set your own limit for this month. Outgoing calls stop when you reach it. Incoming calls are never affected."
    >
      <dl className="divide-y divide-line border-y border-line text-body">
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
          value={
            current.trial_active
              ? `${formatDecimal(current.minutes_used)} min · ${formatINR(current.spend_used_inr)}, free during your trial`
              : `${formatDecimal(current.minutes_used)} min · ${formatINR(current.spend_used_inr)}`
          }
        />
      </dl>

      <div className="mt-6 space-y-3">
        <RestrictionNote reason={write.reason} />
        {saveFeedback.error ? <ProblemNotice error={saveFeedback.error} /> : null}

        <form
          className="grid grid-cols-1 items-end gap-x-4 gap-y-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,14rem)_auto]"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (!write.allowed) return;
            saveFeedback.run({
              capMinutes: minutesField,
              // A STRING all the way to the server (hard rule 7).
              capSpendInr: spendField === "" ? null : spendField,
            });
          }}
        >
          <NumberField
            label="Minutes"
            value={minutesField}
            onChange={(next) => setMinutes(next)}
            optional
            unit="minutes"
            disabled={!write.allowed}
          />
          <MoneyInput
            label="Spend"
            value={spendField}
            onChange={setSpend}
            disabled={!write.allowed}
          />
          <ActionButton
            type="submit"
            variant="secondary"
            status={saveFeedback.status}
            pendingLabel="Saving"
            successLabel="Saved"
            disabled={!write.allowed}
            className="sm:mb-0.5"
          >
            Save limit
          </ActionButton>
        </form>

        <p className="text-meta text-ink-muted">
          Leave a box empty to remove your own limit and fall back on your plan&apos;s. A
          limit below what you have already spent this month takes effect immediately —
          outgoing calls stop for the rest of the month, and you can raise it again here
          at any time.
        </p>

        {/* What the save put in force, which can be stricter than what was typed (the plan's
            limit wins) — said once, beside the form, after a save. */}
        {save.data && (
          <div
            role="status"
            className={`${NOTICE_BASE} ${NOTICE_BAR[save.data.capped ? "warn" : "ok"]}`}
          >
            {save.data.capped
              ? "Outgoing calls are stopped for the rest of this month. Incoming calls still get through."
              : `In force this month: ${describeLimit(save.data.effective_cap_minutes, save.data.effective_cap_spend_inr)}.`}
          </div>
        )}
      </div>
    </Section>
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


function Row({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 py-3.5">
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
