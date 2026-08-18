/**
 * Which navigation entry the current path belongs to — ONE rule, read by both halves of
 * both shells.
 *
 * The two shells each used to compute this twice: the header title by longest-prefix
 * match, the sidebar highlight (and with it `aria-current="page"`) by exact match, four
 * lines apart. The consequence was that on every detail route in the product —
 * `/c/<slug>/calls/<id>`, `/c/<slug>/leads/<id>`, all eight `/admin/tenants/<id>/*`,
 * `/admin/qa-sampling/<id>` — the header named a section while the sidebar highlighted
 * nothing and NO element in the document carried `aria-current`. A sighted reader lost
 * the location cue on the deepest screens; a screen-reader user could not answer "where
 * am I" from the navigation at all (WCAG 2.4.8 is the advisory one, but `aria-current`
 * is the mechanism ARIA 1.2 §5.2 names for it and the shells already reached for it).
 *
 * It lives here rather than in either `layout.tsx` because Next's route-file typing
 * rejects any export from a layout that is not one of its own conventions (`OmitWithTag`
 * in `.next/types`), so a helper both shells share cannot live in one of them — and a
 * second copy of the rule is the defect this module exists to remove.
 *
 * LONGEST PREFIX WINS, and that is the rule the exact-match half was missing rather
 * than the one it had:
 *
 * - `/admin/ops/dnc` keeps "Global do-not-call" instead of inheriting "Operations",
 *   which a plain `startsWith` in list order would give it.
 * - `/admin/new` keeps its own name instead of inheriting `/admin`'s.
 * - `/c/<slug>/calls/<id>` resolves to "Call logs" instead of falling through to the
 *   dashboard.
 *
 * The `/` boundary in the prefix test is load-bearing: without it `/admin/newsletter`
 * would match `/admin/new`.
 */

/** The one thing this rule needs from a nav entry. */
export interface NavHref {
  readonly href: string;
}

/**
 * The entry `pathname` sits under, or `undefined` when it sits under none.
 *
 * `undefined` rather than a fallback entry on purpose: "no nav entry owns this path" and
 * "this path is the dashboard" are different facts, and only the caller knows which
 * default its shell wants for the title. What the caller must NOT do is invent a
 * different answer for the highlight than for the title, which is what this returning
 * one value prevents.
 */
export function currentNavItem<T extends NavHref>(
  items: readonly T[],
  pathname: string,
): T | undefined {
  let best: T | undefined;
  for (const item of items) {
    if (pathname === item.href || pathname.startsWith(`${item.href}/`)) {
      if (!best || item.href.length > best.href.length) best = item;
    }
  }
  return best;
}
