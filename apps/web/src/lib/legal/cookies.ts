import type { LegalDocument } from "./types";

/**
 * The cookie notice, and it exists because the answer was CHECKED rather than assumed.
 *
 * The brief said to write one only if the site actually sets cookies. It does — but not
 * where a template would put them, and the difference is the whole document:
 *
 * - `src/app/layout.tsx` (the root layout, which the public pages inherit) mounts no
 *   authentication provider, no analytics and no third-party script. Fonts are local
 *   (`next/font/local`), so there is not even a font request leaving the browser. The
 *   public pages therefore set nothing.
 * - `ClerkProvider` is mounted only inside `src/app/admin/layout.tsx`, the client-realm
 *   layout and the `(auth)` sign-in pages. Clerk's cookies are key-suffixed per
 *   application so the two realms can coexist on one registrable domain — the mechanism
 *   is documented in `src/lib/auth/clerkRuntime.tsx`.
 *
 * So the honest notice is: nothing on the public site, strictly-necessary session cookies
 * once you sign in, no consent banner because there is nothing to consent to. Writing a
 * generic "we use cookies to enhance your experience" banner over that would be a false
 * statement AND a worse experience.
 */
export const COOKIE_NOTICE: LegalDocument = {
  slug: "cookies",
  title: "Cookies & Tracking",
  shortTitle: "Cookies & Tracking",
  summary:
    "What is stored in your browser, when, and why there is no cookie banner on this " +
    "site.",
  appliesTo: "Anyone using calevate.tech or app.calevate.tech.",
  sections: [
    {
      id: "public",
      heading: "1. The public pages set no cookies",
      blocks: [
        {
          kind: "para",
          text:
            "The home page and these legal pages set no cookies at all — not analytics " +
            "cookies, not preference cookies, not even a cookie recording that you have " +
            "read this notice. There is nothing to accept and nothing to reject, which is " +
            "why you are not being asked.",
        },
        {
          kind: "para",
          text: "Also absent, deliberately:",
        },
        {
          kind: "list",
          items: [
            "No analytics of any kind — no Google Analytics, no product analytics, no " +
              "heatmaps, no session recording.",
            "No advertising or remarketing tags, and no social media pixels.",
            "No third-party fonts. The typeface is served from our own server, so your " +
              "browser makes no request to a font provider.",
            "No embedded video, no chat widget, no third-party script of any kind.",
            "No local storage or session storage on the public pages.",
          ],
        },
        {
          kind: "para",
          text:
            "What is recorded is the ordinary web request — your IP address, the page, " +
            "the time, the referring page and your browser's user-agent — in our web " +
            "server's logs and in Cloudflare's, which provides TLS and protection against " +
            "attack in front of the site. That is not a cookie, it is not tied to a " +
            "profile, and it exists to keep the site up and to investigate abuse.",
        },
      ],
    },
    {
      id: "signed-in",
      heading: "2. Once you sign in to a dashboard",
      blocks: [
        {
          kind: "para",
          text:
            "Signing in to app.calevate.tech or admin.calevate.tech sets cookies. All of " +
            "them are strictly necessary: they are what keeps you signed in, and without " +
            "them the dashboard cannot work at all. Under every framework we are aware of, " +
            "strictly necessary cookies do not require consent — so there is still no " +
            "banner.",
        },
        {
          kind: "table",
          caption: "Cookies set after sign-in",
          columns: ["Cookie", "Set by", "What it does", "How long it lasts"],
          rows: [
            [
              "Session cookie",
              "Clerk, our authentication provider",
              "Carries the short-lived token that proves you are signed in. It is what " +
                "makes every page you load yours rather than somebody else's.",
              "Short-lived and refreshed while you use the dashboard.",
            ],
            [
              "Client state cookie (name ends in a short suffix, for example " +
                "__client_uat_a1b2c3d4)",
              "Clerk",
              "Records that a signed-in session exists in this browser, so the app knows " +
                "whether to show you the dashboard or the sign-in screen. The suffix is " +
                "derived from the application's public key: Calevate runs two entirely " +
                "separate sign-in applications, one for clients and one for our operators, " +
                "and the suffix is what stops them colliding on one domain.",
              "Until the session ends. Operator sessions last 12 hours; client sessions " +
                "refresh for up to 7 days.",
            ],
            [
              "Development-only cookie",
              "Clerk",
              "Used only on a developer's machine, where the browser will not share a " +
                "cookie across ports. It is never set on the live site.",
              "Not applicable in production.",
            ],
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "Two applications, two sets of cookies, and no shared session",
          text:
            "The client dashboard and the operator console use separate authentication " +
            "applications with separate cookies and no shared session logic. Being signed " +
            "in to one tells the other nothing. That separation is a security property, " +
            "not a technical accident, and it is why you may see two similarly named " +
            "cookies if you have used both.",
        },
      ],
    },
    {
      id: "control",
      heading: "3. Controlling them",
      blocks: [
        {
          kind: "para",
          text:
            "Your browser lets you block or delete cookies for any site. Blocking them for " +
            "calevate.tech has no effect on the public pages, because there are none. " +
            "Blocking them for the dashboard signs you out and stops you signing back in, " +
            "since the cookie is the sign-in.",
        },
        {
          kind: "para",
          text:
            "We honour a Global Privacy Control or Do Not Track signal by default, in the " +
            "sense that there is nothing for it to switch off: we do no tracking whether " +
            "or not you send one.",
        },
      ],
    },
    {
      id: "changes",
      heading: "4. If this changes",
      blocks: [
        {
          kind: "para",
          text:
            "If we ever add analytics, a chat widget or any other non-essential " +
            "technology, this page changes first and a consent mechanism appears with it. " +
            "We will not add a tracker and quietly update the wording here. Questions to " +
            "{{DATA_PROTECTION_CONTACT_EMAIL}}.",
        },
      ],
    },
  ],
};
