"use client";

import Link from "next/link";

import { TierComparison, type Tier } from "@/components/arc/tier-comparison";
import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatCount, formatINR, hasNonZeroDigit } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useVoiceTierComparison, type VoiceTierCompare } from "@/lib/api/voiceTiers";

import { formatWhole } from "./lots";

/** "12.5000" → "12.5"; one decimal at most, read rather than parsed. */
function formatMinutes(value: string): string {
  const [whole = "0", fraction = ""] = value.split(".");
  const tenth = fraction.replace(/0+$/, "").slice(0, 1);
  return `${formatWhole(whole)}${tenth ? `.${tenth}` : ""}`;
}

/**
 * The rate a card shows. With open credit it is this account's own next-minute rate (the
 * oldest purchase's, which is what the next call is charged); with none it is the card's
 * range across packs, because no single figure would be true until a pack is chosen.
 */
function toTier(tier: VoiceTierCompare, notOfferedNotice: string | null): Tier {
  const yours = tier.your_inr_per_min;
  const used = hasNonZeroDigit(tier.minutes_this_month);
  return {
    id: tier.tier,
    name: tier.label,
    ratePerMinute: yours ?? tier.from_inr_per_min,
    rateTo: yours === null ? tier.to_inr_per_min : undefined,
    rateNote:
      yours !== null
        ? tier.minutes_left === null
          ? "Your rate now"
          : `Your rate now · your credit covers about ${formatCount(tier.minutes_left)} minutes`
        : "Depends on the pack you buy. Your rate is fixed when you add credit.",
    summary: !tier.offered
      ? (notOfferedNotice ?? "Not open on your account yet.")
      : used
        ? `This month: ${formatMinutes(tier.minutes_this_month)} minutes, ${formatINR(tier.charged_this_month_inr)}`
        : "Not used this month",
    includes: tier.includes,
    bestFor: tier.best_for,
  };
}

/**
 * Clear against Studio: the per-minute rate, what each includes, and which suits this
 * account (D-869). Everything is the server's (`/v1/billing/voice-tiers`); no rupee is
 * typed here. The voice is chosen per agent, on the agent's own screen, so the cards carry
 * no switch button and the guidance says where the choice is made.
 */
export function VoiceTiers({ session, agentsHref }: { session: Session; agentsHref: string }) {
  const comparison = useVoiceTierComparison(session);
  const data = comparison.data;
  if (comparison.error || !data) {
    return (
      <Section title={TITLE}>
        {comparison.error ? (
          <ProblemNotice error={comparison.error} onRetry={() => void comparison.refetch()} />
        ) : (
          <Skeleton rows={4} label="Loading the voice comparison" />
        )}
      </Section>
    );
  }
  return (
        <TierComparison
          title={TITLE}
          tiers={data.tiers.map((tier) => toTier(tier, data.not_offered_notice))}
          strings={{ guidanceTitle: "Which is right for me?" }}
          guidance={
            <>
              <p>
                <span className="font-semibold text-ink">
                  {data.tiers.find((tier) => tier.tier === data.recommended)?.label ?? data.recommended} suits you.
                </span>{" "}
                {data.recommendation_reason}
              </p>
              <p>
                Each agent speaks with one of them, and you can change it on the agent&apos;s own
                screen.{" "}
                <Link href={agentsHref} className="font-medium text-ink underline underline-offset-2 hover:text-brand-strong">
                  Open your agents
                </Link>
              </p>
            </>
          }
        />
  );
}

const TITLE = "Clear or Studio";
