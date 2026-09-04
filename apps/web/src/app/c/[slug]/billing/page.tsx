"use client";

import { useSearchParams } from "next/navigation";
import { use, useState } from "react";

import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useCreditPacks } from "@/lib/api/billing";
import { useMe } from "@/lib/api/hooks";
import { currentISTMonth } from "@/lib/api/invoice";
import { useClientRealm } from "@/lib/api/session";
import { runwaySentence, useWallet, useWalletLedger, walletState } from "@/lib/api/wallet";
import { useTabs } from "@/components/interior/tabs";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { CreditsTab } from "./CreditsTab";
import { InvoicedAccount } from "./InvoicedAccount";
import { OverviewTab } from "./OverviewTab";
import { TransactionsTab } from "./TransactionsTab";
import { UsageTab } from "./UsageTab";
import { BILLING_TABS, DEFAULT_BILLING_TAB, isBillingTab, type BillingTab } from "./tabs";

/**
 * CREDITS & BILLING — one hub, four tabs (D-525).
 *
 * ## The defect this closes
 *
 * The client realm had FOUR sidebar entries about money: Calling credit, Usage, Spend and
 * Invoice. Each answered a real question and none of them answered "what am I paying?" —
 * to get an answer a client had to already know which of the four held it. The same
 * confusion is what made the assistant look foolish when a client asked it for "the
 * billing page": there were four candidates and no hub, and it picked wrong.
 *
 * So: **Overview / Credits / Transactions / Usage**, one screen, and the four old routes
 * redirect into the tab that answers them (`/credits` → Credits, `/usage` and `/spend` →
 * Usage, `/invoice` → Transactions). No link anywhere — an email, a bookmark, a blocker's
 * copy — breaks.
 *
 * ## The tab is in the URL, and that is not decoration
 *
 * `?tab=` is read on mount and written on every change (`history.replaceState`, not a
 * router push: switching a tab is not a navigation, and pushing would make Back walk the
 * tab strip instead of leaving the screen). It buys three things — a deep link the
 * redirects can aim at, a tab that survives a refresh, and a copy-pasteable link to the
 * exact panel a support conversation is about. An unrecognised value lands on Overview
 * rather than a blank panel.
 *
 * The tab STRIP itself is `components/interior/tabs.ts::useTabs`, which is this repo's
 * one implementation of the WAI-ARIA tabs pattern: `role="tablist"` / `role="tab"` /
 * `role="tabpanel"`, roving `tabIndex` so the strip is ONE tab stop, Left/Right/Home/End
 * moving selection, and `aria-controls`/`aria-labelledby` tying the two halves together.
 * Writing a second one here would have been the drift this repo's "one way per problem"
 * rule exists to stop.
 *
 * ## PERMISSION: the screen reads on `wallet:read`, and the OWNER's figures refuse per tab
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
export default function BillingPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
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

  /* The list rate the explainer quotes. `/v1/billing/topups/packs` is `billing:read`, so
     for a staff session this stays `undefined` and the explainer drops the one sentence
     that needs a rupee figure rather than inventing one. */
  const packs = useCreditPacks(session);

  /* One month for the two panels that can look backwards — the per-agent breakdown and the
     statement. Held HERE rather than in each tab so a client who picks July on one does not
     find the other still showing August; they are two views of the same month and having
     them disagree is how a support call starts. */
  const [month, setMonth] = useState(currentISTMonth);

  const requested = searchParams.get("tab");
  const [tab, setTab] = useState<BillingTab>(
    isBillingTab(requested) ? requested : DEFAULT_BILLING_TAB,
  );
  const selectTab = (next: string) => {
    if (!isBillingTab(next)) return;
    setTab(next);
    /* `replaceState`, not `router.push`: switching a tab is not a navigation, and a push
       would make the Back button walk the tab strip instead of leaving the screen. Guarded
       because `window` is absent while this renders on the server. */
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", next);
      window.history.replaceState(window.history.state, "", url);
    }
  };

  const tabs = useTabs({
    items: BILLING_TABS.map((item) => ({ value: item.value, label: item.label })),
    value: tab,
    onValueChange: selectTab,
    /* AUTOMATIC activation — selection follows the arrow keys. It is the WAI-ARIA
       recommendation when every panel is already loaded or cheap to load, which is the
       case here: all four read queries that TanStack has cached or will fire once. */
    activation: "automatic",
  });

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
        value: tab,
        help: "One of: overview, credits, transactions, usage.",
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
      { key: "tab", label: "The open tab", value: tab },
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
              key: "ai_assist_inr",
              label: "Of that, extra AI help (INR)",
              value: wallet.data.drawdown.ai_assist_inr,
            },
          ]
        : []),
      {
        key: "gst",
        label: "Is GST added, and can a tax invoice be issued?",
        value:
          "no GST is added — the price shown is the price paid — and what we can issue is " +
          "a bill of supply, not a tax invoice, so no input tax credit is available",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        const wanted = typeof item.value === "string" ? item.value : String(item.value);
        if (item.field_id === "billing-tab" && isBillingTab(wanted)) selectTab(wanted);
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

  /* §52, all three arms. A skeleton while it is in flight, the server's own refusal when
     it failed, and — for the case neither arm catches — a refusal rather than a blank:
     TanStack PARKS a query while the browser is offline (`fetchStatus: "paused"`), which
     reports `isLoading === false` AND `error === null` with `data === undefined`. A
     `return null` there is a screen that says a wallet has nothing in it. */
  if (wallet.isLoading) return <Skeleton rows={6} label="Loading your billing" />;
  if (wallet.error || !wallet.data) {
    return <ProblemNotice error={wallet.error} onRetry={() => void wallet.refetch()} />;
  }

  const notPrepaid = walletState(wallet.data) === "not-prepaid";
  const listRate = packs.data?.list_rate_inr_per_min ?? null;

  const panel = () => {
    switch (tab) {
      case "credits":
        /* AN INVOICED ACCOUNT HAS NO WALLET, so there is nothing to buy — and the Credits
           tab says that rather than offering a form whose click earns a
           `topup_not_available` refusal. The tab is not HIDDEN: a client told "top up your
           credit" by somebody who assumed wrong has to be able to find out why they
           cannot, and a tab that is missing explains nothing. */
        return notPrepaid ? (
          <InvoicedAccount onGoTo={selectTab} />
        ) : (
          <CreditsTab session={session} listRate={listRate} billingRefused={billingRefused} />
        );
      case "transactions":
        return (
          <TransactionsTab
            session={session}
            month={month}
            onMonthChange={setMonth}
            billingRefused={billingRefused}
          />
        );
      case "usage":
        return (
          <UsageTab
            session={session}
            slug={slug}
            month={month}
            onMonthChange={setMonth}
            refused={billingRefused}
          />
        );
      default:
        return notPrepaid ? (
          <InvoicedAccount onGoTo={selectTab} />
        ) : (
          <OverviewTab
            session={session}
            wallet={wallet.data}
            funded={funded}
            listRate={listRate}
          />
        );
    }
  };

  return (
    <div className="space-y-5 pb-12">
      {/* The strip is ONE tab stop (roving `tabIndex`); Left/Right/Home/End move the
          selection. `aria-label` names it, because a page can hold more than one tablist
          and "Tabs" tells a screen-reader user nothing. */}
      <div
        {...tabs.tabListProps}
        aria-label="Billing sections"
        className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-px [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {BILLING_TABS.map((item, index) => {
          const selected = item.value === tab;
          return (
            <button
              key={item.value}
              {...tabs.getTabProps({ value: item.value, label: item.label }, index)}
              className={`shrink-0 rounded-t-md border-b-2 px-3 py-2 text-sm outline-none transition-colors touch:min-h-11 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${
                selected
                  ? "border-brand-strong font-semibold text-ink"
                  : "border-transparent text-ink-muted hover:text-ink"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      <div {...tabs.getPanelProps(tab)} className="outline-none">
        {panel()}
      </div>
    </div>
  );
}
