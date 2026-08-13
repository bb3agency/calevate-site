"use client";

/**
 * `admin.calevate.tech/admin/sign-in` — the OPERATOR realm's door.
 *
 * A separate Clerk application from the client realm's, on purpose and at every level:
 * separate publishable key, separate cookies, separate JWKS. `core/auth.py::jwks_url`
 * spells out why in the place it matters most — resolving both realms to one host would
 * leave `admin_users` membership as the only thing between a client token and the admin
 * console, "an authorization check standing in for an authentication one".
 *
 * **There is no `/admin/sign-up`, and there must not be.** D-37 makes the admin realm
 * invite-only with signup disabled: an operator account is created in the Clerk dashboard
 * and mirrored into `admin_users`. Accordingly this page offers no "create an account"
 * link, and `AdminRealmClerkProvider` passes no `signUpUrl`, so Clerk's own card has none
 * to render either.
 *
 * ## Why this file lives in `app/(auth)/` and not in `app/admin/`
 *
 * The URL is still `/admin/sign-in` — a route group is invisible to the router — but the
 * FILESYSTEM path decides which layouts wrap a page, and `app/admin/layout.tsx` is not on
 * this one's chain. That matters exactly once, and fatally: the admin console shell is
 * the thing that will be wrapped in `<AdminRealmClerkProvider protect>`, and a protected
 * subtree containing its own sign-in page is an infinite redirect — signed out, redirect
 * to sign-in, still signed out, redirect again. Next has no way for a page to opt out of
 * a parent layout other than this, which is why Clerk's own quickstart puts its auth
 * routes outside the application shell too.
 *
 * The shell also calls `/v1/admin/me` on every render; rendering a sign-in page inside it
 * would fire an authenticated request on behalf of somebody who is, by definition, not
 * authenticated yet.
 *
 * ## What this page cannot do on its own
 *
 * Mounting the admin Clerk application HERE lets an operator sign in and out. It does not
 * put a session on the rest of `/admin/**`, because that subtree renders inside
 * `app/admin/layout.tsx`, which is owned by another change in flight. Wrapping that
 * layout in `<AdminRealmClerkProvider protect>` is the one remaining edit; until it
 * lands, the admin console keeps working on `dev:admin:` tokens locally and would show
 * `AuthProblem` refusals in a Clerk deployment rather than silently falling back to
 * anything.
 */

import Link from "next/link";

import { SignIn, SignOutButton } from "@clerk/nextjs";

import { AuthPageFrame } from "@/components/authPage";
import { Card, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import {
  ADMIN_SIGN_IN_PATH,
  AdminRealmClerkProvider,
  AdminRealmSignedIn,
  AdminRealmSignedOut,
} from "@/lib/auth/adminRealm";
import { AUTH_MODE, AUTH_MODE_ENV } from "@/lib/auth/mode";

export default function AdminSignInPage() {
  return (
    <AdminRealmClerkProvider>
      <AuthPageFrame realmLabel="Operator console">
        {AUTH_MODE === "dev" ? <LocalDevelopmentNotice /> : <ClerkDoor />}
      </AuthPageFrame>
    </AdminRealmClerkProvider>
  );
}

function ClerkDoor() {
  return (
    <>
      <AdminRealmSignedOut>
        <SignIn path={ADMIN_SIGN_IN_PATH} />
      </AdminRealmSignedOut>
      <AdminRealmSignedIn>
        <Card title="You are signed in as an operator">
          <div className="space-y-3 text-sm text-ink-muted">
            <p>
              An operator session can read every client account, and every view of one is
              written to the audit log.
            </p>
            <div className="flex flex-wrap gap-2">
              <Link href="/admin" className={PRIMARY_BUTTON}>
                Open the console
              </Link>
              <SignOutButton>
                <button type="button" className={SECONDARY_BUTTON}>
                  Sign out
                </button>
              </SignOutButton>
            </div>
          </div>
        </Card>
      </AdminRealmSignedIn>
    </>
  );
}

/** See `/sign-in`: locally the console runs on `dev:admin:<NEXT_PUBLIC_DEV_ADMIN>` and
 * there is no Clerk application to sign in to. */
function LocalDevelopmentNotice() {
  return (
    <Card title="Local development build">
      <div className="space-y-3 text-sm text-ink-muted">
        <p>
          This build signs operator requests with a local development token, so there is
          nothing to sign in to. The API accepts those only when it is running with{" "}
          <code className="font-mono">APP_ENV=local</code> and no Clerk secret for this
          realm.
        </p>
        <p>
          Set <code className="font-mono">{AUTH_MODE_ENV}=clerk</code> and the admin
          publishable key to exercise the real flow.
        </p>
        <Link href="/admin" className={SECONDARY_BUTTON}>
          Open the console
        </Link>
      </div>
    </Card>
  );
}
