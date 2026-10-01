"use client";

import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import { PageHeader } from "@/components/console/pageHeader";
import { Panel } from "@/components/console/panel";
import { ProgressBar } from "@/components/interior/progress-bar";
import {
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatINR,
} from "@/components/ui";
import { useAiQuota } from "@/lib/api/aiQuota";
import { useMe } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { formatBillingMonth } from "@/lib/billingMonth";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { Row, StateNotice } from "./notices";

/**
 * AI help: what this month includes, what it has used, and what more costs (D-127 —
 * G-3, G-4, G-5).
 *
 * ## What this screen is for
 *
 * Calevate owns the AI credential and absorbs the cost (G-3), which is invisible until
 * the moment it stops — so this screen exists to make the ceiling visible BEFORE it is
 * reached, and to be the one place a person can agree to spend money on more.
 *
 * ## Two units, and which one is real
 *
 * The ceiling is RUPEES; the assist counts are what an owner can plan around. Nobody can
 * reason about "₹41.70 of ₹100 of language-model inference", and a count alone would be
 * a promise we cannot keep — one long document costs what a hundred short questions do.
 * So both are shown, the count carries the word "about", and the rupee figure is the one
 * every sentence about blocking refers to. Neither number is computed here: the server
 * publishes both, because a browser dividing a rupee amount is hard rule 7 waiting to
 * happen (`lib/api/aiQuota.ts`).
 *
 * ## §52
 *
 * Loading is a skeleton and failure is a refusal, and neither is a number: there is no
 * `?? 0` and no `?? "—"` anywhere below. A failed read leaves the tiles unrendered and a
 * `ProblemNotice` with a retry in their place — an allowance figure invented while the
 * request was in flight is exactly the class of defect that has an owner planning around
 * a ceiling that is not theirs.
 *
 * ## The modal (G-5)
 *
 * Nothing leaves the wallet until a person accepts, so the button opens a dialog that
 * names the exact figure, says what it buys, says plainly that the unused part is not
 * carried over, and says that nothing has been charged YET. "Not now" is a real answer
 * and is the button that gets focus semantics for free by being first in the DOM after
 * the text. The accept button is the only control in this console that debits a wallet.
 *
 * The offer is gated on the SERVER's `extra_available`, never on the browser's reading
 * of three other fields, and it is disabled with the reason beside it when the person
 * lacks `org:manage` — a 403 after the click would be a refusal we could see coming.
 */
export function AiAssistScreen() {
  const session = useClientSession();
  const quota = useAiQuota(session);
  const me = useMe(session);

  /**
   * `GET /v1/billing/ai-quota` requires `billing:read` (billing/ai_quota_routes.py),
   * which `staff` does not hold — spend is an owner's business (SEC-COMP §5). Read off
   * `/v1/me` rather than from a role list this build would have to keep in step with
   * `core/rbac.py`, and NOT through `useWriteAccess`: that refuses every permission to
   * an impersonating operator (D-22), which is right for a control that spends money and
   * wrong for a panel an operator on a support call should be able to see.
   *
   * While `/v1/me` is in flight nothing is refused, so the screen never flashes an
   * explanation it is about to withdraw.
   */
  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`) — including the
   * one screen that is ABOUT the assistant, which is the screen a person opens when it
   * has just refused them.
   *
   * The whole of it is money and counts. The one act here — buying another block of AI
   * help — spends the client's money behind an explicit charge dialog, so nothing is
   * declared writable and the dialog's own controls are not declared at all.
   */
  useCopilotSurface({
    route: "/c/{slug}/ai-assist",
    title: "AI help",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value:
          me.data !== undefined && !me.data.permissions.includes("billing:read")
            ? "a refusal — this session may not read billing, so the allowance is not shown"
            : quota.data
              ? "the allowance below has loaded"
              : quota.error
                ? "the allowance failed to load"
                : "still loading",
      },
      ...(quota.data
        ? [
            { key: "month", label: "Billing month (IST)", value: quota.data.month },
            { key: "plan_tier", label: "Plan", value: quota.data.plan_tier },
            { key: "quota_state", label: "State of the allowance", value: quota.data.state },
            { key: "requests_used", label: "AI requests used this month", value: String(quota.data.requests_used) },
            { key: "requests_included", label: "AI requests included", value: String(quota.data.requests_included) },
            { key: "requests_remaining", label: "AI requests remaining", value: String(quota.data.requests_remaining) },
            { key: "used_inr", label: "Spent on AI help this month (INR)", value: quota.data.used_inr },
            { key: "kb_used_inr", label: "Of that, spent on adding knowledge (INR)", value: quota.data.kb_used_inr },
            { key: "kb_requests_used", label: "Knowledge jobs this month", value: String(quota.data.kb_requests_used) },
            { key: "balance_inr", label: "Allowance left, signed — negative means overdrawn (INR)", value: quota.data.balance_inr },
            { key: "allowance_inr", label: "Allowance for AI help (INR)", value: quota.data.allowance_inr },
            { key: "remaining_inr", label: "Allowance left (INR)", value: quota.data.remaining_inr },
            {
              key: "extra_available",
              label: "May another block be bought?",
              value: quota.data.extra_available
                ? `yes — ${quota.data.extra_block_requests} more requests for INR ${quota.data.extra_block_inr}`
                : `no — ${quota.data.extra_unavailable_reason ?? "no reason given"}`,
            },
            {
              key: "extra_purchased_inr",
              label: "Extra already bought this month (INR)",
              value: quota.data.extra_purchased_inr ?? "none",
            },
          ]
        : []),
    ],
    apply: noFill,
  });

  const refused = me.data !== undefined && !me.data.permissions.includes("billing:read");
  if (refused) {
    return (
      <RestrictionNote reason="AI help and what it costs are limited to the account owner. Ask them to check this month's allowance, or to give you owner access." />
    );
  }

  const data = quota.data;

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        description={
          data
            ? formatBillingMonth(data.month)
            : "What AI help this account has used this month."
        }
      />

      {quota.error && <ProblemNotice error={quota.error} onRetry={() => void quota.refetch()} />}

      {/* A skeleton is not a number and a failure is not a zero. */}
      {!data ? (
        quota.error ? null : <Skeleton rows={5} label="Loading this month's AI help" />
      ) : (
        <>
          <StateNotice quota={data} session={session} />

          {/* THE METER. Its length is the request COUNT against the included count — two
              integers the server publishes — never a division of rupee strings. */}
          <section className="space-y-3 border-b border-line pb-6">
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
              <div>
                <p className="flex items-center gap-1 text-[13px] font-medium text-ink-muted">
                  AI help used
                  <InfoTip label="AI help">
                    <p>
                      AI help is the assistance built into this console — re-writing a call
                      summary, reshaping notes, answering a question about a call. It also
                      covers preparing what you add: when you send us a document or a
                      photograph of a printed page, we read the text out of it, write a short
                      English key beside anything in another script, and index both — so your
                      agent answers from what you approved. Calevate pays for all of it up to
                      the allowance; past that you can add more for a fixed amount.
                    </p>
                  </InfoTip>
                </p>
                <p className="mt-1 flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[26px] font-semibold leading-tight tracking-tight tabular-nums text-ink">
                    {formatCount(data.requests_used)}
                  </span>
                  <span className="text-sm text-ink-muted">
                    of about {formatCount(data.requests_included)} this month
                  </span>
                </p>
              </div>
              <p className="text-sm text-ink-muted sm:text-right">
                <span className="font-semibold tabular-nums text-ink">
                  {formatINR(data.remaining_inr)}
                </span>{" "}
                left
                {" · "}
                {data.requests_remaining > 0
                  ? `about ${formatCount(data.requests_remaining)} more`
                  : "none left this month"}
              </p>
            </div>
            {data.requests_included > 0 ? (
              <ProgressBar
                value={data.requests_used}
                max={data.requests_included}
                label="Share of this month's included AI help used"
                completeLabel="All of this month's included AI help is used"
                /* The figures above already say it in words; the bar's own label row stays
                   for assistive technology (it names the progressbar) but not on screen. */
                className="[&>div:first-child]:sr-only"
              />
            ) : (
              <p className="text-sm text-ink-muted">No AI help is included on your plan.</p>
            )}
          </section>

          <div className="grid grid-cols-2 gap-x-6 gap-y-5">
            <Metric
              label="Preparing what you add"
              value={formatINR(data.kb_used_inr)}
              hint={
                data.kb_requests_used > 0
                  ? `part of the amount used — ${formatCount(data.kb_requests_used)} ${
                      data.kb_requests_used === 1 ? "job" : "jobs"
                    } on your documents`
                  : "part of the amount used — nothing added this month"
              }
            />
            <Metric
              label="Extra added"
              value={
                data.extra_purchased_inr === null ? "None" : formatINR(data.extra_purchased_inr)
              }
              hint={
                data.extra_purchased_inr === null
                  ? "Nothing extra bought this month"
                  : "Taken from your calling credit"
              }
            />
          </div>

          <Panel title="How AI help is billed">
            <dl className="space-y-2 text-sm">
              <Row label="Included with your plan" value={formatINR(data.included_inr)} />
              <Row label="Used so far" value={formatINR(data.used_inr)} />
              {/* "of which" (D-608): the knowledge line is a COMPONENT of the amount used,
                  so it must never read as a second charge. */}
              <Row
                label="— of which, preparing what you added"
                value={formatINR(data.kb_used_inr)}
                muted
              />
              <Row label="Available this month" value={formatINR(data.allowance_inr)} emphasis />
            </dl>
            <p className="mt-3 text-xs text-ink-muted">
              Your calls, campaigns and leads are never affected by this allowance.
            </p>
            {/* THE OVERDRAFT, IN WORDS, ONLY WHEN IT IS REAL (D-608). Uploading is not
                blocked at the ceiling, so the balance can go negative and `remaining_inr`
                clamps at zero; saying nothing would hide a number this screen knows. It is
                not dressed as a demand, because what happens next is undecided. */}
            {data.balance_inr.trimStart().startsWith("-") && (
              <p className="mt-3 text-xs text-ink-muted">
                You have used{" "}
                <strong className="font-semibold text-ink">
                  {formatINR(data.balance_inr.replace("-", ""))}
                </strong>{" "}
                more than this month&apos;s allowance, mostly on preparing what you
                added. Nothing has been charged for it and nothing has stopped — what you
                send is still being prepared. We will be in touch before anything about
                that changes.
              </p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
