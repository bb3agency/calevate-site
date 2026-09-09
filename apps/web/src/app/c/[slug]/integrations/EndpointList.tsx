"use client";

import {
  Card,
  EmptyState,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import type { WriteAccess } from "@/lib/api/hooks";
import { SHEET_KIND, useEndpoints, type Endpoint } from "@/lib/api/integrations";

/** Every destination this account has registered, and the one thing you can do to each. */
export function EndpointList({
  endpoints,
  write,
  busy,
  onStop,
}: {
  endpoints: ReturnType<typeof useEndpoints>;
  write: WriteAccess;
  busy: boolean;
  onStop: (endpoint: Endpoint) => void;
}) {
  return (
    <Card title="Your endpoints">
      {endpoints.isLoading ? (
        <Skeleton rows={2} />
      ) : endpoints.error || !endpoints.data ? (
        /* A failed read AND a read TanStack never started both land here. `?.length`
           alone rendered `null` on a failure and "No endpoints yet" on a paused
           query (offline: not loading, `error === null`, `data === undefined`) — a
           client told their CRM is unconfigured off a request that never left the
           browser. §52: failure is a refusal, and neither non-answer is an empty
           state. The refusal now owns both, the way the dashboard's latest-calls
           card does (`app/c/[slug]/page.tsx`). */
        <ProblemNotice
          error={endpoints.error ?? new Error("Your endpoints could not be loaded.")}
          onRetry={() => endpoints.refetch()}
        />
      ) : endpoints.data.length ? (
        <ul className="divide-y divide-line">
          {endpoints.data.map((endpoint) => (
            <li key={endpoint.id} className="flex flex-wrap items-center gap-2 py-2.5">
              <span className="break-all font-mono text-xs text-ink-muted">
                {endpoint.url}
              </span>
              {!endpoint.active && (
                <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-ink-muted dark:bg-white/10">
                  off
                </span>
              )}
              {endpoint.kind === SHEET_KIND && (
                <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-ink-muted dark:bg-white/10">
                  Google Sheet
                </span>
              )}
              <span className="text-xs text-ink-faint">{endpoint.events.join(", ")}</span>
              {/* The fingerprint answers a different question per kind, so it says a
                  different thing per kind. For a webhook it identifies WHICH signing
                  secret this is; for a sheet `secret_ref` holds a secrets-manager
                  reference, so its presence means only "a Google credential is attached
                  yet or not" — and the row this screen can now CREATE always starts
                  without one. Printing `key ···null` there, which is what a single line
                  for both kinds produced, is the defect that would have shipped with the
                  sheets form. */}
              <span className="ml-auto text-xs text-ink-faint">
                {endpoint.kind === SHEET_KIND
                  ? endpoint.secret_fingerprint
                    ? "Google connection ready"
                    : "not connected to Google yet — deliveries will fail until we connect it"
                  : `key ···${endpoint.secret_fingerprint ?? "—"}`}
              </span>
              {endpoint.active ? (
                <button
                  type="button"
                  disabled={!write.allowed || busy}
                  onClick={() => onStop(endpoint)}
                  /* Named for the ROW. Five endpoints used to give a screen reader five
                     buttons announced identically — the defect `do-not-call` and
                     `settings/team` already fixed on their own list rows. */
                  aria-label={`Stop sending events to ${endpoint.url}`}
                  className={SECONDARY_BUTTON_SM}
                >
                  Stop sending events
                </button>
              ) : (
                /* The dead state explains itself. An `off` row carries no control at
                   all — there is no re-activate route on the API, only
                   `DELETE /v1/integrations/endpoints/{id}` — so without this sentence
                   the row reads as a button that failed to render. */
                <span className="text-xs text-ink-faint">
                  stopped — add a new endpoint to resume
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          title="No endpoints yet"
          hint="Add the web address your CRM gives you and we'll start sending leads the moment they arrive."
        />
      )}
    </Card>
  );
}
