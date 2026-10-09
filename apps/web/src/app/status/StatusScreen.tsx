"use client";

import { CircleCheck, CircleAlert, CircleX } from "lucide-react";

import { formatIST } from "@/components/ui";
import {
  COMPONENT_STATE_WORDS,
  usePublicStatus,
  type StatusComponent,
  type StatusIncident,
} from "@/lib/api/statusPage";

const STATE_ICON = {
  operational: CircleCheck,
  degraded: CircleAlert,
  outage: CircleX,
} as const;

const STATE_TONE: Record<StatusComponent["state"], string> = {
  operational: "text-emerald-700 dark:text-emerald-300",
  degraded: "text-warn",
  outage: "text-danger",
};

/**
 * Each part of the service with its state in words (colour is the second channel, never
 * the only one), then what has been posted. A read that fails says so rather than
 * painting everything green.
 */
export function StatusScreen() {
  const status = usePublicStatus();
  const data = status.data;
  const allWell = data?.components.every((c) => c.state === "operational") ?? false;
  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-12 sm:px-6 sm:py-16">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          Service status
        </h1>
        <p className="text-sm text-ink-muted" aria-live="polite">
          {status.isLoading
            ? "Checking…"
            : !data
              ? "We could not load the current status. Please try again in a minute."
              : allWell
                ? "Everything is working normally."
                : "Some parts of the service have problems. Details below."}
        </p>
      </header>

      {data && (
        <section aria-labelledby="status-components" className="space-y-3">
          <h2 id="status-components" className="text-lg font-semibold text-ink">
            Right now
          </h2>
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {data.components.map((component) => {
              const Icon = STATE_ICON[component.state];
              return (
                <li
                  key={component.key}
                  className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
                >
                  <span className="text-sm font-medium text-ink">{component.name}</span>
                  <span
                    className={`inline-flex items-center gap-1.5 text-sm font-medium ${STATE_TONE[component.state]}`}
                  >
                    <Icon aria-hidden className="h-4 w-4" />
                    {COMPONENT_STATE_WORDS[component.state]}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-ink-faint">Updated {formatIST(data.updated_at)}</p>
        </section>
      )}

      {data && (
        <section aria-labelledby="status-history" className="space-y-3">
          <h2 id="status-history" className="text-lg font-semibold text-ink">
            Recent problems
          </h2>
          {data.incidents.length === 0 ? (
            <p className="text-sm text-ink-muted">Nothing in the last 90 days.</p>
          ) : (
            <ul className="space-y-3">
              {data.incidents.map((incident) => (
                <IncidentRow key={incident.id} incident={incident} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function IncidentRow({ incident }: { incident: StatusIncident }) {
  return (
    <li className="rounded-card border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-ink">{incident.title}</p>
        <span className="text-xs font-medium text-ink-muted">
          {incident.state === "ongoing" ? "Ongoing" : "Resolved"}
        </span>
      </div>
      <p className="mt-1 text-xs text-ink-faint">
        Started {formatIST(incident.started_at)}
        {incident.resolved_at && <> · resolved {formatIST(incident.resolved_at)}</>}
      </p>
    </li>
  );
}
