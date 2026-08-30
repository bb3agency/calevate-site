import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  CSP_HEADER_NAME,
  apiConnectOrigin,
  buildContentSecurityPolicy,
} from "@/lib/security/csp";

/**
 * Emits the Content-Security-Policy (report-only) with a per-request nonce, following
 * Next.js's documented middleware CSP pattern: the nonce is forwarded on the REQUEST
 * headers as `x-nonce` so Next stamps it onto its own framework scripts, and the same
 * policy is set on the RESPONSE so the browser observes it. See `lib/security/csp.ts` for
 * the policy and why it is report-only for now.
 *
 * A fresh 128-bit nonce per request, base64 — `crypto.randomUUID()` is not enough entropy
 * for a CSP nonce and must not be reused across requests.
 */
export function middleware(request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.getRandomValues(new Uint8Array(16))).toString("base64");
  const csp = buildContentSecurityPolicy(nonce, {
    apiOrigin: apiConnectOrigin(),
    // Only in production: locally the dev server is plain HTTP and this directive would
    // force-upgrade every localhost request to https.
    upgradeInsecure: process.env.NODE_ENV === "production",
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set(CSP_HEADER_NAME, csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set(CSP_HEADER_NAME, csp);
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
