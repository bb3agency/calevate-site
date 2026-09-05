"use client";

/**
 * What a client sees about planned maintenance: a banner before it, a door during it.
 *
 * ══ TWO COMPONENTS, ONE QUERY, BECAUSE THERE ARE TWO SITUATIONS ═════════════════════
 *
 * A client meets a window in one of two states and only one of them can make a successful
 * request:
 *
 * - **before it closes** (`scheduled`, `draining`) — nothing is shed, `GET /v1/maintenance`
 *   answers, and `MaintenanceBanner` puts a strip above every screen.
 * - **while it is closed** (`active`) — EVERY client request is refused with a 503 whose
 *   code is `platform_maintenance`, including the banner's own. `MaintenanceGate` reads the
 *   answer out of that refusal and renders the door instead of the app.
 *
 * The failure IS the answer, which is why the gate does not treat the query's error state
 * as something to hide. A second request to find out why the first failed would fail in
 * exactly the same way.
 *
 * ══ WHY THE DOOR REPLACES THE APP RATHER THAN LETTING EACH SCREEN FAIL ══════════════
 *
 * Without it, a locked-out client meets twenty screens each rendering their own red box
 * about a request that did not go through — the "generic error" the founder's brief
 * explicitly refuses. One page, once, saying what is happening and when it ends, is the
 * requirement; and it is a REPLACEMENT rather than an overlay so nothing behind it keeps
 * polling into a closed door.
 *
 * ══ THE SHELL STAYS ═════════════════════════════════════════════════════════════════
 *
 * The gate wraps `children` inside the layout, not the layout itself, so the sidebar,
 * the header and the skip link survive. A client who lands here should see their own
 * console with a message in it, not a bare error page that could be anybody's.
 *
 * ══ NOTHING HERE IS COMPUTED FROM THE BROWSER'S CLOCK ═══════════════════════════════
 *
 * Both the strip and the door render the server's own instants (`formatIST`, which fixes
 * the ZONE and never the offset) and the server's own `Retry-After` count. A laptop whose
 * clock is wrong would otherwise tell a shop owner to come back at a time nobody chose.
 */

import type { ReactNode } from "react";
import { CalendarClock, Wrench } from "lucide-react";

import { NoticeBox, formatIST } from "@/components/ui";
import { maintenanceFromProblem, useMaintenanceBanner } from "@/lib/api/maintenance";
import { useClientRealm } from "@/lib/api/session";

/**
 * Roughly how long until the platform is back, from the server's own count.
 *
 * Rounded UP to the minute and never to zero: "back in less than a minute" is a true and
 * useful sentence, and "back in 0 minutes" beside a door that is still shut is not.
 */
function backIn(seconds: number | null): string {
  if (seconds === null) return "shortly";
  const minutes = Math.ceil(seconds / 60);
  if (minutes <= 1) return "in less than a minute";
  if (minutes < 90) return `in about ${minutes} minutes`;
  return `in about ${Math.round(minutes / 60)} hours`;
}

/**
 * The strip that appears above every client screen while a window is scheduled or
 * draining. Renders nothing at all otherwise — no wrapper, no empty live region — so a
 * client on an ordinary day pays no DOM for it (`OfflineBanner`'s rule).
 *
 * `role="status"` (polite), not `role="alert"`: a window announced hours ahead is not an
 * interruption, and a screen reader should finish the sentence it is on.
 */
export function MaintenanceBanner() {
  // The realm's session rather than a prop, for `ClientCopilotDock`'s reason: it is the
  // one this document restored, and it carries an operator's view-as session unchanged
  // when one is looking. Both components here therefore require the provider, which is
  // exactly where the layout mounts them.
  const { session } = useClientRealm();
  const window = useMaintenanceBanner(session);
  const state = window.data?.state ?? "none";
  if (state !== "scheduled" && state !== "draining") return null;
  const reason = window.data?.reason ?? "";
  return (
    <div
      role="status"
      className="flex items-start gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200 lg:px-8"
    >
      <CalendarClock className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="min-w-0">
        {state === "scheduled" ? (
          <>
            <span className="font-semibold">
              Planned maintenance {formatIST(window.data?.starts_at)} to{" "}
              {formatIST(window.data?.ends_at)}.
            </span>{" "}
            Your dashboard will be unavailable during that time. Your phone numbers keep
            ringing — callers are answered and told when to call back.
          </>
        ) : (
          <>
            <span className="font-semibold">
              Maintenance is starting; the dashboard closes shortly.
            </span>{" "}
            Nothing you have already done is affected, and anything still running is being
            allowed to finish. Back by {formatIST(window.data?.ends_at)}.
          </>
        )}{" "}
        {reason !== "" && <span className="text-amber-800 dark:text-amber-300">{reason}</span>}
      </p>
    </div>
  );
}

/**
 * The door. Renders `children` normally; renders the maintenance page instead when the
 * platform has refused this client with a maintenance 503.
 *
 * It reads the refusal from the BANNER's query rather than from a query of its own, which
 * is what keeps this to one request per minute during a window instead of one per screen.
 */
export function MaintenanceGate({ children }: { children: ReactNode }) {
  const { session } = useClientRealm();
  const window = useMaintenanceBanner(session);
  const shut = maintenanceFromProblem(window.error);
  if (shut === null) return <>{children}</>;
  return (
    <div className="mx-auto max-w-2xl py-10">
      <NoticeBox
        tone="warn"
        icon={<Wrench className="h-5 w-5" />}
        title="Calevate is down for planned maintenance"
      >
        {/* THE OPERATOR'S OWN SENTENCE, VERBATIM. It is what the client was emailed and
            what they read in the banner; re-wording it here would give them two accounts
            of one outage. */}
        <p className="mt-2">{shut.detail}</p>
        <p className="mt-3">
          We expect to be back <span className="font-semibold">{backIn(shut.retryAfterSeconds)}</span>.
          This page will not update itself — reload it then.
        </p>
        <ul className="mt-3 list-disc space-y-1 pl-5">
          <li>
            <span className="font-semibold">Your phone numbers are still ringing.</span>{" "}
            Callers are answered and told we are briefly closed and when to call back,
            rather than getting a failed call.
          </li>
          <li>
            Any campaign that was running has been paused and will resume by itself, from
            exactly where it stopped.
          </li>
          <li>Nothing is deleted. Your calls, recordings, leads and settings are untouched.</li>
        </ul>
      </NoticeBox>
    </div>
  );
}
