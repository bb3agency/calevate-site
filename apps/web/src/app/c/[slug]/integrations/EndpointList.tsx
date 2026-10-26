"use client";

import { Webhook } from "lucide-react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { IconTile } from "@/components/console/iconTile";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatIST } from "@/components/ui";
import type { WriteAccess } from "@/lib/api/hooks";
import { SHEET_KIND, eventLabel, useEndpoints, type Endpoint } from "@/lib/api/integrations";
import { StatusPill } from "@/components/console/statusPill";

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
  onRotate,
}: {
  endpoints: ReturnType<typeof useEndpoints>;
  write: WriteAccess;
  busy: boolean;
  onStop: (endpoint: Endpoint) => void;
  /** Offer a new signing secret for an active webhook (not a sheet, which has none). */
  onRotate: (endpoint: Endpoint) => void;
}) {
  const columns: DataColumn<Endpoint>[] = [
    {
      id: "url",
      header: "Destination",
      cell: (endpoint) => (
        <div className="flex min-w-0 items-start gap-3">
        <IconTile service={endpoint.kind === SHEET_KIND ? "google_sheets" : null} icon={Webhook} />
        <div className="min-w-0 space-y-1">
          <p className="break-all font-mono text-xs text-ink">{endpoint.url}</p>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {endpoint.kind === SHEET_KIND && (
              <span className="text-meta text-ink-muted">
                Google Sheet
              </span>
            )}
            {!endpoint.active && (
              <StatusPill>Off</StatusPill>
            )}
          </div>
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
          {endpoint.previous_secret_expires_at && (
            <span className="block">
              old key also signs until {formatIST(endpoint.previous_secret_expires_at)}
            </span>
          )}
        </span>
      ),
    },
    {
      id: "action",
      header: "Action",
      align: "right",
      cell: (endpoint) =>
        endpoint.active ? (
          <div className="flex flex-wrap justify-end gap-2">
            {endpoint.kind !== SHEET_KIND && (
              <button
                type="button"
                disabled={!write.allowed || busy}
                onClick={() => onRotate(endpoint)}
                aria-label={`New signing secret for ${endpoint.url}`}
                className={SECONDARY_BUTTON_SM}
              >
                New signing secret
              </button>
            )}
            <button
              type="button"
              disabled={!write.allowed || busy}
              onClick={() => onStop(endpoint)}
              aria-label={`Stop sending events to ${endpoint.url}`}
              className={SECONDARY_BUTTON_SM}
            >
              Stop sending events
            </button>
          </div>
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
        <EmptyState
          illustration={<EmptySketch kind="deliveries" />}
          message="No endpoints yet."
          hint="Add the web address your CRM gives you and we'll send each lead as it arrives."
        />
      )}
    </div>
  );
}
