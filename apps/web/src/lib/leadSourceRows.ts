/**
 * Row keys for the delivery log, out of the page module (D-196).
 *
 * IT LIVED IN `app/c/[slug]/lead-sources/page.tsx` AND WAS EXPORTED FROM IT, which
 * `next build` refuses: a Next.js page module may export only `default` and a fixed set of
 * route fields, so `export function deliveryRowKeys` failed the production build with
 * *"deliveryRowKeys is not a valid Page export field"*. Nothing imported it — it was
 * exported to be reachable — so the constraint cost nothing but a build.
 *
 * It is a MODULE rather than a private function for the reason it was exported in the
 * first place: it is a pure function with a real argument behind it, worth testing on its
 * own, and a page file is the one place in this app where making something testable
 * breaks the build. Here it cannot bite again.
 *
 * ── WHY THE KEY IS WHAT IT IS ──
 *
 * `lead_source_id` + `event_key` is not unique. `apps/api/ingest/routes.py` maps two
 * keyspaces onto one `lead_source_id` and discards the provider, so two rows can carry an
 * identical identity and React renders a duplicate-key warning — which the suite printed
 * on a green run, the state in which the next collision hides.
 *
 * The real fix is one server field (the provider on `IngestActivityItemOut`); the route
 * has the value in hand and throws it away. That is `apps/api`'s to make, and this file
 * cannot reach it.
 *
 * What this does instead is refuse to be wrong with the payload it has: identity plus its
 * OCCURRENCE COUNT among identical identities, unique by construction whatever the server
 * sends. The rejected alternative is the array index, which is unique too and re-keys
 * every row whenever the 30-second refetch reorders the table — this key survives a
 * reorder for every row whose identity is unambiguous, i.e. all of them until the server
 * actually collides. Delete it, and this comment, when the field lands.
 */

import type { IngestActivityItem } from "@/lib/api/leadSources";

export function deliveryRowKeys(
  items: readonly IngestActivityItem[],
): [IngestActivityItem, string][] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const identity = `${item.lead_source_id}-${item.event_key}`;
    const nth = seen.get(identity) ?? 0;
    seen.set(identity, nth + 1);
    return [item, nth === 0 ? identity : `${identity}#${nth}`];
  });
}
