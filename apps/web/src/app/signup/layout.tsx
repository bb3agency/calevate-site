import type { Metadata } from "next";
import type { ReactNode } from "react";

import { publicPageMetadata } from "@/lib/seo/metadata";

/**
 * A LAYOUT THAT EXISTS ONLY TO CARRY `/signup`'s METADATA, and could not be anything else.
 *
 * `app/signup/page.tsx` opens with `"use client"` — it is a form with state, validation and
 * a session provider. A client component MAY NOT export `metadata`: Next's metadata is
 * resolved on the server, and the export is silently ignored rather than rejected, which is
 * the failure this file removes. Before it, `/signup` inherited the root layout's fallback
 * and went to search engines as "Calevate / AI phone agents for Indian businesses" — the
 * same title and the same description as `/`, on the two public pages that matter most.
 *
 * It renders `{children}` and NOTHING ELSE, deliberately. The marketing chrome is a
 * COMPONENT (`components/marketing/pageShell.MarketingPage`) rather than a layout, and
 * `pageShell.tsx`'s own header says why: `tests/a11y.test.tsx` renders each `page.tsx`
 * without its layout, so chrome in a layout would be chrome no accessibility gate ever
 * scans. Putting anything visible here would reintroduce exactly that hole.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/signup",
  title: "Get started — Calevate",
  // True whether or not self-serve signup is open on this deployment. `SIGNUP_OPEN`
  // defaults to CLOSED and the page then renders the "how an account is obtained today"
  // panel instead of the form, so a description promising a form would be false half the
  // time — and the half where it is false is the one a stranger arrives on.
  description:
    "How a business gets a Calevate workspace: what you choose during setup, the " +
    "languages an agent can answer in, and who to contact if self-serve signup is closed.",
});

export default function SignupLayout({ children }: { children: ReactNode }) {
  return children;
}
