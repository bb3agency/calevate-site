"use client";

/**
 * A list row whose actions a phone reaches by swiping (founder, 24 Oct 2026): swipe right
 * reveals the row's primary action (Call back), swipe left reveals the rest (Mark status,
 * Call back later, Send a WhatsApp follow-up — whatever the caller passes). On a pointer
 * that can hover, and for anyone on a keyboard, the same actions sit in the row's ⋯ menu,
 * so nothing is reachable only by a gesture.
 *
 * Adapted from uiarc's `swipe-actions` (MIT, see ./LICENSE), but built the way the
 * platform guide for swipe-to-reveal says (modern-web-guidance `swipe-to-reveal`): a
 * horizontal scroll-snap track, not JavaScript gesture handlers. The browser then owns
 * momentum, snapping, vertical-scroll disambiguation and keyboard scrolling, and a swipe
 * only REVEALS actions — Arc's long-swipe-to-commit is not carried over, because the
 * primary action here places a phone call and must be a deliberate press.
 *
 * A destructive action carries `confirm` and goes through `ConfirmDialog`; every action
 * reports its own result through `status` (from the caller's `useActionFeedback`), and an
 * Undo, where one is safe, is the caller's success toast.
 */

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import clsx from "clsx";

import { ConfirmDialog } from "@/components/confirmDialog";

import type { FeedbackStatus } from "./feedback";
import { RowMenu } from "./menu";
import { useToast } from "./toast";

export type SwipeAction = {
  id: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  tone?: "danger";
  disabled?: boolean;
  /** Why it is disabled: shown in the ⋯ menu, and said when the revealed button is pressed. */
  hint?: string;
  status?: FeedbackStatus;
  /** Ask first: the action cannot be taken back. */
  confirm?: {
    title: string;
    body: ReactNode;
    confirmLabel: string;
    pendingLabel: string;
    error?: unknown;
  };
};

export type SwipeActionsProps = {
  /** The row's name, for "More actions for …" and the action groups. */
  label: string;
  /** Revealed by swiping right. */
  primary?: SwipeAction;
  /** Revealed by swiping left, in order. */
  secondary?: SwipeAction[];
  /** The row itself. */
  children: ReactNode;
  className?: string;
};

const ACTION_BUTTON =
  "flex w-19 shrink-0 flex-col items-center justify-center gap-1 px-3 text-[12px] font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white aria-disabled:opacity-50";

export function SwipeActions({ label, primary, secondary = [], children, className }: SwipeActionsProps) {
  const track = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [askingId, setAskingId] = useState<string | null>(null);
  const toasts = useToast();

  const hasPrimary = primary !== undefined;
  // Rest on the row, not on the leading panel. `scroll-initial-target` does this natively
  // where supported; elsewhere the track starts at 0 with the panel showing, so jump once.
  useLayoutEffect(() => {
    const el = track.current;
    const row = content.current;
    if (el && row && hasPrimary) el.scrollLeft = row.offsetLeft;
  }, [hasPrimary]);

  const close = () => content.current?.scrollIntoView?.({ block: "nearest", inline: "start" });

  const choose = (action: SwipeAction, fromPanel = false) => {
    // A revealed button that cannot act still answers a press: on a phone the ⋯ menu that
    // carries the reason is hidden, so the reason is said here instead.
    if (action.disabled) {
      if (action.hint) toasts.toast({ id: `swipe-${action.id}`, kind: "info", title: `${action.label} is not available`, description: action.hint });
      return;
    }
    close();
    // A dialog the action opens hands focus back to whatever held it when it closes. Left
    // on the revealed button, that focus scrolls the panel open again; on the row, it
    // does not.
    if (fromPanel) content.current?.querySelector<HTMLElement>("a[href], button")?.focus({ preventScroll: true });
    if (action.confirm) setAskingId(action.id);
    else action.onSelect();
  };

  const all = [...(primary ? [primary] : []), ...secondary];
  const pending = all.find((a) => a.status === "pending");
  // Read live, so the dialog shows the action's current state and failure.
  const asking = all.find((a) => a.id === askingId) ?? null;
  // A confirmed action that succeeded closes its dialog; its toast says what happened.
  useEffect(() => {
    if (asking?.status === "success") setAskingId(null);
  }, [asking?.status]);

  return (
    <div className={clsx("relative", className)} aria-busy={pending ? true : undefined}>
      <div
        ref={track}
        className={clsx(
          "grid overflow-hidden",
          primary ? "grid-cols-[max-content_100%_max-content]" : "grid-cols-[100%_max-content]",
          "touch:snap-x touch:snap-mandatory touch:overflow-x-auto touch:overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        )}
      >
        {primary ? (
          <div role="group" aria-label={`${primary.label}: ${label}`} className="col-start-1 row-start-1 hidden snap-start touch:flex">
            <button
              type="button"
              onClick={() => choose(primary, true)}
              aria-disabled={primary.disabled || undefined}
              className={clsx(ACTION_BUTTON, "bg-brand-strong text-white")}
            >
              {primary.icon ? <span aria-hidden>{primary.icon}</span> : null}
              {primary.label}
            </button>
          </div>
        ) : null}

        <div
          ref={content}
          // Tabbing back into the row from a revealed action closes the panel again.
          onFocus={(event) => {
            if (event.target.matches?.(":focus-visible")) close();
          }}
          className={clsx(
            "row-start-1 flex min-w-0 snap-start items-center gap-2 bg-surface [scroll-initial-target:nearest]",
            primary ? "col-start-2" : "col-start-1",
          )}
        >
          <div className="min-w-0 flex-1">{children}</div>
          {all.length > 0 ? (
            <div className="shrink-0 touch:hidden">
              <RowMenu
                label={label}
                items={all.map((action) => ({
                  id: action.id,
                  label: action.label,
                  icon: action.icon,
                  tone: action.tone,
                  disabled: action.disabled || action.status === "pending",
                  hint: action.hint,
                  onSelect: () => choose(action),
                }))}
              />
            </div>
          ) : null}
        </div>

        {secondary.length > 0 ? (
          <div
            role="group"
            aria-label={`More actions for ${label}`}
            className={clsx("row-start-1 hidden snap-end touch:flex", primary ? "col-start-3" : "col-start-2")}
          >
            {secondary.map((action) => (
              <button
                key={action.id}
                type="button"
                onClick={() => choose(action, true)}
                aria-disabled={action.disabled || undefined}
                aria-busy={action.status === "pending" || undefined}
                className={clsx(
                  ACTION_BUTTON,
                  action.tone === "danger" ? "bg-danger text-white" : "bg-surface-muted text-ink",
                )}
              >
                {action.icon ? <span aria-hidden>{action.icon}</span> : null}
                {action.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {asking?.confirm ? (
        <ConfirmDialog
          title={asking.confirm.title}
          confirmLabel={asking.confirm.confirmLabel}
          pendingLabel={asking.confirm.pendingLabel}
          status={asking.status}
          error={asking.confirm.error ?? null}
          onCancel={() => setAskingId(null)}
          onConfirm={() => {
            asking.onSelect();
          }}
        >
          {asking.confirm.body}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
