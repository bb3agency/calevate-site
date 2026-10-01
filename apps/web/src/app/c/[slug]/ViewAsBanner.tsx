"use client";

import Link from "next/link";

import { ProblemNotice } from "@/components/ui";
import { ADMIN_CONSOLE_PATH } from "@/lib/authn/adminAuthn";
import { adminConsoleUrl } from "@/lib/consoleOrigin";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

export function ViewAsBanner({ slug }: { slug: string }) {
  const { session, viewAsRequested } = useClientRealm();
  const me = useMe(session);

  if (me.data?.impersonating) {
    return (
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
        <span>
          Viewing as {me.data.organization?.name ?? slug}. Every page view is logged, and
          anything you change here is recorded against you, not this account.
        </span>
        {/* THE WAY OUT, and it belongs HERE rather than in the sidebar. There was none at
            all: an operator who had finished looking could only know to edit the URL, and
            the one control that looked like an exit — "Sign out" at the foot of the
            sidebar — ends the ADMIN session instead, dropping them at a sign-in page with
            a warning. So the sentence that says "you are impersonating" is now also the
            thing that stops it, which is the only place a reader is already looking.

            ABSOLUTE, through `adminConsoleUrl`: this banner only ever renders on the
            CLIENT hostname, and `app.` answers `location ^~ /admin { return 404; }`
            (`infra/nginx/calevate.conf.template`) — so the bare `/admin` this used to
            assign was a not-found screen for every operator who finished looking. The
            exact mirror of the view-as bug that produced `clientConsoleUrl`.

            A hard navigation, for `SidebarSignOut`'s reason: the in-memory grant cache
            (`admin.ts::grantCache`) and this tab's TanStack cache both hold another
            account's data, and a client-side route change would carry both into the admin
            console. `/admin` rather than the tenant's own page because this shell holds
            the SLUG and never the tenant id — inventing a lookup to land one screen
            deeper would be a request that can fail on the way out of a session. */}
        <button
          type="button"
          onClick={() => window.location.assign(adminConsoleUrl(ADMIN_CONSOLE_PATH))}
          className="press shrink-0 rounded border border-amber-950/40 px-2 py-0.5 font-semibold underline-offset-2 hover:bg-amber-950/10 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-950 touch:min-h-11"
        >
          Exit and return to the admin console
        </button>
      </div>
    );
  }

  // THE PENDING ARM, and it is a safety property rather than a polish item. The two arms
  // below cover "the server says you are impersonating" and "the read failed"; while the
  // read is IN FLIGHT `me.data` is undefined and `me.error` is null, so this component
  // rendered NOTHING — an operator sitting in a client's account with no marker at all,
  // on a console otherwise identical to that client's own. That was the visible half of
  // the `StepUpPrompt` deadlock (`lib/api/session.tsx`), where the read never resolved
  // and "in flight" lasted forever; the deadlock is fixed, but a slow read reproduces the
  // same unmarked screen and the marker must not depend on a request having answered.
  //
  // It states the INTENT, not the fact, and says which it is: the amber arm below quotes
  // the server's own `impersonating`, and this one must never be mistaken for it.
  if (viewAsRequested && me.isPending) {
    return (
      <div className="bg-amber-500/60 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
        Opening as an operator — confirming with the server…
      </div>
    );
  }

  if (viewAsRequested && !me.data?.impersonating && me.error != null) {
    return (
      <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 dark:border-rose-900 dark:bg-rose-950">
        <ProblemNotice error={me.error} />
        <p className="mt-2 text-xs text-rose-800 dark:text-rose-300">
          This page was opened as an operator. Open it from the admin console, or{" "}
          <Link href={`/c/${slug}`} className="underline">
            continue as a normal user
          </Link>
          .
        </p>
      </div>
    );
  }

  return null;
}
