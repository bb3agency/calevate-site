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

const LINK = "rounded-md px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5";
const PRIMARY =
  "inline-flex items-center gap-1.5 rounded-md bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-strong";

export interface MarketingAccountNavProps {
  /** The signup call to action, whose wording the page owns (`SIGNUP_OPEN`). */
  readonly signupLabel: string;
}

export function MarketingAccountNav({ signupLabel }: MarketingAccountNavProps) {
  const { status, session } = useRealmSession(clientAuthn, "guest");

  // SIGNED IN ONLY WHEN THE SERVER SAID SO. `restoring` and every failure render the
  // signed-out header: a marketing page that hid its sign-in link because a request was
  // in flight would strand somebody whose session had in fact expired, on the one page
  // that can send them to fix it.
  const signedIn = status === "ready" && session !== null;

  if (!signedIn) {
    return (
      <nav className="flex items-center gap-2">
        <Link href={CLIENT_SIGN_IN_PATH} className={LINK}>
          Sign in
        </Link>
        <Link href="/signup" className={PRIMARY}>
          {signupLabel}
          <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </nav>
    );
  }

  return (
    <nav className="flex items-center gap-2">
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
