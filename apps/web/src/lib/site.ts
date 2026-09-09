/**
 * THE PUBLIC SITE'S OWN ORIGIN AND ITS OWN PAGE LIST — one table, four readers.
 *
 * Before this module the site had no idea what its own address was and no single list of
 * the pages it publishes. The address was prose in three places (`lib/consoleOrigin.ts:4`
 * names `calevate.tech` as the marketing apex, `lib/legal/cookies.ts:62` and
 * `lib/legal/privacy.ts:87` publish it to readers), and the page list existed twice — in
 * `components/marketing/siteHeader.NAV_ROUTES` and again, spelled by hand, in
 * `tests/browser/gate.ts::SCAN_TARGETS`. A sitemap would have been a THIRD copy, which is
 * the drift CLAUDE.md's "one way per problem" rule exists to refuse: the copy that falls
 * behind is never the one you are editing, and a sitemap that has fallen behind is the
 * kind of defect nobody notices for a quarter.
 *
 * So the table below is the site map, and everything that needs one derives from it:
 *
 *   - `app/sitemap.ts`               — what search engines are told exists
 *   - `app/robots.ts`                — what they are told to stay out of
 *   - `components/marketing/siteHeader.NAV_ROUTES` — what a visitor is offered
 *   - `tests/browser/gate.ts`        — what the accessibility gate scans
 *   - `tests/seo.test.ts`            — the guard that holds the four together
 *
 * It has no imports, deliberately: `tests/browser/gate.ts` runs in a NODE environment
 * whose job is to spawn a server, and its own comment explains why it may not import a
 * `.tsx` component (React, `next/link` and the icon set would come with it). A plain data
 * module costs that harness nothing.
 */

/**
 * WHERE THE PUBLIC SITE LIVES. Canonical URLs, the sitemap and `metadataBase` all resolve
 * against it, so it is the one string that decides what a search engine indexes us as.
 *
 * `calevate.tech` — the APEX, not `app.` and not `admin.`. This deployment is three
 * hostnames and one bundle (`lib/consoleOrigin.ts` sets that out in full): the apex serves
 * the marketing site and the three auth screens, and nginx answers 404 there for `/admin`
 * and `/c/`. Every page in `PUBLIC_ROUTES` below is served on the apex and only on the
 * apex, so the apex is the canonical origin for all of them.
 *
 * ⚠ NOT AN ENVIRONMENT VARIABLE, and that is a decision rather than an omission. A
 * `NEXT_PUBLIC_SITE_ORIGIN` would be inlined at build time and would ship as the empty
 * string wherever it was not set (`next.config.ts` opens with that failure mode), and the
 * symptom of an empty canonical origin is not a crash — it is a sitemap full of relative
 * URLs and a canonical tag pointing at nothing, which validates fine and is silently
 * useless. The origin of the production marketing site is also not a per-deployment fact:
 * a preview build wants the SAME canonical, because a canonical URL naming a preview host
 * is how a preview gets indexed instead of the real site. One constant, changed in a diff
 * with a name on it, is the honest shape.
 */
export const SITE_ORIGIN = "https://calevate.tech";

/** How often a page's content actually changes, in `sitemap.xml`'s vocabulary. */
export type ChangeFrequency = "daily" | "weekly" | "monthly" | "yearly";

/** One page the public internet may see. */
export interface PublicRoute {
  /** The path, no origin and no trailing slash (`/` itself excepted). */
  readonly path: string;
  /**
   * The header/footer label, when this page appears in the site navigation. Absent means
   * the page is public and linked from the body of the site rather than from the nav —
   * `/` is the nav's home mark, `/signup` is the call to action, `/legal` is the footer.
   */
  readonly navLabel?: string;
  /**
   * Relative importance within this site, 0..1. It is a HINT about our own ranking of the
   * pages against each other and nothing more — it says nothing to a search engine about
   * how we compare to anybody else.
   */
  readonly priority: number;
  readonly changeFrequency: ChangeFrequency;
  /** Why this page is in the list — read by nobody until it needs to change. */
  readonly why: string;
}

/**
 * EVERY PUBLIC MARKETING PAGE. The legal documents are NOT here: there are eight of them
 * under one dynamic route and their list already exists, typed, in `lib/legal`
 * (`LEGAL_DOCUMENTS`), each with a real effective date. `app/sitemap.ts` reads both.
 *
 * What is deliberately absent, because a sitemap entry is an invitation to crawl:
 *
 *   - `/c/**` and `/admin/**` — the two authenticated realms. A tenant slug is the client
 *     business's identity; publishing one in a sitemap would be a cross-tenant disclosure
 *     performed by us, at scale, to every crawler on the internet.
 *   - `/auth/**` — the three sign-in screens. Nothing to index and a login form is not a
 *     landing page.
 *   - `/invite` — reachable only with a token that came in an email.
 */
export const PUBLIC_ROUTES: readonly PublicRoute[] = [
  {
    path: "/",
    priority: 1,
    changeFrequency: "weekly",
    why: "the landing page",
  },
  {
    path: "/solutions",
    navLabel: "Solutions",
    priority: 0.8,
    changeFrequency: "monthly",
    why: "what the product does, job by job",
  },
  {
    path: "/industries",
    navLabel: "Industries",
    priority: 0.8,
    changeFrequency: "monthly",
    why: "the same product in the four trades it is sold to",
  },
  {
    path: "/why-calevate",
    navLabel: "Why Calevate",
    priority: 0.8,
    changeFrequency: "monthly",
    why: "the argument against the alternatives, and the claims we refuse",
  },
  {
    path: "/pricing",
    navLabel: "Pricing",
    priority: 0.8,
    changeFrequency: "monthly",
    why: "the only page printing money; the rate card moves under it",
  },
  {
    path: "/roi",
    navLabel: "ROI",
    priority: 0.8,
    changeFrequency: "monthly",
    why: "the calculator a buyer drives with their own numbers",
  },
  {
    path: "/security",
    navLabel: "Security",
    priority: 0.8,
    changeFrequency: "monthly",
    why: "what is enforced on every dial, and where each leg of a call runs",
  },
  {
    path: "/resources",
    navLabel: "Resources",
    priority: 0.6,
    changeFrequency: "monthly",
    why: "the index into the rest of the site, plus the glossary",
  },
  {
    path: "/signup",
    priority: 0.7,
    changeFrequency: "monthly",
    why: "the header call to action, and the first form a client meets",
  },
  {
    path: "/legal",
    priority: 0.4,
    changeFrequency: "yearly",
    why: "the legal index, linked from every footer",
  },
];

/**
 * URL PREFIXES NO CRAWLER MAY ENTER — read by `app/robots.ts`, and asserted against the
 * sitemap by `tests/seo.test.ts` so the two can never disagree.
 *
 * These are stated as a positive list rather than inferred from "not in PUBLIC_ROUTES",
 * because inference gets a NEW private realm wrong by default and this list gets it wrong
 * only if somebody forgets to add it — and a `Disallow` that is missing is visible in the
 * served `robots.txt`, whereas an inference that under-matched is visible nowhere.
 */
export const DISALLOWED_PREFIXES: readonly { readonly prefix: string; readonly why: string }[] = [
  {
    prefix: "/c/",
    why:
      "the client console. Every path under it carries a TENANT SLUG, which is the client " +
      "business's own identity — indexing one discloses a customer of ours to anybody who " +
      "searches, and the console needs a session to render anything in any case.",
  },
  {
    prefix: "/admin/",
    why: "the operator console: our own internal surface, and every tenant's name is in it",
  },
  {
    prefix: "/auth/",
    why: "sign-in, password reset and invitation acceptance. Nothing to index, and reset links are single-use",
  },
  {
    prefix: "/invite",
    why: "invitation acceptance — reachable only with a token that arrived by email",
  },
  {
    prefix: "/api/",
    why:
      "not a route this app serves today (the API is a separate origin), disallowed " +
      "ahead of the day it is, because a crawler that finds a JSON endpoint indexes it",
  },
];

/** An absolute URL on the public site, for a canonical tag or a sitemap entry. */
export function siteUrl(path: string): string {
  if (!path.startsWith("/")) throw new Error(`siteUrl expects a rooted path, got ${path}`);
  // `/` must not become `https://calevate.tech/` + `/`, and every other path must not
  // gain a trailing slash: a canonical URL that differs from the served URL by a slash is
  // two URLs to a search engine and one page to everybody else.
  return path === "/" ? SITE_ORIGIN : `${SITE_ORIGIN}${path}`;
}

/** Whether a path lies inside a realm no crawler may enter. */
export function isDisallowedPath(path: string): boolean {
  return DISALLOWED_PREFIXES.some(
    (entry) => path === entry.prefix.replace(/\/$/, "") || path.startsWith(entry.prefix),
  );
}
