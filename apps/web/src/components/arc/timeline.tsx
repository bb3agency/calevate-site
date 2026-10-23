"use client";

/**
 * A vertical history: what happened to a lead, a call, a campaign, newest first.
 *
 * Adapted from uiarc's `timeline` (MIT, see ./LICENSE) as an ordered list of items, each
 * a marker, a title, an optional detail, a meta line (when, who) and an optional body for
 * anything richer (a call's key moments). The connecting rail is drawn by CSS between
 * markers, so it needs no measuring and survives wrapped Telugu titles. Arc's staggered
 * reveal is not carried over: a history is read, not watched.
 */

import type { ComponentType, ReactNode, SVGProps } from "react";
import clsx from "clsx";

export function Timeline({
  children,
  label,
  className,
}: {
  children: ReactNode;
  /** Names the list when the heading above it does not: "Lead history". */
  label?: string;
  className?: string;
}) {
  return (
    <ol aria-label={label} className={clsx("relative", className)}>
      {children}
    </ol>
  );
}

export type TimelineItemProps = {
  title: ReactNode;
  detail?: ReactNode;
  /** When and who: "24 Oct, 10:42 am · Priya". */
  meta?: ReactNode;
  /** The marker's icon (lucide). Without one the marker is a dot. */
  icon?: ComponentType<SVGProps<SVGSVGElement>>;
  /** Classes for the marker's medallion: tone it by event kind ("bg-brand-soft text-brand-strong"). */
  markerClassName?: string;
  children?: ReactNode;
  className?: string;
};

export function TimelineItem({
  title,
  detail,
  meta,
  icon: Icon,
  markerClassName = "bg-surface-muted text-ink-muted",
  children,
  className,
}: TimelineItemProps) {
  return (
    <li
      className={clsx(
        // The rail: a hairline from under this marker to the next, hidden on the last item.
        "relative flex gap-3 px-3 py-3 before:absolute before:bottom-0 before:left-[1.625rem] before:top-10 before:w-px before:bg-line last:before:hidden",
        className,
      )}
    >
      <span aria-hidden className={clsx("relative mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", markerClassName)}>
        {Icon ? <Icon className="h-3.5 w-3.5" /> : <span className="h-2 w-2 rounded-full bg-current" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink [overflow-wrap:anywhere]">{title}</p>
        {detail ? <p className="mt-0.5 text-xs text-ink-muted [overflow-wrap:anywhere]">{detail}</p> : null}
        {children}
        {meta ? <p className="mt-1 text-xs text-ink-faint">{meta}</p> : null}
      </div>
    </li>
  );
}
