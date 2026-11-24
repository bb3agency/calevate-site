"use client";

/**
 * The shell every Improve card sits in: a title, one line saying what it does, an optional
 * "more" tip, then the card's own state. The state line under a card's action is always the
 * same three kinds (`StateLine`): what it is waiting for, what it found, what it did.
 */

import type { ReactNode } from "react";

import { problemToast } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";

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
