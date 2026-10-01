import type { ReactNode } from "react";

import { InfoTip } from "./infoTip";

/**
 * A compact titled panel for console screens: a `<section>` with an `h2`, an optional ⓘ
 * beside the title for the explanation that used to be a paragraph, and an optional
 * action on the right. Same outline semantics as `Card` (UX-DOCTRINE §2: the panel title
 * is the h2) with a tighter header, for side columns and dense screens where `Card`'s
 * 17px title and divider read as a document rather than a tool.
 */
export function Panel({
  title,
  info,
  action,
  children,
  className = "",
  bodyClassName = "px-4 pb-4",
}: {
  title: string;
  /** Help prose, moved behind an ⓘ. Never a compliance sentence or an error. */
  info?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`rounded-card border border-line bg-surface shadow-card ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 pb-2 pt-3.5">
        <div className="flex min-w-0 items-center gap-1">
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          {info && <InfoTip label={title}>{info}</InfoTip>}
        </div>
        {action}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
