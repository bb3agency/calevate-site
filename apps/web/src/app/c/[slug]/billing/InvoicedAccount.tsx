"use client";

import { Activity, FileText, ReceiptIndianRupee } from "lucide-react";
import type { ReactNode } from "react";

import { Card, NoticeBox } from "@/components/ui";

import type { BillingTab } from "./tabs";

/**
 * The OVERVIEW an INVOICED account gets, where a prepaid one gets a wallet.
 *
 * ## Why this is a panel and not a sentence
 *
 * It used to be four lines in a card: "this account is invoiced, not prepaid … there is
 * nothing to top up here and your calls never stop for want of credit." Every word of
 * that was true and the whole thing was a dead end — it named what the screen is NOT and
 * left the reader with nothing on it. That was survivable while almost every account was
 * invoiced and hardly anyone opened the wallet. It is not survivable now that it is the
 * RARE branch: an invoiced client who lands here has usually been sent by somebody who
 * assumed they had a balance, and it has to answer "so where IS my money, then" rather
 * than only "not here".
 *
 * ## What changed with the hub (D-525)
 *
 * The three answers used to be three OTHER SCREENS, and this panel's own comment said the
 * quiet part: "Usage" and "Spend" and "Invoice" are three words a client would reasonably
 * expect to mean the same thing. They are TABS now, on the screen this panel is already
 * on, so these are buttons that move the tab rather than links that navigate away — one
 * fewer page load, and no way to end up somewhere with no route back.
 *
 * ## What it deliberately does not do
 *
 * No balance, no ₹0.00, no top-up form. There is no wallet behind this account, so a
 * figure would be a number about nothing and the control would earn a
 * `topup_not_available` refusal after the click instead of before it.
 */
export function InvoicedAccount({ onGoTo }: { onGoTo: (tab: BillingTab) => void }) {
  return (
    <div className="space-y-5">
      <NoticeBox
        tone="ok"
        icon={<FileText className="h-4 w-4" aria-hidden />}
        title="This account is billed on a monthly invoice"
      >
        <p className="mt-1">
          Your calling is billed against the plan we agreed with you rather than from a
          credit balance, so there is nothing to top up and no balance to keep an eye on.
          Your outgoing calls never stop for want of credit, and people calling you always
          get through.
        </p>
      </NoticeBox>

      <Card title="Where to find what you have been charged">
        <ul className="space-y-3">
          <MoneyLink
            onClick={() => onGoTo("usage")}
            icon={<Activity className="h-4 w-4" aria-hidden />}
            label="Usage"
            hint="What this month has cost so far against what your plan includes, and — call by call — which agent spent it."
          />
          <MoneyLink
            onClick={() => onGoTo("transactions")}
            icon={<ReceiptIndianRupee className="h-4 w-4" aria-hidden />}
            label="Transactions"
            hint="Your statement for the month, ready to print or save."
          />
        </ul>
      </Card>

      <Card title="Expecting to add credit here?">
        <p className="text-sm text-ink-muted">
          Most accounts pay as they go: they keep a credit balance on this screen and top it
          up whenever they like. Yours is set up the other way, on an invoice. If that is not
          what you agreed with us, ask your account manager to check it — it is a setting on
          our side and nothing on your account is lost either way.
        </p>
      </Card>
    </div>
  );
}

/**
 * One destination, sized so a thumb can hit it — the same row shape the settings screens
 * use for a link out. The hint says what QUESTION the tab answers, because the words on
 * the tabs are short by design and a client should not have to open all four to find out
 * which one holds their answer.
 */
function MoneyLink({
  onClick,
  icon,
  label,
  hint,
}: {
  onClick: () => void;
  icon: ReactNode;
  label: string;
  hint: string;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-start gap-3 rounded-card border border-line bg-app p-3 text-left text-sm hover:border-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand sm:p-4"
      >
        <span className="mt-0.5 shrink-0 text-brand">{icon}</span>
        <span className="min-w-0">
          <span className="block font-medium text-ink underline underline-offset-2">
            {label}
          </span>
          <span className="mt-0.5 block text-ink-muted">{hint}</span>
        </span>
      </button>
    </li>
  );
}
