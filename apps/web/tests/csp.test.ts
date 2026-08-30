import { describe, expect, it } from "vitest";

import {
  CSP_HEADER_NAME,
  apiConnectOrigin,
  buildContentSecurityPolicy,
} from "@/lib/security/csp";

describe("the content-security policy", () => {
  const csp = buildContentSecurityPolicy("TESTNONCE", { apiOrigin: "https://api.calevate.tech" });

  it("carries the per-request nonce in script-src and forbids inline script", () => {
    expect(csp).toContain("script-src 'self' 'nonce-TESTNONCE' https://checkout.razorpay.com");
    // No 'unsafe-inline' / 'unsafe-eval' on scripts — the whole point of the nonce.
    const scriptSrc = csp.split(";").find((d) => d.trim().startsWith("script-src")) ?? "";
    expect(scriptSrc).not.toContain("unsafe-inline");
    expect(scriptSrc).not.toContain("unsafe-eval");
  });

  it("locks the vectors a bare default-src leaves open", () => {
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).toContain("form-action 'self'");
  });

  it("allows the API origin (and only it) for connect, and Razorpay for the checkout frame", () => {
    expect(csp).toContain("connect-src 'self' https://api.calevate.tech");
    expect(csp).toContain("frame-src https://checkout.razorpay.com https://api.razorpay.com");
  });

  it("keeps only the ORIGIN of the API base url, never a path", () => {
    expect(apiConnectOrigin("https://api.calevate.tech/v1/whatever")).toBe(
      "https://api.calevate.tech",
    );
  });

  it("fails closed to no cross-origin connect on a malformed api base url", () => {
    // A broken env value must narrow to 'self', never widen the policy.
    expect(buildContentSecurityPolicy("N", { apiOrigin: apiConnectOrigin("not a url") })).toContain(
      "connect-src 'self';",
    );
  });

  it("adds upgrade-insecure-requests only in production", () => {
    expect(buildContentSecurityPolicy("N", { upgradeInsecure: true })).toContain(
      "upgrade-insecure-requests",
    );
    expect(buildContentSecurityPolicy("N", { upgradeInsecure: false })).not.toContain(
      "upgrade-insecure-requests",
    );
  });

  it("ships report-only until a real session confirms no violations", () => {
    // Guards the deliberate staged rollout: enforce is a one-line flip of this constant.
    expect(CSP_HEADER_NAME).toBe("Content-Security-Policy-Report-Only");
  });
});
