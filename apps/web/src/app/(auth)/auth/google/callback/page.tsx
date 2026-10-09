"use client";

/**
 * `/auth/google/callback` — where Google returns someone who chose "Continue with Google"
 * (D-703). This address is `google_signin_redirect_uri`, registered on the platform's
 * Google OAuth client.
 *
 * It takes the `code` and `state` out of the address bar at once, hands them to the API
 * (which checks them against the cookie this browser got when sign-in started and starts
 * a session), then goes where the person belongs: the workspace an invitation just joined,
 * the page they were sent from, or `/c`, which forwards a person with no workspace to set
 * one up.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Providers } from "@/app/providers";
import { AuthCard, AuthHeading, AuthPageFrame } from "@/components/authPage";
import { AuthProblemNotice } from "@/components/authn/fields";
import { NoticeBox, PRIMARY_BUTTON, Skeleton } from "@/components/ui";
import {
  CLIENT_CONSOLE_PATH,
  CLIENT_SIGN_IN_PATH,
  completeGoogleSignIn,
} from "@/lib/authn/clientAuthn";
import { safeNextPath } from "@/lib/authn/nextPath";
import { clientConsoleUrl } from "@/lib/consoleOrigin";

type View =
  | { kind: "working" }
  | { kind: "cancelled" }
  | { kind: "failed"; error: unknown }
  | { kind: "mismatch"; destination: string };

export default function GoogleCallbackPage() {
  const [view, setView] = useState<View>({ kind: "working" });
  const started = useRef(false);

  useEffect(() => {
    // Strict mode runs effects twice in development; the code is single-use.
    if (started.current) return;
    started.current = true;
    const url = new URL(window.location.href);
    const code = url.searchParams.get("code") ?? "";
    const state = url.searchParams.get("state") ?? "";
    const refused = url.searchParams.get("error");
    window.history.replaceState(null, "", url.pathname);
    if (refused || !code || !state) {
      setView({ kind: "cancelled" });
      return;
    }
    completeGoogleSignIn({ code, state })
      .then((done) => {
        const destination = done.joined_slug
          ? clientConsoleUrl(`/c/${done.joined_slug}`)
          : clientConsoleUrl(safeNextPath(done.next, CLIENT_CONSOLE_PATH) ?? CLIENT_CONSOLE_PATH);
        if (done.invitation_mismatch) {
          setView({ kind: "mismatch", destination });
          return;
        }
        window.location.replace(destination);
      })
      .catch((error: unknown) => setView({ kind: "failed", error }));
  }, []);

  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        <AuthCard>
          {view.kind === "working" && (
            <div className="space-y-4">
              <AuthHeading title="Signing you in" lead="Finishing your Google sign-in…" />
              <Skeleton rows={2} label="Finishing your Google sign-in…" />
            </div>
          )}
          {view.kind === "cancelled" && (
            <div className="space-y-4">
              <AuthHeading
                title="Google sign-in was cancelled"
                lead="Nothing was changed. You can try again or use your email address."
              />
              <Link href={CLIENT_SIGN_IN_PATH} className={`${PRIMARY_BUTTON} w-full justify-center`}>
                Back to sign in
              </Link>
            </div>
          )}
          {view.kind === "failed" && (
            <div className="space-y-4">
              <AuthHeading title="We could not sign you in" />
              <AuthProblemNotice error={view.error} />
              <Link href={CLIENT_SIGN_IN_PATH} className={`${PRIMARY_BUTTON} w-full justify-center`}>
                Back to sign in
              </Link>
            </div>
          )}
          {view.kind === "mismatch" && (
            <div className="space-y-4">
              <AuthHeading title="You are signed in" />
              <NoticeBox tone="warn" title="The invitation was for another email address">
                <p className="mt-1">
                  The Google account you chose uses a different email address from the one
                  the invitation was sent to, so you have not joined that workspace. Open the
                  invitation again and choose the Google account for that address.
                </p>
              </NoticeBox>
              <a href={view.destination} className={`${PRIMARY_BUTTON} w-full justify-center`}>
                Continue
              </a>
            </div>
          )}
        </AuthCard>
      </AuthPageFrame>
    </Providers>
  );
}
