"use client";

/**
 * Header actions for one record (a call, a lead, a campaign): `ButtonGroup` shows the most
 * important few as buttons and folds the rest into a ⋯ menu, fewer on a phone than on a
 * desktop, so the header never wraps into a second row of buttons. `SplitButton` is one
 * action with its close variants behind a chevron ("Call back" / "Call back later").
 *
 * Adapted from uiarc's `button-group` and `split-button` (MIT, see ./LICENSE), on the kit's
 * `ActionButton` (each action shows its own pending / done / failed state) and `Menu`
 * (Radix dropdown) instead of Arc's own. Arc's joined pill segments are not carried over:
 * the console spaces its buttons apart (D-771), and a segmented look is reserved for a
 * choice between values (`SegmentedControl`).
 */

import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronDown, MoreHorizontal } from "lucide-react";
import clsx from "clsx";

import { SECONDARY_BUTTON } from "@/components/ui";

import { ActionButton, type ActionButtonVariant, type FeedbackStatus } from "./feedback";
import { Menu, type MenuItem } from "./menu";

export type GroupAction = {
  id: string;
  label: string;
  icon?: ReactNode;
  /** Runs the action. Omit when `href` is given. */
  onSelect?: () => void;
  href?: string;
  /** From the caller's `useActionFeedback(...).status`. */
  status?: FeedbackStatus;
  successLabel?: string;
  pendingLabel?: string;
  tone?: "danger";
  disabled?: boolean;
  /** Why it is disabled, shown in the menu. */
  hint?: string;
};

export type ButtonGroupProps = {
  /** Names the group: "Call actions". */
  label: string;
  /** In priority order: the first is the primary action. */
  actions: GroupAction[];
  /** Names the overflow menu: "More actions for this call". */
  moreLabel: string;
  /** Buttons shown before the menu on a phone. */
  phoneVisible?: number;
  /** Buttons shown before the menu from `sm`. */
  desktopVisible?: number;
  /**
   * False when the page's one filled action lives elsewhere (a call's "call back now" in
   * its verdict): every button here is then secondary, so the page keeps one primary.
   */
  primaryFirst?: boolean;
  className?: string;
};

function asMenuItem(action: GroupAction): MenuItem {
  return {
    id: action.id,
    label: action.label,
    icon: action.icon,
    href: action.href,
    onSelect: action.onSelect,
    tone: action.tone,
    disabled: action.disabled || action.status === "pending",
    hint: action.hint,
  };
}

function GroupButton({ action, primary }: { action: GroupAction; primary: boolean }) {
  const variant: ActionButtonVariant = action.tone === "danger" ? "danger" : primary ? "primary" : "secondary";
  if (action.href && !action.disabled) {
    return (
      <Link href={action.href} className={clsx(SECONDARY_BUTTON, "justify-center")}>
        {action.icon ? <span aria-hidden>{action.icon}</span> : null}
        {action.label}
      </Link>
    );
  }
  return (
    <ActionButton
      variant={variant}
      status={action.status}
      pendingLabel={action.pendingLabel}
      successLabel={action.successLabel}
      disabled={action.disabled}
      title={action.disabled ? action.hint : undefined}
      onClick={action.onSelect}
    >
      {action.icon ? <span aria-hidden>{action.icon}</span> : null}
      {action.label}
    </ActionButton>
  );
}

const MORE_TRIGGER =
  "press inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-line bg-surface text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand data-[state=open]:bg-ink/[0.06] touch:h-11 touch:w-11";

export function ButtonGroup({
  label,
  actions,
  moreLabel,
  phoneVisible = 1,
  desktopVisible = 3,
  primaryFirst = true,
  className,
}: ButtonGroupProps) {
  const phoneMenu = actions.slice(phoneVisible);
  const desktopMenu = actions.slice(desktopVisible);
  return (
    <div role="group" aria-label={label} className={clsx("flex items-center gap-2", className)}>
      {actions.slice(0, Math.max(phoneVisible, desktopVisible)).map((action, index) => (
        <div
          key={action.id}
          className={clsx(
            index >= phoneVisible && "hidden sm:flex",
            index >= desktopVisible && "sm:hidden",
          )}
        >
          <GroupButton action={action} primary={primaryFirst && index === 0} />
        </div>
      ))}
      {phoneMenu.length > 0 ? (
        <div className="sm:hidden">
          <Menu
            label={moreLabel}
            items={phoneMenu.map(asMenuItem)}
            trigger={
              <button type="button" aria-label={moreLabel} className={MORE_TRIGGER}>
                <MoreHorizontal aria-hidden className="h-4 w-4" />
              </button>
            }
          />
        </div>
      ) : null}
      {desktopMenu.length > 0 ? (
        <div className="hidden sm:block">
          <Menu
            label={moreLabel}
            items={desktopMenu.map(asMenuItem)}
            trigger={
              <button type="button" aria-label={moreLabel} className={MORE_TRIGGER}>
                <MoreHorizontal aria-hidden className="h-4 w-4" />
              </button>
            }
          />
        </div>
      ) : null}
    </div>
  );
}

export type SplitButtonProps = {
  /** The main action's label. */
  children: ReactNode;
  onClick: () => void;
  status?: FeedbackStatus;
  pendingLabel?: ReactNode;
  successLabel?: ReactNode;
  disabled?: boolean;
  /** The variants behind the chevron. */
  items: MenuItem[];
  /** Names the chevron: "More ways to call back". */
  menuLabel: string;
  variant?: "primary" | "secondary";
};

export function SplitButton({
  children,
  onClick,
  status,
  pendingLabel,
  successLabel,
  disabled,
  items,
  menuLabel,
  variant = "primary",
}: SplitButtonProps) {
  const primary = variant === "primary";
  return (
    <div className="inline-flex items-stretch">
      <ActionButton
        variant={variant}
        status={status}
        pendingLabel={pendingLabel}
        successLabel={successLabel}
        disabled={disabled}
        onClick={onClick}
        className="rounded-r-none"
      >
        {children}
      </ActionButton>
      <Menu
        label={menuLabel}
        items={items}
        trigger={
          <button
            type="button"
            aria-label={menuLabel}
            disabled={disabled}
            className={clsx(
              "press inline-flex w-9 items-center justify-center rounded-r-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 touch:min-h-11 touch:w-11",
              primary
                ? "border-l border-white/25 bg-brand-strong text-white hover:bg-brand-deep"
                : "border border-l-0 border-line bg-surface text-ink hover:bg-black/5",
            )}
          >
            <ChevronDown aria-hidden className="h-4 w-4" />
          </button>
        }
      />
    </div>
  );
}
