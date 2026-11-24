"use client";

/**
 * The shell every Improve card sits in, on a campaign's and an Inbound line's Improve: a
 * title, one line saying what it does, an optional "more" tip, then the card's own state.
 * The state line under a card's action is always the same three kinds (`StateLine`): what it
 * is waiting for, what it found, what it did. The Diagnose cards draw their state from the
 * one `…/diagnosis` read (`WithDiagnosis`): loading, failed, then their own body.
 */

import type { ReactNode } from "react";

import { problemToast } from "@/components/arc/feedback";
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

/** A failed move, said where it was pressed. */
export function MoveError({ error, fallback }: { error: unknown; fallback: string }) {
  if (error == null) return null;
  return (
    <p role="alert" className="mt-2 text-meta text-danger">
      {problemToast(error, fallback).description ?? fallback}
    </p>
  );
}

/** 0.4567 → "46%". */
export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
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
