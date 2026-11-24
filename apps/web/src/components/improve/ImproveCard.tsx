"use client";

/**
 * The frame every Diagnose card on a campaign's or Inbound line's Improve shares, and the
 * states each draws from the one `…/diagnosis` read: loading, failed, then its own body.
 */

import type { ReactNode } from "react";

import { InfoTip } from "@/components/console/infoTip";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useHolderDiagnosis, type Holder, type HolderDiagnosis } from "@/lib/api/improve";
import { useClientRealm } from "@/lib/api/session";

export type ImproveCardProps = {
  slug: string;
  holder: Holder;
  canWrite: boolean;
  refusal?: string;
};

export function ImproveCard({
  title,
  hint,
  info,
  children,
}: {
  title: string;
  hint: string;
  info?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-card border border-line p-4 sm:p-5" aria-label={title}>
      <h3 className="text-body font-semibold text-ink">{title}</h3>
      <p className="mt-0.5 flex items-center gap-1 text-meta text-ink-muted">
        <span className="block">{hint}</span>
        {info && (
          <InfoTip label={title.toLowerCase()} align="start">
            {info}
          </InfoTip>
        )}
      </p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** The diagnosis for `holder`, or its loading or failed state in the card's place. */
export function WithDiagnosis({
  holder,
  label,
  children,
}: {
  holder: Holder;
  /** What is being read, for the skeleton's accessible name. */
  label: string;
  children: (data: HolderDiagnosis) => ReactNode;
}) {
  const { session } = useClientRealm();
  const diagnosis = useHolderDiagnosis(session, holder);
  if (diagnosis.isLoading) return <Skeleton rows={3} label={label} />;
  if (!diagnosis.data) {
    return <ProblemNotice error={diagnosis.error} onRetry={() => void diagnosis.refetch()} />;
  }
  return <>{children(diagnosis.data)}</>;
}
