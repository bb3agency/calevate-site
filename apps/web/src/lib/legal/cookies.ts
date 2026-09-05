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
 *
 * ## Section 3 exists because "no cookies" was answering an easier question
 *
 * Re-verified 26 August 2026 by grepping the whole of `apps/web/src` for browser storage
 * rather than by re-reading this file. `src/lib/authn/signedOutNotice.ts` writes ONE
 * `sessionStorage` key (`calevate.authn.had-session.<realm>`), and the sign-in pages
 * (`app/(auth)/auth/sign-in`, `.../auth/admin/sign-in`) read and clear it. This notice
 * said "no local storage or session storage on the public pages" and stopped there — true
 * of the home page and these legal pages, and a reader who counts the sign-in page as
 * public was being told something false by omission. F-11 in `docs/LEGAL-SURFACE.md` is
 * the finding about naming trackers this site does not have; the mirror-image defect is
 * not naming the one item it does, so it is now section 3 rather than a silence.
 *
 * ## And the home page turned out NOT to be exempt, which §1 asserted until 27 Aug 2026
 *
 * `src/app/page.tsx:423` mounts `components/authn/marketingAccountNav`, which calls
 * `useRealmSession(clientAuthn, "guest")`; a restore that answers `ok` runs
 * `rememberSession(authn.realm)` (`src/lib/authn/useRealmSession.ts:125`) and that writes
 * `calevate.authn.had-session.client`. So a visitor who ALREADY HOLDS a live client
 * session has that one key written by the home page, on the client realm only. The
 * legal pages remain genuinely clean — nothing under `src/app/legal/` mounts a session
 * hook — and a visitor with no session gets nothing anywhere. §1 said "there is exactly
 * one item of browser storage anywhere on this service, it is not on these pages", which
 * was right about the item and wrong about the page, in the direction that matters: it
 * denied a write that happens.
 *
 * Nothing else writes to the browser: `set_cookie` appears in exactly one module in the
 * backend (`apps/api/authn/cookies.py`), no code in `apps/web/src` touches
 * `document.cookie`, and there is no `localStorage` anywhere in the tree.
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
            "No local storage anywhere on this service, and — on these legal pages — no " +
              "session storage either. The home page is one narrow exception and we " +
              "would rather state it than round it off: if you are already signed in to " +
              "a client dashboard, the header on the home page checks with our server " +
              "so that it can offer you your console instead of a sign-in link, and a " +
              "successful check leaves a single mark in session storage. That is the " +
              "same one item section 3 describes, it is the only item of browser storage " +
              "anywhere on this service, and a visitor who is not signed in never gets " +
              "it.",
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
              "It is set to last until your session's own final expiry and no longer, " +
                "so it survives closing your browser or your phone putting the tab to " +
                "sleep. Our server is the authority and can end it sooner: a client " +
                "session ends after 12 hours of inactivity, and after 14 days no matter " +
                "how active you are. Signing out ends it immediately on our server, so " +
                "the cookie stops working whether or not your browser still has it.",
            ],
            [
              "__Host-calevate_admin_session",
              "Calevate.",
              "Exactly the same cookie for the operator console, under a different name. " +
                "The two are separate cookies backed by separate session logic, so being " +
                "signed in to one grants nothing in the other.",
              "This one carries no expiry date of its own, so your browser drops it " +
                "when you close it — deliberately shorter-lived than the client cookie, " +
                "because it opens an operator console. Our server ends an operator " +
                "session after 30 minutes of inactivity, and after 8 hours regardless.",
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
      id: "browser-storage",
      heading: "3. One thing that is not a cookie",
      blocks: [
        {
          kind: "para",
          text:
            "A cookie notice that answers only the cookie question is answering an easier " +
            "question than the one you asked, so: there is one other thing kept in your " +
            "browser by this service. It is not a tracker, it is not a cookie, and it " +
            "never leaves your machine.",
        },
        {
          kind: "definitions",
          items: [
            {
              term:
                "calevate.authn.had-session.client and calevate.authn.had-session.admin — " +
                "session storage, not cookies",
              detail:
                "A single mark saying that a session existed in this browser tab. It " +
                "holds no identifier, no name and nothing that distinguishes you from " +
                "anyone else who has ever signed in. It is written by any page of ours " +
                "that confirms with our server that this tab holds a live session — a " +
                "dashboard tab, and also the home page, whose header asks about a client " +
                "session so that it can point you at your console rather than at a " +
                "sign-in form. It is never written for someone who is not signed in, so " +
                "a stranger arriving at the home page gets no storage at all. The " +
                "sign-in page reads it once and deletes it as " +
                "it reads. It exists so that the sign-in page can tell \"your session " +
                "just ended\" from \"you have never signed in here\" — which our server " +
                "genuinely cannot do, because an expired session cookie and an absent one " +
                "arrive looking identical, and because the cookie is HttpOnly no script " +
                "can inspect it either. It is per-tab storage, so closing the tab removes " +
                "it, and it is never sent to us or to anyone else.",
            },
          ],
        },
        {
          kind: "para",
          text:
            "It is strictly necessary in the same sense the cookies are, and its entire " +
            "effect is one sentence of explanation on a sign-in page. A browser that " +
            "refuses storage gets no mark, no sentence, and no other difference — the " +
            "code that reads it treats a refusal as \"say nothing\" rather than as an " +
            "error.",
        },
      ],
    },
    {
      id: "control",
      heading: "4. Controlling them",
      blocks: [
        {
          kind: "para",
          text:
            "Your browser lets you block or delete cookies and site storage for any " +
            "site. Blocking them for calevate.tech has no effect on these legal pages, " +
            "because they set none, and none on the home page beyond the mark in " +
            "section 3 — which you only ever had if you were signed in. Blocking them " +
            "for the dashboard " +
            "signs you out and stops you signing back in, since the cookie is the " +
            "sign-in; blocking storage alone costs you only the sentence described in " +
            "section 3.",
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
      heading: "5. If this changes",
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
