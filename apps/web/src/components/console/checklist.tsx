"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, Check, ChevronDown, ChevronRight, Clock3, Lock } from "lucide-react";

import { InfoTip } from "./infoTip";
import { TEXT_ACTION } from "./section";
import { StatusPill } from "./statusPill";
import { NOTICE_BAR, type NoticeTone } from "@/components/ui";

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
  // One line of text: centre the marker on the row, because a touch-sized action (44px)
  // makes the row taller than the text and a top-aligned marker then sits above it.
  const oneLine = !(disabled ? item.disabledReason : item.detail);
  return (
    <li
      className={`flex gap-3 py-3 first:pt-0 last:pb-0 ${oneLine ? "items-center" : "items-start"} ${disabled ? "opacity-70" : ""}`}
    >
      <span className={oneLine ? "flex" : "mt-0.5"}>
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

/* ─────────────────────────────────────────────────────────────────────────────────── */

export type ChecklistRowStatus = "done" | "waiting" | "not_started" | "blocked";

const ROW_STATUS: Record<ChecklistRowStatus, { text: string; tone: NoticeTone }> = {
  done: { text: "Done", tone: "ok" },
  waiting: { text: "Waiting", tone: "neutral" },
  not_started: { text: "Not started", tone: "warn" },
  blocked: { text: "Blocked", tone: "stop" },
};

export type ChecklistRow = {
  id: string;
  /** A short noun: "Identity (KYC)", "First campaign". */
  label: ReactNode;
  status: ChecklistRowStatus;
  /** A more exact word for the pill than the default ("Not filed", "In review"). */
  statusText?: string;
  /** The explanation, behind an ⓘ. Never a compliance sentence or a refusal. */
  info?: ReactNode;
  /** ONE action: a link ("Open"), or any control. */
  link?: { href: string; label: string };
  action?: ReactNode;
};

/** The text action a checklist row carries: "Open ›". */
export function RowLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className={TEXT_ACTION}>
      {children}
      <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0" />
    </Link>
  );
}

/**
 * SEVERAL BLOCKERS OR STEPS, one row each: a short label, a status pill, an optional ⓘ
 * and one action. The notice counterpart of `NoticeBox`: a list a person can scan,
 * rather than blockers crammed into a paragraph (founder, 11 Oct 2026).
 *
 * The heading is a real heading (`headingLevel`), the rows a list between hairlines, and
 * each status is said in words inside the pill, so colour is never the only signal.
 * `tone` puts the same left rule a `NoticeBox` has beside the whole block.
 */
export function ChecklistRows({
  heading,
  headingLevel = 3,
  info,
  summary,
  rows,
  tone,
  footer,
  className = "",
}: {
  heading: string;
  headingLevel?: 2 | 3 | 4;
  info?: ReactNode;
  /** One short line under the heading. */
  summary?: ReactNode;
  rows: ChecklistRow[];
  tone?: NoticeTone;
  /** A closing line or a single action for the whole list ("Review & release"). */
  footer?: ReactNode;
  className?: string;
}) {
  const Heading = headingLevel === 2 ? "h2" : headingLevel === 4 ? "h4" : "h3";
  return (
    <section
      aria-label={heading}
      data-notice={tone ?? "checklist"}
      className={`${tone ? `border-l-2 pl-3 ${NOTICE_BAR[tone]}` : ""} ${className}`}
    >
      <div className="flex items-center gap-1">
        <Heading className="text-body font-semibold text-ink">{heading}</Heading>
        {info && <InfoTip label={heading}>{info}</InfoTip>}
      </div>
      {summary && <p className="mt-0.5 text-body text-ink-muted">{summary}</p>}
      <ul className="mt-2 divide-y divide-line border-y border-line">
        {rows.map((row) => {
          const status = ROW_STATUS[row.status];
          const action = row.link ? <RowLink href={row.link.href}>{row.link.label}</RowLink> : row.action;
          return (
            <li key={row.id} className="flex items-center gap-3 py-2">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                <span className="min-w-0 text-body font-medium text-ink">{row.label}</span>
                <StatusPill tone={status.tone}>{row.statusText ?? status.text}</StatusPill>
                {row.info && (
                  <InfoTip label={typeof row.label === "string" ? row.label : heading}>{row.info}</InfoTip>
                )}
              </div>
              {action && <span className="shrink-0">{action}</span>}
            </li>
          );
        })}
      </ul>
      {footer && <div className="mt-2 flex flex-wrap items-center gap-3 text-body text-ink-muted">{footer}</div>}
    </section>
  );
}
