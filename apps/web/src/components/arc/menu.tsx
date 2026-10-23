"use client";

/**
 * THE action menu, on `@radix-ui/react-dropdown-menu`: the APG menu-button pattern (arrow
 * keys that skip disabled items and wrap, Home/End, type-ahead, Escape back to the
 * trigger, Tab closes) with collision-aware placement, portalled on the `z-popover` layer.
 *
 * It replaces the hand-rolled `console/rowMenu.tsx`, whose keyboard model was right but
 * whose panel sat on `z-dropdown`, under any drawer or dialog it was opened from. It is
 * non-modal (`modal={false}`): a modal menu would hide the rest of the page from assistive
 * tech, toasts included, and fight the focus trap of a dialog it opens inside.
 *
 * - `Menu` takes any trigger element (a split button's chevron, a header "More").
 * - `RowMenu` is the ⋯ button on one row of a list, named for the row.
 */

import Link from "next/link";
import { useId, useRef, useState, type ReactElement, type ReactNode } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal } from "lucide-react";
import clsx from "clsx";

import { FLOATING_PANEL } from "./popover";

export type MenuItem = {
  id: string;
  label: string;
  /** Runs on choose. Omit when `href` is given. */
  onSelect?: () => void;
  /** Navigates instead. In-realm callers pass the result of `href()` from the realm. */
  href?: string;
  /** A destructive action: red text. Still confirm it where it is irreversible. */
  tone?: "danger";
  disabled?: boolean;
  /**
   * Why it is disabled, or a short qualifier, shown on the right. It DESCRIBES the item
   * rather than naming it, so a screen reader hears "Release" and then why.
   */
  hint?: string;
  /** The item's accessible name, when the visible label leans on what is around it. */
  ariaLabel?: string;
  icon?: ReactNode;
  /** Draws a separator above this item, to group what follows. */
  separated?: boolean;
};

/** Kept for the callers that named the old module's type. */
export type RowMenuItem = MenuItem;

const ITEM =
  "flex min-h-9 w-full cursor-default select-none items-center gap-2.5 rounded-[7px] px-2.5 text-left text-[13px] outline-none data-[highlighted]:bg-ink/[0.06] data-[disabled]:text-ink-faint touch:min-h-11";

export function Menu({
  trigger,
  items,
  label,
  align = "end",
  side = "bottom",
}: {
  /** A single focusable element; it becomes the menu button. */
  trigger: ReactElement;
  items: MenuItem[];
  /** The menu's accessible name: "Actions for Reception". */
  label: string;
  align?: "start" | "center" | "end";
  side?: "top" | "bottom";
}) {
  const [open, setOpen] = useState(false);
  // Radix opens on pointerdown and on Enter/Space/ArrowDown, never on a bare `click`. A
  // click with no pointer press before it is what a screen reader's virtual cursor and
  // voice control send, so that click toggles the menu here; a real pointer's click is
  // ignored, since its pointerdown already did.
  const pressed = useRef(false);
  return (
    <DropdownMenu.Root modal={false} open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger
        asChild
        onPointerDown={() => {
          pressed.current = true;
        }}
        onClick={() => {
          if (!pressed.current) setOpen((was) => !was);
          pressed.current = false;
        }}
      >
        {trigger}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          aria-label={label}
          // Radix labels the menu by its trigger; `label` is the more specific name.
          aria-labelledby={undefined}
          align={align}
          side={side}
          sideOffset={4}
          collisionPadding={8}
          loop
          className={clsx(
            FLOATING_PANEL,
            "max-h-(--radix-dropdown-menu-content-available-height) w-max min-w-48 max-w-[calc(100vw-1rem)] overflow-y-auto p-1",
          )}
        >
          {items.map((item) => (
            <MenuRow key={item.id} item={item} />
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function MenuRow({ item }: { item: MenuItem }) {
  const uid = useId();
  const hintId = item.hint ? `${uid}-hint` : undefined;
  const body = (
    <>
      {item.icon && (
        <span aria-hidden className="shrink-0 text-ink-faint">
          {item.icon}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.hint && (
        <span id={hintId} className="shrink-0 text-[12px] text-ink-faint">
          {item.hint}
        </span>
      )}
    </>
  );
  const common = {
    disabled: item.disabled,
    "aria-label": item.ariaLabel ?? (item.hint ? item.label : undefined),
    "aria-describedby": hintId,
    className: clsx(ITEM, !item.disabled && item.tone === "danger" ? "text-danger" : "text-ink"),
  };
  return (
    <>
      {item.separated && <DropdownMenu.Separator className="my-1 h-px bg-line" />}
      {item.href && !item.disabled ? (
        <DropdownMenu.Item asChild {...common} onSelect={item.onSelect}>
          <Link href={item.href}>{body}</Link>
        </DropdownMenu.Item>
      ) : (
        <DropdownMenu.Item {...common} onSelect={item.onSelect}>
          {body}
        </DropdownMenu.Item>
      )}
    </>
  );
}

/**
 * THE ROW'S "MORE" MENU — the secondary actions on one row of a list (archive, rename,
 * open the record), behind a ⋯ button so the row itself stays one target (UX-DOCTRINE §4).
 *
 * `label` names the row: the button reads "More actions for Reception", because a table
 * of buttons all called "More" cannot be told apart. Items that would be refused are
 * shown disabled with their reason as the hint rather than hidden. On a phone the same
 * actions can also sit behind a swipe (`SwipeActions`); this menu stays as their
 * keyboard and desktop route.
 */
export function RowMenu({
  label,
  items,
  align = "end",
  className = "",
}: {
  /** The row's name: "Reception" → "More actions for Reception". */
  label: string;
  items: MenuItem[];
  align?: "start" | "end";
  className?: string;
}) {
  return (
    <Menu
      label={`Actions for ${label}`}
      items={items}
      align={align}
      trigger={
        <button
          type="button"
          aria-label={`More actions for ${label}`}
          className={clsx(
            "press relative z-raised inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.06] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand data-[state=open]:bg-ink/[0.06] data-[state=open]:text-ink touch:h-11 touch:w-11",
            className,
          )}
        >
          <MoreHorizontal aria-hidden className="h-4 w-4" />
        </button>
      }
    />
  );
}
