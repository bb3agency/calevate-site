"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";

import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  PRIMARY_BUTTON_LG,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatINR,
  formatRupeeRate,
} from "@/components/ui";
import { useCreditPacks } from "@/lib/api/billing";
import { useMe } from "@/lib/api/hooks";
import { currentISTMonth } from "@/lib/api/invoice";
import { useClientRealm } from "@/lib/api/session";
import {
  activeTrial,
  runwaySentence,
  trialEndsAt,
  trialTimeLeft,
  useWallet,
  useWalletLedger,
  walletState,
} from "@/lib/api/wallet";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { GST_STATUS_SENTENCE } from "@/lib/gstStatus";
import { asText } from "@/lib/copilot/types";

import { AddCreditDrawer } from "./AddCredit";
import {
  VOICE_TIERS,
  formatWhole,
  lotRate,
  tierLabels,
  tierRunway,
  useWalletLots,
} from "./lots";
import { InvoicedAccount } from "./InvoicedAccount";
import { LotsPanel } from "./LotsPanel";
import { StatementsView } from "./StatementsView";
import { TransactionsTab } from "./TransactionsTab";
import { UnfinishedPayments } from "./UnfinishedPayments";
import { UsageView } from "./UsageView";
import { WalletHero } from "./WalletHero";
import { BILLING_VIEWS, isBillingView, resolveBillingTab, type BillingView } from "./tabs";

/**
 * CREDITS & BILLING — one hub (D-525): a wallet header over three views.
 *
 * The client realm once had four money screens and none answered "what am I paying?".
 * D-525 made them one, and the round-2 redesign made that one a wallet header — balance,
 * runway and the screen's one primary action, Add credit — above three PEER VIEWS of the
 * account's money (Usage, Transactions, Statements) on a SegmentedControl (D-655). The four
 * old routes still redirect here, and `?tab=` still resolves (`tabs.ts`).
 *
 * The view is in the URL: read on mount and written on every change, so a support
 * conversation can link to the exact view, and a refresh keeps it.
 *
 * ## PERMISSION: the screen reads on `wallet:read`, and the OWNER's figures refuse per view
 *
 * This is the change that matters most for staff. `wallet:read` is held by EVERY client
 * role including `staff` — the thing that stops a staff member dialling is an empty
 * wallet, and a refusal whose explanation only the owner can see is a refusal with no
 * words in it. `billing:read` (the month's figures, the per-call breakdown, the statement,
 * the pack prices) is the owner's, and each tab that needs it says so in a sentence.
 *
 * Before the hub, a staff member saw "Usage", "Spend" and "Invoice" in the sidebar and got
 * a whole-screen refusal on each. Now they get the balance, the runway, the reason their
 * dialling stopped, and one honest sentence where the owner's figures would be.
 *
 * The gate is read off `/v1/me` rather than from a role list this build would have to keep
 * in step with `core/rbac.py`. While `/v1/me` is in flight nothing is refused, so the
 * screen never flashes an explanation it is about to withdraw (§52). NOT `useWriteAccess`:
 * that refuses every permission to an impersonating operator (D-22), which is right for a
 * control that writes and wrong for a read an operator legitimately holds.
 *
 * ## It computes nothing
 *
 * Every rupee figure on every tab is the server's, formatted from its digits and never
 * parsed (hard rule 7 reaches the browser), and no verdict is re-derived here.
 *
 * NO `<h1>`: the app shell renders the page title from the nav list it also renders.
 */
export function BillingScreen({ slug }: { slug: string }) {
  const { session } = useClientRealm();
  const me = useMe(session);
  const wallet = useWallet(session);
  const searchParams = useSearchParams();

  /*
   * THE HISTORY, read HERE as well as in the Transactions tab — and it costs no request:
   * both callers share one query key, so TanStack serves the second from the cache of the
   * first. What the Overview hero needs from it is one bit the wallet read structurally
   * cannot carry: `outbound_stopped` is identically true for an account that has spent
   * everything and for one that has never had anything, and those are different news.
   * `null` while it is in flight, never `false` — an unknown is not an answer (§52).
   */
  const ledger = useWalletLedger(session);
  const funded = ledger.data ? ledger.data.entries.length > 0 : null;

  /* The rate card the explainer and the pack chooser quote. `/v1/billing/topups/packs` is
     `billing:read`, so for a staff session this stays `undefined` and the explainer drops
     the sentences that need a rupee figure rather than inventing one. */
  const packs = useCreditPacks(session);
  /* The tier NAMES a client reads ("Clear", "Studio"), from the same response. Held
     nowhere in this tree: no client-facing surface names a vendor as a product tier
     (founder, 7 Sep 2026), and a copy in TypeScript is how the two definitions drift
     until one client meets both. Absent on a build that does not send them yet, and
     every panel then renders no quality name and no per-minute rate at all. */
  const labels = tierLabels(packs.data);

  /*
   * THE LOT QUEUE — what credit is left, at which two rates, in the order it is spent, and
   * the runway in minutes on each quality (D-547).
   *
   * Its own read rather than a field on the wallet: a balance under lots is several
   * purchases at several frozen rates, and NOTHING on this screen may quote a per-minute
   * price that is not one of them. A read that has not answered renders no lot list, no
   * runway pair and no rate — never `wallet.minutes_left`, which divides one balance by one
   * LIST rate and is the arithmetic lots exist to retire.
   */
  const lots = useWalletLots(session).data;

  /* One month for the two panels that can look backwards — the per-agent breakdown and the
     statement. Held HERE rather than in each tab so a client who picks July on one does not
     find the other still showing August; they are two views of the same month and having
     them disagree is how a support call starts. */
  const [month, setMonth] = useState(currentISTMonth);

  /* `?tab=` is read once on mount: a view, or `credits`, which opens the Add credit
     drawer over the default view (`tabs.ts` keeps the retired values resolving). */
  const [initial] = useState(() => resolveBillingTab(searchParams.get("tab")));
  const [view, setView] = useState<BillingView>(initial.view);
  const [addingCredit, setAddingCredit] = useState(initial.addCredit);
  const selectView = (next: string) => {
    if (!isBillingView(next)) return;
    setView(next);
    /* `replaceState`, not `router.push`: switching a view is not a navigation, and a push
       would make the Back button walk the views instead of leaving the screen. */
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", next);
      window.history.replaceState(window.history.state, "", url);
    }
  };

  /*
   * THE HUB, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ONE surface for four tabs, and it says WHICH tab is open — an assistant that knew the
   * client was "on the billing page" but not which panel would answer half of every
   * question wrongly. The tab is a WRITABLE field for the same reason the month picker is
   * on the screens it replaced: "show me my transactions" is what a person opens this
   * screen to say, and moving the tab changes nothing but what is rendered.
   *
   * NOTHING THAT SPENDS MONEY IS REACHABLE FROM IT. There is no field here that starts a
   * payment; an assistant that could would be an assistant that can talk an account into
   * one.
   */
  useCopilotSurface({
    route: "/c/{slug}/billing",
    title: "Credits & billing",
    realm: "client",
    fields: [
      {
        id: "billing-tab",
        label: "Which part of billing is open",
        type: "text",
        value: view,
        help: "One of: usage, transactions, statements.",
      },
      {
        id: "billing-month",
        label: "Billing month for the breakdown and the statement",
        type: "text",
        value: month,
        help: "YYYY-MM, in Indian Standard Time.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value:
          me.data !== undefined && !me.data.permissions.includes("wallet:read")
            ? "a refusal — this session may not see the account's billing"
            : wallet.data
              ? "the figures below have loaded"
              : wallet.error
                ? "the figures failed to load"
                : "still loading",
      },
      { key: "tab", label: "The open view", value: view },
      {
        key: "owner_figures",
        label: "May this session see the month's figures and the statement?",
        value:
          me.data === undefined
            ? "we have not read this session's access yet"
            : me.data.permissions.includes("billing:read")
              ? "yes"
              : "no — those are limited to the account owner",
      },
      ...(wallet.data
        ? [
            {
              key: "prepaid",
              label: "Does this account have a wallet?",
              value: wallet.data.prepaid
                ? "yes, it is prepaid"
                : "no — it is invoiced against a retainer",
            },
            { key: "balance_inr", label: "Calling credit balance (INR)", value: wallet.data.balance_inr },
            { key: "runway", label: "How long the credit lasts", value: runwaySentence(wallet.data.runway) },
            {
              /* PER VOICE QUALITY, because one balance no longer buys one number of
                 minutes: each purchase freezes its own two rates and the answer depends
                 on which voice the agent that takes the call speaks with. Named with the
                 API's own words for the qualities, never the vendors'. */
              key: "minutes_left",
              label: "Minutes of calling the credit buys, per voice quality",
              value:
                lots === undefined
                  ? "we cannot say — this deployment does not publish the per-purchase rates yet"
                  : lots.tiers
                      .map(
                        (tier) =>
                          `${tier.label}: ${
                            /* `formatWhole`, not the raw string: the wire sends
                               `"1080.0000"` and every screen on this hub renders it as
                               "1,080". A copilot fact is read ALOUD, and "one thousand
                               and eighty point zero zero zero zero minutes" is the
                               assistant quoting a database column at a client. */
                            tier.minutes_left === null
                              ? "not priced"
                              : `${formatWhole(tier.minutes_left)} minutes`
                          }`,
                      )
                      .join("; "),
            },
            {
              key: "credit_lots",
              label: "The credit on the account, oldest purchase first, with its rates",
              value:
                lots === undefined
                  ? "we have not read the purchases behind this balance"
                  : lots.lots.length === 0
                    ? "no credit is left on the account"
                    : lots.lots
                        .map((lot) => {
                          // The NAME comes from the server's runway row and the RATE from
                          // the lot, joined on the quality — never a vendor string typed
                          // here, and no name at all for a quality the server did not send.
                          const priced = VOICE_TIERS.flatMap((tier) => {
                            const runway = tierRunway(lots, tier);
                            return runway
                              ? [`${formatRupeeRate(lotRate(lot, tier))}/min on ${runway.label}`]
                              : [];
                          });
                          return `${formatINR(lot.credits_remaining)} of credit at ${priced.join(" or ")}`;
                        })
                        .join(", then "),
            },
            {
              key: "outbound_stopped",
              label: "Are calls stopped for lack of credit?",
              /* THE LABEL SAYS "calls", NOT "outgoing calls", AND THE FIELD KEEPS ITS
                 WIRE NAME. An empty wallet now stops both directions (D-551), so an
                 assistant told only about outgoing would answer "your phone is still
                 being answered" to the one client for whom that is false. */
              value: wallet.data.outbound_stopped
                ? "yes — outgoing calls have stopped and the agents are no longer answering incoming ones; adding credit starts both again straight away"
                : "no",
            },
            {
              /* WHY A ₹0.00 WALLET IS STILL CALLING, when it is. Without it an assistant
                 reading a zero balance would tell a client on a trial to top up before
                 their calls stop, which is false until the trial ends (D-536). */
              key: "trial",
              label: "Is the account on a free trial?",
              value: (() => {
                const trial = activeTrial(wallet.data);
                return trial === null
                  ? "no"
                  : `yes, until ${trialEndsAt(trial)} (${trialTimeLeft(trial).text}) — calls are on us, nothing is taken from the credit, and an empty balance stops no calls until then`;
              })(),
            },
            {
              /* THE SAME BIT THE HERO NEEDS, declared for the same reason: the assistant
                 must not tell a client on their first afternoon that their credit ran
                 out, and `outbound_stopped` alone cannot tell it that it did not. */
              key: "funded",
              label: "Has anything ever been added to this wallet?",
              value:
                funded === null
                  ? "we have not read the history yet"
                  : funded
                    ? "yes"
                    : "no — nothing has ever moved on it",
            },
            {
              key: "spent_inr",
              label: `Spent in the last ${wallet.data.runway.window_days} days (INR)`,
              value: wallet.data.drawdown.spent_inr,
            },
            { key: "calls_inr", label: "Of that, calls (INR)", value: wallet.data.drawdown.calls_inr },
            {
              key: "number_rental_inr",
              label: "Of that, phone number rental (INR)",
              value: wallet.data.drawdown.number_rental_inr,
            },
            {
              key: "ai_assist_inr",
              label: "Of that, extra AI help (INR)",
              value: wallet.data.drawdown.ai_assist_inr,
            },
          ]
        : []),
      {
        key: "gst",
        label: "Is GST added, and can a tax invoice be issued?",
        value: GST_STATUS_SENTENCE,
      },
    ],
    apply: (items) => {
      for (const item of items) {
        const wanted = asText(item.value);
        if (item.field_id === "billing-tab" && isBillingView(wanted)) selectView(wanted);
        if (item.field_id === "billing-month" && /^\d{4}-(0[1-9]|1[0-2])$/.test(wanted)) {
          setMonth(wanted);
        }
      }
    },
  });

  /* THE PERMISSION GATE, in the two-step shape every gated client screen uses — and the
     `!== undefined` is the load-bearing half. While `/v1/me` is in flight nothing is
     refused, so the screen never flashes an explanation it is about to withdraw; and if
     `/v1/me` itself FAILED we do not know what this session may see, so the requests go
     out and the API's own answers are what render. */
  const refused = me.data !== undefined && !me.data.permissions.includes("wallet:read");
  if (refused) {
    return (
      <RestrictionNote reason="Your account's billing is limited to people with access to it. Ask the account owner to share the balance, or to give you access." />
    );
  }
  const billingRefused = me.data !== undefined && !me.data.permissions.includes("billing:read");
  /* For the owner-only reads this screen GATES (the statement list and the daily series):
     `null` while `/v1/me` is in flight, so nothing is sent or refused yet; and when `/v1/me`
     itself failed we do not know, so the read goes out and the API's answer renders. */
  const billingAllowed: boolean | null =
    me.data !== undefined ? !billingRefused : me.isError ? true : null;

  /*
   * The wallet header — §52, all three arms. A skeleton while it is in flight, the server's
   * own refusal when it failed, and a refusal rather than a blank for the case neither arm
   * catches: TanStack PARKS a query while the browser is offline, reporting no error and no
   * data. It is scoped to the header, not the screen: a failed balance read must not take
   * the statements and the month's figures down with it.
   */
  const header = () => {
    if (wallet.isLoading) return <Skeleton rows={4} label="Loading your balance" />;
    if (wallet.error || !wallet.data) {
      return <ProblemNotice error={wallet.error} onRetry={() => void wallet.refetch()} />;
    }
    if (walletState(wallet.data) === "not-prepaid") return <InvoicedAccount />;
    return (
      <div className="space-y-5">
        <WalletHero
          wallet={wallet.data}
          funded={funded}
          lots={lots}
          action={
            <button
              type="button"
              onClick={() => setAddingCredit(true)}
              className={`${PRIMARY_BUTTON_LG} w-full justify-center lg:w-auto`}
            >
              <Plus aria-hidden className="h-4 w-4" />
              Add credit
            </button>
          }
        />
        <UnfinishedPayments session={session} />
        {lots && <LotsPanel lots={lots} />}
      </div>
    );
  };

  const view_ = () => {
    switch (view) {
      case "transactions":
        return <TransactionsTab session={session} labels={labels} />;
      case "statements":
        return <StatementsView session={session} allowed={billingAllowed} />;
      default:
        return (
          <UsageView
            session={session}
            slug={slug}
            month={month}
            onMonthChange={setMonth}
            billingAllowed={billingAllowed}
            wallet={wallet.data}
            card={packs.data}
            labels={labels}
          />
        );
    }
  };

  return (
    <div className="space-y-6 pb-12">
      {header()}
      {/* D-525 + D-655: three peer views of the account's money under one header. */}
      <SegmentedControl
        label="Billing view"
        value={view}
        onValueChange={selectView}
        options={BILLING_VIEWS.map((item) => ({ value: item.value, label: item.label }))}
      />
      <div key={view} className="settings-enter">
        {view_()}
      </div>
      <AddCreditDrawer
        session={session}
        open={addingCredit}
        onClose={() => setAddingCredit(false)}
        billingRefused={billingRefused}
      />
    </div>
  );
}
