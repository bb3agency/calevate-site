"use client";

import { FileText } from "lucide-react";

import { NoticeBox } from "@/components/ui";

/**
 * The wallet header an INVOICED account gets, where a prepaid one gets a balance.
 *
 * No balance, no ₹0.00, no Add credit: there is no wallet behind this account, so a figure
 * would be a number about nothing and the button would earn a `topup_not_available`
 * refusal after the click instead of before it. Where the money IS answered by the views
 * right under this header (Usage, Transactions, Statements), which is why the panel no
 * longer carries its own links to them.
 *
 * Prepaid is what an account gets unless an operator says otherwise, so the second
 * paragraph says so: a client reading it who expected a wallet is reading OUR setting.
 */
export function InvoicedAccount() {
  return (
    <div className="space-y-2">
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
      <p className="max-w-prose text-meta text-ink-muted">
        Most accounts pay as they go: they keep a credit balance on this screen and top it
        up whenever they like. Yours is set up the other way, on an invoice. If that is not
        what you agreed with us, ask your account manager to check it — it is a setting on
        our side and nothing on your account is lost either way.
      </p>
    </div>
  );
}
