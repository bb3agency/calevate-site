import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminLayout from "@/app/admin/layout";
import { ADMIN_ME_PATH } from "@/app/admin/access";
import { ADMIN_SIGN_IN_PATH } from "@/lib/auth/adminRealm";
import { HOLDS_PATH } from "@/lib/api/holds";

import { stubApi, type Routes } from "./harness";

/**
 * The operator console's front door — the edit `app/(auth)/admin/sign-in` had been
 * waiting on.
 *
 * `app/admin/layout.tsx` wrapped the whole console in `Providers` and nothing else, while
 * the client realm mounted its protecting provider in `lib/api/session.tsx`. The
 * asymmetry was not cosmetic: against a real Clerk deployment `adminRealmToken()` has no
 * session to read, so every screen under `/admin` answered its own `AuthProblem` — a wall
 * of "You are not signed in to the Calevate admin console" with no redirect to the
 * sign-in page that already existed. The sign-in page's own docstring named this as "the
 * one remaining edit".
 *
 * Two properties are asserted here, and the second is the one that could have been broken
 * by the fix rather than by the defect:
 *
 * 1. **The ADMIN realm's provider is what wraps the console** — not the client realm's,
 *    which would present a `dev:client:`/client-Clerk credential to `/v1/admin/*`. Two
 *    Clerk applications with two publishable keys and two cookies is a hard rule
 *    (CLAUDE.md conventions, TRD §11, D-37), and the two realm modules import each other
 *    never.
 * 2. **A local run is untouched.** The repo runs with `ENGINE=fake`, a dev credential and
 *    no Clerk keys at all; `lib/auth/mode.ts` resolves an unset `NEXT_PUBLIC_AUTH_MODE`
 *    outside a production build to `dev`, and `AdminRealmClerkProvider` then mounts
 *    nothing — no provider, no clerk-js, no network. If that had regressed, every admin
 *    suite in this directory would have gone red at once; this file makes the property
 *    itself the subject rather than an inference from other tests passing.
 */

const OPERATOR = { role: "operator", permissions: ["admin:read", "admin:impersonate"] };

/** Everything the shell itself asks for on mount, before any page under it. */
const SHELL_ROUTES: Routes = { [ADMIN_ME_PATH]: OPERATOR, [HOLDS_PATH]: [] };

function renderShell(routes: Routes = SHELL_ROUTES) {
  const calls = stubApi(routes);
  const result = render(
    <AdminLayout>
      <p>console body</p>
    </AdminLayout>,
  );
  return Object.assign(result, { calls });
}

describe("the console in a local build", () => {
  it("still renders unprotected, with no Clerk anywhere in the tree", async () => {
    /**
     * THE regression guard on the fix. `AdminRealmClerkProvider` returns `children`
     * untouched when `AUTH_MODE === "dev"`, so wrapping the shell in it must be
     * invisible locally: the page body renders, the sidebar renders, and no refusal
     * panel replaces the surface. A wrapper that mounted `<ClerkProvider>` here would
     * try to load clerk-js from Clerk's CDN on every developer's machine.
     */
    const { container } = renderShell();
    await act(async () => {});

    expect(container.textContent).toContain("console body");
    // The shell's own furniture, so this cannot pass by rendering a bare fragment.
    expect(container.textContent).toContain("Cross-client · every action is audited");
    // The refusal `ClerkNotConfigured` renders INSTEAD of the surface — its absence is
    // what says the dev branch was taken rather than the unconfigured-Clerk one.
    expect(container.textContent).not.toContain("Sign-in is not configured");
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
      expect(call.headers.Authorization, call.path).toMatch(/^Bearer dev:admin:/);
    }
  });
});

describe("the console in a Clerk deployment", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("mounts the ADMIN application, and replaces the console when its key is missing", async () => {
    /**
     * The assertion that fails if the layout is not wrapped at all.
     *
     * A Clerk-mode build with no `NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY` makes
     * `AdminRealmClerkProvider` render `ClerkNotConfigured` INSTEAD of its children —
     * deliberately a render and not a throw, so `next build` still succeeds on a machine
     * without Clerk credentials (see `clerkRuntime.tsx`). That branch is reachable
     * offline, unlike a real `<ClerkProvider>`, which loads clerk-js from a CDN; so it is
     * the one place a test can observe "the provider is really in this tree" without
     * asserting a stub's opinion of a sign-in form.
     *
     * It also pins WHICH realm: the panel names the realm and the environment variable,
     * and the client realm's twin would name `client` and
     * `NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY`. A mis-wired import is the failure this
     * catches, and it is the expensive one — a client credential reaching `/v1/admin/*`.
     *
     * The module graph is rebuilt because `AUTH_MODE` and both publishable keys are read
     * at module load (mode.ts: "computed once, so a misconfiguration surfaces at build
     * time rather than on the first request"). Vitest keeps externalised dependencies —
     * React among them — out of `resetModules`, so the fresh graph renders through the
     * same React instance and the hooks below are the ones the app uses.
     */
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "clerk");
    vi.stubEnv("NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY", "");
    vi.resetModules();

    const { default: FreshAdminLayout } = await import("@/app/admin/layout");
    const calls = stubApi(SHELL_ROUTES);
    const { container } = render(
      <FreshAdminLayout>
        <p>console body</p>
      </FreshAdminLayout>,
    );
    await act(async () => {});

    expect(container.textContent).toContain("Sign-in is not configured");
    expect(container.textContent).toContain("admin console");
    expect(container.textContent).toContain("NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY");
    // Not the client realm's key, and not the client realm's word for the realm.
    expect(container.textContent).not.toContain("NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY");

    // The console is REPLACED, not decorated: there is no half-working state where the
    // shell polls `/v1/admin/*` behind a panel saying nobody is signed in.
    expect(container.textContent).not.toContain("console body");
    expect(calls).toEqual([]);
  });
});

describe("the door the console now redirects to", () => {
  it("is inside /admin but outside this layout, so protection cannot loop", () => {
    /**
     * `protect` renders `<RedirectToSignIn/>` for a signed-out operator, and the page it
     * lands on is `ADMIN_SIGN_IN_PATH`. That page lives in `app/(auth)/admin/sign-in/`,
     * NOT in `app/admin/`: a route group is invisible to the router but decides which
     * layouts wrap a page, so the sign-in page is not wrapped by the layout that
     * redirects to it. Wrapped, it would be an infinite redirect — signed out, redirect
     * to sign-in, still signed out, redirect again — and it would fire `/v1/admin/me` on
     * behalf of somebody who is by definition not authenticated.
     *
     * Asserted as a URL fact because that is the part a future move of the file would
     * break silently; the sign-in page's own suite (`auth.test.tsx`) covers what it
     * renders.
     */
    expect(ADMIN_SIGN_IN_PATH).toBe("/admin/sign-in");
    stubApi({});
    render(
      <AdminLayout>
        <p>console body</p>
      </AdminLayout>,
    );
    // Nothing in the shell links to the sign-in page — the redirect is Clerk's job, and
    // a hand-rolled "sign in" link here would be a second way to do one thing.
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
  });
});
