"use client";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import type { WriteAccess } from "@/lib/api/hooks";
import { SHEET_KIND, eventLabel, useEndpoints, type Endpoint } from "@/lib/api/integrations";

/**
 * Every destination this account has registered, and the one thing you can do to each.
 *
 * "Stop sending events" stays a visible row button rather than a menu item: it ends a
 * client's lead feed immediately and cannot be undone here, and a high-consequence
 * control is never tucked away (UX-DOCTRINE §3). Its confirmation carries the cost.
 *
 * §52: a failed read AND a paused one (offline: not loading, no error, no data) are both
 * refused here, never shown as "No endpoints yet".
 */
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
  const columns: DataColumn<Endpoint>[] = [
    {
      id: "url",
      header: "Destination",
      cell: (endpoint) => (
        <div className="min-w-0 space-y-1">
          <p className="break-all font-mono text-xs text-ink">{endpoint.url}</p>
          <div className="flex flex-wrap gap-1.5">
            {endpoint.kind === SHEET_KIND && (
              <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-xs text-ink-muted">
                Google Sheet
              </span>
            )}
            {!endpoint.active && (
              <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-xs text-ink-muted">off</span>
            )}
          </div>
        </div>
      ),
    },
    {
      id: "events",
      header: "Sends",
      hideBelow: "md",
      cell: (endpoint) => (
        <span className="text-xs text-ink-muted">
          {endpoint.events.map((name) => eventLabel(name) ?? name).join(", ")}
        </span>
      ),
    },
    {
      id: "key",
      header: "Key",
      hideBelow: "sm",
      // The fingerprint answers a different question per kind: WHICH signing secret for a
      // webhook, and only "is a Google credential attached yet" for a sheet.
      cell: (endpoint) => (
        <span className="text-xs text-ink-faint">
          {endpoint.kind === SHEET_KIND
            ? endpoint.secret_fingerprint
              ? "Google connection ready"
              : "not connected to Google yet — deliveries will fail until we connect it"
            : `key ···${endpoint.secret_fingerprint ?? "—"}`}
        </span>
      ),
    },
    {
      id: "action",
      header: "Action",
      align: "right",
      cell: (endpoint) =>
        endpoint.active ? (
          <button
            type="button"
            disabled={!write.allowed || busy}
            onClick={() => onStop(endpoint)}
            aria-label={`Stop sending events to ${endpoint.url}`}
            className={SECONDARY_BUTTON_SM}
          >
            Stop sending events
          </button>
        ) : (
          // There is no re-activate route, so a stopped row says how to resume.
          <span className="text-xs text-ink-faint">stopped — add a new endpoint to resume</span>
        ),
    },
  ];

  return (
    <div className="border-y border-line">
      {endpoints.isLoading ? (
        <Skeleton rows={2} />
      ) : endpoints.error || !endpoints.data ? (
        <ProblemNotice
          error={endpoints.error ?? new Error("Your endpoints could not be loaded.")}
          onRetry={() => endpoints.refetch()}
        />
      ) : endpoints.data.length ? (
        <DataTable label="Your endpoints" rows={endpoints.data} columns={columns} getRowId={(e) => e.id} />
      ) : (
        <EmptyState message="No endpoints yet. Add the web address your CRM gives you and we'll send each lead as it arrives." />
      )}
    </div>
  );
}
