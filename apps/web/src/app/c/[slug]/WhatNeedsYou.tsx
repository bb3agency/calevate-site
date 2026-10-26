"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { useEnterClass } from "@/components/live/arrivals";
import { formatCount } from "@/components/ui";
import type { Dashboard } from "@/lib/api/client";
import type { useAttention } from "@/lib/api/attention";
import type { useKnowledgeGaps } from "@/lib/api/knowledgeGaps";
import { QUESTION_PARAM, QUESTIONS_TAB } from "@/lib/api/teachQuestions";
import { activeTrial, minutesLeftPhrase, walletState, type useWallet } from "@/lib/api/wallet";

import { AttentionBanner } from "./AttentionBanner";

/**
 * WHAT NEEDS YOU TODAY — the first thing on the dashboard (founder, REDESIGN-2): the few
 * things an owner should act on before reading any figure, each one sentence and one
 * action. Built only from reads the dashboard already makes (attention queue, dashboard
 * figures, wallet, open knowledge gaps); nothing here is inferred beyond what those say.
 *
 * - The attention queue keeps `AttentionBanner`'s own sentences and failure arm.
 * - Hot leads: interested and not yet won or lost, from `hot_leads_open`.
 * - Calls that did not connect today: today's row of `daily_7d` (the last day, IST).
 * - Questions the agents could not answer on real calls: the server's open-gap count and
 *   the way to teach them. The gaps themselves are listed on Training and Knowledge.
 * - Credit: only when the wallet itself says low or stopped, and never during a trial,
 *   when an empty wallet stops nothing (D-536).
 */
export function WhatNeedsYou({
  data,
  attention,
  wallet,
  gaps,
  href,
}: {
  data: Dashboard;
  attention: ReturnType<typeof useAttention>;
  wallet: ReturnType<typeof useWallet>;
  gaps: ReturnType<typeof useKnowledgeGaps>;
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
  if (today && missed > 0) {
    // The calls list filters on one status, so link to the one that holds every missed call,
    // and to the unfiltered list when they are split between failed and no answer.
    const missedHref =
      today.no_answer === 0 ? "/calls?status=failed"
      : today.failed === 0 ? "/calls?status=no_answer"
      : "/calls";
    rows.push({
      key: "missed",
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(missed)}</span>{" "}
          {missed === 1 ? "call" : "calls"} did not connect today
        </>
      ),
      action: (
        <Link href={href(missedHref)} className={TEXT_ACTION}>
          See missed calls
        </Link>
      ),
    });
  }

  const unanswered = gaps.data?.open_count ?? 0;
  if (unanswered > 0) {
    // One agent's gaps open on its Training tab, which leads with its Questions to answer
    // (D-826, D-893); several agents' open the same list, account-wide, on Knowledge. One
    // topic opens on that question, never on a blank page.
    const complete = gaps.data?.items.length === unanswered;
    const agentIds = new Set(gaps.data?.items.map((gap) => gap.agent_id));
    const topics = new Set(gaps.data?.items.map((gap) => gap.topic_key));
    const [only] = agentIds;
    const [topic] = topics;
    const focus =
      complete && topic !== undefined && topics.size === 1
        ? `${QUESTION_PARAM}=${encodeURIComponent(topic)}`
        : null;
    const teachHref =
      only !== undefined && agentIds.size === 1 && complete
        ? `/agents/${only}?section=training${focus ? `&${focus}` : ""}`
        : `/knowledge?${focus ?? QUESTIONS_TAB}`;
    rows.push({
      key: "gaps",
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(unanswered)}</span>{" "}
          {unanswered === 1 ? "question" : "questions"} your agents could not answer
        </>
      ),
      action: (
        <Link href={href(teachHref)} className={TEXT_ACTION}>
          {unanswered === 1 ? "Teach the answer" : "Teach the answers"}
        </Link>
      ),
    });
  } else if (gaps.error) {
    // A failed read is not an all-clear (§52): say so, with the retry.
    rows.push({
      key: "gaps",
      text: "We could not check for questions your agents could not answer",
      action: (
        <button type="button" onClick={() => void gaps.refetch()} className={TEXT_ACTION}>
          Try again
        </button>
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

  // A row that appears while the dashboard is open (a lead turned hot, credit ran low)
  // enters softly (D-774); the rows present on load do not.
  const enter = useEnterClass(rows.map((row) => row.key));
  const queueWaiting = attention.data !== undefined && attention.data.total > 0;
  const allClear = rows.length === 0 && attention.data !== undefined && !queueWaiting && gaps.data !== undefined;

  return (
    <Section title="What needs you today">
      <div className="space-y-3">
        {/* The queue's own banner: its count, its link and its "could not check" arm. */}
        <AttentionBanner attention={attention} href={href("/attention")} />
        {rows.length > 0 ? (
          <ul className="divide-y divide-line border-y border-line">
            {rows.map((row) => (
              <li
                key={row.key}
                className={`flex flex-wrap items-center justify-between gap-x-6 gap-y-1 py-3.5 ${enter(row.key)}`}
              >
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
