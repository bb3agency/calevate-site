"use client";

/**
 * The top-bar bell: a count on the button and, on press, the waiting items in a popover,
 * each with what happened, when (IST) and a link to where it is fixed.
 *
 * Adapted from uiarc's `notification-center` (MIT, see ./LICENSE), made CONTROLLED: Arc read
 * its list into local state once, so a poll never reached it; here every item comes from the
 * caller's query on each render. Arc's All/Unread views, rolling digits and blur swaps are
 * not carried over — the queue is a list of things to fix, and reading one does not fix it.
 *
 * The count is the caller's (the server's total, never `items.length`) and three states are
 * kept apart, because a calm bell that has lost the API is the defect §52 exists to stop:
 * `ready` with a count, `loading` with no badge, `error` with a warn dot and the words in
 * the label.
 */

import Link from "next/link";
import type { ReactNode } from "react";
import { Bell, RotateCcw, X } from "lucide-react";
import clsx from "clsx";

import { formatIST } from "@/components/ui";

import { Popover, PopoverClose } from "./popover";

export type NotificationItem = {
  id: string;
  title: string;
  /** One line: what happened, or what to do about it. */
  detail?: string;
  /** A short figure on the right ("2 waiting"). */
  meta?: string;
  /** Where the fix lives. The whole row becomes the link. */
  href?: string | null;
  /** When it happened, ISO; shown in IST. */
  at?: string;
  tone?: "default" | "warn" | "danger";
};

export type NotificationCenterProps = {
  /** The bell's accessible name, including the count or the failure in words. */
  label: string;
  /** A hover title for the bell (the failure sentence, typically). */
  title?: string;
  /** The server's count. Undefined while unknown; 0 or undefined draws no badge. */
  count?: number;
  state: "ready" | "loading" | "error";
  /**
   * Some of the sources behind the list could not be read: the bell takes the warn dot (and
   * the caller says so in `label`) while the list still shows what did answer.
   */
  partial?: boolean;
  items: NotificationItem[];
  heading: string;
  /** The full screen behind the bell. */
  seeAll?: { href: string; label: string };
  emptyText?: string;
  loadingText?: string;
  errorText?: string;
  onRetry?: () => void;
  retryLabel?: string;
  /** Per-row dismiss, once the server can record one. Report its result with useActionFeedback. */
  onDismiss?: (id: string) => void;
  dismissLabel?: (item: NotificationItem) => string;
  /** Shown under the list when the server holds more than `items` (a page of a larger set). */
  shortfall?: ReactNode;
  closeLabel?: string;
};

const TONE_DOT: Record<NonNullable<NotificationItem["tone"]>, string> = {
  default: "bg-ink-faint",
  warn: "bg-warn",
  danger: "bg-danger",
};

export function NotificationCenter({
  label,
  title,
  count,
  state,
  partial = false,
  items,
  heading,
  seeAll,
  emptyText = "Nothing needs you right now.",
  loadingText = "Checking…",
  errorText = "We couldn't check for new items.",
  onRetry,
  retryLabel = "Try again",
  onDismiss,
  dismissLabel = (item) => `Dismiss ${item.title}`,
  shortfall,
  closeLabel = "Close",
}: NotificationCenterProps) {
  return (
    <Popover
      label={heading}
      align="end"
      className="w-[min(24rem,calc(100vw-1rem))]"
      trigger={
        <button
          type="button"
          aria-label={label}
          title={title}
          className="press relative flex h-9 w-9 items-center justify-center rounded-md border border-line bg-surface text-ink-muted hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 data-[state=open]:bg-ink/[0.04] data-[state=open]:text-ink touch:h-11 touch:w-11"
        >
          <Bell aria-hidden className="h-4 w-4" />
          {state === "error" || partial ? (
            // A plain warn dot, not a "?": the label and title carry the meaning in words,
            // and a lone glyph reads as a riddle.
            <span
              aria-hidden
              data-testid="attention-unchecked"
              className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-warn"
            />
          ) : (
            state === "ready" &&
            count !== undefined &&
            count > 0 && (
              <span
                aria-hidden
                className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full border-2 border-surface bg-danger px-1 text-[9px] font-bold text-white"
              >
                {count > 99 ? "99+" : count}
              </span>
            )
          )}
        </button>
      }
    >
      {/* The shared panel pads by 0.75rem; this list runs edge to edge. */}
      <div className="-m-3">
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
          <p className="text-meta font-semibold text-ink">{heading}</p>
          <PopoverClose
            aria-label={closeLabel}
            className="-mr-1 grid h-8 w-8 place-items-center rounded-md text-ink-faint hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <X aria-hidden className="h-4 w-4" />
          </PopoverClose>
        </div>

        {state === "error" ? (
          <div className="space-y-2 px-3 py-3">
            <p className="text-body text-ink">{errorText}</p>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="press inline-flex min-h-8 items-center gap-1.5 rounded-md border border-line px-2.5 text-meta font-semibold text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              >
                <RotateCcw aria-hidden className="h-3.5 w-3.5" />
                {retryLabel}
              </button>
            ) : null}
          </div>
        ) : state === "loading" ? (
          <p className="px-3 py-3 text-body text-ink-muted">{loadingText}</p>
        ) : items.length === 0 ? (
          <p className="px-3 py-4 text-body text-ink-muted">{emptyText}</p>
        ) : (
          <ul className="max-h-[min(24rem,60dvh)] divide-y divide-line overflow-y-auto overscroll-contain">
            {items.map((item) => (
              <li key={item.id} className="group relative flex items-start gap-2">
                <Row item={item} />
                {onDismiss ? (
                  <button
                    type="button"
                    onClick={() => onDismiss(item.id)}
                    aria-label={dismissLabel(item)}
                    className="mr-1 mt-2 grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-faint hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
                  >
                    <X aria-hidden className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {state === "ready" && shortfall ? (
          <p className="border-t border-line px-3 py-2 text-meta text-ink-muted">{shortfall}</p>
        ) : null}
        {seeAll ? (
          <div className="border-t border-line px-3 py-2">
            <PopoverClose asChild>
              <Link
                href={seeAll.href}
                className="inline-flex min-h-8 items-center rounded-sm text-meta font-semibold text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              >
                {seeAll.label}
              </Link>
            </PopoverClose>
          </div>
        ) : null}
      </div>
    </Popover>
  );
}

function Row({ item }: { item: NotificationItem }) {
  const body = (
    <>
      <span aria-hidden className={clsx("mt-1.5 h-2 w-2 shrink-0 rounded-full", TONE_DOT[item.tone ?? "default"])} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-3">
          <span className="min-w-0 break-words text-body font-medium text-ink">{item.title}</span>
          {item.meta ? (
            <span className="shrink-0 text-meta tabular-nums text-ink-muted">{item.meta}</span>
          ) : null}
        </span>
        {item.detail ? (
          <span className="mt-0.5 block break-words text-meta text-ink-muted">{item.detail}</span>
        ) : null}
        {item.at ? <span className="mt-0.5 block text-[12px] text-ink-faint">{formatIST(item.at)}</span> : null}
      </span>
    </>
  );
  const rowClass = "flex min-w-0 flex-1 items-start gap-2.5 px-3 py-2.5";
  // A row link closes the popover: the bar stays mounted across navigation, so an open
  // panel would otherwise sit over the screen it just opened.
  return item.href ? (
    <PopoverClose asChild>
      <Link
        href={item.href}
        className={clsx(
          rowClass,
          "hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand",
        )}
      >
        {body}
      </Link>
    </PopoverClose>
  ) : (
    <div className={rowClass}>{body}</div>
  );
}
