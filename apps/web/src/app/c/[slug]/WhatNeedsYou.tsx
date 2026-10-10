"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import type { Dashboard } from "@/lib/api/client";
import type { useAttention } from "@/lib/api/attention";
import { activeTrial, minutesLeftPhrase, walletState, type useWallet } from "@/lib/api/wallet";

import { AttentionBanner } from "./AttentionBanner";

/**
 * WHAT NEEDS YOU TODAY — the first thing on the dashboard (founder, REDESIGN-2): the few
 * things an owner should act on before reading any figure, each one sentence and one
 * action. Built only from reads the dashboard already makes (attention queue, dashboard
 * figures, wallet); nothing here is inferred beyond what those say.
 *
 * - The attention queue keeps `AttentionBanner`'s own sentences and failure arm.
 * - Hot leads: interested and not yet won or lost, from `hot_leads_open`.
 * - Calls that did not connect today: today's row of `daily_7d` (the last day, IST).
 * - Credit: only when the wallet itself says low or stopped, and never during a trial,
 *   when an empty wallet stops nothing (D-536).
 */
export function WhatNeedsYou({
  data,
  attention,
  wallet,
  href,
}: {
  data: Dashboard;
  attention: ReturnType<typeof useAttention>;
  wallet: ReturnType<typeof useWallet>;
  href: (path: string) => string;
}) {
  const rows: { key: string; text: ReactNode; action: ReactNode }[] = [];

  if (data.hot_leads_open > 0) {
    rows.push({
      key: "hot",
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(data.hot_leads_open)}</span>{" "}
          {data.hot_leads_open === 1 ? "hot lead is" : "hot leads are"} waiting for a call back
        </>
      ),
      action: (
        <Link href={href("/leads")} className={TEXT_ACTION}>
          Open leads
        </Link>
      ),
    });
  }

  const today = data.daily_7d.at(-1);
  const missed = today ? today.failed + today.no_answer : 0;
  if (missed > 0) {
    rows.push({
      key: "missed",
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(missed)}</span>{" "}
          {missed === 1 ? "call" : "calls"} did not connect today
        </>
      ),
      action: (
        <Link href={href("/calls?status=failed")} className={TEXT_ACTION}>
          See calls
        </Link>
      ),
    });
  }

  if (wallet.data && activeTrial(wallet.data) === null) {
    const state = walletState(wallet.data);
    if (state === "low" || state === "stopped") {
      const minutes = minutesLeftPhrase(wallet.data);
      rows.push({
        key: "credit",
        text:
          state === "stopped"
            ? "Calls have stopped, outgoing and incoming, until credit is added"
            : `Credit is running low${minutes ? `: ${minutes.charAt(0).toLowerCase()}${minutes.slice(1)}` : ""}`,
        action: (
          <Link href={href("/billing?tab=credits")} className={TEXT_ACTION}>
            Add credit
          </Link>
        ),
      });
    }
  }

  const queueWaiting = attention.data !== undefined && attention.data.total > 0;
  const allClear = rows.length === 0 && attention.data !== undefined && !queueWaiting;

  return (
    <Section title="What needs you today">
      <div className="space-y-3">
        {/* The queue's own banner: its count, its link and its "could not check" arm. */}
        <AttentionBanner attention={attention} href={href("/attention")} />
        {rows.length > 0 ? (
          <ul className="divide-y divide-line border-y border-line">
            {rows.map((row) => (
              <li key={row.key} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 py-3.5">
                <span className="text-body text-ink">{row.text}</span>
                {row.action}
              </li>
            ))}
          </ul>
        ) : null}
        {allClear ? (
          <p className="flex items-center gap-2 text-body text-ink-muted">
            <CheckCircle2 aria-hidden className="h-4 w-4 text-brand-strong" />
            Nothing needs you right now.
          </p>
        ) : null}
      </div>
    </Section>
  );
}
