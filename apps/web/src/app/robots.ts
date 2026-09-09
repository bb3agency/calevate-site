import type { MetadataRoute } from "next";

import { DISALLOWED_PREFIXES, SITE_ORIGIN, siteUrl } from "@/lib/site";

/**
 * `robots.txt`, generated — the Metadata Route file convention (`app/robots.ts`).
 *
 * EVIDENCE FOR THE EXPORT SHAPE: `MetadataRoute.Robots` in the INSTALLED framework,
 * `node_modules/next/dist/lib/metadata/types/metadata-interface.d.ts:539-553` in
 * next 15.5.21, read 9 Sep 2026. A default export returning `{ rules, sitemap?, host? }`,
 * where `rules` is one object or an array of them and each carries
 * `userAgent`/`allow`/`disallow`/`crawlDelay`. Read from the type rather than recalled,
 * because the shape has moved between Next versions and the failure is silent — a wrong
 * key is dropped, and the served file is simply missing the rule you thought you wrote.
 *
 * A static `public/robots.txt` was the alternative. It would be a second place the private
 * realms are named, next to `lib/site.ts::DISALLOWED_PREFIXES`, with nothing holding the
 * two together; here the file IS that constant, and `tests/seo.test.ts` reads this module.
 *
 * ## What `Disallow` is and is not
 *
 * It is a request to crawlers that honour it, and it is NOT access control — every path
 * below is also refused at nginx (the apex answers 404 for `/admin` and `/c/`) and needs a
 * session behind that. Nothing here is the security boundary; this exists so that a
 * well-behaved crawler does not spend our budget on pages it cannot render, and so that a
 * URL a tenant pasted somewhere public does not turn into an indexed page.
 *
 * `Allow: /` for `*` comes first on purpose: the default with no rule at all is "crawl
 * everything", and stating it makes the disallows read as exceptions rather than as the
 * whole policy.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: DISALLOWED_PREFIXES.map((entry) => entry.prefix),
      },
    ],
    sitemap: siteUrl("/sitemap.xml"),
    // The canonical hostname, for the crawlers that read it. Same constant the sitemap
    // and every canonical tag resolve against, so the three cannot name different sites.
    host: SITE_ORIGIN,
  };
}
