"use client";

/**
 * Connecting an account by signing in to it (Google Calendar, Google Sheets, Zoho CRM,
 * HubSpot), from any screen that needs one: the Integrations page, and an agent's Actions
 * when a job needs an account that is not connected yet.
 *
 * One hook so the popup hand-off (`oauthReturn.ts`) has one implementation. The consent
 * page opens in a popup; the provider returns to `/oauth/callback/<provider>`, which writes
 * the result to storage; this hook hears the `storage` event (or finds the result on mount
 * after a full-page redirect) and finishes the connection with this tab's session.
 */

import { useEffect } from "react";

import { useOAuthComplete, useOAuthConnect, type OAuthKind } from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { beginOAuthReturn, OAUTH_RETURN_KEY, takeOAuthReturn } from "./oauthReturn";

export function useAccountSignIn(session: Session) {
  const connect = useOAuthConnect(session);
  const complete = useOAuthComplete(session);

  useEffect(() => {
    const finish = () => {
      const back = takeOAuthReturn(session.orgSlug);
      if (back) complete.mutate(back);
    };
    finish();
    const onStorage = (e: StorageEvent) => {
      if (e.key === OAUTH_RETURN_KEY) finish();
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
    // `complete` is stable for this component's life; re-running on it would re-read storage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.orgSlug]);

  function signIn(kind: OAuthKind) {
    connect.mutate(kind, {
      onSuccess: (r) => {
        const popup = window.open(r.authorize_url, "calevate-connect", "width=520,height=720");
        beginOAuthReturn(session.orgSlug, kind, popup !== null);
        // A blocked popup: go there in this tab; the callback page brings the client back.
        if (!popup) window.location.assign(r.authorize_url);
      },
    });
  }

  // The refusal to render, whichever half failed: starting the sign-in or finishing it.
  const error = connect.error ?? complete.error;

  return { signIn, connect, complete, error };
}
