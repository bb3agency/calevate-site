"use client";

/**
 * THE 404 — the app had none, so every mistyped URL got Next's built-in default: no
 * wordmark, no typography, no tokens, no realm and no link back. Verified against the
 * framework we ship: `next@15.5.21`,
 * `dist/client/components/builtin/not-found.js` renders `HTTPAccessErrorFallback` with the
 * bare sentence *"This page could not be found."*
 *
 * This file replaces it for BOTH ways a 404 happens:
 *
 *   1. **A `notFound()` call.** `app/legal/[slug]/page.tsx:38` is currently the only one in
 *      the product, and its own docstring says an unknown slug *"should tell the reader
 *      there is no such document"*. Until now it told them nothing, in Times New Roman, to
 *      an audience its index page names as *"a payment gateway's onboarding reviewer, a
 *      client's procurement team and a regulator"*.
 *   2. **Any URL the router does not match** — a stale bookmark, a typo, `/c/<slug>/settings`.
 *
 * ## Why this is a client component, and why there is no realm-scoped `not-found.tsx`
 *
 * The exits have to be realm-appropriate: an operator who mistypes an admin URL should land
 * back in the operator console, not on our sales page. A segment-scoped `not-found.tsx`
 * cannot do that job, because a segment boundary only catches a `notFound()` THROWN inside
 * that segment — and nothing under `/admin` or `/c` throws one. Adding those files would
 * have shipped two screens nothing can reach, which is the half-wired defect CLAUDE.md
 * names, while leaving the actual unmatched-URL case landing here anyway. So the realm is
 * read from the path instead, in the one file that every 404 genuinely reaches.
 *
 * No part of the URL is interpolated into a link. `/c` is the junction that already
 * resolves a signed-in user's own console (`app/c/page.tsx`), so the exit needs no slug
 * from the address bar — which also means no untrusted string reaches an `href`.
 */

import { usePathname } from "next/navigation";

import { NotFoundScreen, type Exit } from "@/components/failureScreen";

const HOME: Exit = { href: "/", label: "Go to the homepage" };
const CONSOLE: Exit = { href: "/c", label: "Open your console" };
const LEGAL: Exit = { href: "/legal", label: "Legal documents" };

/** The way out, chosen for where the reader was when the address failed. */
function exitsFor(pathname: string | null): Exit[] {
  if (pathname?.startsWith("/admin")) {
    return [{ href: "/admin", label: "Back to the operator console" }, HOME];
  }
  if (pathname?.startsWith("/c")) return [CONSOLE, HOME];
  if (pathname?.startsWith("/legal")) {
    return [{ href: "/legal", label: "All legal documents" }, HOME];
  }
  return [HOME, CONSOLE, LEGAL];
}

export default function NotFound() {
  return (
    <NotFoundScreen
      detail={
        "The address you followed does not exist here — it may have been mistyped, or the " +
        "page may have moved since the link was made. Nothing is broken, and nothing has " +
        "been lost."
      }
      exits={exitsFor(usePathname())}
    />
  );
}
