import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import AdminLayout from "@/app/admin/layout";
import { ADMIN_ME_PATH } from "@/app/admin/access";
import { HOLDS_PATH } from "@/lib/api/holds";
import { adminAuthn, ADMIN_SIGN_IN_PATH } from "@/lib/authn/adminAuthn";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The operator console's front door.
 *
 * `app/admin/layout.tsx` wrapped the whole console in `Providers` and nothing else, so
 * against a deployed API every screen under `/admin` answered its own refusal — a wall of
 * "you are not signed in" with no redirect to a sign-in page that existed. D-174 built the
 * pages; D-177 is what put the realm's own provider and gate above the console, and this
 * file is what says the gate is really in the tree.
 *
 * Three properties, and the last two are the ones a fix could break rather than the defect:
 *
 * 1. **The gate is fail-CLOSED.** `ready` is the only status that paints the console. A
 *    signed-out restore replaces the surface rather than decorating it, so there is no
 *    half-working state where the shell polls `/v1/admin/*` behind a panel saying nobody
 *    is signed in.
 * 2. **It is the ADMIN realm's session, never the client realm's.** The two session
 *    modules import each other never, and the shell's own two queries are the observable
 *    proof of which one is under it.
 * 3. **A local run is untouched.** The repo runs with `ENGINE=fake` and a dev credential;
 *    `lib/authn/mode.ts` resolves an unset `NEXT_PUBLIC_AUTH_MODE` outside a production
 *    build to `dev`, and the restore call answers from that credential exactly as it
 *    answers from a cookie. If that regressed, every admin suite in this directory would
 *    go red at once; this file makes the property the subject rather than an inference.
 */

const OPERATOR = { role: "operator", permissions: ["admin:read", "admin:impersonate"] };

/** What a restored, fully authenticated operator session looks like on the wire. */
const LIVE_SESSION = {
  realm: "admin",
  subject_id: "018f0000-0000-7000-8000-000000000001",
  mfa_complete: true,
  email_verified: true,
};

/** Everything the shell itself asks for on mount, before any page under it. */
const SESSION_ROUTE = "GET /v1/auth/admin/session";
const SESSION_PATH = "/v1/auth/admin/session";

const SHELL_ROUTES: Routes = {
  [SESSION_ROUTE]: LIVE_SESSION,
  [ADMIN_ME_PATH]: OPERATOR,
  [HOLDS_PATH]: [],
};

function renderShell(routes: Routes = SHELL_ROUTES) {
  const calls = stubApi(routes);
  const result = render(
    <AdminLayout>
      <p>console body</p>
    </AdminLayout>,
  );
  return Object.assign(result, { calls });
}

beforeEach(() => {
  adminAuthn.reset();
});

describe("the console behind a live operator session", () => {
  it("renders the shell once the restore answers", async () => {
    const { container } = renderShell();
    await act(async () => {});

    expect(container.textContent).toContain("console body");
    // The shell's own furniture, so this cannot pass by rendering a bare fragment.
    expect(container.textContent).toContain("Cross-client · every action is audited");
  });

  it("keeps speaking the admin realm's credential, never the client realm's", async () => {
    // `_verify_dev_token` checks the realm segment first, so a client token on an admin
    // surface is not a weak admin token — it is not a token at all. The shell's own two
    // queries are the observable proof that the session helper under it is still
    // `adminRealmSession`.
    const { calls } = renderShell();
    await act(async () => {});

    const paths = calls.map((c) => c.path);
    expect(paths).toContain(ADMIN_ME_PATH);
    expect(paths).toContain(HOLDS_PATH);
    for (const call of calls) {
      if (call.path === SESSION_PATH) continue;
      expect(call.headers.Authorization, call.path).toMatch(/^Bearer dev:admin:/);
    }
  });
});

describe("the console with no session", () => {
  it("is REPLACED by the gate, and asks the API for nothing else", async () => {
    /**
     * The assertion that fails if the layout is not gated at all.
     *
     * A 401 from the restore is the ordinary signed-out answer, and what must follow is
     * the gate INSTEAD of the console — not beside it. The console polling `/v1/admin/*`
     * on behalf of somebody who is by definition not authenticated is the wall of
     * refusals this whole slice removes.
     */
    const { container, calls } = renderShell({
      [SESSION_ROUTE]: problem(401, {
        type: "urn:calevate:auth/unauthorized",
        title: "Unauthorized",
        detail: "Your session is not valid.",
        kind: "auth",
      }),
    });
    await act(async () => {});

    expect(container.textContent).not.toContain("console body");
    expect(container.textContent).not.toContain("Cross-client · every action is audited");
    // The restore itself, and nothing behind it.
    expect(calls.map((c) => c.path)).toEqual([SESSION_PATH]);
  });
});

describe("the door the console redirects to", () => {
  it("is outside this layout, so the gate cannot loop", () => {
    /**
     * The gate sends a signed-out operator to `ADMIN_SIGN_IN_PATH`, and that page lives
     * in `app/(auth)/auth/admin/`, NOT in `app/admin/`: a route group is invisible to the
     * router but decides which layouts wrap a page, so the sign-in page is not wrapped by
     * the layout that redirects to it. Wrapped, it would be an infinite redirect — signed
     * out, redirect to sign-in, still signed out, redirect again.
     *
     * Asserted as a URL fact because that is the part a future move of the file would
     * break silently; `tests/authnScreens.test.tsx` covers what the page renders.
     */
    expect(ADMIN_SIGN_IN_PATH).toBe("/auth/admin/sign-in");
    expect(ADMIN_SIGN_IN_PATH.startsWith("/admin")).toBe(false);

    stubApi(SHELL_ROUTES);
    render(
      <AdminLayout>
        <p>console body</p>
      </AdminLayout>,
    );
    // Nothing in the shell links to the sign-in page — the redirect is the gate's job,
    // and a hand-rolled "sign in" link here would be a second way to do one thing.
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
  });
});
