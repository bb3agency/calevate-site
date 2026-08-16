"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * The WAI-ARIA APG modal-dialog focus contract, in one hook, for every modal in the app.
 *
 * It was written inside `components/navDrawer.tsx`, whose header calls itself *"the
 * first"* focus-trap idiom in this repo and says the next one should borrow it. The
 * second modal did not: `AcceptChargeDialog` — the one control in the console that
 * DEBITS A WALLET — moved focus on open and handled Escape, and stopped there. So the
 * first Tab left the `aria-modal="true"` panel and landed on the page behind it, and
 * Escape dropped focus onto `<body>`, leaving a keyboard user with no idea where they
 * were and a screen-reader user reading the page they had just been taken out of.
 *
 * Extracting rather than copying is the point (CLAUDE.md: one way per problem, and
 * migrate rather than accumulate) — `navDrawer` moved onto this in the same change, so
 * there is one implementation and not two that will drift.
 *
 * ## What it does, and in what order
 *
 * 1. **On activation**, remembers what had focus and moves focus INSIDE the panel, never
 *    outside it — focus landing outside the trap means the first Tab escapes it. WHERE
 *    inside is the caller's to say (`initialFocus`) and the two callers legitimately
 *    differ: the drawer is a list of destinations, so the first one is its content and a
 *    keyboard user wants to be on it; the money dialog is a STATEMENT to be read before a
 *    decision, so focus lands on the container, whose `aria-labelledby`/`aria-describedby`
 *    make a screen reader read the amount and "nothing has been charged yet" — landing on
 *    "Not now" would announce a button and nothing about what it declines.
 * 2. **Tab and Shift+Tab cycle** within the panel. The tabbable list is re-queried on
 *    every press: a dialog whose contents change (a `ProblemNotice` with a retry button
 *    appearing after a failed charge) would otherwise cycle against a stale list.
 * 3. **Escape** calls `onEscape`.
 * 4. **On deactivation or unmount**, focus returns to whatever opened it.
 *
 * ## Three details that are easy to get wrong and are load-bearing
 *
 * * **The listener is on `document`, not on the panel.** A React `onKeyDown` fires only
 *   for keys pressed inside its own subtree, so Escape would stop working the moment
 *   focus left the dialog — which is exactly when a person reaches for it. It is also
 *   what keeps the trap able to pull focus BACK when something outside it steals focus.
 * * **`onEscape` is read through a ref.** The key listener must not be re-registered on
 *   every render (callers pass inline arrows), and the focus effect must not re-run and
 *   re-steal focus when a parent re-renders — so the effect depends on `active` alone and
 *   reads the current callback at the moment of the key press.
 * * **Restoring focus checks `isConnected` and `!== body`.** On a route change the whole
 *   shell unmounts and the trigger is detached; focusing a detached node silently moves
 *   focus to `<body>`. And when nothing held focus at open time there is nothing to give
 *   back to — blanking focus is worse than leaving it where it is.
 *
 * No `focus-trap` / `focus-trap-react` dependency: this is ~50 lines against a repo that
 * treats every new package as supply-chain surface (hard rule 9, `incident_report.md`).
 * A native `<dialog showModal>` would give the trap for free and cannot be used by
 * `navDrawer`, whose element must stay a plain in-flow `<aside>` above `lg`.
 *
 * ## Known limit, stated rather than hidden
 *
 * The page BEHIND the modal is not made inert, so a screen reader's virtual cursor can
 * still reach it. `aria-modal="true"` declares the intent and the trap holds for keyboard
 * users; doing better needs the main region to be reachable from each caller, which is a
 * change to both shells' DOM shape.
 */

/** Elements that can hold focus from a Tab press, in DOM order when queried. */
const TABBABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function tabbablesWithin(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(TABBABLE));
}

/**
 * Where focus lands when the trap arms.
 *
 * `container` requires the panel to carry `tabIndex={-1}`; both callers do, because the
 * fallback below needs it too — a panel with no tabbable child has nowhere else to put
 * focus that is still inside the trap.
 */
export type InitialFocus = "first-tabbable" | "container";

export function useFocusTrap(
  panel: RefObject<HTMLElement | null>,
  active: boolean,
  onEscape: () => void,
  initialFocus: InitialFocus = "first-tabbable",
): void {
  const escape = useRef(onEscape);
  escape.current = onEscape;
  const openedFrom = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    openedFrom.current = document.activeElement as HTMLElement | null;
    const target =
      initialFocus === "container" ? panel.current : tabbablesWithin(panel.current)[0];
    (target ?? panel.current)?.focus();
    return () => {
      const trigger = openedFrom.current;
      openedFrom.current = null;
      if (trigger && trigger !== document.body && trigger.isConnected) trigger.focus();
    };
  }, [active, panel, initialFocus]);

  useEffect(() => {
    if (!active) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        escape.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = tabbablesWithin(panel.current);
      const first = items[0];
      const last = items[items.length - 1];
      const activeElement = document.activeElement;
      const inside = panel.current?.contains(activeElement) ?? false;
      if (!first || !last) {
        // Nothing to cycle between; keep focus on the panel rather than letting Tab out.
        event.preventDefault();
        panel.current?.focus();
        return;
      }
      if (event.shiftKey && (activeElement === first || !inside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (activeElement === last || !inside)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [active, panel]);
}
