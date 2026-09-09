import { headers } from "next/headers";

import { siteJsonLd } from "@/lib/seo/structuredData";

/**
 * The site's JSON-LD, in the one shape a strict Content-Security-Policy will actually run.
 *
 * ## Why this needs the nonce, which is the whole reason it is a component
 *
 * `<script type="application/ld+json">` is a `<script>` ELEMENT, and CSP's `script-src`
 * governs script elements by their presence, not by whether the browser would execute
 * them. This app's policy is `script-src 'self' 'nonce-…'` with no `'unsafe-inline'`
 * (`lib/security/csp.ts`, ENFORCING since D-541), so an inline JSON-LD block with no nonce
 * is REFUSED by the browser and never reaches the parser — which is a defect with no
 * symptom at all on the page, and shows up only as structured data that a validator says
 * is absent. `middleware.ts` mints the nonce per request and forwards it on the request
 * headers as `x-nonce`; this reads it back the same way Next's own renderer does.
 *
 * ## Why it is a separate async component rather than code in `app/layout.tsx`
 *
 * `headers()` is async in Next 15, so reading it in the root layout would make
 * `RootLayout` an async function. That is legal and it is not free: the root layout is
 * read as SOURCE by `tests/copilotViewport.test.ts`, which asserts
 * `export default function RootLayout` in order to prove it is looking at the right file
 * before checking the viewport export. An async server component as a CHILD keeps that
 * true, and keeps the async boundary next to the thing that needs it.
 *
 * ## Site-wide rather than marketing-only
 *
 * `Organization` and `WebSite` are statements about the SITE, not about a page, so they
 * belong in the root layout — which is also the only place in this app that renders on
 * every realm without `tests/a11y.test.tsx` rendering it (that suite mounts each
 * `page.tsx` without its layout). The consoles are behind a session and disallowed in
 * `robots.txt`; nothing crawls them, and a duplicated site-level node would be harmless
 * if anything did.
 */
export async function StructuredData() {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  // `<` is escaped rather than the whole string being trusted: the one sequence that can
  // break out of a `<script>` block is a literal `</script>` inside it, and every value in
  // this document comes from `lib/legal/placeholders.ts` where a future value is a string
  // somebody typed. Escaping `<` costs nothing and closes the injection permanently — the
  // JSON is still valid, because `<` is a legal JSON escape.
  const json = JSON.stringify(siteJsonLd()).replace(/</g, "\\u003c");
  return (
    <script
      type="application/ld+json"
      nonce={nonce}
      // The only way to emit a script body in React. The content is `JSON.stringify` of an
      // object this repository builds — never user input, never an API response.
      dangerouslySetInnerHTML={{ __html: json }}
    />
  );
}
