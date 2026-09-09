import type { Metadata } from "next";

import { siteUrl } from "@/lib/site";

/**
 * ONE WAY TO DESCRIBE A PUBLIC PAGE TO A SEARCH ENGINE AND TO A LINK PREVIEW.
 *
 * Before this, the eight interior pages each carried a hand-written `metadata` object with
 * a title and a description and nothing else — no canonical URL, no Open Graph, no Twitter
 * card. Adding those three by hand to ten route files is ten chances to spell `og:url`
 * against the wrong origin, and the failure is invisible from the page: a canonical tag
 * that names a URL other than the one being served silently asks a search engine to index
 * a different page, and nothing in the app ever renders it.
 *
 * So a route says what it IS — path, title, description — and this decides how that is
 * spelled everywhere. `tests/seo.test.ts` holds every public route to having called it.
 *
 * ## The canonical is ABSOLUTE and per-page, and is not set in the root layout
 *
 * `alternates.canonical` inherits down the segment tree. Setting it once in the root
 * layout is the tempting shape and is exactly wrong: every page that did not override it
 * would declare `/` as its canonical, which asks Google to drop nine pages and keep the
 * homepage. `metadataBase` in the root layout is what IS inherited — it makes a relative
 * OG image resolve — and the canonical is stated by each page, here, from `siteUrl`.
 *
 * ## Open Graph `type`
 *
 * `website` for all of these. `article` is for a datelined piece with an author, which
 * none of these are; the legal documents come closest and are still not articles — they
 * are living documents whose date is an effective date, not a publication date.
 */
export interface PublicPageMetadata {
  /** The path this page is served on, as it appears in `lib/site.PUBLIC_ROUTES`. */
  readonly path: string;
  /** The `<title>`, in full. Not a template — every page here already reads `X — Calevate`. */
  readonly title: string;
  /** One or two sentences, under ~160 characters where possible. Shown in a search result. */
  readonly description: string;
}

/** The site's name, as it should appear in a link preview and in `WebSite` structured data. */
export const SITE_NAME = "Calevate";

/**
 * The locale these pages are written in.
 *
 * ⚠ `en_IN`, AND THERE ARE NO `hreflang` ALTERNATES, which is the part worth stating
 * because this is a Telugu-first product and the temptation is to declare Telugu here.
 * Telugu-first describes what the AGENT SPEAKS ON A PHONE CALL. Every page of this website
 * is written in English and there is no Telugu translation of any of them —
 * `<html lang="en">` in the root layout is the accurate statement. An `hreflang="te"`
 * alternate pointing at a page that does not exist is a broken promise a search engine
 * acts on: it would serve a Telugu speaker a URL that 404s. If Telugu pages are ever
 * built, this is where their `alternates.languages` goes, and not before.
 */
export const SITE_LOCALE = "en_IN";

/** The metadata a public marketing page ships, from the three facts only the page knows. */
export function publicPageMetadata({ path, title, description }: PublicPageMetadata): Metadata {
  const url = siteUrl(path);
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      type: "website",
      url,
      title,
      description,
      siteName: SITE_NAME,
      locale: SITE_LOCALE,
    },
    twitter: {
      // `summary_large_image` rather than `summary`: the card image this site serves is
      // the 1200x630 one `app/opengraph-image.tsx` renders, and `summary` would crop it to
      // a square thumbnail. There is no `twitter:site` handle — see the note in
      // `lib/seo/structuredData.ts` about accounts this repository cannot prove exist.
      card: "summary_large_image",
      title,
      description,
    },
  };
}
