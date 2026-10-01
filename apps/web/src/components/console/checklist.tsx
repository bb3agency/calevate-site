"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, Check, ChevronDown, Clock3, Lock } from "lucide-react";

export type ChecklistState = "done" | "todo" | "waiting" | "blocked";

export type ChecklistItem = {
  id: string;
  label: ReactNode;
  state: ChecklistState;
  /** One short line: what is left, or who it is waiting on. */
  detail?: ReactNode;
  /** The usual action: a link that goes and does it ("Add your hours →"). */
  link?: { href: string; label: string };
  /** Any other action — a quiet button. Ignored when `link` is set. */
  action?: ReactNode;
  /**
   * Why this cannot be done yet, in one line. The row is shown dimmed with this reason and
   * offers no action, rather than a link that would be refused after the click.
   */
  disabledReason?: string;
};

const STATE_TEXT: Record<ChecklistState, string> = {
  done: "Done",
  todo: "To do",
  waiting: "Waiting",
  blocked: "Blocked",
};

function Marker({ state }: { state: ChecklistState }) {
  const base = "flex h-5 w-5 shrink-0 items-center justify-center rounded-full";
  if (state === "done") {
    return (
      <span aria-hidden className={`${base} bg-brand-strong text-white`}>
        <Check className="h-3 w-3" strokeWidth={3} />
      </span>
    );
  }
  if (state === "waiting") {
    return (
      <span aria-hidden className={`${base} bg-ink/[0.06] text-ink-muted`}>
        <Clock3 className="h-3 w-3" />
      </span>
    );
  }
  if (state === "blocked") {
    return (
      <span aria-hidden className={`${base} bg-danger-soft text-danger`}>
        <Lock className="h-3 w-3" />
      </span>
    );
  }
  return <span aria-hidden className={`${base} border-[1.5px] border-ink/25`} />;
}

function Progress({ label, done, total }: { label: string; done: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);
  return (
    <div
      role="progressbar"
      aria-label={`${label}: ${done} of ${total} done`}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
      className="h-1.5 overflow-hidden rounded-full bg-ink/[0.07]"
    >
      <div
        className="h-full origin-left rounded-full bg-brand transition-transform duration-(--duration-slow) ease-out motion-reduce:transition-none"
        style={{ transform: `scaleX(${pct / 100})` }}
      />
    </div>
  );
}

function Row({ item }: { item: ChecklistItem }) {
  const disabled = item.disabledReason !== undefined;
  const action =
    !disabled && item.link ? (
      <Link
        href={item.link.href}
        className="inline-flex max-w-full items-center gap-1 rounded-sm text-[13px] font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        {item.link.label}
        <ArrowRight aria-hidden className="h-3.5 w-3.5 shrink-0" />
      </Link>
    ) : !disabled && item.action ? (
      item.action
    ) : null;
  return (
    <li className={`flex items-start gap-3 py-3 first:pt-0 last:pb-0 ${disabled ? "opacity-70" : ""}`}>
      <span className="mt-0.5">
        <Marker state={item.state} />
      </span>
      {/* The text and the action WRAP rather than share a line at any cost: the text asks
          for at least 14rem, and when that and the action do not both fit, the action
          drops under the text instead of squeezing it to a word per line. */}
      <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
        <div className="min-w-0 grow basis-56">
          <p className={`text-[14px] font-medium ${item.state === "done" ? "text-ink-muted" : "text-ink"}`}>
            <span className="sr-only">{STATE_TEXT[item.state]}: </span>
            {item.label}
          </p>
          {(disabled || item.detail) && (
            <div className="mt-0.5 text-[13px] text-ink-muted">{disabled ? item.disabledReason : item.detail}</div>
          )}
        </div>
        {action && <div className="max-w-full shrink-0">{action}</div>}
      </div>
    </li>
  );
}

/**
 * WHAT IS LEFT TO DO, as a list rather than paragraphs: "2 of 4 done", a bar, and one row
 * per item with its state and the action that moves it.
 *
 * - Every state is said in text as well as drawn (WCAG 1.4.1): the marker is decorative
 *   and each row carries a visually hidden "Done" / "To do" / "Waiting" / "Blocked".
 * - The count is computed from the items passed. Pass only items whose state the server
 *   actually answered: an item we could not read is not "to do" (§52).
 * - When everything is done it says "All done" and, if `collapsible`, folds away.
 * - `collapsible` makes the header a native disclosure (`<details>`, UX-DOCTRINE §3) whose
 *   closed state still says "2 of 4 done" — for a phone, where the list would push the
 *   screen's job below the fold. `defaultOpen` decides the first state.
 */
export function Checklist({
  items,
  label,
  headingLevel = 3,
  collapsible = false,
  defaultOpen = true,
  className = "",
}: {
  items: ChecklistItem[];
  /** Names and heads the list: "Before your first call". */
  label: string;
  /** 2 when the checklist is a top-level block on the screen, 3 inside a titled panel. */
  headingLevel?: 2 | 3;
  collapsible?: boolean;
  defaultOpen?: boolean;
  className?: string;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const done = items.filter((item) => item.state === "done").length;
  const total = items.length;
  const allDone = total > 0 && done === total;
  const count = (
    <span className={`flex items-center gap-1.5 text-[13px] tabular-nums ${allDone ? "text-brand-strong" : "text-ink-muted"}`}>
      {allDone && <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={3} />}
      {allDone ? "All done" : `${done} of ${total} done`}
    </span>
  );
  const list = (
    <ol className="divide-y divide-line">
      {items.map((item) => (
        <Row key={item.id} item={item} />
      ))}
    </ol>
  );

  if (collapsible) {
    return (
      <details open={defaultOpen && !allDone} className={`group ${className}`}>
        <summary className="flex cursor-pointer list-none flex-col gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 [&::-webkit-details-marker]:hidden">
          <span className="flex items-center justify-between gap-3">
            <Heading className="text-[15px] font-semibold text-ink">{label}</Heading>
            <span className="flex items-center gap-2">
              {count}
              <ChevronDown
                aria-hidden
                className="h-4 w-4 text-ink-faint transition-transform duration-(--duration-fast) ease-out group-open:rotate-180 motion-reduce:transition-none"
              />
            </span>
          </span>
          <Progress label={label} done={done} total={total} />
        </summary>
        <div className="pt-4">{list}</div>
      </details>
    );
  }

  return (
    <section aria-label={label} className={className}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <Heading className="text-[15px] font-semibold text-ink">{label}</Heading>
        {count}
      </div>
      <div className="mb-4">
        <Progress label={label} done={done} total={total} />
      </div>
      {list}
    </section>
  );
}
