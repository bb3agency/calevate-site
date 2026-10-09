"use client";

/**
 * `/c` — "take me to my console", for everyone who does not know their own slug.
 *
 * WHY THIS ROUTE EXISTS. Every client screen lives under `/c/<slug>`, and the slug is a
 * fact about the ACCOUNT rather than about the person: it arrives on `/v1/me`, which needs
 * a session, which is exactly what somebody who has just signed in has and nothing else.
 * So the sign-in door could not name a destination, and sent people to `/auth/account`
 * instead — a page whose entire content is "you are signed in", an email panel and two
 * sign-out buttons. The reward for signing in was a dead end, and the same dead end the
 * admin realm had until D-441 (`ADMIN_CONSOLE_PATH`); the client half was harder only
 * because `/admin` needs no slug and this does.
 *
 * ONE RESOLVER, THREE CALLERS. The sign-in door, the guest guard that bounces an
 * already-signed-in person off it, and the marketing header's "your console" link all
 * need the same answer, and none of them can compute it. Three copies of a `/v1/me` read
 * plus a redirect would be three places to get the failure states wrong.
 *
 * IT REDIRECTS RATHER THAN RENDERING. `replace`, not `assign`: this page is a junction and
 * has no content of its own, so leaving it in the history means Back from the dashboard
 * lands here and immediately bounces forward again — a Back button that does nothing.
 *
 * WHAT IT DOES NOT DO IS INVENT AN ACCOUNT. A person who belongs to more than one gets
 * `org_required` from the API, and there is no endpoint that lists their memberships — so
 * this says so plainly rather than guessing at one. That gap is real and named here rather
 * than hidden behind a redirect to whichever account happened to sort first.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { AuthProblemNotice } from "@/components/authn/fields";
import { Card, Skeleton } from "@/components/ui";
import { useUnscopedMe } from "@/lib/api/hooks";
import { ApiProblem, apiRequest } from "@/lib/api/client";
import { BUSINESS_PROFILE_PATH, type BusinessProfile } from "@/lib/api/businessProfile";
import { clientRealmSession } from "@/lib/authn/realmSessions";
import { CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";
import { ClientSessionGate, ClientSessionProvider } from "@/lib/authn/clientSession";

export default function ClientConsoleJunction() {
  return (
    <Providers>
      <ClientSessionProvider>
        <AuthPageFrame realmLabel="Client console">
          <ClientSessionGate>
            <Resolve />
          </ClientSessionGate>
        </AuthPageFrame>
      </ClientSessionProvider>
    </Providers>
  );
}

function Resolve() {
  // `useUnscopedMe` (lib/api/hooks.ts) — the same read `/auth/account` makes, from the
  // same place, under its own key. It used to be written out here; the day a second page
  // needed "who am I, without a slug" the read moved rather than being copied.
  const me = useUnscopedMe();
  const slug = me.data?.organization?.slug ?? null;
  // AN OWNER WHO HAS NEVER OPENED THE BUSINESS SETUP STARTS THERE (D-695): their first
  // sign-in. Anyone else, or an owner who has started or hidden it, goes to the dashboard.
  // A failed read of the profile keeps nobody out: it falls through to the dashboard, whose
  // setup checklist reads the same answer again.
  // Only decided once `/v1/me` has answered: `slug` is null until then, so nothing below
  // runs on a guess.
  const owner =
    me.data !== undefined &&
    me.data.permissions.includes("org:manage") &&
    me.data.impersonating === false;
  const profile = useQuery({
    queryKey: ["junction-business-profile", slug],
    queryFn: () =>
      apiRequest<BusinessProfile>(clientRealmSession(slug as string), BUSINESS_PROFILE_PATH),
    enabled: Boolean(slug) && owner,
    retry: false,
  });
  const decided = !owner || profile.isSuccess || profile.isError;
  const firstVisit =
    profile.data !== undefined && !profile.data.setup.started && !profile.data.setup.dismissed;

  useEffect(() => {
    if (!slug || !decided || typeof window === "undefined") return;
    // `replace`: see the module docstring — this junction must not sit in the history.
    window.location.replace(firstVisit ? `/c/${slug}/setup` : `/c/${slug}`);
  }, [slug, decided, firstVisit]);

  // A signed-in person with no workspace yet (a new self-serve account, D-703) goes to
  // create one rather than reading a refusal.
  const noWorkspace =
    me.error instanceof ApiProblem && me.error.status === 403 && me.error.code === "forbidden";
  useEffect(() => {
    if (noWorkspace) window.location.replace("/signup");
  }, [noWorkspace]);

  if (me.error != null && !noWorkspace) {
    return (
      <Card>
        <div className="space-y-3">
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            We could not open your console
          </h1>
          <AuthProblemNotice error={me.error} />
          <p className="text-sm text-ink-muted">
            If you belong to more than one Calevate account, open the link for the one you
            want — this page can only open one account, and there is no list of yours to
            choose from yet. Otherwise, reload, or{" "}
            <a href={CLIENT_SIGN_IN_PATH} className="underline underline-offset-2">
              sign in again
            </a>
            .
          </p>
        </div>
      </Card>
    );
  }

  // Both the in-flight read AND the moment after it lands, while `replace` is in flight —
  // BUILD-LOG §52: loading is a skeleton, and a blank screen is not a loading state.
  return <Skeleton rows={3} label="Opening your console…" />;
}
