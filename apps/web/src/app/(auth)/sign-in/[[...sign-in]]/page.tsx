"use client";

/**
 * `app.calevate.tech/sign-in` — the CLIENT realm's door, and the route that did not
 * exist.
 *
 * Until now `apps/web` had no Clerk integration at all: `/signup` told a stranger to
 * sign in with an account they had no way to create, and every console screen minted
 * `dev:client:<user>` from an environment variable. This is the other half — a real
 * sign-in for the client Clerk application (D-37: email/password + Google OAuth), which
 * `core/auth.py::verify_token` has been ready to verify against that application's JWKS
 * the whole time.
 *
 * ## Why the route is a catch-all
 *
 * `[[...sign-in]]` is Clerk's documented App Router shape and it is load-bearing, not
 * decoration: the component owns sub-paths for the steps of a real sign-in — a second
 * factor, a password reset, the SSO callback Google redirects back to. Mounting it on a
 * single `/sign-in` segment leaves those as 404s, which is a broken login on exactly the
 * accounts that turned MFA on.
 *
 * ## Why `app/(auth)/`
 *
 * A route group changes no URL — this is still `/sign-in` — but it keeps the three auth
 * doors off every console layout's filesystem chain. `/admin/sign-in`'s note explains
 * why that is load-bearing rather than tidy: a shell that redirects the signed-out to a
 * sign-in page it also wraps is an infinite redirect. The client doors do not share that
 * shell, but they belong in the same group for the same reason a reader should be able to
 * see at a glance: nothing here is inside a console.
 *
 * ## Sign-out lives here too
 *
 * A signed-in visitor gets the sign-out control rather than a redirect, so there is one
 * URL a person can always reach to end a session — including the case that needs it
 * most, an account signed in to the wrong workspace. The console shells (`/c/<slug>` and
 * `/admin`) should also carry Clerk's `<UserButton/>` in their sidebar footer; that is a
 * change to files this one deliberately does not touch.
 */

import Link from "next/link";

import { SignIn, SignOutButton } from "@clerk/nextjs";

import { AuthPageFrame } from "@/components/authPage";
import { Card, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import {
  CLIENT_AFTER_SIGN_UP_PATH,
  CLIENT_SIGN_IN_PATH,
  CLIENT_SIGN_UP_PATH,
  ClientRealmClerkProvider,
  ClientRealmSignedIn,
  ClientRealmSignedOut,
} from "@/lib/auth/clientRealm";
import { AUTH_MODE, AUTH_MODE_ENV } from "@/lib/auth/mode";

export default function ClientSignInPage() {
  return (
    <ClientRealmClerkProvider>
      <AuthPageFrame realmLabel="Client console">
        {AUTH_MODE === "dev" ? <LocalDevelopmentNotice /> : <ClerkDoor />}
      </AuthPageFrame>
    </ClientRealmClerkProvider>
  );
}

function ClerkDoor() {
  return (
    <>
      <ClientRealmSignedOut>
        {/* `path` rather than `routing="hash"`: path routing is Clerk's default and
            gives every step a real URL, which is what a password-reset link in an email
            has to point at. */}
        <SignIn path={CLIENT_SIGN_IN_PATH} signUpUrl={CLIENT_SIGN_UP_PATH} />
      </ClientRealmSignedOut>
      <ClientRealmSignedIn>
        <AlreadySignedIn />
      </ClientRealmSignedIn>
    </>
  );
}

/**
 * What a signed-in visitor sees. It offers no link into a workspace, because this page
 * cannot know the slug — `/v1/me` answers that and this screen makes no API calls. The
 * workspace door it CAN name is the one for a user who has no workspace yet.
 */
function AlreadySignedIn() {
  return (
    <Card title="You are already signed in">
      <div className="space-y-3 text-sm text-ink-muted">
        <p>
          Your workspace lives at{" "}
          <code className="rounded bg-black/5 px-1 font-mono text-ink dark:bg-white/10">
            /c/your-slug
          </code>{" "}
          — the URL your account manager gave you.
        </p>
        <div className="flex flex-wrap gap-2">
          <Link href={CLIENT_AFTER_SIGN_UP_PATH} className={PRIMARY_BUTTON}>
            Create a workspace
          </Link>
          {/* No `redirectUrl` here: the provider's `afterSignOutUrl` already names the
              destination, and stating it twice is two places to change it. */}
          <SignOutButton>
            <button type="button" className={SECONDARY_BUTTON}>
              Sign out
            </button>
          </SignOutButton>
        </div>
      </div>
    </Card>
  );
}

/**
 * The local build, told the truth about.
 *
 * With `NEXT_PUBLIC_AUTH_MODE` unset (or `dev`) outside a production build, no Clerk
 * application is mounted and every request carries `dev:client:<NEXT_PUBLIC_DEV_USER>`,
 * which the API accepts only under `APP_ENV=local` with no Clerk secret. Rendering
 * Clerk's sign-in card here would be a form with nothing behind it; saying so is more
 * use to the developer who arrived at this URL wondering why nothing happened.
 */
function LocalDevelopmentNotice() {
  return (
    <Card title="Local development build">
      <div className="space-y-3 text-sm text-ink-muted">
        <p>
          This build signs every request with a local development token, so there is
          nothing to sign in to. The API accepts those only when it is running with{" "}
          <code className="font-mono">APP_ENV=local</code> and no Clerk secret.
        </p>
        <p>
          To exercise the real flow, set{" "}
          <code className="font-mono">{AUTH_MODE_ENV}=clerk</code> together with the
          realms&apos; Clerk publishable keys.
        </p>
        <Link href="/" className={SECONDARY_BUTTON}>
          Back to the front page
        </Link>
      </div>
    </Card>
  );
}
