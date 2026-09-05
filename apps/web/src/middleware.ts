import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  CSP_HEADER_NAME,
  REPORTING_ENDPOINTS_HEADER_NAME,
  apiConnectOrigin,
  buildContentSecurityPolicy,
  mediaOrigin,
  reportingEndpointsHeader,
} from "@/lib/security/csp";

/**
 * Emits the Content-Security-Policy (ENFORCING since D-541) with a per-request nonce,
 * following Next.js's documented middleware pattern: the nonce is forwarded on the REQUEST
 * headers as `x-nonce` so Next stamps it onto its own framework scripts, and the same
 * policy is set on the RESPONSE so the browser enforces it. Next reads EITHER header name
 * off the request (`app-render.js:108`), so the enforce flip did not orphan the nonce.
 * See `lib/security/csp.ts` for the policy and the audit the flip rests on.
 *
 * `Reporting-Endpoints` rides alongside it: it is what maps the policy's `report-to csp`
 * group onto the collector's URL, and without it that directive names nothing. It is
 * omitted — and `report-to` with it — when the collector is not HTTPS, so a local http
 * API keeps `report-uri` as the whole mechanism instead of losing both.
 *
 * A fresh 128-bit nonce per request, base64 — `crypto.randomUUID()` is not enough entropy
 * for a CSP nonce and must not be reused across requests.
 */
export function middleware(request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.getRandomValues(new Uint8Array(16))).toString("base64");
  const apiOrigin = apiConnectOrigin();
  const csp = buildContentSecurityPolicy(nonce, {
    apiOrigin,
    mediaOrigin: mediaOrigin(),
    // Only in production: locally the dev server is plain HTTP and this directive would
    // force-upgrade every localhost request to https.
    upgradeInsecure: process.env.NODE_ENV === "production",
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set(CSP_HEADER_NAME, csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set(CSP_HEADER_NAME, csp);
  const reportingEndpoints = reportingEndpointsHeader(apiOrigin);
  if (reportingEndpoints) response.headers.set(REPORTING_ENDPOINTS_HEADER_NAME, reportingEndpoints);
  return response;
}

export const config = {
  // Every document, but not the static/image asset paths (which are immutable and served
  // without a nonce) or the favicon — matching Next's own recommended matcher so the nonce
  // is generated once per real navigation, not per asset.
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp)$).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
