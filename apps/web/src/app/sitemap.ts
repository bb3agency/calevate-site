import type { MetadataRoute } from "next";

import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { LEGAL_VERSIONS } from "@/lib/legal/versions";
import { lookup } from "@/lib/lookup";
import { PUBLIC_ROUTES, isDisallowedPath, siteUrl } from "@/lib/site";

/**
 * `sitemap.xml`, generated — the Metadata Route file convention (`app/sitemap.ts`).
 *
 * EVIDENCE FOR THE EXPORT SHAPE: `MetadataRoute.Sitemap` in the INSTALLED framework,
 * `node_modules/next/dist/lib/metadata/types/metadata-interface.d.ts:554-563` in
 * next 15.5.21, read 9 Sep 2026 — an array of
 * `{ url, lastModified?, changeFrequency?, priority?, alternates?, images?, videos? }`.
 *
 * ## THE LIST IS DERIVED, NEVER TYPED
 *
 * Two sources, both already the truth for something else: `lib/site.PUBLIC_ROUTES` (which
 * the site navigation and the browser accessibility gate also read) and `lib/legal`'s
 * `LEGAL_DOCUMENTS` (which the footer and the `/legal` index render). A hand-kept list
 * here would be a third site map, and the one that falls behind is never the one you are
 * editing.
 *
 * ## AND WHAT IT MUST NEVER CONTAIN
 *
 * No path under `/c/` or `/admin/`. A client-console URL carries a TENANT SLUG — the
 * identity of a business that is our customer — so a sitemap entry for one is a
 * cross-tenant disclosure we performed ourselves, to every crawler, at scale. That is not
 * left to the derivation being correct: `assertNothingPrivate` below re-checks every URL
 * against `isDisallowedPath` before returning, and `tests/seo.test.ts` checks it again.
 * Two cheap checks, because the cost of the failure is not proportional to the cost of the
 * check.
 *
 * ## `lastModified`
 *
 * Present on the eight legal documents and ABSENT everywhere else, deliberately. A legal
 * document has a real, published effective date (`LEGAL_VERSIONS[slug].effectiveDate`,
 * mirrored from `apps/api/legal/catalogue.py` and drift-checked in CI), so that is a fact
 * this repository holds. A marketing page has no such fact: nothing in the tree records
 * when `/pricing`'s copy last changed, and `new Date()` — the value it is tempting to
 * write — would tell every crawler that every page changed on the day of the request,
 * which is a false statement made continuously and the fastest way to have the field
 * disbelieved for the pages where it IS true. Omitting it is honest and costs nothing:
 * the field is optional in the protocol.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const marketing: MetadataRoute.Sitemap = PUBLIC_ROUTES.map((route) => ({
    url: siteUrl(route.path),
    changeFrequency: route.changeFrequency,
    priority: route.priority,
  }));

  const legal: MetadataRoute.Sitemap = LEGAL_DOCUMENTS.map((doc) => {
    // `lookup` rather than a bare index read: the ESLint config bans indexing a record
    // with a value that is not provably a literal key (`lib/lookup.ts` holds the
    // prototype-chain argument). `undefined` is a legitimate answer and means "no
    // effective date published", which is `null` on the entry itself in any case.
    const version = lookup(LEGAL_VERSIONS, doc.slug);
    const effective = version?.effectiveDate;
    return {
      url: siteUrl(`/legal/${doc.slug}`),
      // A published legal document changes when a revision is issued, which is a rare and
      // deliberate act — `yearly` is what that actually looks like, and claiming `monthly`
      // for eight documents that have moved once would just cost crawl budget.
      changeFrequency: "yearly" as const,
      priority: 0.3,
      ...(effective ? { lastModified: new Date(`${effective}T00:00:00Z`) } : {}),
    };
  });

  return assertNothingPrivate([...marketing, ...legal]);
}

/**
 * The last gate before the file is served, and it THROWS rather than filtering.
 *
 * Filtering would make the mistake invisible: a `/c/<slug>` entry that quietly vanished
 * from the output would leave whatever produced it still producing it, and the next reader
 * of this module would have no idea the check was doing anything. A build-time failure
 * naming the URL is the only response that gets the cause fixed.
 */
function assertNothingPrivate(entries: MetadataRoute.Sitemap): MetadataRoute.Sitemap {
  for (const entry of entries) {
    const path = new URL(entry.url).pathname;
    if (isDisallowedPath(path)) {
      throw new Error(
        `sitemap.xml would have published ${entry.url}, which is inside a realm no ` +
          "crawler may enter (lib/site.ts::DISALLOWED_PREFIXES). A client-console URL " +
          "carries a tenant slug; publishing one discloses a customer.",
      );
    }
  }
  return entries;
}
