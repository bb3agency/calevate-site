"use client";

/**
 * `app.calevate.tech/sign-up` — creating a Calevate ACCOUNT (D-37, client realm only).
 *
 * ## `/sign-up` and `/signup` are two steps, in that order
 *
 * They are one hyphen apart and that is worth being blunt about, because a link to the
 * wrong one is a dead end for a business trying to buy the product:
 *
 *  - **`/sign-up` (here)** creates the identity. Clerk owns it — email/password or
 *    Google, per D-37 — and it is what makes `Authorization: Bearer <jwt>` possible at
 *    all.
 *  - **`/signup`** creates the WORKSPACE: `POST /v1/auth/signup`, which requires a
 *    Clerk-verified user who has no organization yet and creates the membership. Our
 *    Postgres owns that, and RLS keys off the `tenant_id` it mints (D-37, hard rule 1).
 *
 * So this page hands off to that one, through `CLIENT_AFTER_SIGN_UP_PATH`, which is
 * spelled once in `lib/auth/clientRealm.tsx` and never typed out at a call site.
 *
 * Nothing here is gated on the self-serve kill switch. `SELF_SERVE_SIGNUP_ENABLED` (R-11)
 * governs whether we open WORKSPACES, which is the compliance-shaped act — an account
 * with no workspace can do nothing at all — and `/signup` refuses in its own words when
 * the switch is off. Duplicating that gate here would put the refusal one screen earlier
 * and one message vaguer.
 */

import { SignUp } from "@clerk/nextjs";

import { AuthPageFrame } from "@/components/authPage";
import { Card, SECONDARY_BUTTON } from "@/components/ui";
import Link from "next/link";

import {
  CLIENT_AFTER_SIGN_UP_PATH,
  CLIENT_SIGN_IN_PATH,
  CLIENT_SIGN_UP_PATH,
  ClientRealmClerkProvider,
  ClientRealmSignedIn,
  ClientRealmSignedOut,
} from "@/lib/auth/clientRealm";
import { AUTH_MODE, AUTH_MODE_ENV } from "@/lib/auth/mode";

export default function ClientSignUpPage() {
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
        {/* `fallbackRedirectUrl`, not `forceRedirectUrl`: a person who arrived here from
            an invitation link carries a redirect of their own in the URL, and forcing
            ours would drop them out of the flow they were invited into. Ours applies
            only when nothing else has an opinion — which is the plain case, a stranger
            who now needs a workspace. */}
        <SignUp
          path={CLIENT_SIGN_UP_PATH}
          signInUrl={CLIENT_SIGN_IN_PATH}
          fallbackRedirectUrl={CLIENT_AFTER_SIGN_UP_PATH}
        />
      </ClientRealmSignedOut>
      <ClientRealmSignedIn>
        <Card title="You already have a Calevate account">
          <div className="space-y-3 text-sm text-ink-muted">
            <p>The next step is your workspace — that is what your agent lives in.</p>
            <Link href={CLIENT_AFTER_SIGN_UP_PATH} className={SECONDARY_BUTTON}>
              Create your workspace
            </Link>
          </div>
        </Card>
      </ClientRealmSignedIn>
    </>
  );
}

/** See the note on the same component in `/sign-in`: locally there is no Clerk to talk
 * to, and a sign-up card with nothing behind it would be the third false door this
 * change exists to remove. */
function LocalDevelopmentNotice() {
  return (
    <Card title="Local development build">
      <div className="space-y-3 text-sm text-ink-muted">
        <p>
          This build has no Clerk application mounted — every request is signed with a
          local development token instead, so there is no account to create.
        </p>
        <p>
          Set <code className="font-mono">{AUTH_MODE_ENV}=clerk</code> and the realms&apos;
          publishable keys to exercise the real flow.
        </p>
        <Link href={CLIENT_AFTER_SIGN_UP_PATH} className={SECONDARY_BUTTON}>
          Go to workspace creation
        </Link>
      </div>
    </Card>
  );
}
