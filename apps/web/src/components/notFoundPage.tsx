"use client";

/**
 * The body of `app/not-found.tsx`: the 404 screen with its exits chosen from the path.
 *
 * Its own client module because the route file must stay a Server Component to export
 * `metadata` (a client module cannot), and the exits need `usePathname`.
 *
 * The exits have to be realm-appropriate: an operator who mistypes an admin URL should land
 * back in the operator console, not on our sales page. A segment-scoped `not-found.tsx`
 * cannot do that job, because a segment boundary only catches a `notFound()` THROWN inside
 * that segment — and nothing under `/admin` or `/c` throws one. So the realm is read from
 * the path instead, in the one file that every 404 genuinely reaches.
 *
 * No part of the URL is interpolated into a link. `/c` is the junction that already
 * resolves a signed-in user's own console (`app/c/page.tsx`), so the exit needs no slug
 * from the address bar — which also means no untrusted string reaches an `href`.
 */

import { usePathname } from "next/navigation";

import { NotFoundScreen, type Exit } from "@/components/failureScreen";
import { adminConsoleUrl, clientConsoleUrl } from "@/lib/consoleOrigin";

const HOME: Exit = { href: "/", label: "Go to the homepage" };
/**
 * THROUGH THE ORIGIN HELPERS, because this screen is the one page that renders on all
 * three hostnames — nginx routes every refused address here (`error_page 404
 * /_calevate_not_found`). A bare `/c` offered on the apex reaches the junction, which
 * forwards to `/c/<slug>`, which the apex refuses; a bare `/admin` offered on `app.` is
 * refused outright. An exit from a not-found page that lands on another not-found page is
 * the worst possible version of this defect.
 */
const CONSOLE: Exit = { href: clientConsoleUrl("/c"), label: "Open your console" };
const LEGAL: Exit = { href: "/legal", label: "Legal documents" };

/** The way out, chosen for where the reader was when the address failed. */
function exitsFor(pathname: string | null): Exit[] {
  if (pathname?.startsWith("/admin")) {
    return [
      { href: adminConsoleUrl("/admin"), label: "Back to clients" },
      HOME,
    ];
  }
  if (pathname?.startsWith("/c")) return [CONSOLE, HOME];
  if (pathname?.startsWith("/legal")) {
    return [{ href: "/legal", label: "All legal documents" }, HOME];
  }
  return [HOME, CONSOLE, LEGAL];
}

export function NotFoundPage() {
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
