"use client";

import { useRef, useSyncExternalStore, type ReactNode } from "react";

import { useFocusTrap } from "@/lib/focusTrap";

/**
 * The mobile navigation drawer, for BOTH shells — `app/admin/layout.tsx` and
 * `app/c/[slug]/layout.tsx`.
 *
 * The two shells had a byte-for-byte copy of this markup each, and both carried the same
 * defect: below `lg` the panel is pushed off-screen with `-translate-x-full` and nothing
 * else, so a CLOSED drawer kept ~18 links and buttons in the tab order. A keyboard user
 * tabbing off the header's menu button walked an invisible menu; a screen reader read it
 * out as ordinary page content. Transform is a paint, not a state — the browser has no
 * reason to believe the panel is gone.
 *
 * ## What makes it gone: `inert`, and `inert` alone
 *
 * `inert` on the container removes the whole subtree from the tab order, blocks pointer
 * and click events, and removes it from the ACCESSIBILITY TREE — which is why no
 * `aria-hidden` sits beside it here (web.dev/articles/inert; MDN "inert" global
 * attribute, Baseline since 2023 in all evergreen engines). The two are not additive:
 * `aria-hidden="true"` hides from assistive tech while leaving focus intact, so the
 * `aria-hidden` + `pointer-events: none` stack this replaces was the workaround for not
 * having `inert`, and `aria-hidden` on a subtree that is still focusable is itself an axe
 * failure (`aria-hidden-focus`). One mechanism, not two.
 *
 * React 19 (this app pins react 19.2.4) treats `inert` as a real BOOLEAN prop, so
 * `inert={false}` renders no attribute at all (facebook/react#24730, shipped in the React
 * 19 upgrade guide's breaking-change list). Under React 18 the same expression rendered
 * `inert="false"` — a present attribute, therefore inert — which is exactly the trap that
 * makes an "assert the attribute is there" test pass on a broken drawer. That is why the
 * test beside this file counts TABBABLE ELEMENTS instead of reading an attribute.
 *
 * ## Why a media query and not just `!isOpen`
 *
 * Above `lg` this same element is the permanent desktop sidebar (`lg:static
 * lg:translate-x-0`), and `isOpen` is false there in normal use. Gating `inert` on
 * `!isOpen` alone would make the desktop sidebar unfocusable AND unclickable — a far
 * worse bug than the one being fixed. `inert` is not a CSS property, so a media query in
 * the stylesheet cannot express this (the CSS `interactivity: inert` proposal that would
 * — w3c/csswg-drafts#10711 — is not shipped); it has to be evaluated in JS.
 *
 * `useSyncExternalStore` over `matchMedia` is React 18+'s prescribed way to read an
 * external, subscribable value without tearing. The server snapshot is `false` — "not an
 * overlay" — so server-rendered and pre-hydration markup is byte-identical to what
 * shipped before, and a desktop sidebar is never briefly inert (unclickable) while JS
 * loads. The cost of that choice is that the closed mobile drawer is tabbable for the few
 * ms before hydration; the opposite default would break the pointer on every desktop load
 * for the same window, which is the trade the other way round and the worse one.
 *
 * ## Focus, when it OPENS
 *
 * `useFocusTrap` (src/lib/focusTrap.ts) — focus moves into the panel on open, Tab and
 * Shift+Tab cycle inside it, Escape closes, and focus returns to whatever opened it (the
 * header's "Open navigation" button): the WAI-ARIA APG modal-dialog pattern.
 *
 * That code WAS here, and this header said it was "the first" such idiom in the repo and
 * that the next modal should borrow it. The second one — `AcceptChargeDialog`, the
 * control that debits a wallet — did not, and shipped with no Tab cycling and no restore.
 * So it moved out to a hook and both call it. The trade-offs it makes (no `focus-trap`
 * dependency; no native `<dialog showModal>`, because THIS element has to remain a plain
 * in-flow `<aside>` above `lg`) and its known limit about the page behind the panel are
 * written out there.
 */

/** Below Tailwind's `lg` (1024px) — the width at which the sidebar becomes an overlay. */
const OVERLAY_QUERY = "(max-width: 1023.98px)";

function subscribeToOverlayWidth(onChange: () => void): () => void {
  // jsdom implements no `matchMedia`, and this hook runs in every layout test.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(OVERLAY_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function isOverlayWidth(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(OVERLAY_QUERY).matches;
}

/** See the comment above: never inert before we know the width. */
function isOverlayWidthOnServer(): boolean {
  return false;
}

/** True when this panel is currently an overlay drawer rather than the desktop sidebar. */
function useOverlayWidth(): boolean {
  return useSyncExternalStore(subscribeToOverlayWidth, isOverlayWidth, isOverlayWidthOnServer);
}

export function NavDrawer({
  isOpen,
  onClose,
  label,
  className = "",
  children,
}: {
  isOpen: boolean;
  onClose: () => void;
  /** Names the panel for assistive tech while it is a dialog, e.g. "Admin navigation". */
  label: string;
  /** Shell-specific sizing (the collapsed/expanded width), not structure. */
  className?: string;
  children: ReactNode;
}) {
  const panel = useRef<HTMLElement | null>(null);
  const isOverlay = useOverlayWidth();
  // The ONE condition every rule below keys on: an overlay panel that is showing. Above
  // `lg` this is false at all times, so the desktop sidebar keeps plain sidebar behaviour
  // — no dialog role, no trap, and never inert.
  const isModal = isOverlay && isOpen;

  // Only while it IS a modal. Above `lg` the same element is the permanent desktop
  // sidebar, and trapping focus in a sidebar nobody opened would be a far worse bug than
  // the one this file was written for.
  useFocusTrap(panel, isModal, onClose);

  return (
    <>
      {isOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-ink/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}
      <aside
        ref={panel}
        // Removed from the tab order and the accessibility tree the moment it is an
        // off-screen overlay. The whole point of this file.
        inert={isOverlay && !isOpen}
        role={isModal ? "dialog" : undefined}
        aria-modal={isModal ? true : undefined}
        aria-label={isModal ? label : undefined}
        tabIndex={isModal ? -1 : undefined}
        className={`fixed inset-y-0 left-0 z-50 flex shrink-0 flex-col border-r border-line bg-surface transition-transform duration-300 lg:static lg:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        } ${className}`}
      >
        {children}
      </aside>
    </>
  );
}
