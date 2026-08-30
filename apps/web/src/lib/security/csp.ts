/**
 * The Content-Security-Policy this app serves — built here as a PURE function so it can be
 * unit-tested without a request, and set by `src/middleware.ts` on every document response.
 *
 * ## Why this exists, and why REPORT-ONLY first
 *
 * `infra/nginx/snippets/calevate-headers.conf` deliberately sets NO CSP, stating that it
 * belongs in the app tier "where the nonce is generated … not in a shared edge fragment."
 * That was the right call — but the app-tier CSP it deferred to never existed, leaving the
 * console (which renders other businesses' CRM data, call transcripts and LLM output) with
 * no second containment layer if an XSS foothold ever opened. This module is that layer.
 *
 * It is emitted as `Content-Security-Policy-Report-Only` (see `middleware.ts`), NOT enforcing,
 * on purpose: a wrong CSP white-screens a live client's dashboard, and a strict nonce policy
 * cannot be fully verified without loading the real production build in a browser. Report-Only
 * NEVER blocks — it only surfaces violations — so it ships with zero breakage risk, proves the
 * nonce wiring against real traffic, and the enforce-flip is then a one-line change (the header
 * name in `middleware.ts`). This is the standard staged CSP rollout, not a half-measure: the
 * policy itself is the final one.
 *
 * ## The directives, each with its reason
 *
 * - `script-src 'self' 'nonce-…' https://checkout.razorpay.com` — our own bundles are nonced
 *   by Next (the nonce is forwarded via the request header in `middleware.ts`); the one
 *   external script is Razorpay Checkout (`lib/razorpayCheckout.ts::RAZORPAY_CHECKOUT_SRC`),
 *   injected from a click on one paying screen. No `'unsafe-inline'`, no `'strict-dynamic'`
 *   (an explicit host is more predictable to verify than dynamic propagation).
 * - `style-src 'self' 'unsafe-inline'` — Next and Tailwind inject inline `<style>`; a nonce
 *   for styles is not reliably supported and `'unsafe-inline'` on styles alone does not grant
 *   script execution. A documented, bounded tradeoff.
 * - `connect-src 'self' <api origin>` — the console (admin./app.) calls the API on a sibling
 *   subdomain (`NEXT_PUBLIC_API_BASE_URL`); XHR/fetch to anywhere else is refused.
 * - `frame-src` Razorpay — Checkout renders its own iframe inside our page.
 * - `frame-ancestors 'none'` — clickjacking (belt-and-braces with the edge `X-Frame-Options`).
 * - `object-src 'none'`, `base-uri 'none'`, `form-action 'self'` — kill the plugin, base-tag
 *   and form-exfiltration vectors that a bare `default-src` does not.
 */

const RAZORPAY_CHECKOUT_ORIGIN = "https://checkout.razorpay.com";
const RAZORPAY_API_ORIGIN = "https://api.razorpay.com";

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

/** The full policy string for one request's `nonce`. Pure — no globals beyond the env-derived
 *  API origin, which the caller may pass explicitly (the test does). */
export function buildContentSecurityPolicy(
  nonce: string,
  opts: { apiOrigin?: string; upgradeInsecure?: boolean } = {},
): string {
  const apiOrigin = opts.apiOrigin ?? apiConnectOrigin();
  const connect = ["'self'", apiOrigin].filter(Boolean).join(" ");
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' ${RAZORPAY_CHECKOUT_ORIGIN}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src ${connect}`,
    `frame-src ${RAZORPAY_CHECKOUT_ORIGIN} ${RAZORPAY_API_ORIGIN}`,
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ];
  if (opts.upgradeInsecure) directives.push("upgrade-insecure-requests");
  return directives.join("; ");
}

/** The header name. A single flip of this constant (drop `-Report-Only`) turns the policy
 *  from observed to enforced, once a real session shows no violations. */
export const CSP_HEADER_NAME = "Content-Security-Policy-Report-Only";
