"use client";

import { useEffect, useRef, useState } from "react";
import { Coins, Sparkles, Wallet } from "lucide-react";

import {
  Card,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
} from "@/components/ui";
import { useAiQuota, useBuyAiExtra, type AiQuota } from "@/lib/api/aiQuota";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import type { Session } from "@/lib/api/client";

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
export default function AiAssistPage() {
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
  const refused = me.data !== undefined && !me.data.permissions.includes("billing:read");
  if (refused) {
    return (
      <RestrictionNote reason="AI help and what it costs are limited to the account owner. Ask them to check this month's allowance, or to give you owner access." />
    );
  }

  const data = quota.data;

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        {data
          ? `Billing month ${data.month} (Indian Standard Time).`
          : "What AI help this account has used this month."}
      </p>

      {quota.error && <ProblemNotice error={quota.error} onRetry={() => void quota.refetch()} />}

      {/* A skeleton is not a number and a failure is not a zero: with no answer yet the
          screen shows neither figures nor a reassuring blank. */}
      {!data ? (
        quota.error ? null : <Skeleton rows={5} />
      ) : (
        <>
          <StateNotice quota={data} session={session} />

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <StatTile
              label="AI help used"
              value={formatCount(data.requests_used)}
              icon={<Sparkles className="h-5 w-5" />}
              hint={`of about ${formatCount(data.requests_included)} this month`}
            />
            <StatTile
              label="Allowance left"
              value={formatINR(data.remaining_inr)}
              icon={<Coins className="h-5 w-5" />}
              hint={
                data.requests_remaining > 0
                  ? `about ${formatCount(data.requests_remaining)} more`
                  : "none left this month"
              }
            />
            <StatTile
              label="Extra added"
              value={data.extra_purchased_inr === null ? "None" : formatINR(data.extra_purchased_inr)}
              icon={<Wallet className="h-5 w-5" />}
              tone={data.extra_purchased_inr === null ? "soft" : "strong"}
              hint={
                data.extra_purchased_inr === null
                  ? "Nothing extra bought this month"
                  : "Taken from your calling credit"
              }
            />
          </div>

          <Card title="How AI help is billed">
            <dl className="space-y-2 text-sm">
              <Row label="Included with your plan" value={formatINR(data.included_inr)} />
              <Row label="Used so far" value={formatINR(data.used_inr)} />
              <Row label="Available this month" value={formatINR(data.allowance_inr)} emphasis />
            </dl>
            <p className="mt-3 text-xs text-ink-muted">
              AI help is the assistance built into this console — re-writing a call
              summary, reshaping notes, answering a question about a call. Calevate pays
              for it up to the allowance above; past that you can add more for a fixed
              amount. Your calls, campaigns and leads are never affected by this
              allowance.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * What state this month is in, in the SERVER's own words.
 *
 * The four states are named by the API (`state`), not derived here from three numbers,
 * for the reason the module docstring gives: two implementations of "is this account at
 * its ceiling" is how a screen ends up offering a purchase the route will refuse.
 */
function StateNotice({ quota, session }: { quota: AiQuota; session: Session }) {
  if (quota.state === "platform_paused") {
    return (
      <NoticeBox tone="warn" title="AI help is paused right now">
        <p className="mt-1">
          We have paused AI help across Calevate while we check unusually high usage.
          Your calls, campaigns and leads are unaffected, and nothing has been charged.
          It comes back on its own — ask your account manager if you need it sooner.
        </p>
      </NoticeBox>
    );
  }

  if (quota.state === "exhausted") {
    return (
      <NoticeBox tone="stop" title="This month's AI help is finished">
        <p className="mt-1">
          You have used the AI help included with your plan and the extra you added. It
          starts again at the beginning of next month. Talk to your account manager if
          you need more before then.
        </p>
      </NoticeBox>
    );
  }

  if (quota.state === "ceiling_reached") {
    return <CeilingReached quota={quota} session={session} />;
  }

  return null;
}

/** The ceiling, and the only control in this console that debits a wallet. */
function CeilingReached({ quota, session }: { quota: AiQuota; session: Session }) {
  const [asking, setAsking] = useState(false);
  const buy = useBuyAiExtra(session);
  // `POST /v1/billing/ai-quota/extra` requires `org:manage` — a MUTATING permission, so
  // `staff` does not hold it and an impersonating operator is refused it (D-22).
  // Disabled with the reason beside it, rather than a 403 after the click.
  const write = useWriteAccess(session, "org:manage", "add more AI help");

  return (
    <>
      <NoticeBox tone="warn" title="You have used this month's included AI help">
        <p className="mt-1">
          AI help in the console has stopped for this month. Everything else — your
          calls, campaigns and leads — carries on exactly as before.
        </p>
        {quota.extra_available ? (
          <>
            <div className="mt-3">
              <RestrictionNote reason={write.reason} />
            </div>
            <button
              type="button"
              className={`${PRIMARY_BUTTON} mt-3`}
              disabled={!write.allowed}
              onClick={() => setAsking(true)}
            >
              See what more AI help costs
            </button>
          </>
        ) : (
          <p className="mt-3">{unavailableSentence(quota)}</p>
        )}
      </NoticeBox>

      {asking && (
        <AcceptChargeDialog
          quota={quota}
          pending={buy.isPending}
          error={buy.error}
          onCancel={() => {
            buy.reset();
            setAsking(false);
          }}
          onAccept={() =>
            // The SERVER's figure, echoed back untouched. Nothing here computes an
            // amount, and a mismatch is refused rather than clamped.
            buy.mutate(quota.extra_block_inr, { onSuccess: () => setAsking(false) })
          }
        />
      )}

      {buy.data && !asking && (
        <div role="status">
          <NoticeBox tone="ok" title="Added">
            <p className="mt-1">
              {formatINR(buy.data.extra_block_inr)} was taken from your calling credit and
              AI help is available again for the rest of {buy.data.month}.
            </p>
          </NoticeBox>
        </div>
      )}
    </>
  );
}

/**
 * Why the block is not on offer — the SERVER's reason, mapped to a sentence.
 *
 * The mapping is exhaustive and its fallback is deliberately vague rather than
 * confident: a reason this build does not know is a reason it must not paraphrase, and
 * "talk to your account manager" is true whatever it turns out to be.
 */
function unavailableSentence(quota: AiQuota): string {
  switch (quota.extra_unavailable_reason) {
    case "not_prepaid":
      return "More AI help for this month is arranged with your account manager — it goes on your invoice rather than coming out of a balance.";
    case "already_purchased":
      return "You have already added extra AI help this month.";
    case "not_at_ceiling":
      return "There is still included AI help left this month.";
    // The block expires with the billing month, so within the last hour of one there is
    // nothing left to sell: the server refuses the purchase (`ai_extra_month_ending`)
    // and this is that refusal said BEFORE the click rather than after it.
    case "month_ending":
      return "This month is nearly over, so there is nothing worth adding to it — your included AI help comes back within the hour, and it is larger than what you would be buying.";
    default:
      return "More AI help cannot be added from here right now — talk to your account manager.";
  }
}

/**
 * G-5, as a screen: the feature blocks and ASKS, naming what it will cost and what will
 * be debited, and nothing moves until a person presses accept.
 *
 * Four sentences are load-bearing and each is here because leaving it out would make the
 * dialog a worse bargain than the one being offered:
 *
 * 1. the exact amount, as the server sent it — `formatINR` groups the digits and never
 *    parses them;
 * 2. what it buys, as a count the server derived, with "about";
 * 3. that the unused part is NOT refunded and does NOT carry over — the honest cost of
 *    selling a block rather than metering per use;
 * 4. that nothing has been charged yet, which is the whole promise of the dialog.
 *
 * ACCESSIBILITY. `role="dialog"` + `aria-modal` + a heading it is labelled by, focus
 * moved to the dialog on open, and Escape cancels. The two buttons are real buttons in
 * DOM order, so a keyboard reaches "Not now" first — the safe answer should not be the
 * one that takes more keystrokes.
 */
function AcceptChargeDialog({
  quota,
  pending,
  error,
  onCancel,
  onAccept,
}: {
  quota: AiQuota;
  pending: boolean;
  error: unknown;
  onCancel: () => void;
  onAccept: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
  }, []);

  /**
   * Escape on the DOCUMENT, not on a wrapper's `onKeyDown`.
   *
   * Two reasons and the second is the real one. A React handler on the backdrop only
   * fires for keys pressed inside its own subtree, so Escape would stop working the
   * moment focus left the dialog — which is exactly when a person reaches for it. And a
   * `<div onKeyDown>` is a non-native interactive element (`jsx-a11y/
   * no-static-element-interactions`): the lint rule is right, and the fix it is asking
   * for is this one rather than a role that would lie about what the element is.
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-extra-title"
        aria-describedby="ai-extra-body"
        tabIndex={-1}
        className="w-full max-w-md rounded-card border border-line bg-surface p-6 shadow-lg outline-none"
      >
        <h2 id="ai-extra-title" className="text-[17px] font-semibold text-ink">
          Add more AI help this month
        </h2>

        <div id="ai-extra-body" className="mt-3 space-y-3 text-sm text-ink-muted">
          <p>
            <strong className="font-semibold tabular-nums text-ink">
              {formatINR(quota.extra_block_inr)}
            </strong>{" "}
            will be taken from your calling credit. It covers about{" "}
            {formatCount(quota.extra_block_requests)} more uses of AI help for the rest of{" "}
            {quota.month}.
          </p>
          <p>
            Anything you do not use is not refunded and does not carry into next month.
            You can add this once per month.
          </p>
          <p className="font-medium text-ink">Nothing has been charged yet.</p>
        </div>

        {/* A refusal INSIDE the dialog, because that is where the decision is being
            made: closing the dialog to show it elsewhere would leave a person unsure
            whether the money moved. */}
        {error != null && (
          <div className="mt-3">
            <ProblemNotice error={error} />
          </div>
        )}

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button type="button" className={SECONDARY_BUTTON} onClick={onCancel} disabled={pending}>
            Not now
          </button>
          <button type="button" className={PRIMARY_BUTTON} onClick={onAccept} disabled={pending}>
            {pending ? "Adding…" : `Add ${formatINR(quota.extra_block_inr)}`}
          </button>
        </div>
      </div>
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
