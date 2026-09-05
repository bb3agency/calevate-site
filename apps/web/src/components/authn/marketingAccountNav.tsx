"use client";

/**
 * The marketing header's right-hand side, which used to offer "Sign in" to people who
 * already were.
 *
 * A visitor holding a live session was shown the same two calls to action as a stranger —
 * "Sign in" and "Create a workspace" — so the one thing they wanted, their console, was
 * the one thing the page did not link to, and the most prominent button invited them to
 * make a SECOND workspace. Nothing was broken; it was just addressed to the wrong person.
 *
 * WHY A CLIENT COMPONENT INSIDE A SERVER PAGE. `app/page.tsx` is a server component and
 * the session cookie is `HttpOnly`, so neither the server render nor any script can read
 * it — the only way to know is to ask the API. That is a round trip, and it must not
 * block the marketing page's first paint, so this island renders the signed-OUT state
 * immediately and swaps once the answer lands. See `_settled` for why it never flickers
 * the other way.
 *
 * THE CLIENT REALM ONLY, and that is a boundary rather than an omission. This header
 * belongs to `app.calevate.tech` and its "Sign in" already pointed at the client door;
 * probing the admin realm from here would be the realm bleed CLAUDE.md forbids, and it
 * would put an operator's session state on a public marketing page. An operator visiting
 * this page sees the signed-out header, which is correct — they have no client session,
 * and the door it offers is not theirs.
 *
 * THE `"guest"` AUDIENCE, for §5.4's reason: the console and the guest pages keep separate
 * `blocked` flags, so a failed restore here cannot convince the console that restore is
 * impossible — nor the sign-in page, whose whole job is to fix that.
 */

import { ArrowRight, LayoutDashboard } from "lucide-react";
import Link from "next/link";

import { CLIENT_CONSOLE_PATH, CLIENT_SIGN_IN_PATH, clientAuthn } from "@/lib/authn/clientAuthn";
import { useRealmSession } from "@/lib/authn/useRealmSession";
import { clientConsoleUrl } from "@/lib/consoleOrigin";

// TIGHTER BELOW `sm`, because this nav shares one row with the logo and at 320px that row
// did not fit — measured in Chromium, 374px of content in a 320px viewport. The padding
// and type step back up at `sm`, so nothing changes on the screens that have the room.
const LINK =
  "rounded-md px-2 py-1.5 text-xs font-medium whitespace-nowrap text-ink-muted hover:bg-black/5 sm:px-3 sm:text-sm dark:hover:bg-white/5";
const PRIMARY =
  "inline-flex items-center gap-1.5 rounded-md bg-brand-strong px-2.5 py-1.5 text-xs font-semibold whitespace-nowrap text-white hover:bg-brand-strong sm:px-3 sm:text-sm";

export interface MarketingAccountNavProps {
  /**
   * Where the header's call to action goes, and what it says.
   *
   * IT IS NO LONGER THE SIGNUP DOOR, and the prop is generic for that reason rather than
   * out of taste. The founder's decision of 5 Sep 2026 makes the header CTA deliberately
   * low-commitment — it sends a cold visitor into the page rather than at an account
   * form, and the signup call to action lives in the hero and at the foot where the
   * reader has been given a reason for it. `components/marketing/siteHeader.tsx` owns
   * both values; this component owns only the row they sit in.
   */
  readonly ctaHref: string;
  readonly ctaLabel: string;
}

export function MarketingAccountNav({ ctaHref, ctaLabel }: MarketingAccountNavProps) {
  const { status, session } = useRealmSession(clientAuthn, "guest");

  // SIGNED IN ONLY WHEN THE SERVER SAID SO. `restoring` and every failure render the
  // signed-out header: a marketing page that hid its sign-in link because a request was
  // in flight would strand somebody whose session had in fact expired, on the one page
  // that can send them to fix it.
  const signedIn = status === "ready" && session !== null;

  if (!signedIn) {
    return (
      // NAMED, because the page now renders four navigation landmarks (this one, the
      // header's section nav, the header's menu and the footer's legal list) and axe's
      // `landmark-unique` rule is about a screen-reader user moving between them by name.
      <nav aria-label="Account" className="flex items-center gap-2">
        <Link href={CLIENT_SIGN_IN_PATH} className={LINK}>
          Sign in
        </Link>
        <Link href={ctaHref} className={PRIMARY}>
          {ctaLabel}
          <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </nav>
    );
  }

  return (
    <nav aria-label="Account" className="flex items-center gap-2">
      {/* `/c`, not `/c/<slug>`: this component has a session and no slug, and the junction
          is what turns one into the other. Linking anywhere else would mean a second
          `/v1/me` read here purely to build an href.
          ABSOLUTE, because this nav renders on the APEX, which serves `/c` and refuses
          `/c/<slug>` — so the bare path reached the junction and died at its destination. */}
      <Link href={clientConsoleUrl(CLIENT_CONSOLE_PATH)} className={PRIMARY}>
        <LayoutDashboard aria-hidden className="h-3.5 w-3.5" />
        Go to your console
      </Link>
      {/* The account screen, reachable but secondary. NOT a sign-out: this is a marketing
          page, and putting the one destructive session control next to a call to action
          is how somebody ends a session they meant to open. `/auth/account` owns that. */}
      <Link href="/auth/account" className={LINK} aria-label="Your account">
        Account
      </Link>
    </nav>
  );
}
