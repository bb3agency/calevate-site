"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import type { Dashboard } from "@/lib/api/client";
import type { useUsage } from "@/lib/api/hooks";
import type { Agent } from "@/lib/api/agents";
import { activeTrial, minutesLeftPhrase, type useWallet } from "@/lib/api/wallet";
import { isAnsweringNow, isDeleted } from "@/lib/agentState";
import { weekOnWeek } from "@/lib/weekOnWeek";

/**
 * THE WEEK IN A FEW SENTENCES, under "What needs you today".
 *
 * Prose rather than another strip of tiles: the figures row below already answers "how
 * many", and what an owner wants from a recap is the reading of those numbers in order —
 * how busy, whether anybody was missed, how much was handled, whether the agents are on,
 * how long the credit lasts. Sentences carry that order; a grid of equal tiles does not
 * (visual-hierarchy: tell the story in sequence; critique-information-density: one
 * rendering per fact).
 *
 * Every clause comes from a read the dashboard already makes and is LEFT OUT while its read
 * has not answered, so the paragraph never states a number it does not have.
 */
export function WeekRecap({
  data,
  usage,
  agents,
  wallet,
  href,
}: {
  data: Dashboard;
  usage: ReturnType<typeof useUsage>;
  agents: Agent[] | undefined;
  wallet: ReturnType<typeof useWallet>;
  href: (path: string) => string;
}) {
  const sentences: { key: string; text: ReactNode }[] = [];
  const figure = (n: number | string) => <span className="font-semibold tabular-nums text-ink">{n}</span>;

  const trend = weekOnWeek(data.calls_7d, data.calls_prev_7d);
  sentences.push({
    key: "calls",
    text:
      data.calls_7d === 0 ? (
        <>No calls in the last 7 days.</>
      ) : (
        <>
          {agents && agents.filter((agent) => !isDeleted(agent)).length === 1 ? "Your agent" : "Your agents"} handled{" "}
          {figure(formatCount(data.calls_7d))} {data.calls_7d === 1 ? "call" : "calls"} in
          the last 7 days{trend ? `, ${trend}` : ""}.
        </>
      ),
  });

  // The chart's own seven IST days, so this agrees with the bars beside it.
  const missed = data.daily_7d.reduce((sum, day) => sum + day.failed + day.no_answer, 0);
  const anyCalls = data.daily_7d.some((day) => day.total > 0);
  if (anyCalls) {
    sentences.push({
      key: "missed",
      text:
        missed === 0 ? (
          <>Every one of them connected.</>
        ) : (
          <>
            {figure(formatCount(missed))} {missed === 1 ? "call" : "calls"} did not connect.
          </>
        ),
    });
  }

  if (usage.data) {
    const minutes = Math.round(Number(usage.data.minutes_used));
    if (Number.isFinite(minutes) && minutes > 0) {
      sentences.push({
        key: "minutes",
        text: (
          <>
            This month your calls ran to {figure(formatCount(minutes))} {minutes === 1 ? "minute" : "minutes"}.
          </>
        ),
      });
    }
  }

  if (agents) {
    const current = agents.filter((agent) => !isDeleted(agent));
    const on = current.filter(isAnsweringNow).length;
    if (current.length > 0) {
      sentences.push({
        key: "agents",
        text:
          on === current.length ? (
            <>
              {current.length === 1 ? "Your agent is" : `All ${formatCount(current.length)} agents are`} switched on.
            </>
          ) : (
            <>
              {figure(formatCount(on))} of {formatCount(current.length)} agents {on === 1 ? "is" : "are"} switched on.
            </>
          ),
      });
    }
  }

  if (wallet.data && wallet.data.prepaid && activeTrial(wallet.data) === null) {
    const left = minutesLeftPhrase(wallet.data);
    if (left) {
      sentences.push({ key: "credit", text: <>{left.replace(" left", " of calls left")} on your credit.</> });
    }
  }

  return (
    <Section title="This week">
      <p className="max-w-prose text-[17px] leading-7 text-ink-muted [text-wrap:pretty]">
        {sentences.map((sentence, i) => (
          <span key={sentence.key}>
            {i > 0 ? " " : null}
            {sentence.text}
          </span>
        ))}
      </p>
      {/* Quick ways in, after the reading rather than above it: they are where an owner
          goes next, not part of the week. */}
      <div className="mt-3">
        <nav aria-label="Shortcuts" className="flex flex-wrap gap-x-5 gap-y-1">
          <Link href={href("/agents/new")} className={TEXT_ACTION}>
            New agent
          </Link>
          <Link href={href("/campaigns")} className={TEXT_ACTION}>
            Campaigns
          </Link>
          <Link href={href("/billing?tab=credits")} className={TEXT_ACTION}>
            Add credit
          </Link>
        </nav>
      </div>
    </Section>
  );
}
