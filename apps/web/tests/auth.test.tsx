import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import { adminSession } from "@/lib/api/admin";
import { apiRequest, AuthProblem, devSession, devToken } from "@/lib/api/client";
import { CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";
import { AUTH_MODE_ENV, AuthConfigError, resolveAuthMode } from "@/lib/authn/mode";
import { clientRealmSession } from "@/lib/authn/realmSessions";

import { stubApi } from "./harness";

/**
 * The browser's half of authentication — which credential this build presents, and what
 * it does when it cannot get one.
 *
 * D-177 removed the vendor, so the two modes are `session` and `dev`. That changed the
 * SPELLING and not the danger, which is why almost every assertion below survived it: a
 * deployment that quietly falls back to a dev token authenticates a stranger as any
 * subject id they type, on any API still running with `APP_ENV=local`, and hard rule 1
 * turns that into a cross-tenant read of other businesses' data. Two independent guards
 * refuse it — the mode and the credential builder — and both are exercised here.
 *
 * What is NOT here any more: the three Clerk sign-in/sign-up route tests. Those pages are
 * deleted, their successors are `app/(auth)/auth/**`, and `tests/authnScreens.test.tsx`
 * and `tests/authnGuards.test.tsx` own them — with far more than "the route is not a 404",
 * because the screens are ours to test now rather than a vendor's iframe.
 */

describe("which credential this build presents", () => {
  /**
   * The whole decision table. It is written out rather than generated because each row
   * is a deployment somebody will actually create, and the interesting ones are the
   * mistakes — a forgotten variable and a typo'd one.
   */
  it("takes an explicit mode at its word outside a production build", () => {
    expect(resolveAuthMode("session", false)).toBe("session");
    expect(resolveAuthMode("dev", false)).toBe("dev");
    expect(resolveAuthMode(" dev ", false)).toBe("dev");
  });

  it("reads an UNSET variable as dev locally and as session in a production build", () => {
    // Locally the variable is unset on every developer's machine and dev tokens are what
    // they want. In a production build the same absence is a forgotten variable, and the
    // safe reading of a forgotten variable is the one that cannot sign anybody in by
    // itself — `session` constructs no credential at all, it relies on a cookie only a
    // completed sign-in can produce.
    expect(resolveAuthMode(undefined, false)).toBe("dev");
    expect(resolveAuthMode("", false)).toBe("dev");
    expect(resolveAuthMode(undefined, true)).toBe("session");
    expect(resolveAuthMode("", true)).toBe("session");
  });

  it("NEVER resolves to dev in a production build, even when asked to", () => {
    // THE auth-bypass case. Asking for dev tokens in a production build is refused at
    // module initialisation, which happens during `next build` — so this is a failed
    // build rather than a live deployment handing out `dev:client:<anything>`.
    expect(() => resolveAuthMode("dev", true)).toThrow(AuthConfigError);
    expect(() => resolveAuthMode("dev", true)).toThrow(/production build/);
  });

  it("refuses a mode it does not recognise instead of guessing", () => {
    // `=production` and `=true` are both reasonable guesses at the name; so, now, is
    // `=clerk`, which is what every deployment configured before D-177 has written down.
    // One of the possible guesses back is an auth bypass, so it guesses none of them —
    // and a stale `clerk` fails the build loudly rather than resolving to anything.
    // Surrounding whitespace is forgiven (an `.env` line ends up with it) — a different
    // WORD is not.
    for (const value of ["production", "true", "clerk", "SESSION", "prod", "1", "session;dev"]) {
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

describe("the credential that reaches the wire", () => {
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

  it("sends NO Authorization header when the session has no token source", async () => {
    // THE DEPLOYED CASE (D-177). The credential is the realm's `HttpOnly` cookie, which
    // the browser attaches and no script can read, so there is nothing for this code to
    // put in a header — and an empty `Bearer ` would be a malformed credential the API is
    // obliged to refuse before it ever looks at the cookie, turning a signed-in user into
    // a 401 nobody can explain.
    const calls = stubApi({ "/v1/me": ME });
    await apiRequest({ orgSlug: "acme" }, "/v1/me");
    expect(calls[0].headers.Authorization).toBeUndefined();
    expect(calls[0].headers["X-Org-Slug"]).toBe("acme");
  });

  it("is resolved per request, not captured when the session was built", async () => {
    // The console polls for hours, so a session object that carried a STRING would go
    // stale in a tab left open. The observable version of that promise: the source is
    // consulted on every call.
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
        throw new AuthProblem("not_signed_in", "Not signed in.", "Sign in at /auth/sign-in.");
      },
      orgSlug: "acme",
    };
    await expect(apiRequest(refusing, "/v1/me")).rejects.toBeInstanceOf(AuthProblem);
    expect(calls).toEqual([]);
  });

  it("keeps devSession as the local client path", async () => {
    // Named in this suite because the whole frontend suite runs through it: the local
    // path survived both the Clerk integration and its removal.
    const calls = stubApi({ "/v1/me": ME });
    await apiRequest(devSession("acme"), "/v1/me");
    expect(calls[0].headers.Authorization).toMatch(/^Bearer dev:client:/);
  });
});

describe("the doors a person can actually reach", () => {
  it("gives a returning client somewhere to click from the front page", () => {
    // The landing page named `/c/your-slug` and stopped, because there was no sign-in
    // route to point at. There is one now, and an unlinked route is not a door.
    stubApi({});
    render(<Home />);
    // `getAllBy`, not `getBy`: the redesigned page offers the door twice on purpose —
    // once in the sticky header, where a returning client looks first, and once in the
    // "Already a client" card beside the workspace URL. The property this test exists
    // for is that a returning client HAS a door and it points somewhere real, not that
    // there is exactly one of them.
    const doors = screen.getAllByRole("link", { name: /Sign in/i });
    expect(doors.length).toBeGreaterThan(0);
    for (const door of doors) {
      // The FIRST-PARTY sign-in page. `/sign-in` was Clerk's hosted route and is a 404
      // since D-177, so a stale href here would be the landing page's one call to action
      // pointing at nothing.
      expect(door.getAttribute("href")).toBe(CLIENT_SIGN_IN_PATH);
    }
  });
});
