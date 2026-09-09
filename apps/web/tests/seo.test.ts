import type { Metadata } from "next";
import { describe, expect, it } from "vitest";

import robots from "@/app/robots";
import sitemap from "@/app/sitemap";
import { generateMetadata as legalDocumentMetadata } from "@/app/legal/[slug]/page";
import { metadata as homeMetadata } from "@/app/page";
import { metadata as industriesMetadata } from "@/app/industries/page";
import { metadata as legalIndexMetadata } from "@/app/legal/page";
import { metadata as pricingMetadata } from "@/app/pricing/page";
import { metadata as resourcesMetadata } from "@/app/resources/page";
import { metadata as roiMetadata } from "@/app/roi/page";
import { metadata as securityMetadata } from "@/app/security/page";
import { metadata as signupMetadata } from "@/app/signup/layout";
import { metadata as solutionsMetadata } from "@/app/solutions/page";
import { metadata as whyCalevateMetadata } from "@/app/why-calevate/page";
import { NAV_ROUTES } from "@/components/marketing/siteHeader";
import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { organizationJsonLd, siteJsonLd, websiteJsonLd } from "@/lib/seo/structuredData";
import { DISALLOWED_PREFIXES, PUBLIC_ROUTES, SITE_ORIGIN, siteUrl } from "@/lib/site";

/**
 * THE TECHNICAL-SEO FLOOR, and one of its four assertions is a compliance assertion.
 *
 * Three of the things checked here are ordinary site hygiene — a canonical URL on every
 * public page, a title and a description that are present and are not the same as some
 * other page's, a sitemap that lists what exists. The fourth is not: **no URL under `/c/`
 * or `/admin/` may ever appear in `sitemap.xml`**. A client-console path carries a TENANT
 * SLUG, which is the identity of a business that is our customer, so a sitemap entry for
 * one is a cross-tenant disclosure performed by us, at scale, to every crawler on the
 * internet — and unlike most disclosures it is one we would be actively advertising.
 *
 * `app/sitemap.ts` already refuses to emit one (it throws rather than filtering, so the
 * cause gets fixed rather than hidden). This is the second check, because the cost of the
 * failure is not proportional to the cost of the check.
 *
 * ## Why the page list is not in this file
 *
 * It is `lib/site.PUBLIC_ROUTES`, which is also what the navigation renders, what the
 * sitemap publishes and what the browser accessibility gate scans. A list here would be a
 * fifth copy and would pass while the site drifted underneath it — the exact failure this
 * suite exists to catch elsewhere.
 */

/** Every public page's declared metadata, keyed by the path it is served on. */
const STATIC_METADATA: Readonly<Record<string, Metadata>> = {
  "/": homeMetadata,
  "/solutions": solutionsMetadata,
  "/industries": industriesMetadata,
  "/why-calevate": whyCalevateMetadata,
  "/pricing": pricingMetadata,
  "/roi": roiMetadata,
  "/security": securityMetadata,
  "/resources": resourcesMetadata,
  "/signup": signupMetadata,
  "/legal": legalIndexMetadata,
};

/** `Metadata["title"]` is a union with a template form; these pages all use plain strings. */
function titleOf(meta: Metadata): string {
  const title = meta.title;
  expect(typeof title, `title is not a plain string: ${JSON.stringify(title)}`).toBe("string");
  return String(title);
}

function canonicalOf(meta: Metadata): string {
  const canonical = meta.alternates?.canonical;
  expect(canonical, "no alternates.canonical").toBeTruthy();
  return String(canonical);
}

describe("the public route inventory", () => {
  it("covers every static page under src/app that is not in a private realm", () => {
    // The premise. `PUBLIC_ROUTES` is the site map four other modules read; an empty or
    // truncated one would make every assertion below vacuously true.
    expect(PUBLIC_ROUTES.length).toBeGreaterThanOrEqual(10);
    expect(Object.keys(STATIC_METADATA).sort()).toEqual(PUBLIC_ROUTES.map((r) => r.path).sort());
  });

  it("is the same list the site navigation renders", () => {
    // NAV_ROUTES is derived from PUBLIC_ROUTES rather than typed a second time. This holds
    // the derivation to producing the seven interior pages — not `/`, not `/signup`, not
    // `/legal`, which are reached from the brand mark, the CTA and the footer.
    expect(NAV_ROUTES.map((item) => item.href)).toEqual(
      PUBLIC_ROUTES.filter((route) => route.navLabel).map((route) => route.path),
    );
    expect(NAV_ROUTES.length).toBe(7);
  });
});

describe("sitemap.xml", () => {
  const entries = sitemap();
  const urls = entries.map((entry) => entry.url);

  it("NEVER publishes a client-console or operator-console URL", () => {
    // The one assertion in this file that is about disclosure rather than about ranking.
    const leaked = urls.filter((url) => {
      const path = new URL(url).pathname;
      return DISALLOWED_PREFIXES.some((entry) => path.startsWith(entry.prefix));
    });
    expect(
      leaked,
      "a sitemap entry inside a private realm — a /c/ path carries a tenant slug",
    ).toEqual([]);
    // Stated twice on purpose: the loop above depends on DISALLOWED_PREFIXES being right,
    // and these two spellings are the ones that actually cost a customer.
    expect(urls.filter((url) => url.includes("/c/"))).toEqual([]);
    expect(urls.filter((url) => url.includes("/admin"))).toEqual([]);
  });

  it("lists every public marketing page, once", () => {
    for (const route of PUBLIC_ROUTES) {
      expect(urls, `missing ${route.path}`).toContain(siteUrl(route.path));
    }
    expect(new Set(urls).size, "a duplicate URL").toBe(urls.length);
  });

  it("lists all eight legal documents, with their published effective date", () => {
    expect(LEGAL_DOCUMENTS.length).toBe(8);
    for (const doc of LEGAL_DOCUMENTS) {
      const entry = entries.find((e) => e.url === siteUrl(`/legal/${doc.slug}`));
      expect(entry, `no sitemap entry for /legal/${doc.slug}`).toBeDefined();
      // Real date or absent — never `new Date()`, which would tell every crawler that
      // every document changed on the day of the request.
      expect(entry?.lastModified).toBeInstanceOf(Date);
    }
  });

  it("emits absolute URLs on the canonical origin, with no trailing slash", () => {
    for (const url of urls) {
      expect(url.startsWith(`${SITE_ORIGIN}`), `${url} is not on ${SITE_ORIGIN}`).toBe(true);
      if (url !== SITE_ORIGIN) expect(url.endsWith("/"), `${url} has a trailing slash`).toBe(false);
    }
    // `/` is the origin itself, not `origin + "/"` — otherwise the canonical tag and the
    // sitemap name two URLs for one page.
    expect(urls).toContain(SITE_ORIGIN);
  });

  it("gives every entry a priority and a change frequency", () => {
    for (const entry of entries) {
      expect(typeof entry.priority, `${entry.url} has no priority`).toBe("number");
      expect(entry.priority).toBeGreaterThan(0);
      expect(entry.priority).toBeLessThanOrEqual(1);
      expect(entry.changeFrequency, `${entry.url} has no changeFrequency`).toBeTruthy();
    }
  });
});

describe("robots.txt", () => {
  const file = robots();
  const rules = Array.isArray(file.rules) ? file.rules : [file.rules];
  const disallowed = rules.flatMap((rule) => {
    const value = rule.disallow ?? [];
    return Array.isArray(value) ? value : [value];
  });

  it("disallows BOTH authenticated realms", () => {
    expect(disallowed, "the client console is crawlable").toContain("/c/");
    expect(disallowed, "the operator console is crawlable").toContain("/admin/");
  });

  it("disallows every prefix the sitemap refuses to publish", () => {
    // One list, two readers. A prefix added to DISALLOWED_PREFIXES for the sitemap's sake
    // and not reflected here would be a realm the sitemap hides and robots.txt invites.
    for (const entry of DISALLOWED_PREFIXES) {
      expect(disallowed, `${entry.prefix} is not disallowed`).toContain(entry.prefix);
    }
  });

  it("still allows the public site, and names the sitemap on the canonical origin", () => {
    const allowed = rules.flatMap((rule) => {
      const value = rule.allow ?? [];
      return Array.isArray(value) ? value : [value];
    });
    expect(allowed).toContain("/");
    expect(rules.some((rule) => rule.userAgent === "*")).toBe(true);
    expect(file.sitemap).toBe(`${SITE_ORIGIN}/sitemap.xml`);
    expect(file.host).toBe(SITE_ORIGIN);
  });
});

describe("every public page's metadata", () => {
  it("has a non-empty title and description", () => {
    for (const [path, meta] of Object.entries(STATIC_METADATA)) {
      expect(titleOf(meta).trim().length, `${path} has an empty title`).toBeGreaterThan(0);
      expect(String(meta.description ?? "").trim().length, `${path} has no description`)
        .toBeGreaterThan(50);
    }
  });

  it("has a title and a description shared with NO other public page", () => {
    // The defect this catches is real and was live: `/` and `/signup` both inherited the
    // root layout's fallback ("Calevate" / "AI phone agents for Indian businesses"),
    // because a client-component page silently cannot export `metadata`.
    const titles = Object.entries(STATIC_METADATA).map(([path, meta]) => [path, titleOf(meta)]);
    const descriptions = Object.entries(STATIC_METADATA).map(([path, meta]) => [
      path,
      String(meta.description),
    ]);
    for (const [kind, pairs] of [
      ["title", titles],
      ["description", descriptions],
    ] as const) {
      const seen = new Map<string, string>();
      for (const [path, value] of pairs) {
        const first = seen.get(value);
        expect(first, `${path} and ${first} share a ${kind}: ${JSON.stringify(value)}`).toBe(
          undefined,
        );
        seen.set(value, path);
      }
    }
  });

  it("declares its own absolute canonical URL", () => {
    for (const [path, meta] of Object.entries(STATIC_METADATA)) {
      expect(canonicalOf(meta), `${path} has the wrong canonical`).toBe(siteUrl(path));
    }
  });

  it("carries Open Graph and a Twitter card that agree with the page", () => {
    for (const [path, meta] of Object.entries(STATIC_METADATA)) {
      const og = meta.openGraph;
      expect(og, `${path} has no openGraph`).toBeTruthy();
      expect(String(og?.title)).toBe(titleOf(meta));
      expect(String((og as { description?: string })?.description)).toBe(String(meta.description));
      expect(String((og as { url?: string })?.url)).toBe(siteUrl(path));
      expect((og as { siteName?: string })?.siteName).toBe("Calevate");
      expect((og as { type?: string })?.type).toBe("website");
      expect((og as { locale?: string })?.locale).toBe("en_IN");
      expect((meta.twitter as { card?: string })?.card).toBe("summary_large_image");
    }
  });

  it("gives each legal document its own title, description and canonical", async () => {
    const seen = new Set<string>();
    for (const doc of LEGAL_DOCUMENTS) {
      const meta = await legalDocumentMetadata({ params: Promise.resolve({ slug: doc.slug }) });
      expect(canonicalOf(meta)).toBe(siteUrl(`/legal/${doc.slug}`));
      const title = titleOf(meta);
      expect(seen.has(title), `two legal documents titled ${title}`).toBe(false);
      seen.add(title);
      expect(String(meta.description ?? "").length).toBeGreaterThan(20);
    }
  });

  it("marks an unknown legal slug noindex, so a soft 404 cannot be indexed", async () => {
    const meta = await legalDocumentMetadata({ params: Promise.resolve({ slug: "gdpr" }) });
    expect((meta.robots as { index?: boolean })?.index).toBe(false);
    expect(meta.alternates?.canonical, "a 404 has no canonical URL to claim").toBeUndefined();
  });

  it("declares no hreflang alternates, because there are no translated pages", () => {
    // Telugu-first describes what the AGENT SPEAKS ON A CALL. Every page of this site is
    // English, and an `hreflang="te"` pointing at a page that does not exist is a broken
    // promise a search engine acts on — it would serve a Telugu speaker a 404.
    for (const [path, meta] of Object.entries(STATIC_METADATA)) {
      expect(meta.alternates?.languages, `${path} declares a translation that does not exist`)
        .toBeUndefined();
    }
  });
});

describe("the site's JSON-LD", () => {
  const graph = siteJsonLd();

  it("parses, and is a schema.org graph of exactly Organization and WebSite", () => {
    const parsed = JSON.parse(JSON.stringify(graph)) as {
      "@context": string;
      "@graph": { "@type": string }[];
    };
    expect(parsed["@context"]).toBe("https://schema.org");
    expect(parsed["@graph"].map((node) => node["@type"])).toEqual(["Organization", "WebSite"]);
  });

  it("survives being embedded in a <script> block", () => {
    // `components/structuredData.tsx` escapes `<` before writing this into the document.
    // The escaped form must still be valid JSON, or the markup is silently unparseable.
    const escaped = JSON.stringify(graph).replace(/</g, "\\u003c");
    expect(escaped).not.toContain("</script");
    expect(() => JSON.parse(escaped)).not.toThrow();
  });

  it("states ONLY facts this repository can source", () => {
    // The bright line. Each of these is a field it takes six seconds to invent and which
    // nobody would ever see rendered — an `aggregateRating` here is a FABRICATED REVIEW
    // published under the company's name. `lib/seo/structuredData.ts` records, field by
    // field, why each is absent. Adding one means finding the source first.
    const FORBIDDEN = [
      "aggregateRating",
      "review",
      "ratingValue",
      "reviewCount",
      "sameAs",
      "foundingDate",
      "priceRange",
      "offers",
      "numberOfEmployees",
      "vatID",
      "taxID",
      "award",
      "slogan",
      "duns",
    ];
    const serialized = JSON.stringify(graph);
    for (const field of FORBIDDEN) {
      expect(serialized, `structured data claims ${field}, which nothing in this repo sources`)
        .not.toContain(`"${field}"`);
    }
  });

  it("carries the sourced identity fields, spelled as the legal documents spell them", () => {
    const org = organizationJsonLd() as Record<string, string>;
    expect(org.name).toBe("Calevate");
    expect(org.legalName).toBe("Calevate");
    // The Udyam number, the city-level address, the published phone and the published
    // mailbox — all four come from `lib/legal/placeholders.ts`, whose source is the Udyam
    // certificate the founder read on 25 Aug 2026.
    expect(JSON.stringify(org)).toContain("UDYAM-AP-04-0146106");
    expect(org.address).toBe("Guntur, Andhra Pradesh, India");
    expect(org.telephone).toBe("+91 80198 57559");
    expect(org.email).toBe("calevate.voice@gmail.com");
    expect(org.url).toBe(SITE_ORIGIN);
    // ⚠ THE STREET LINES WERE REMOVED FROM THE LEGAL SET ON 4 SEP 2026 BECAUSE THEY ARE
    // THE FOUNDER'S HOME. They must not reappear here, which is a place nobody would look.
    expect(org.address).not.toMatch(/\d{6}/);
  });

  it("links WebSite to Organization by id, so the two are one entity", () => {
    const site = websiteJsonLd() as Record<string, unknown>;
    expect((site.publisher as Record<string, string>)["@id"]).toBe(
      (organizationJsonLd() as Record<string, string>)["@id"],
    );
    expect(site.inLanguage).toBe("en-IN");
    // No sitelinks search box: this site has no search endpoint to point one at.
    expect(JSON.stringify(site)).not.toContain("SearchAction");
  });
});
