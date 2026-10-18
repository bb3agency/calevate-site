/**
 * WHERE THE ASSISTANT IS ALLOWED TO SEND SOMEBODY — the browser's half of D-524.
 *
 * The `navigate` frame carries a route TEMPLATE (`/c/{slug}/credits`), because the server is
 * never told this account's slug on the ask path: a declaring screen sends the template
 * (`registry.ts`) and the fallback sends a masked address bar (`fallback.ts`). So the slug is
 * substituted HERE — and then the result is checked against `lib/clientNav.ts`, the one list
 * the sidebar itself renders.
 *
 * ## Why the check exists when the server already checked
 *
 * Because they are checks of different things, and the cheap one is the one that makes the
 * property STRUCTURAL rather than trusted. The server refuses a screen name that is not in
 * its inventory and emits a route constant the model never touched
 * (`apps/api/copilot/navigation.py`); this refuses a route that is not one this console
 * actually has. Together: an attacker who could influence the model cannot produce a path at
 * all, and an attacker who could somehow influence the SERVER's frame still cannot produce
 * one this function will hand to the router. A single filtered `router.push(payload.route)`
 * would be an open redirect one bug away — `//evil.example` is a same-looking string and a
 * different origin — and no amount of pattern-matching is as good as membership of a list of
 * 28 constants.
 *
 * ## It returns a path for the app's own router and nothing else
 *
 * Every entry in `clientNavigation()` is an in-app path beginning `/c/<slug>`, so what comes
 * back is always same-origin and always a client-side route change. There is deliberately no
 * branch here for an external address, a full page load or a new tab: the assistant has no
 * business doing any of the three, and the way to keep it that way is to have nowhere to put
 * one.
 */

import { clientNavigation } from "@/lib/clientNav";

/** The token a route template carries where the account's slug goes. */
const SLUG = "{slug}";

/**
 * The in-app path this frame means, or `null` when it means nothing this console has.
 *
 * `null` is not an error to show anybody: the answer beside it has already said where the
 * screen is in words, so the honest response to an unrecognised destination is to leave the
 * person where they are rather than to explain a defect they did not cause. The caller logs
 * nothing and shows nothing — see `CopilotPanel`.
 */
export function resolveDestination(route: string, slug: string): string | null {
  if (!route.includes(SLUG)) return null;
  // `split`/`join` rather than `replace`, so a template that somehow carried two `{slug}`
  // tokens cannot leave one behind for the membership check to trip over — and so that
  // nothing here depends on `replace`'s special treatment of `$` in the replacement.
  const candidate = route.split(SLUG).join(slug);
  const known = clientNavigation(slug).flatMap((group) => group.items.map((item) => item.href));
  return known.includes(candidate) ? candidate : null;
}
