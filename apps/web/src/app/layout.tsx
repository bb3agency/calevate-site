import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";

import { StructuredData } from "@/components/structuredData";
import { SITE_LOCALE, SITE_NAME } from "@/lib/seo/metadata";
import { SITE_ORIGIN } from "@/lib/site";

import "./globals.css";

const ppMori = localFont({
  src: [
    {
      path: "../fonts/PPMori-Extralight.otf",
      weight: "200",
      style: "normal",
    },
    {
      path: "../fonts/PPMori-ExtralightItalic.otf",
      weight: "200",
      style: "italic",
    },
    {
      path: "../fonts/PPMori-Regular.otf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../fonts/PPMori-RegularItalic.otf",
      weight: "400",
      style: "italic",
    },
    {
      path: "../fonts/PPMori-SemiBold.otf",
      weight: "600",
      style: "normal",
    },
    {
      path: "../fonts/PPMori-SemiBoldItalic.otf",
      weight: "600",
      style: "italic",
    },
  ],
  variable: "--font-pp-mori",
});

// JetBrains Mono for keys, IDs, codes and any fixed-width value an operator reads or
// pastes. Chosen over the system monospace stack because it disambiguates the glyphs
// those values collide on — a dotted zero distinct from O, and 1/l/I all distinct — so
// a mistyped or misread API key is caught by the eye, not by a failed call later.
// Self-hosted (SIL OFL 1.1, JetBrainsMono-OFL.txt) like PP Mori: no CDN, no CSP egress.
// Only the two weights the UI uses are bundled — Regular for values, Medium for the rare
// emphasised token — keeping the payload to ~180KB.
const jetbrainsMono = localFont({
  src: [
    {
      path: "../fonts/JetBrainsMono-Regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../fonts/JetBrainsMono-Medium.woff2",
      weight: "500",
      style: "normal",
    },
  ],
  variable: "--font-jetbrains-mono",
});

/**
 * The site-wide metadata every route inherits, and the ONE thing here that is load-bearing
 * beyond the title: `metadataBase`.
 *
 * Without it Next resolves `openGraph.url`, `alternates.canonical` and the generated
 * `opengraph-image` as RELATIVE URLs and logs *"metadataBase property in metadata export
 * is not set... using default"* at build time. A relative `og:image` is not a defect the
 * page shows — every link preview simply fails to render an image, which is discovered by
 * somebody pasting the URL into WhatsApp, not by a gate. It resolves against
 * `lib/site.SITE_ORIGIN`, the same constant `sitemap.ts`, `robots.ts` and every canonical
 * tag use, so the four cannot name different sites.
 *
 * ⚠ NO `alternates.canonical` HERE, deliberately. Canonical inherits down the segment
 * tree, so one set at the root would make every page that did not override it declare `/`
 * as its canonical — which asks a search engine to drop nine pages and keep the homepage.
 * Each public route states its own through `lib/seo/metadata.publicPageMetadata`, and
 * `tests/seo.test.ts` fails if one does not.
 *
 * The title and description below are the FALLBACK, for the realms that are not public
 * pages (the two consoles, the auth screens). Every public page overrides both.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  title: "Calevate",
  description: "AI phone agents for Indian businesses",
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    locale: SITE_LOCALE,
    url: SITE_ORIGIN,
  },
  twitter: { card: "summary_large_image" },
};

/**
 * THE MOBILE KEYBOARD MUST MOVE `position: fixed`, NOT SIT ON TOP OF IT.
 *
 * `width`/`initialScale` are Next's own defaults, restated because declaring this export
 * REPLACES the default tag rather than extending it — dropping them here would ship a page
 * with no `width=device-width` and break every responsive layout in both consoles. There is
 * deliberately no `maximumScale` and no `userScalable: false`: pinch-zoom stays available
 * (WCAG 2.1 SC 1.4.4), and `tests/a11y.test.tsx` already reads the absence as correct.
 *
 * `interactiveWidget` is the whole reason this export exists. Its default is
 * `resizes-visual`, under which a virtual keyboard resizes only the VISUAL viewport, so
 * "elements with `position: fixed` will remain in place and can be obscured by the
 * keyboard". `CopilotPanel` is exactly that: a fixed card anchored to `bottom-20` whose
 * only control is a textarea. `resizes-content` resizes the LAYOUT viewport too, so a
 * fixed element is pushed up above the keyboard instead.
 *
 * It is set on the root rather than per-realm because the hazard is not the copilot's: the
 * five modals, `ReceiptSheet` and the toast stack are all fixed and several hold inputs.
 * A viewport key cannot be scoped to a subtree in any case — there is one meta tag.
 *
 * EVIDENCE. The FIELD and its three accepted values are VERIFIED from the installed
 * framework's own types — `next/dist/lib/metadata/types/extra-types.d.ts:53` in next
 * 15.5.21, read 7 Sep 2026. The BEHAVIOUR (which of the three is the default, and what each
 * does to a fixed element) is MDN's description of the `interactive-widget` viewport key,
 * relayed through a web search on 7 Sep 2026 — ⚠ EVIDENCE CLASS: VENDOR-PUBLISHED, NOT
 * read at source: `developer.mozilla.org` is egress-blocked from this container, so nobody
 * here has opened the page. Support is reported as Chrome 108+ / Firefox 132+ on the same
 * footing. Nothing about the fix depends on that being exact: a browser that does not
 * implement the key ignores it and behaves exactly as it does today, so the downside of a
 * wrong reading is no change rather than a regression. What has NOT been verified is the
 * effect on a real handset — nobody in this session has loaded the console on a phone.
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  interactiveWidget: "resizes-content",
};

/**
 * EVERY PAGE RENDERS PER REQUEST, AND THE CSP IS THE ONLY REASON.
 *
 * `middleware.ts` mints a fresh nonce per request and `script-src` names it with no
 * `'unsafe-inline'` beside it. Under CSP3 a nonce SUPPRESSES `'self'` for inline scripts,
 * and Next emits its RSC payload as bare inline `<script>self.__next_f.push(...)` tags —
 * so the nonce has to reach the HTML or none of them run. Next can only stamp it while
 * RENDERING A REQUEST; a statically prerendered route is built once, before any nonce
 * exists, and ships those scripts bare.
 *
 * That combination served a BLANK WHITE SCREEN in production: the document and the
 * external `/_next/static` bundles loaded (both allowed by `'self'`), every inline script
 * carrying the hydration data was refused, and React had nothing to mount. It was
 * invisible until the policy went enforcing (D-541), because report-only reports and
 * then permits.
 *
 * The cost is real and accepted deliberately: the marketing pages were static and are now
 * rendered per request. The alternatives were worse — dropping the nonce for
 * `'unsafe-inline'` gives up exactly the XSS protection the policy exists for, and adding
 * `'unsafe-inline'` ALONGSIDE the nonce fixes nothing, because a nonce-capable browser
 * ignores it. Next's own guidance is that nonce-based CSP requires dynamic rendering.
 */
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${ppMori.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        {/* Organization + WebSite JSON-LD. Last in the body because it renders nothing and
            reads the per-request CSP nonce; see `components/structuredData.tsx`. */}
        <StructuredData />
      </body>
    </html>
  );
}
