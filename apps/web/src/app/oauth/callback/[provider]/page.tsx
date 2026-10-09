"use client";

/**
 * `/oauth/callback/<provider>` — where Google, Zoho and HubSpot send a client back after
 * they agree to connect their account (D-700). These are the redirect addresses registered
 * with each provider (OPERATIONS gates A-1..A-3).
 *
 * It holds no session and calls no API. It notes the code, the `state` and Zoho's
 * `accounts-server` next to the record the Integrations screen left when it opened the
 * consent page (`integrations/oauthReturn.ts`), takes them out of the address bar, and then
 * either closes itself (it was the popup: the opener finishes the connection) or sends this
 * tab back to the Integrations screen, which finishes it. The server checks the `state`.
 */

import { useEffect, useState } from "react";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { NoticeBox, Skeleton } from "@/components/ui";

import { noteOAuthReturn } from "../../../c/[slug]/integrations/oauthReturn";

export default function OAuthCallbackPage({ params }: { params: Promise<{ provider: string }> }) {
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void params.then(({ provider }) => {
      if (cancelled) return;
      const url = new URL(window.location.href);
      const code = url.searchParams.get("code") ?? "";
      const state = url.searchParams.get("state") ?? "";
      const accountsServer = url.searchParams.get("accounts-server");
      const refused = url.searchParams.get("error");
      // The code is single-use and short-lived; it still leaves the address bar at once.
      window.history.replaceState(null, "", url.pathname);
      if (refused || !code || !state) {
        setProblem("The connection was cancelled or did not complete. Start it again from Integrations.");
        return;
      }
      const back = noteOAuthReturn(provider, { code, state, accountsServer });
      if (!back) {
        setProblem("This connection was not started from this browser, or it took too long. Start it again from Integrations.");
        return;
      }
      if (window.opener) window.close();
      else window.location.replace(back);
    });
    return () => {
      cancelled = true;
    };
  }, [params]);

  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        {problem ? (
          <NoticeBox tone="warn" title="Not connected">
            {problem}
          </NoticeBox>
        ) : (
          <Skeleton rows={2} label="Finishing the connection…" />
        )}
      </AuthPageFrame>
    </Providers>
  );
}
