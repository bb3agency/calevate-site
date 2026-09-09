import { PLACEHOLDERS } from "@/lib/legal/placeholders";
import { lookup } from "@/lib/lookup";
import { SITE_ORIGIN, siteUrl } from "@/lib/site";

import { SITE_NAME } from "./metadata";

/**
 * SCHEMA.ORG STRUCTURED DATA — and, much more importantly, the list of what it REFUSES
 * to say.
 *
 * JSON-LD is the one place on a website where inventing a fact is trivially easy and
 * indistinguishable from research. A `Product` with an `aggregateRating` of 4.8 over 127
 * reviews takes six seconds to type, renders nowhere a human will see it, and is a
 * FABRICATED REVIEW published under this company's name — CLAUDE.md's hard rule 11 in its
 * purest form, and the reason this module is a small function with a long comment.
 *
 * ## Every field below is sourced from this repository, at a named line
 *
 *  - `name`, `legalName`  — `PLACEHOLDERS.LEGAL_ENTITY_NAME`, whose source is the Udyam
 *    Registration Certificate read by the founder on 25 Aug 2026.
 *  - `identifier`         — `PLACEHOLDERS.ENTITY_REGISTRATION_NUMBER`, same certificate.
 *  - `address`            — `PLACEHOLDERS.REGISTERED_ADDRESS`, same certificate, reduced
 *    to city level on 4 Sep 2026. Emitted as schema.org Text, NOT as a `PostalAddress`
 *    with split fields: the repository holds one string, and splitting it into
 *    `addressLocality`/`addressRegion` would be this module inventing a structure the
 *    source does not have. ⚠ AND THE STREET LINES MUST NOT COME BACK HERE EITHER — they
 *    are the founder's home address and were deliberately removed from the legal set.
 *  - `telephone`, `email` — `PLACEHOLDERS.CONTACT_PHONE` / `SUPPORT_EMAIL`, both already
 *    published to the internet on `/legal/grievance` and `/legal/refunds`.
 *  - `logo`               — `public/brand/calevate-full-logo-without-tagline.png`, a file
 *    that exists in this tree (2171x724).
 *
 * ## AND EVERY FIELD DELIBERATELY LEFT OUT, with why
 *
 *  - **`aggregateRating`, `review`** — there is no client #1 in production (ROADMAP M2)
 *    and therefore no rating and no review. Any number here would be fabricated. This is
 *    the same absence the homepage keeps: `publicLanding.test.tsx` bans social proof from
 *    the rendered copy, and structured data is copy a machine reads.
 *  - **`Product` / `Offer` / `priceRange`** — commercial pricing is negotiated per client
 *    (D-11) and the self-serve rates are FETCHED from `GET /v1/public/rate-card` at render
 *    time, never typed into this bundle. A price in a static JSON-LD blob would be a
 *    fourth spelling of money that no rate-card change can reach.
 *  - **`foundingDate`** — the Udyam registration date (25/08/2026) is the date of a
 *    REGISTRATION, not of a founding, and nothing in this tree records the latter.
 *  - **`sameAs`** — social profiles. This repository knows of no verified account on any
 *    platform; `sameAs` pointing at a handle nobody has proved we control is how an
 *    impersonator gets endorsed by our own markup.
 *  - **`numberOfEmployees`, `vatID`/`taxID`** — the first is unrecorded;
 *    `PLACEHOLDERS.GST_STATUS` says the business is NOT registered for GST, so there is
 *    no number and an empty field would read as an omission rather than as a fact.
 *  - **`SearchAction` on `WebSite`** — the sitelinks search box. This site has no search
 *    endpoint; declaring one would hand Google a URL template that 404s.
 *  - **`areaServed`, `availableLanguage`** — the PRODUCT speaks Telugu, Hindi and English
 *    (`lib/api/signup.SIGNUP_LANGUAGES`) and is sold in Andhra Pradesh and Telangana. What
 *    LANGUAGES AND TERRITORIES OUR SUPPORT CHANNEL COVERS is a different fact and is one
 *    nobody has recorded, so the contact point does not claim one.
 *
 * The shape is `unknown`-free but deliberately untyped beyond `Record<string, unknown>`:
 * a `schema-dts`-style dependency to type a forty-line object literal is the trade hard
 * rule 9 governs, and `tests/seo.test.ts` asserts the fields that matter by name.
 */

/** A JSON-LD node. `@type` is schema.org's, not ours. */
export type JsonLdNode = Record<string, unknown>;

/**
 * Read a placeholder's decided VALUE, or throw naming the token.
 *
 * A throw rather than a fallback string, because the failure mode this prevents is a
 * blank: `PLACEHOLDERS` is the registry of facts this repository does not know, and the
 * `value` field is present exactly when the fact HAS been decided
 * (`lib/legal/placeholders.ts` sets that out). An undecided one reaching structured data
 * would publish `undefined`, or worse the literal `{{TOKEN}}`, as the company's name.
 */
function sourcedFact(token: string): string {
  const placeholder = lookup(PLACEHOLDERS, token);
  const value = placeholder?.value;
  if (!value) {
    throw new Error(
      `structured data needs {{${token}}}, and lib/legal/placeholders.ts has no decided ` +
        "value for it. Nothing here may invent one — fill the placeholder or drop the field.",
    );
  }
  return value;
}

/** The `@id` of the Organization node, so `WebSite.publisher` can reference it. */
export const ORGANIZATION_ID = `${SITE_ORIGIN}/#organization`;

/** The `@id` of the WebSite node. */
export const WEBSITE_ID = `${SITE_ORIGIN}/#website`;

/**
 * The one-sentence description of the business, reused from the homepage hero's own
 * words rather than written fresh — the hero is the copy `publicLanding.test.tsx` already
 * holds to this company's claim rules, and a second description of the product is a second
 * thing to keep true.
 */
export const SITE_DESCRIPTION =
  "Calevate answers your calls, follows up on every enquiry, works out who is worth " +
  "your team’s time, and turns each conversation into a lead they can act on.";

export function organizationJsonLd(): JsonLdNode {
  return {
    "@type": "Organization",
    "@id": ORGANIZATION_ID,
    name: SITE_NAME,
    legalName: sourcedFact("LEGAL_ENTITY_NAME"),
    url: SITE_ORIGIN,
    logo: siteUrl("/brand/calevate-full-logo-without-tagline.png"),
    description: SITE_DESCRIPTION,
    address: sourcedFact("REGISTERED_ADDRESS"),
    telephone: sourcedFact("CONTACT_PHONE"),
    email: sourcedFact("SUPPORT_EMAIL"),
    identifier: {
      "@type": "PropertyValue",
      // The Udyam (MSME) registration, which is the identifier the legal documents
      // publish. Named in full rather than as an acronym: a consumer of this markup has
      // no reason to know what "Udyam" is.
      name: "Udyam Registration Number",
      value: sourcedFact("ENTITY_REGISTRATION_NUMBER"),
    },
    contactPoint: {
      "@type": "ContactPoint",
      contactType: "customer support",
      email: sourcedFact("SUPPORT_EMAIL"),
      telephone: sourcedFact("CONTACT_PHONE"),
    },
  };
}

export function websiteJsonLd(): JsonLdNode {
  return {
    "@type": "WebSite",
    "@id": WEBSITE_ID,
    name: SITE_NAME,
    url: SITE_ORIGIN,
    description: SITE_DESCRIPTION,
    // BCP-47, which is what schema.org's `inLanguage` takes, and the same language
    // `<html lang="en">` declares narrowed to the variant this site is written in.
    inLanguage: "en-IN",
    publisher: { "@id": ORGANIZATION_ID },
  };
}

/**
 * Both nodes in one `@graph`, which is how two nodes that reference each other are
 * published in a single script tag — the alternative is two script tags whose `@id`s have
 * to agree across a file boundary.
 */
export function siteJsonLd(): JsonLdNode {
  return {
    "@context": "https://schema.org",
    "@graph": [organizationJsonLd(), websiteJsonLd()],
  };
}
