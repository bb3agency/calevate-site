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
 * - The dashboards set ONE cookie each, and we mint it ourselves. There is no
 *   authentication vendor and no vendor cookie: `apps/api/authn/cookies.py` is the only
 *   thing in this system that sets a session cookie, and `COOKIE_NAMES` there is the
 *   authority for the two names below. This document used to describe a third party's
 *   cookies, key-suffixed per application; that vendor was removed (D-166/D-170/D-177)
 *   and the `__Host-` pair replaced them. A cookie notice naming cookies the site does
 *   not set, and omitting the one it does, is the failure this file exists to avoid.
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
              "__Host-calevate_client_session",
              "Calevate. There is no third-party sign-in provider and no vendor cookie.",
              "The client dashboard's session. It carries a random secret that identifies " +
                "your session row on our server and nothing else — no name, no email, no " +
                "account identifier. It is HttpOnly, so no script on the page can read " +
                "it; Secure, so it is never sent over plain HTTP; SameSite=Strict, so it " +
                "is not sent on a request another site started.",
              "It is a session cookie and carries no expiry date of its own, so your " +
                "browser drops it when you close it. Our server is the authority: a " +
                "client session ends after 12 hours of inactivity, and after 14 days no " +
                "matter how active you are.",
            ],
            [
              "__Host-calevate_admin_session",
              "Calevate.",
              "Exactly the same cookie for the operator console, under a different name. " +
                "The two are separate cookies backed by separate session logic, so being " +
                "signed in to one grants nothing in the other.",
              "Also a session cookie. Our server ends an operator session after 30 " +
                "minutes of inactivity, and after 8 hours regardless — shorter than a " +
                "client session, deliberately.",
            ],
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "Two realms, two cookies, and no shared session",
          text:
            "The client dashboard and the operator console use separate cookies backed " +
            "by separate session code, with nothing shared between them. Being signed in " +
            "to one tells the other nothing. That separation is a security property, not " +
            "a technical accident, and it is why you may see two similarly named cookies " +
            "if you have used both.",
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
