"use client";

/**
 * `/oauth/callback/<provider>` — where Google, Zoho and HubSpot send a client back after
 * they agree to connect their account (D-700). These are the redirect addresses registered
 * with each provider (OPERATIONS gates A-1..A-3).
 *
 * It holds no session and calls no API. It notes the code, the `state` and Zoho's
 * `accounts-server` next to the record the Integrations screen left when it opened the
 * consent page (`integrations/oauthReturn.ts`), takes them out of the address bar, and then
 * either closes itself (it was the popup: the screen that opened it finishes the connection
 * from storage) or sends this tab back to the Integrations screen, which finishes it. The
 * server checks the `state`. Whether it is the popup comes from that record, not from
 * `window.opener`, which Google's Cross-Origin-Opener-Policy has already cut.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { NoticeBox, Skeleton } from "@/components/ui";

import { noteOAuthReturn } from "../../../c/[slug]/integrations/oauthReturn";

export default function OAuthCallbackPage({ params }: { params: Promise<{ provider: string }> }) {
  const [problem, setProblem] = useState<string | null>(null);
  // Set when this popup could not close itself (a browser may refuse): say so, and offer
  // the way back, rather than loading the console inside the small window.
  const [leftOpen, setLeftOpen] = useState<string | null>(null);

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
      const route = noteOAuthReturn(provider, { code, state, accountsServer });
      if (!route) {
        setProblem("This connection was not started from this browser, or it took too long. Start it again from Integrations.");
        return;
      }
      if (!route.popup) {
        window.location.replace(route.back);
        return;
      }
      window.close();
      setLeftOpen(route.back);
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
        ) : leftOpen ? (
          <NoticeBox tone="ok" title="Connected">
            You can close this window; the Integrations screen finishes the connection. If it
            is no longer open,{" "}
            <Link className="font-medium underline underline-offset-2" href={leftOpen}>
              go back to Integrations
            </Link>
            .
          </NoticeBox>
        ) : (
          <Skeleton rows={2} label="Finishing the connection…" />
        )}
      </AuthPageFrame>
    </Providers>
  );
}
