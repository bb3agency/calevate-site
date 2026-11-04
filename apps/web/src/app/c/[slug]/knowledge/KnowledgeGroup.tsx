"use client";

import type { ReactNode } from "react";

import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import { formatCount } from "@/components/ui";

/** One kind of thing the agents were given: a heading with its count, then its rows. */
export function Group({
  title,
  count,
  hidden,
  info,
  status,
  children,
}: {
  title: string;
  count: number;
  /** A search left nothing in this group; the page says so once, not per group. */
  hidden: boolean;
  info?: ReactNode;
  status?: ReactNode;
  children: ReactNode;
}) {
  if (hidden) return null;
  return (
    <Section
      title={
        <>
          {title}
          {count > 0 ? (
            <span className="ml-2 text-meta font-normal tabular-nums text-ink-faint">
              {formatCount(count)}
            </span>
          ) : null}
        </>
      }
      headingLevel={3}
      info={info}
      action={status}
    >
      {children}
    </Section>
  );
}

/** A list the search emptied: says so, and offers the way back. */
export function NoMatch({ message, onClear }: { message: string; onClear: () => void }) {
  return (
    <EmptyState
      variant="filtered"
      align="start"
      className="py-4"
      message={message}
      onClear={onClear}
      clearLabel="Clear the search"
    />
  );
}
