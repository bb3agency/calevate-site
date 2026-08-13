import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminSignInPage from "@/app/(auth)/admin/sign-in/[[...sign-in]]/page";
import Home from "@/app/page";
import ClientSignInPage from "@/app/(auth)/sign-in/[[...sign-in]]/page";
import ClientSignUpPage from "@/app/(auth)/sign-up/[[...sign-up]]/page";
import { adminSession } from "@/lib/api/admin";
import { apiRequest, AuthProblem, devSession, devToken } from "@/lib/api/client";
import { clientRealmSession } from "@/lib/auth/clientRealm";
import { AUTH_MODE_ENV, AuthConfigError, resolveAuthMode } from "@/lib/auth/mode";

import { stubApi } from "./harness";

/**
 * The browser's half of authentication — which credential this build presents, and what
 * it does when it cannot get one.
 *
 * The API has always been able to verify a real Clerk session (`core/auth.py`); the
 * browser could only mint `dev:<realm>:<user>` from an environment variable, and there
 * was no sign-in route to reach. Wiring Clerk in creates exactly one way to get this
 * catastrophically wrong, and it is the subject of most of this file: a deployment
 * configured for Clerk that quietly falls back to a dev token. `_verify_dev_token`
 * accepts those whenever the API is running with `APP_ENV=local` — which is the DEFAULT
 * of `Settings.app_env`, as its own docstring warns — so the fallback would authenticate
 * a stranger as any user id they typed, and hard rule 1 turns that into a cross-tenant
 * read of other businesses' data.
 *
 * The rest asserts the realm separation TRD §11 requires, at the one place the two
 * realms are observable from a test: the bearer token that reaches `fetch`.
 */

describe("which credential this build presents", () => {
  /**
   * The whole decision table. It is written out rather than generated because each row
   * is a deployment somebody will actually create, and the interesting ones are the
   * mistakes — a forgotten variable and a typo'd one.
   */
  it("takes an explicit mode at its word outside a production build", () => {
    expect(resolveAuthMode("clerk", false)).toBe("clerk");
    expect(resolveAuthMode("dev", false)).toBe("dev");
    expect(resolveAuthMode(" dev ", false)).toBe("dev");
  });

  it("reads an UNSET variable as dev locally and as clerk in a production build", () => {
    // Locally the variable is unset on every developer's machine and dev tokens are what
    // they want. In a production build the same absence is a forgotten variable, and the
    // safe reading of a forgotten variable is the one that cannot sign anybody in by
    // itself.
    expect(resolveAuthMode(undefined, false)).toBe("dev");
    expect(resolveAuthMode("", false)).toBe("dev");
    expect(resolveAuthMode(undefined, true)).toBe("clerk");
    expect(resolveAuthMode("", true)).toBe("clerk");
  });

  it("NEVER resolves to dev in a production build, even when asked to", () => {
    // THE auth-bypass case. Asking for dev tokens in a production build is refused at
    // module initialisation, which happens during `next build` — so this is a failed
    // build rather than a live deployment handing out `dev:client:<anything>`.
    expect(() => resolveAuthMode("dev", true)).toThrow(AuthConfigError);
    expect(() => resolveAuthMode("dev", true)).toThrow(/production build/);
  });

  it("refuses a mode it does not recognise instead of guessing", () => {
    // `=production` and `=true` are both reasonable guesses at the name. One of the two
    // possible guesses back is an auth bypass, so it guesses neither.
    // Surrounding whitespace is forgiven (an `.env` line ends up with it) — a different
    // WORD is not.
    for (const value of ["production", "true", "CLERK", "prod", "1", "clerk;dev"]) {
      expect(() => resolveAuthMode(value, false), value).toThrow(AuthConfigError);
    }
    expect(() => resolveAuthMode("production", false)).toThrow(new RegExp(AUTH_MODE_ENV));
  });
});

describe("the local credential", () => {
  it("is realm-tagged, so a client token cannot pass as an admin one", async () => {
    // `_verify_dev_token` checks the realm segment before anything else, which is why
    // the two realms must build different strings rather than one string plus a header.
    expect(await devToken("client", "user_x")()).toBe("dev:client:user_x");
    expect(await devToken("admin", "op_x")()).toBe("dev:admin:op_x");
  });

  it("is refused outright in a production build, whatever the mode said", async () => {
    // The SECOND guard. `resolveAuthMode` already refuses to reach this path in a
    // production build; this is the credential itself refusing, so a future refactor
    // that mis-wires the mode cannot silently re-open the bypass. Asserted through a
    // fresh module graph because both guards read `NODE_ENV` at import time.
    vi.stubEnv("NODE_ENV", "production");
    vi.resetModules();
    try {
      const fresh = await import("@/lib/api/client");
      // No React is involved in this module, so a second copy of the graph is harmless
      // here — unlike the component tests, which say why they cannot do this.
      expect(() => fresh.devToken("client", "user_x")()).toThrow(fresh.AuthProblem);
      expect(() => fresh.devToken("client", "user_x")()).toThrow(/never valid here/);
    } finally {
      vi.unstubAllEnvs();
      vi.resetModules();
    }
  });
});

describe("a refusal the browser produced itself", () => {
  it("carries the API's error shape so every screen can already render it", () => {
    const problem = new AuthProblem("auth_not_configured", "No key.", "Set the key.");
    // `status: 0` says plainly that no HTTP response happened — nothing here claims the
    // server spoke.
    expect(problem.status).toBe(0);
    expect(problem.code).toBe("auth_not_configured");
    expect(problem.remediation).toBe("Set the key.");
    // Not retryable: a missing environment variable does not fix itself on the second
    // attempt, and `app/providers.tsx` keys its retry policy off exactly this flag.
    expect(problem.retryable).toBe(false);
  });
});

describe("the token that reaches the wire", () => {
  const ME = { organization: { name: "Acme", slug: "acme" }, role: "owner" };

  it("is the client realm's for a client-realm session", async () => {
    const calls = stubApi({ "/v1/me": ME });
    await apiRequest(clientRealmSession("acme"), "/v1/me");
    expect(calls[0].headers.Authorization).toMatch(/^Bearer dev:client:/);
    expect(calls[0].headers["X-Org-Slug"]).toBe("acme");
  });

  it("is the admin realm's for an admin session, and carries no org", async () => {
    const calls = stubApi({ "/v1/admin/tenants": [] });
    await apiRequest(adminSession(), "/v1/admin/tenants");
    expect(calls[0].headers.Authorization).toMatch(/^Bearer dev:admin:/);
  });

  it("is resolved per request, not captured when the session was built", async () => {
    // A Clerk session token lives about sixty seconds and the console polls for hours,
    // so a session object that carried a STRING would go stale in a tab left open. The
    // observable version of that promise: the source is consulted on every call.
    let asked = 0;
    const session = {
      token: () => {
        asked += 1;
        return `dev:client:user_${asked}`;
      },
      orgSlug: "acme",
    };
    const calls = stubApi({ "/v1/me": ME });
    await apiRequest(session, "/v1/me");
    await apiRequest(session, "/v1/me");
    expect(asked).toBe(2);
    expect(calls[0].headers.Authorization).toBe("Bearer dev:client:user_1");
    expect(calls[1].headers.Authorization).toBe("Bearer dev:client:user_2");
  });

  it("never reaches fetch when the credential is refused", async () => {
    // The failure this file exists for, seen from the transport: a refusal must abort
    // the request, not decorate it. `Bearer undefined` would be a request the API
    // answers 401 to, which reads to an operator like an expired session rather than a
    // misconfigured deployment.
    const calls = stubApi({ "/v1/me": ME });
    const refusing = {
      token: () => {
        throw new AuthProblem("not_signed_in", "Not signed in.", "Sign in at /sign-in.");
      },
      orgSlug: "acme",
    };
    await expect(apiRequest(refusing, "/v1/me")).rejects.toBeInstanceOf(AuthProblem);
    expect(calls).toEqual([]);
  });

  it("keeps devSession as the local client path", async () => {
    // Named in this suite because the whole 300-test frontend runs through it: the local
    // path survived the Clerk integration rather than being replaced by it.
    const calls = stubApi({ "/v1/me": ME });
    await apiRequest(devSession("acme"), "/v1/me");
    expect(calls[0].headers.Authorization).toMatch(/^Bearer dev:client:/);
  });
});

describe("the doors a person can actually reach", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /**
   * These render in `dev` mode, which is what the suite runs in — so what they assert is
   * that the routes EXIST, render a real screen, and make no API call. The Clerk card
   * itself cannot be exercised offline: mounting `<ClerkProvider>` loads clerk-js from
   * Clerk's CDN, and a test that stubbed that out would be asserting the stub's opinion
   * of a sign-in form. What is testable here is that no route is a 404 and that a local
   * build says what it is instead of showing a form with nothing behind it.
   */
  it("has a client-realm sign-in route that explains a local build", () => {
    const calls = stubApi({});
    const { container } = render(<ClientSignInPage />);
    expect(container.textContent).toContain("Local development build");
    expect(calls).toEqual([]);
  });

  it("has a client-realm sign-up route", () => {
    const calls = stubApi({});
    const { container } = render(<ClientSignUpPage />);
    expect(container.textContent).toContain("Local development build");
    expect(calls).toEqual([]);
  });

  it("has an admin-realm sign-in route, and offers no way to create an operator account", () => {
    const calls = stubApi({});
    const { container } = render(<AdminSignInPage />);
    expect(container.textContent).toContain("Local development build");
    // D-37: the admin realm is invite-only with signup disabled. A "create an account"
    // affordance on the operator console would be a door that must stay shut.
    expect(container.textContent).not.toMatch(/create an account|sign up/i);
    expect(calls).toEqual([]);
  });

  it("gives a returning client somewhere to click from the front page", () => {
    // The landing page named `/c/your-slug` and stopped, because there was no sign-in
    // route to point at. There is one now, and an unlinked route is not a door.
    stubApi({});
    render(<Home />);
    expect(screen.getByRole("link", { name: /Sign in/i }).getAttribute("href")).toBe("/sign-in");
  });
});
