/**
 * The Content-Security-Policy this app serves — built here as a PURE function so it can be
 * unit-tested without a request, and set by `src/middleware.ts` on every document response.
 *
 * ## Why this exists
 *
 * `infra/nginx/snippets/calevate-headers.conf` deliberately sets NO CSP, stating that it
 * belongs in the app tier "where the nonce is generated … not in a shared edge fragment."
 * That was the right call — but the app-tier CSP it deferred to never existed, leaving the
 * console (which renders other businesses' CRM data, call transcripts and LLM output) with
 * no second containment layer if an XSS foothold ever opened. This module is that layer.
 *
 * ## It is ENFORCING (D-541, 5 Sep 2026), and it was report-only until then
 *
 * The staged rollout this file used to describe had an exit condition nobody could ever
 * evaluate: it said the flip happens "once a real session shows no violations", and the
 * policy carried **no `report-uri` and no `report-to`**, with no collector anywhere in
 * `apps/api`. Violations went to no one. Report-Only was therefore buying neither
 * protection (it never blocks) nor information (nothing was listening) — the worst of the
 * two states, and it had been that way since the header shipped. The September 2026 audit
 * then demonstrated a reachable XSS (an uploaded file stored under an attacker-chosen
 * `Content-Type`, served to a reviewer through a presigned link — fixed twice over since,
 * at `kb/uploads.stored_content_type` and at `workers/storage.presigned_url`), which is
 * the second containment layer's whole job.
 *
 * So the flip was taken on EVIDENCE rather than on an observation window, and this is what
 * was checked against the live tree on 5 Sep 2026 rather than reasoned about:
 *
 * 1. **The nonce reaches Next's own inline scripts.** `middleware.ts` forwards it on the
 *    REQUEST headers, and Next 15.5.21 reads it back at
 *    `node_modules/next/dist/server/app-render/app-render.js:108` —
 *    `headers['content-security-policy'] || headers['content-security-policy-report-only']`
 *    — so BOTH header names work and renaming the constant below does not orphan the
 *    nonce. Its parser (`get-script-nonce-from-header.js:11`) accepts
 *    `/^'nonce-([A-Za-z0-9+/_-]+={0,2})'$/`, which admits the base64 of 16 random bytes
 *    that `middleware.ts` mints. No inline `<script>` and no `dangerouslySetInnerHTML`
 *    exists anywhere in `src` (grepped): the only script tag this app creates is
 *    `lib/razorpayCheckout.ts`, which sets `src` and no inline body.
 * 2. **Nothing is loaded from an origin the policy does not admit.** Every external URL in
 *    `src` is either a comment, a placeholder inside a `placeholder=`/example string, or
 *    Razorpay. Both fonts are `next/font/local` from `src/fonts` (`app/layout.tsx`), so
 *    they are served from `/_next/static/media` — `'self'`. Every image is a local
 *    `/brand/*` asset (`components/brand.tsx`). There is no analytics, no CDN, no map
 *    tile, no avatar host, no service worker, no web worker and no manifest.
 * 3. **`connect-src`.** The only cross-origin fetches this app makes are to the API:
 *    `lib/api/client.ts:645` and the copilot's streaming reader `lib/copilot/stream.ts:204`
 *    both build `${API_BASE}${path}`, and `API_BASE` is `NEXT_PUBLIC_API_BASE_URL` — the
 *    same value `apiConnectOrigin()` reads here. `lib/copilot/sse.ts` parses the stream
 *    from that same `fetch`; it does not open a second connection.
 * 4. **`media-src` WAS MISSING AND WOULD HAVE BROKEN CALL RECORDING PLAYBACK.** See the
 *    directive's own note below. This is the one thing the audit of the policy found, and
 *    it is fixed here rather than discovered in production.
 * 5. **`frame-src`** carries both Razorpay origins Checkout needs.
 *
 * ⚠ **WHAT IS NOT VERIFIED, and cannot be from here**: whether Razorpay Checkout's own
 * script pulls further subresources (its own analytics endpoint, a font, a second frame)
 * from origins this policy does not name. `razorpay.com` is egress-blocked from this
 * environment (403 on CONNECT, re-measured 25 Aug 2026) and their published integration
 * code — the only Razorpay source anybody here has read — shows the script tag and nothing
 * about what it then loads. **No origin has been invented to cover the gap.** It is
 * carried as an operator-attested input on OPERATIONS §2 gate 44, which is an ATTENDED
 * first payment: whoever runs it watches the browser console for a CSP refusal on the
 * checkout screen, and the collector (`apps/api/security/`) records any violation whether
 * they are watching or not.
 *
 * ## The directives, each with its reason
 *
 * - `script-src 'self' 'nonce-…' https://checkout.razorpay.com` — our own bundles are
 *   nonced by Next; the one external script is Razorpay Checkout
 *   (`lib/razorpayCheckout.ts::RAZORPAY_CHECKOUT_SRC`), injected from a click on one
 *   paying screen. No `'unsafe-inline'`, no `'strict-dynamic'` (an explicit host is more
 *   predictable to verify than dynamic propagation — and `'strict-dynamic'` would DISABLE
 *   the host allowlist, so the Razorpay entry would silently stop meaning anything).
 * - `'unsafe-eval'` IN DEVELOPMENT ONLY, and it is not a weakening of the shipped policy
 *   — it is the one thing that stops the enforce flip breaking `pnpm dev` for everyone.
 *   READ AT SOURCE in the installed Next 15.5.21:
 *   `node_modules/next/dist/esm/build/webpack/config/blocks/base.js:22-31` sets
 *   `config.devtool = 'eval-source-map'` whenever `ctx.isDevelopment`, which wraps every
 *   module in an `eval()`. Enforcing `script-src` without `'unsafe-eval'` therefore makes
 *   a dev server serve a blank screen, and `package.json`'s `dev` script is plain
 *   `next dev` (webpack, not `--turbopack`), so this is the path every developer takes.
 *   It is refused in a production build twice over: the caller only asks for it when
 *   `NODE_ENV === "development"`, and `buildContentSecurityPolicy` refuses the request
 *   outright when `NODE_ENV === "production"` — a flag that can be passed is a flag that
 *   will eventually be passed by mistake.
 * - `style-src 'self' 'unsafe-inline'` — Next and Tailwind inject inline `<style>`; a
 *   nonce for styles is not reliably supported and `'unsafe-inline'` on styles alone does
 *   not grant script execution. A documented, bounded tradeoff, DELIBERATELY NOT tightened
 *   in the same change as the enforce flip: one change, one risk.
 * - `connect-src 'self' <api origin>` — the console (admin./app.) calls the API on a
 *   sibling subdomain (`NEXT_PUBLIC_API_BASE_URL`); XHR/fetch to anywhere else is refused.
 * - `media-src 'self' <object store origin>` — **call recording playback**. The player
 *   (`components/callAudioPlayer.tsx`) puts a SHORT-LIVED PRESIGNED URL into an `<audio
 *   src>`, and that URL points at the OBJECT STORE's origin, not ours
 *   (`apps/workers/storage.py::presigned_url` says so in those words). `media-src` is not
 *   declared by `default-src`'s absence — it FALLS BACK to `default-src 'self'` — so
 *   enforcing this policy without this directive would have refused every recording on
 *   `/c/{slug}/calls/{callId}`, silently, for every client. That is the breakage this
 *   audit was for.
 * - `frame-src` Razorpay — Checkout renders its own iframe inside our page.
 * - `frame-ancestors 'none'` — clickjacking (belt-and-braces with the edge `X-Frame-Options`).
 * - `object-src 'none'`, `base-uri 'none'`, `form-action 'self'` — kill the plugin, base-tag
 *   and form-exfiltration vectors that a bare `default-src` does not.
 * - `report-uri` AND `report-to` — both, on purpose. See `reportingEndpointsHeader`.
 */

const RAZORPAY_CHECKOUT_ORIGIN = "https://checkout.razorpay.com";
const RAZORPAY_API_ORIGIN = "https://api.razorpay.com";

/** The collector's path in `apps/api` (`apps/api/security/routes.py`). One spelling. */
export const CSP_REPORT_PATH = "/reports/v1/csp";

/**
 * The `Reporting-Endpoints` group name. Arbitrary but stable: it is the token `report-to`
 * names, and the two must agree or reports go nowhere.
 */
export const CSP_REPORT_GROUP = "csp";

/** The header that maps `report-to`'s group name onto a URL. */
export const REPORTING_ENDPOINTS_HEADER_NAME = "Reporting-Endpoints";

/** The origin (scheme+host[:port]) the browser is allowed to call for the API, from the
 *  same env the API client reads. Only the ORIGIN is kept — a path in `connect-src` is
 *  meaningless. Falls back to the client's own local default so dev is not broken. */
export function apiConnectOrigin(
  apiBaseUrl: string | undefined = process.env.NEXT_PUBLIC_API_BASE_URL,
): string {
  const raw = apiBaseUrl?.trim() || "http://localhost:8000";
  try {
    return new URL(raw).origin;
  } catch {
    // A malformed env value must not silently widen the policy to everything; fall back to
    // 'self' only (the API on the same origin still works; a cross-origin API would report).
    return "";
  }
}

/**
 * The origin `media-src` admits, from the object store the presigned recording links point
 * at (`NEXT_PUBLIC_MEDIA_ORIGIN`, whose server-side twin is `OBJECT_STORE_ENDPOINT`).
 *
 * Same fail-closed shape as `apiConnectOrigin`: an unparseable value narrows to `'self'`
 * rather than widening the policy. It is a SEPARATE variable rather than derived from the
 * API base because the two are unrelated hosts — the store may be S3, R2 or a local MinIO
 * — and guessing one from the other is how a policy quietly stops matching the deployment.
 */
export function mediaOrigin(
  rawValue: string | undefined = process.env.NEXT_PUBLIC_MEDIA_ORIGIN,
): string {
  const raw = rawValue?.trim() || "http://localhost:9000";
  try {
    return new URL(raw).origin;
  } catch {
    return "";
  }
}

/** The absolute URL the browser posts violation reports to, or "" when the API origin is
 *  unusable — in which case NO reporting directive is emitted at all. Reporting to a
 *  relative path would post to the Next server, which serves no such route. */
export function cspReportUri(apiOrigin: string): string {
  return apiOrigin ? `${apiOrigin}${CSP_REPORT_PATH}` : "";
}

/**
 * The value for the `Reporting-Endpoints` response header, or `null` when there is none to
 * emit. `middleware.ts` sets it beside the policy.
 *
 * WHY BOTH `report-to` AND `report-uri`, which is a duplication on purpose.
 * `report-uri` is deprecated in the spec and is still the ONLY mechanism some shipping
 * browsers implement; `report-to` (with this header) is what current Chromium-family
 * browsers use, and a browser that understands `report-to` IGNORES `report-uri`, so
 * nothing is double-reported. Emitting only the modern one loses the older half of the
 * audience — including Safari, whose `report-to` support is partial — and emitting only
 * the legacy one is a deprecation we would have to come back to.
 * (REPORTED, corroborated across independent secondaries, 5 Sep 2026: MDN's `report-to`
 * and `Reporting-Endpoints` pages are egress-blocked from this container, so this is not
 * a primary reading. The two collector shapes below are the same class, and the collector
 * accepts BOTH rather than betting on either.)
 *
 * `null` when the endpoint is not HTTPS: the Reporting API ignores a non-secure endpoint,
 * and a `report-to` group that resolves to nothing would suppress the `report-uri` a
 * Chromium browser would otherwise have honoured. On a local `http://` API that leaves
 * `report-uri` as the whole mechanism, which is exactly what dev needs.
 */
export function reportingEndpointsHeader(apiOrigin: string): string | null {
  const uri = cspReportUri(apiOrigin);
  if (!uri.startsWith("https://")) return null;
  return `${CSP_REPORT_GROUP}="${uri}"`;
}

/** The full policy string for one request's `nonce`. Pure — no globals beyond the
 *  env-derived origins, which the caller may pass explicitly (the tests do). */
export function buildContentSecurityPolicy(
  nonce: string,
  opts: {
    apiOrigin?: string;
    mediaOrigin?: string;
    upgradeInsecure?: boolean;
    /** See `'unsafe-eval'` in the docstring. Ignored outright in a production build. */
    devEval?: boolean;
  } = {},
): string {
  const apiOrigin = opts.apiOrigin ?? apiConnectOrigin();
  const media = opts.mediaOrigin ?? mediaOrigin();
  const connect = ["'self'", apiOrigin].filter(Boolean).join(" ");
  const mediaSources = ["'self'", media].filter(Boolean).join(" ");
  // The second of the two refusals: asking for it in production does not get it.
  const evalSource = opts.devEval && process.env.NODE_ENV !== "production" ? " 'unsafe-eval'" : "";
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}'${evalSource} ${RAZORPAY_CHECKOUT_ORIGIN}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src ${connect}`,
    `media-src ${mediaSources}`,
    `frame-src ${RAZORPAY_CHECKOUT_ORIGIN} ${RAZORPAY_API_ORIGIN}`,
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ];
  if (opts.upgradeInsecure) directives.push("upgrade-insecure-requests");
  const reportUri = cspReportUri(apiOrigin);
  if (reportUri) {
    directives.push(`report-uri ${reportUri}`);
    if (reportingEndpointsHeader(apiOrigin) !== null) {
      directives.push(`report-to ${CSP_REPORT_GROUP}`);
    }
  }
  return directives.join("; ");
}

/** The header name. ENFORCING since D-541 — the policy above was audited directive by
 *  directive against the live tree on 5 Sep 2026 (the module docstring lists what was
 *  checked and how, and names the one gap that is attested by a human instead). Reverting
 *  to `-Report-Only` is a one-line change if an enforced policy ever has to be stood down
 *  in a hurry; it is not the normal way to fix a violation, which is to fix the policy. */
export const CSP_HEADER_NAME = "Content-Security-Policy";
