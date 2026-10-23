"use client";

/**
 * Clear against Studio, the two voice rungs a client chooses between (founder, 24 Oct 2026:
 * "₹ per minute, what each includes, which is right for me"). Adapted from uiarc's
 * `plan-comparison` (MIT, see ./LICENSE), reshaped: there are no monthly or annual plans,
 * so there is no period switch and no "save N%".
 *
 * Every figure and word comes from props. A rate is a decimal STRING from the server
 * (hard rule 7) printed through `formatRupeeRate`, never a constant here and never a
 * number, so the comparison cannot drift from what the wallet is debited. Client-facing
 * text names no provider (D-679): pass what each rung does for the caller, not whose
 * technology it uses.
 *
 * Cards stack on a phone and sit side by side from `md`. The current rung is marked in
 * words as well as by its border.
 */

import type { ReactNode } from "react";
import { Check } from "lucide-react";
import clsx from "clsx";

import { formatRupeeRate } from "@/components/ui";

import { ActionButton, type FeedbackStatus } from "./feedback";

export type Tier = {
  id: string;
  name: string;
  /** Decimal string from the server, e.g. "4.50". */
  ratePerMinute: string;
  /** One line under the name: what it sounds like to a caller. */
  summary?: string;
  includes: string[];
  /** "Best for …": who should pick it. */
  bestFor: string;
  /** The choose button's label: "Use Studio". */
  cta?: string;
};

export type TierComparisonStrings = {
  perMinute: string;
  current: string;
  includes: string;
  bestFor: string;
  guidanceTitle: string;
  switched: string;
};

const DEFAULT_STRINGS: TierComparisonStrings = {
  perMinute: "per minute",
  current: "Your agents use this",
  includes: "What you get",
  bestFor: "Best for",
  guidanceTitle: "Which is right for me?",
  switched: "Switched",
};

export function TierComparison({
  tiers,
  currentId,
  onChoose,
  chooseStatus,
  choosingId,
  guidance,
  title,
  strings: overrides,
  className,
}: {
  tiers: Tier[];
  /** The rung in use, marked as current; it offers no choose button. */
  currentId?: string;
  /** With it, each other rung gets a button that runs the change. */
  onChoose?: (id: string) => void;
  /** The change's state (`useActionFeedback(...).status`), shown on `choosingId`'s button. */
  chooseStatus?: FeedbackStatus;
  choosingId?: string;
  /** "Which is right for me?" — a few plain sentences or a short list. */
  guidance?: ReactNode;
  title?: string;
  strings?: Partial<TierComparisonStrings>;
  className?: string;
}) {
  const strings = { ...DEFAULT_STRINGS, ...overrides };
  return (
    <section aria-label={title ?? strings.guidanceTitle} className={clsx("space-y-4", className)}>
      {title ? <h2 className="text-heading text-ink">{title}</h2> : null}
      <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {tiers.map((tier) => {
          const current = tier.id === currentId;
          return (
            <li
              key={tier.id}
              aria-current={current || undefined}
              className={clsx(
                "flex flex-col gap-4 rounded-card border bg-surface p-5",
                current ? "border-brand ring-1 ring-brand" : "border-line",
              )}
            >
              <div className="space-y-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-heading text-ink">{tier.name}</h3>
                  {current ? (
                    <span className="rounded-full bg-brand-soft px-2 py-0.5 text-meta font-medium text-brand-strong">
                      {strings.current}
                    </span>
                  ) : null}
                </div>
                {tier.summary ? <p className="text-body text-ink-muted">{tier.summary}</p> : null}
              </div>
              <p className="flex items-baseline gap-1.5">
                <span className="text-figure tabular-nums text-ink">{formatRupeeRate(tier.ratePerMinute)}</span>
                <span className="text-meta text-ink-muted">{strings.perMinute}</span>
              </p>
              <div className="space-y-2">
                <h4 className="text-meta font-semibold text-ink-muted">{strings.includes}</h4>
                <ul className="space-y-1.5">
                  {tier.includes.map((line) => (
                    <li key={line} className="flex items-start gap-2 text-body text-ink">
                      <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong" />
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
              <p className="text-body text-ink-muted">
                <span className="font-medium text-ink">{strings.bestFor}: </span>
                {tier.bestFor}
              </p>
              {onChoose && !current ? (
                <div className="mt-auto">
                  <ActionButton
                    variant="secondary"
                    status={choosingId === tier.id ? chooseStatus : "idle"}
                    successLabel={strings.switched}
                    onClick={() => onChoose(tier.id)}
                    className="w-full"
                  >
                    {tier.cta ?? `Use ${tier.name}`}
                  </ActionButton>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {guidance ? (
        <div className="rounded-card border border-line bg-surface-muted p-4">
          <h3 className="text-body font-semibold text-ink">{strings.guidanceTitle}</h3>
          <div className="mt-1 space-y-2 text-body text-ink-muted">{guidance}</div>
        </div>
      ) : null}
    </section>
  );
}
