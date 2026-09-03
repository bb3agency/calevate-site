"use client";

import { Card, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { runwaySentence, useWallet, useWalletLedger, walletState } from "@/lib/api/wallet";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { InvoicedAccount } from "./InvoicedAccount";
import { TopUp } from "./TopUp";
import { UnfinishedPayments } from "./UnfinishedPayments";
import { WalletHero } from "./WalletHero";
import { WalletLedgerPanel } from "./WalletLedgerPanel";
import { WhereItWent } from "./WhereItWent";

/**
 * Calling credit — the screen an account owner opens to answer three questions.
 *
 * ## Why this screen exists
 *
 * The client realm had `spend`, `usage` and `invoice` and NO wallet screen. The balance
 * was a tile at the bottom of Usage, behind `billing:read` — which `staff` does not hold —
 * and the only way to buy credit was to scroll past a month's usage figures to find a
 * panel under it. So the person whose money it is could not see the ledger, could not see
 * a payment that had failed, and could not answer the one question that actually decides
 * whether they top up: how long does this last.
 *
 * ## The order on the page IS the argument
 *
 * 1. **Balance and runway**, as a pair and at the same weight. A rupee figure means
 *    nothing to a clinic owner; days do.
 * 2. **Unfinished payments**, when there are any — above the control that would start
 *    another, because a client who has just paid must not have to look past a rate card to
 *    find out whether it worked.
 * 3. **Add credit.** Two clicks from the dashboard: this nav entry, then a pack.
 * 4. **Where it went**, then **the full history** with a receipt per payment. Both are
 *    explanations, and they belong after the thing they explain.
 *
 * ## Permission: seeing is not buying (the founder's decision, 2 Sep 2026)
 *
 * The READ is `wallet:read`, which every client role holds INCLUDING `staff` — the thing
 * that stops a staff member dialling is an empty wallet, and a refusal whose explanation
 * only the owner can see is a refusal with no words in it. BUYING is `org:manage`, and
 * `TopUp` gates itself on that through `useWriteAccess`, which also refuses an
 * impersonating operator (D-22): support can see a client's wallet and can never spend
 * from it.
 *
 * The gate below is on the READ permission only, and it is read off `/v1/me` rather than
 * from a role list this build would have to keep in step with `core/rbac.py`. While
 * `/v1/me` is in flight nothing is refused, so the screen never flashes an explanation it
 * is about to withdraw (§52).
 *
 * ## What this screen does NOT do
 *
 * It computes nothing. Every rupee figure is the server's, formatted from its digits and
 * never parsed (hard rule 7 reaches the browser); the runway, the burn rate and the
 * drawdown buckets are all `billing/wallet.py`'s arithmetic. And it re-derives no verdict:
 * "outgoing calls have stopped" is `outbound_stopped`, the dial gate's own answer, not a
 * balance comparison made here.
 *
 * NO `<h1>`: the app shell renders the page title from the nav list it also renders.
 */
export default function CreditsPage() {
  const { session } = useClientRealm();
  const me = useMe(session);
  const wallet = useWallet(session);
  /*
   * THE HISTORY, read HERE as well as in the panel below — and it costs no request: both
   * callers share one query key, so TanStack serves the second from the cache of the
   * first. What the hero needs from it is one bit that the wallet read structurally
   * cannot carry: `outbound_stopped` is identically true for an account that has spent
   * everything and for one that has never had anything, and those are different news.
   * `null` while it is in flight, never `false` — an unknown is not an answer (§52).
   */
  const ledger = useWalletLedger(session);
  const funded = ledger.data ? ledger.data.entries.length > 0 : null;

  /*
   * THE WALLET, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * Read-only (`noFill`): there is no field on this screen an assistant may fill, and the
   * one control that spends money is deliberately not reachable from it — an assistant
   * that could start a payment could talk an account into one.
   */
  useCopilotSurface({
    route: "/c/{slug}/credits",
    title: "Calling credit",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value:
          me.data !== undefined && !me.data.permissions.includes("wallet:read")
            ? "a refusal — this session may not see the wallet"
            : wallet.data
              ? "the balance and history below have loaded"
              : wallet.error
                ? "the balance failed to load"
                : "still loading",
      },
      ...(wallet.data
        ? [
            { key: "prepaid", label: "Does this account have a wallet?", value: wallet.data.prepaid ? "yes, it is prepaid" : "no — it is invoiced against a retainer" },
            { key: "balance_inr", label: "Calling credit balance (INR)", value: wallet.data.balance_inr },
            { key: "runway", label: "How long the credit lasts", value: runwaySentence(wallet.data.runway) },
            {
              key: "minutes_left",
              label: "Minutes of calling the balance buys",
              value:
                wallet.data.minutes_left === null
                  ? "not priced on this deployment"
                  : String(wallet.data.minutes_left),
            },
            {
              key: "outbound_stopped",
              label: "Are outgoing calls stopped for lack of credit?",
              value: wallet.data.outbound_stopped
                ? "yes — incoming calls are still answered"
                : "no",
            },
            { key: "spent_inr", label: `Spent in the last ${wallet.data.runway.window_days} days (INR)`, value: wallet.data.drawdown.spent_inr },
            { key: "calls_inr", label: "Of that, calls (INR)", value: wallet.data.drawdown.calls_inr },
            { key: "ai_assist_inr", label: "Of that, extra AI help (INR)", value: wallet.data.drawdown.ai_assist_inr },
          ]
        : []),
    ],
    apply: noFill,
  });

  /* THE PERMISSION GATE, in the two-step shape `/usage` and `/invoice` use — and the
     `!== undefined` is the load-bearing half. While `/v1/me` is in flight nothing is
     refused, so the screen never flashes an explanation it is about to withdraw; and if
     `/v1/me` itself FAILED we do not know what this session may see, so the request goes
     out and the API's own answer is what renders. Refusing on our own ignorance would
     show a client a restriction the server never applied. */
  const refused = me.data !== undefined && !me.data.permissions.includes("wallet:read");
  if (refused) {
    return (
      <RestrictionNote reason="Your calling credit is limited to people with access to this account's billing. Ask the account owner to share the balance, or to give you access." />
    );
  }

  /* §52, all three arms. A skeleton while it is in flight, the server's own refusal when
     it failed, and — for the case neither arm catches — a refusal rather than a blank:
     TanStack PARKS a query while the browser is offline (`fetchStatus: "paused"`), which
     reports `isLoading === false` AND `error === null` with `data === undefined`. A
     `return null` there is a screen that says a wallet has nothing in it. */
  if (wallet.isLoading) return <Skeleton rows={6} label="Loading your calling credit" />;
  if (wallet.error || !wallet.data) {
    return <ProblemNotice error={wallet.error} onRetry={() => void wallet.refetch()} />;
  }

  /* AN INVOICED ACCOUNT HAS NO WALLET, and this is not an empty state — it is a
     different screen, argued in `InvoicedAccount.tsx`. It used to be four lines saying
     what this screen is not, which was survivable while nearly every account was invoiced
     and nobody opened it; prepaid is now what an account gets unless an operator decides
     otherwise, so this is the RARE branch and the one most likely to be reached by
     somebody who was told they had a balance. */
  if (walletState(wallet.data) === "not-prepaid") {
    return <InvoicedAccount />;
  }

  return (
    <div className="space-y-5 pb-12">
      <WalletHero wallet={wallet.data} funded={funded} />

      {/* ABOVE the control that would start another payment (UX-DOCTRINE §4): a client
          who has just paid must not have to look past a rate card to find out whether it
          worked. Renders nothing when there is nothing outstanding. */}
      <UnfinishedPayments session={session} />

      <Card title="Add credit">
        <TopUp session={session} />
      </Card>

      <WhereItWent
        drawdown={wallet.data.drawdown}
        windowDays={wallet.data.runway.window_days}
      />

      <WalletLedgerPanel session={session} />
    </div>
  );
}
