import { describe, expect, it } from "vitest";

import {
  CSP_HEADER_NAME,
  CSP_REPORT_PATH,
  apiConnectOrigin,
  buildContentSecurityPolicy,
  mediaOrigin,
  reportingEndpointsHeader,
} from "@/lib/security/csp";

describe("the content-security policy", () => {
  const csp = buildContentSecurityPolicy("TESTNONCE", {
    apiOrigin: "https://api.calevate.tech",
    mediaOrigin: "https://store.calevate.tech",
  });

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

  it("admits the object store for media, because the recording player is cross-origin", () => {
    // THE ONE THING THE PRE-FLIP AUDIT FOUND (D-541). `<audio src>` is `media-src`, which
    // falls back to `default-src 'self'` when it is not declared, and the src is a
    // presigned URL on the OBJECT STORE's origin — so without this every call recording
    // is refused, silently, for every client.
    expect(csp).toContain("media-src 'self' https://store.calevate.tech");
  });

  it("fails closed to 'self' for media on a malformed object store origin", () => {
    expect(
      buildContentSecurityPolicy("N", { apiOrigin: "", mediaOrigin: mediaOrigin("not a url") }),
    ).toContain("media-src 'self';");
  });

  it("points violations at the collector, by both mechanisms", () => {
    // `report-uri` is deprecated and is still the only one some browsers implement;
    // `report-to` is what current Chromium-family browsers use and it IGNORES report-uri
    // when present, so nothing is double-reported. Emitting one loses half the audience.
    expect(csp).toContain(`report-uri https://api.calevate.tech${CSP_REPORT_PATH}`);
    expect(csp).toContain("report-to csp");
    expect(reportingEndpointsHeader("https://api.calevate.tech")).toBe(
      `csp="https://api.calevate.tech${CSP_REPORT_PATH}"`,
    );
  });

  it("drops report-to (never report-uri) when the collector is not https", () => {
    // The Reporting API ignores a non-secure endpoint, and a `report-to` group resolving
    // to nothing would suppress the `report-uri` a Chromium browser would have honoured.
    // Local dev is http, and must keep the one mechanism that works there.
    const local = buildContentSecurityPolicy("N", { apiOrigin: "http://localhost:8000" });
    expect(local).toContain("report-uri http://localhost:8000/reports/v1/csp");
    expect(local).not.toContain("report-to");
    expect(reportingEndpointsHeader("http://localhost:8000")).toBeNull();
  });

  it("emits no reporting directive at all when the api origin is unusable", () => {
    // Reporting to a relative path would post to the Next server, which serves no such
    // route: fail closed to no reporting rather than to a 404 loop.
    const broken = buildContentSecurityPolicy("N", { apiOrigin: "" });
    expect(broken).not.toContain("report-uri");
    expect(broken).not.toContain("report-to");
  });

  it("is ENFORCING (D-541)", () => {
    // It was report-only with no collector and no report directive, so the staged
    // rollout's exit condition — "once a real session shows no violations" — could never
    // be evaluated by anybody. The flip rests on the audit in the module docstring.
    expect(CSP_HEADER_NAME).toBe("Content-Security-Policy");
  });
});
