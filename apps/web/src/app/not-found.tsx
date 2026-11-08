/**
 * THE 404 — the app had none, so every mistyped URL got Next's built-in default: no
 * wordmark, no typography, no tokens, no realm and no link back. Verified against the
 * framework we ship: `next@15.5.21`,
 * `dist/client/components/builtin/not-found.js` renders `HTTPAccessErrorFallback` with the
 * bare sentence *"This page could not be found."*
 *
 * This file replaces it for BOTH ways a 404 happens:
 *
 *   1. **A `notFound()` call.** `app/legal/[slug]/page.tsx` is currently the only one in
 *      the product, and its own docstring says an unknown slug *"should tell the reader
 *      there is no such document"*.
 *   2. **Any URL the router does not match** — a stale bookmark, a typo, `/c/<slug>/settings`.
 *
 * ## Why the title is `metadata` and not a rendered `<title>`
 *
 * The root `not-found` may export `metadata` (nextjs.org/docs/app/api-reference/
 * file-conventions/not-found, "Metadata"), which only a Server Component can do; the
 * path-dependent exits live in `NotFoundPage`. A `<title>` rendered by the body instead
 * lost to the root layout's `metadata.title` on an unmatched URL: the server HTML carried
 * both titles and the tab read the bare "Calevate".
 */

import type { Metadata } from "next";

import { NotFoundPage } from "@/components/notFoundPage";

export const metadata: Metadata = {
  title: "Page not found — Calevate",
  robots: { index: false },
};

export default function NotFound() {
  return <NotFoundPage />;
}
