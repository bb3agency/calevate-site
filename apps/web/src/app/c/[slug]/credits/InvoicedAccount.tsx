"use client";

import Link from "next/link";
import { Activity, Coins, FileText, ReceiptIndianRupee } from "lucide-react";
import type { ReactNode } from "react";

import { Card, NoticeBox } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";

/**
 * The screen an INVOICED account gets, where a prepaid one gets a wallet.
 *
 * ## Why this is a screen and not a sentence
 *
 * It used to be four lines in a card: "this account is invoiced, not prepaid … there is
 * nothing to top up here and your calls never stop for want of credit." Every word of
 * that was true and the whole thing was a dead end — it named what this screen is NOT,
 * told the reader that the two links they might want were somewhere else, and left them
 * on a page with nothing on it. That was survivable while almost every account was
 * invoiced and this was a screen hardly anyone opened. It is not survivable now that it
 * is the rare branch: an invoiced client who lands here has usually been sent by somebody
 * who assumed they had a balance, and the screen has to answer "so where IS my money,
 * then" rather than only "not here".
 *
 * ## What it says, in order
 *
 * 1. **The good news first, and it is genuinely good news**: nothing to top up, and
 *    outgoing calls never stop for want of credit. On a prepaid account an empty wallet
 *    stops campaigns; on this one there is no such gate at all, and that is worth saying
 *    plainly rather than leaving as the absence of a warning.
 * 2. **Where the three money questions are answered instead** — this month's cost, the
 *    per-call detail, the statement. Real links, not prose naming other screens.
 * 3. **The way out, if this is wrong.** Pay-as-you-go is what new accounts get, so a
 *    client reading this because they expected to be topping up is reading a
 *    misconfiguration on our side, not a mistake of theirs. The plan tier is not something
 *    they can change from here — no client-realm route sets it — so the honest next step
 *    is the person who can, named as such.
 *
 * ## What it deliberately does not do
 *
 * No balance, no ₹0.00, no top-up form. There is no wallet behind this account, so a
 * figure would be a number about nothing and the control would earn a `topup_not_available`
 * refusal after the click instead of before it.
 */
export function InvoicedAccount() {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;

  return (
    <div className="space-y-5 pb-12">
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
            href={href(`/c/${slug}/usage`)}
            icon={<Activity className="h-4 w-4" aria-hidden />}
            label="Usage"
            hint="What this month has cost so far, against what your plan includes."
          />
          <MoneyLink
            href={href(`/c/${slug}/spend`)}
            icon={<Coins className="h-4 w-4" aria-hidden />}
            label="Spend"
            hint="Call by call, so you can check a figure you disagree with against the calls behind it."
          />
          <MoneyLink
            href={href(`/c/${slug}/invoice`)}
            icon={<ReceiptIndianRupee className="h-4 w-4" aria-hidden />}
            label="Invoice"
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
 * use for a link out. The hint says what QUESTION the screen answers, because "Usage" and
 * "Spend" and "Invoice" are three words a client would reasonably expect to mean the same
 * thing.
 */
function MoneyLink({
  href,
  icon,
  label,
  hint,
}: {
  href: string;
  icon: ReactNode;
  label: string;
  hint: string;
}) {
  return (
    <li>
      <Link
        href={href}
        className="flex items-start gap-3 rounded-card border border-line bg-app p-3 text-sm hover:border-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand sm:p-4"
      >
        <span className="mt-0.5 shrink-0 text-brand">{icon}</span>
        <span className="min-w-0">
          <span className="block font-medium text-ink underline underline-offset-2">
            {label}
          </span>
          <span className="mt-0.5 block text-ink-muted">{hint}</span>
        </span>
      </Link>
    </li>
  );
}
