"use client";

import { useCallback, useState, type ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen, X } from "lucide-react";

import { BrandIcon } from "@/components/brand";

/**
 * The desktop sidebar collapse — its state, its geometry, and its ANIMATION — for BOTH
 * shells (`app/admin/layout.tsx` and `app/c/[slug]/layout.tsx`).
 *
 * The two shells had the collapse written out twice, byte for byte, and it was
 * instantaneous in both: `className={isCollapsed ? "w-[255px] lg:w-[72px]" : "w-[255px]"}`
 * and nothing else. The founder asked for it to open and close smoothly. This file is
 * that, written once — `NavDrawer` owns the panel ELEMENT and its mobile behaviour, this
 * owns what the panel does when a desktop reader collapses it.
 *
 * ## The trap: a transition on `width` alone makes it WORSE
 *
 * Every label in both shells was conditionally UNMOUNTED (`{!isCollapsed && <span>…}`).
 * Add a width transition to that and the labels vanish in one frame and THEN the panel
 * slides — a pop followed by a slide, which reads as a rendering fault rather than as an
 * animation. So the labels stop being unmounted: `SidebarLabel` keeps them in the DOM
 * always, lets the flex layout squeeze them to zero as the panel narrows, and fades them
 * while it happens. Width, clip and fade are one gesture because they are one transition
 * driven by one property change.
 *
 * That also FIXES an accessibility defect rather than only a visual one. Unmounting took
 * every nav label, every group heading and the identity block out of the accessibility
 * tree when the rail was collapsed — a screen-reader user who collapsed the sidebar lost
 * the names of all 21 destinations. The admin shell's brand text already knew this and
 * used `sr-only` instead, with a comment saying why (`app/admin/layout.tsx`). Same
 * principle, one step further: opacity-0 and clipped-to-zero content stays in the
 * accessibility tree, so the labels are readable by a screen reader in both states.
 *
 * ## Why `width` and not the grid-template-columns trick
 *
 * `grid-template-columns: 1fr -> 0fr` exists to animate to a CONTENT-DERIVED size, which
 * `width` cannot do. Both of this panel's sizes are FIXED numbers, so plain `width` is the
 * correct tool and the grid trick would only add a wrapper element and an indirection.
 * (It IS used, once, where the size genuinely is content-derived — see
 * `SidebarCollapsibleBlock` below, which is the admin shell's per-entry refusal
 * sentence.)
 *
 * ## What was taken from the sidebar-performance literature, and what was left
 *
 * TAKEN: keep the work per frame small and bounded, and never animate a property on a
 * subtree that does not need it. The icons here do NOT move at all (see the geometry
 * note), the nav rows do not change padding, and only two properties animate anywhere in
 * the panel — the panel's own `width` and the labels' `opacity`.
 *
 * LEFT: "never animate width, animate `transform` instead" (the standard advice, and the
 * reason it is standard is real — width is a layout property and costs a layout pass per
 * frame). It does not apply here, and saying why is the point: this sidebar is a PUSH
 * layout — it is a flex sibling of `<main>`, so the main column must reflow as the panel
 * changes size. A `transform` on the panel would move the panel without moving anything
 * else, which is a different design (an overlay rail floating over the content), not a
 * cheaper version of this one. The layout pass is the feature. What is avoided instead is
 * layout work that buys nothing: no padding, margin, gap or font-size animates anywhere
 * in this file.
 *
 * Sources read for the timing below (September 2026): the round-up at
 * https://www.equal.design/blog/5-rules-for-motion-in-ui-transitions and
 * https://www.appypie.com/blog/mobile-app-animation-guide — UI transitions stay under
 * 300ms, 200ms is the baseline for a control like this, and ease-IN is wrong for a
 * user-initiated change because it delays the exact moment the person is looking. The
 * two links supplied in the brief (joshuawootonn.com, gitbook.com/blog/new-sidebar) are
 * EGRESS-BLOCKED from this container and were NOT read, so nothing here is attributed to
 * them.
 *
 * ## Duration and easing, chosen rather than guessed
 *
 * - **Width: 200ms, `ease-out`.** The panel travels 183px (255 -> 72). At 200ms that is
 *   ~915px/s, which reads as a deliberate movement rather than a jump; below ~100ms the
 *   eye registers a jump with no motion at all, and above ~300ms a control this large
 *   starts to feel like it is waiting on something. `ease-out` (Tailwind's
 *   `cubic-bezier(0,0,0.2,1)`, not the weaker CSS keyword of the same name) starts at
 *   full speed and settles, so the panel is visibly moving in the first frame after the
 *   click.
 * - **Labels: 100ms out with no delay, 150ms in after a 100ms delay.** Asymmetric on
 *   purpose. Collapsing, the text must be gone before the rail is narrow enough to clip
 *   it mid-word, so it leaves first. Expanding, text fading in while the panel is still
 *   moving looks like two things happening; waiting for the width to be most of the way
 *   there makes it one gesture that finishes with the words arriving.
 *
 * ## `prefers-reduced-motion` is a hard gate, not a softening
 *
 * Every transition here is behind Tailwind's `motion-safe:` variant, which compiles to
 * `@media (prefers-reduced-motion: no-preference)`. A reader who asked for less motion
 * gets `transition-property: none` — the collapse is instantaneous and the final state is
 * identical. This is done in CSS rather than by reading `matchMedia` in JS so there is no
 * state to hydrate, nothing to get wrong on the first paint, and the preference is honoured
 * even if the answer changes while the console is open.
 *
 * ## The geometry: why 72px, and why nothing moves sideways
 *
 * The collapsed rail is 72px and the numbers below are DERIVED from it rather than
 * eyeballed — each leading glyph is placed so that its centre sits at 36px, the rail's
 * centre line, which means it is exactly centred when collapsed AND does not move by a
 * single pixel during the transition. Only the labels' width changes.
 *
 *   nav padding 12 + row padding 16 + half a 16px icon    = 36   (nav rows)
 *   brand row padding 18 + half a 36px mark               = 36   (brand)
 *   footer padding 8 + identity row padding 10 + half 36  = 36   (avatar / shield)
 *   footer padding 8 + button padding 20 + half a 16 icon = 36   (sign out)
 *   rail 72 - toggle row padding 22 - half a 28px button  = 36   (collapse toggle)
 *
 * A consequence worth having: expanded, every label in the panel starts at x=56 and the
 * two 36px glyphs' labels start at x=66, so the sidebar is properly aligned in the state
 * it spends most of its life in too.
 *
 * The 12px flex gap between a zero-width label and its icon still occupies space when the
 * rail is narrow, which is why every row here is `overflow-hidden`: the leftover gap and
 * any trailing badge are clipped away rather than pushing the icon off centre.
 */

/**
 * The panel's own classes — width in both states, plus the width transition.
 *
 * `w-[255px]` is UNPREFIXED in both arms and the rail width is `lg:`-only, which is a
 * correctness requirement rather than a style: `isCollapsed` is a desktop control (its
 * button is `lg:flex`) but it is component state that SURVIVES A RESIZE, so a bare
 * `lg:w-[72px]` left the mobile overlay drawer with no width of its own and it
 * shrink-wrapped its content instead of being a 255px drawer. Both shells had that bug;
 * `tests/responsive.test.ts` pins it, and pins it here now that there is one expression
 * instead of two.
 *
 * The transition is `lg:`-gated for the same reason: below `lg` this element's width never
 * changes, and `NavDrawer` owns a `transition-transform` on it for the drawer slide. At
 * `lg` and up the panel is `lg:static lg:translate-x-0` — the transform is constant there
 * — so replacing the transition property with `width` at that breakpoint costs nothing and
 * keeps ONE transition declaration in play at any given width.
 */
export function sidebarPanelClass(isCollapsed: boolean): string {
  return [
    "w-[255px]",
    "lg:motion-safe:transition-[width]",
    "lg:motion-safe:duration-200",
    "lg:motion-safe:ease-out",
    isCollapsed ? "lg:w-[72px]" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * The fade half of the gesture, for anything that leaves the screen with the labels — a
 * label, a count badge, a lock glyph.
 *
 * `lg:`-only throughout: below `lg` the panel is the 255px drawer and everything in it is
 * fully visible whatever `isCollapsed` happens to be holding.
 */
export function sidebarFadeClass(isCollapsed: boolean): string {
  return isCollapsed
    ? "lg:motion-safe:transition-opacity lg:opacity-0 lg:motion-safe:delay-0 lg:motion-safe:duration-100"
    : "lg:motion-safe:transition-opacity lg:opacity-100 lg:motion-safe:delay-100 lg:motion-safe:duration-150";
}

/**
 * A label that collapses with the panel instead of being unmounted by it.
 *
 * `flex-1 min-w-0` is what makes the single width transition do all the work: the label is
 * the only flexible thing in the row, so it absorbs the whole 183px the panel loses and
 * clips itself to nothing, while the icon beside it (`shrink-0`) never moves.
 */
export function SidebarLabel({
  isCollapsed,
  children,
}: {
  isCollapsed: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`min-w-0 flex-1 truncate text-left ${sidebarFadeClass(isCollapsed)}`}>
      {children}
    </span>
  );
}

/**
 * Geometry for one nav row, shared by every entry in both shells.
 *
 * `overflow-hidden` is load-bearing rather than defensive: see the gap note in the header.
 * `touch:min-h-11` keeps these at the 44px finger target — they are the console's
 * most-tapped controls and `py-2` alone left them 36px tall.
 */
export const SIDEBAR_ROW_CLASS =
  "mb-1 flex items-center gap-3 overflow-hidden rounded-lg px-4 py-2 text-sm font-medium touch:min-h-11";

/** The footer that holds the identity block and the way out. */
export const SIDEBAR_FOOTER_CLASS = "border-t border-line px-2 py-4";

/** The identity row inside that footer — 36px glyph, centred on the rail's centre line. */
export const SIDEBAR_IDENTITY_ROW_CLASS =
  "flex items-center gap-3 overflow-hidden rounded-lg p-2.5";

/**
 * The brand block at the top of both panels, and the mobile drawer's close button.
 *
 * The two shells rendered this identically apart from the two lines of text, so it is one
 * component taking those two lines. The mark is `BrandIcon` and NOT a lucide glyph in a
 * `bg-brand-strong` chip: the artwork is dark green ink on transparency and would render
 * green-on-green (`components/brand.tsx`).
 */
export function SidebarBrand({
  isCollapsed,
  onClose,
  title,
  subtitle,
}: {
  isCollapsed: boolean;
  onClose: () => void;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex items-center gap-3 overflow-hidden px-[18px] py-5">
      <BrandIcon size={36} />
      <SidebarLabel isCollapsed={isCollapsed}>
        <span className="block text-[17px] font-bold leading-none tracking-tight text-ink">
          {title}
        </span>
        <span className="block text-[11px] font-medium text-ink-muted">{subtitle}</span>
      </SidebarLabel>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close navigation"
        className="flex shrink-0 items-center justify-center rounded-md p-1.5 text-ink-faint hover:bg-black/5 touch:h-11 touch:w-11 lg:hidden dark:hover:bg-white/5"
      >
        <X className="h-5 w-5" />
      </button>
    </div>
  );
}

/**
 * The one control that collapses and expands the panel.
 *
 * It used to be TWO buttons — a "Collapse sidebar" in the brand row that was unmounted
 * when collapsed, and an "Expand sidebar" in a row that only existed when collapsed. That
 * is two pops in one gesture: a control vanishing, and the panel getting a whole row
 * taller. One button in one row that is always there has neither, and it is also the
 * disclosure pattern a reader expects — same control, `aria-expanded` says which way it
 * currently is.
 *
 * `pr-[22px]` puts it exactly on the rail's centre line when collapsed (72 - 22 - 14 = 36)
 * and, expanded, within 2px of where the old collapse button sat.
 */
export function SidebarCollapseToggle({
  isCollapsed,
  onToggle,
}: {
  isCollapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="hidden justify-end pb-2 pr-[22px] lg:flex">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="flex items-center justify-center rounded-md p-1.5 text-ink-faint hover:bg-black/5 dark:hover:bg-white/5"
      >
        {isCollapsed ? (
          <PanelLeftOpen className="h-4 w-4" />
        ) : (
          <PanelLeftClose className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}

/**
 * A nav group's heading, and the rule that replaces it on the rail.
 *
 * Both shells swapped the `<h3>` for a hairline divider when collapsed, which changed the
 * group's height by 12px — 6 groups' worth of vertical jump, in the same frame the panel
 * started sliding. The two now cross-fade inside a slot of FIXED height, so nothing above
 * or below moves at all, and the heading stays in the accessibility tree in both states
 * rather than being deleted from it.
 */
export function SidebarGroupHeading({
  isCollapsed,
  children,
}: {
  isCollapsed: boolean;
  children: ReactNode;
}) {
  return (
    <div className="relative mb-3 h-4">
      <h3
        className={`absolute inset-0 truncate px-4 text-[11px] font-semibold uppercase leading-4 tracking-wider text-ink-faint ${sidebarFadeClass(
          isCollapsed,
        )}`}
      >
        {children}
      </h3>
      {/* Decorative: it says the same thing the heading above it says, for a reader who
          can see the rail but not read 11px of text on it. */}
      <div
        aria-hidden
        className={`absolute inset-x-2 top-1/2 h-px bg-line opacity-0 ${sidebarFadeClass(
          !isCollapsed,
        )}`}
      />
    </div>
  );
}

/**
 * A block whose height is CONTENT-DERIVED and which must still collapse smoothly — the
 * admin shell's per-entry refusal sentence, which is one or two lines depending on the
 * permission.
 *
 * This is the one place the `grid-template-columns`/`grid-template-rows` `1fr -> 0fr`
 * trick belongs, and it is used here for exactly the reason it exists: `height` cannot
 * animate to or from `auto`, and a `max-height` guess either clips a long sentence or
 * spends most of the transition animating empty space. The panel's own width does NOT use
 * it — both of those sizes are fixed numbers (see the header).
 *
 * Technique: https://css-tricks.com/animating-css-grid-how-to-examples/ and
 * https://theadhocracy.co.uk/wrote/the-trick-to-animating-grid-columns (both supplied in
 * the brief; both EGRESS-BLOCKED from this container and therefore not read here — the
 * `1fr`/`0fr` + `overflow-hidden` shape below is written from the CSS Grid spec's own
 * definition of `<flex>` track sizes as an interpolatable numeric type, which is what
 * makes it animate at all).
 */
export function SidebarCollapsibleBlock({
  isCollapsed,
  children,
}: {
  isCollapsed: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={`grid grid-rows-[1fr] lg:motion-safe:transition-[grid-template-rows] lg:motion-safe:duration-200 lg:motion-safe:ease-out ${
        isCollapsed ? "lg:grid-rows-[0fr]" : "lg:grid-rows-[1fr]"
      }`}
    >
      <div className={`overflow-hidden ${sidebarFadeClass(isCollapsed)}`}>{children}</div>
    </div>
  );
}

/**
 * The collapse state itself.
 *
 * Deliberately NOT persisted. Reading a stored value on mount would either need a
 * `useEffect` (so the panel visibly collapses one frame after the page paints — the exact
 * "appearing twice" glitch `components/marketing/motion.tsx` documents) or a synchronous
 * `localStorage` read during render, which is a hydration mismatch. Neither is worth it
 * for a preference that costs one click to restate, and no one has asked for it.
 */
export function useSidebarCollapse(): { isCollapsed: boolean; toggle: () => void } {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const toggle = useCallback(() => setIsCollapsed((was) => !was), []);
  return { isCollapsed, toggle };
}
