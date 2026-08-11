"use client";

import { use, useState } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { devSession } from "@/lib/api/client";
import {
  EVENT_LABELS,
  useCreateEndpoint,
  useDeactivateEndpoint,
  useDeliveries,
  useEndpoints,
  type OutboundEvent,
} from "@/lib/api/integrations";

/**
 * Outbound sync (D-23) and its delivery log (SURFACES §2b).
 *
 * Two decisions this screen makes visible rather than hiding:
 *
 * 1. **The signing secret appears once.** It is rendered on creation and never
 *    re-fetchable, because a settings page that re-displays a shared secret turns
 *    every screenshot and screen-share into a key disclosure. The list shows a
 *    fingerprint so two endpoints can still be told apart.
 * 2. **Deliveries are shown, including the failures.** An integration that quietly
 *    stops is worse than one that visibly breaks — the client needs to see the 500s
 *    their own endpoint returned before they conclude we never sent anything.
 */

const ALL_EVENTS: OutboundEvent[] = [
  "lead.created",
  "lead.updated",
  "call.completed",
  "campaign.completed",
];

const STATUS_TONE: Record<string, string> = {
  delivered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  skipped: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

export default function IntegrationsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = devSession(slug);

  const endpoints = useEndpoints(session);
  const deliveries = useDeliveries(session);
  const create = useCreateEndpoint(session);
  const deactivate = useDeactivateEndpoint(session);

  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<OutboundEvent[]>(["lead.created"]);
  const [revealed, setRevealed] = useState<string | null>(null);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Integrations</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Send your leads and call results to your own CRM or spreadsheet as they happen.
          Every request we send is signed so your system can verify it came from us.
        </p>
      </div>

      {endpoints.error && (
        <ProblemNotice error={endpoints.error} onRetry={() => endpoints.refetch()} />
      )}
      {create.error && <ProblemNotice error={create.error} />}
      {deactivate.error && <ProblemNotice error={deactivate.error} />}

      {revealed && (
        <Card title="Your signing secret">
          <p className="text-sm text-slate-700 dark:text-slate-300">
            Copy this now — we will not show it again.
          </p>
          <code className="mt-2 block break-all rounded-md bg-slate-100 p-3 font-mono text-xs dark:bg-slate-800">
            {revealed}
          </code>
          <p className="mt-2 text-xs text-slate-500">
            Your endpoint should verify the <code>X-Calevate-Signature</code> header:
            HMAC-SHA256 of <code>{"{timestamp}.{body}"}</code> using this secret, and
            reject anything older than five minutes.
          </p>
          <button
            type="button"
            onClick={() => setRevealed(null)}
            className="mt-3 rounded-md border border-slate-300 px-3 py-1 text-xs dark:border-slate-600"
          >
            I&apos;ve saved it
          </button>
        </Card>
      )}

      <Card title="Where to send events">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { url, events },
              {
                onSuccess: (data) => {
                  setRevealed(data.secret);
                  setUrl("");
                },
              },
            );
          }}
        >
          <input
            required
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-crm.example.com/calevate"
            className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium text-slate-600 dark:text-slate-300">
              Send when…
            </legend>
            {ALL_EVENTS.map((event) => (
              <label key={event} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={events.includes(event)}
                  onChange={(e) =>
                    setEvents((current) =>
                      e.target.checked
                        ? [...current, event]
                        : current.filter((x) => x !== event),
                    )
                  }
                />
                <span className="text-slate-700 dark:text-slate-300">{EVENT_LABELS[event]}</span>
                <code className="text-xs text-slate-400">{event}</code>
              </label>
            ))}
          </fieldset>
          <button
            type="submit"
            disabled={create.isPending || !url || events.length === 0}
            className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {create.isPending ? "Adding…" : "Add endpoint"}
          </button>
        </form>
      </Card>

      <Card title="Your endpoints">
        {endpoints.isLoading ? (
          <Skeleton rows={2} />
        ) : endpoints.data?.length ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {endpoints.data.map((endpoint) => (
              <li key={endpoint.id} className="flex flex-wrap items-center gap-2 py-2.5">
                <span className="break-all font-mono text-xs text-slate-700 dark:text-slate-300">
                  {endpoint.url}
                </span>
                {!endpoint.active && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800">
                    off
                  </span>
                )}
                <span className="text-xs text-slate-500">{endpoint.events.join(", ")}</span>
                <span className="ml-auto text-xs text-slate-400">
                  key ···{endpoint.secret_fingerprint}
                </span>
                {endpoint.active && (
                  <button
                    type="button"
                    disabled={deactivate.isPending}
                    onClick={() => deactivate.mutate(endpoint.id)}
                    className="rounded-md border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-50 dark:border-slate-600"
                  >
                    Turn off
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No endpoints yet"
            hint="Add your CRM's webhook URL and we'll start sending leads the moment they arrive."
          />
        )}
      </Card>

      <Card title="Recent deliveries">
        {deliveries.isLoading ? (
          <Skeleton rows={3} />
        ) : deliveries.data?.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="pb-2 font-medium">Event</th>
                <th className="pb-2 font-medium">Result</th>
                <th className="pb-2 font-medium">Tries</th>
                <th className="pb-2 text-right font-medium">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {deliveries.data.map((delivery) => (
                <tr key={delivery.id}>
                  <td className="py-2">
                    <code className="text-xs">{delivery.event_type}</code>
                  </td>
                  <td className="py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        STATUS_TONE[delivery.status ?? ""] ?? "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {delivery.status}
                    </span>
                  </td>
                  <td className="py-2 tabular-nums text-slate-600 dark:text-slate-400">
                    {delivery.attempts}
                  </td>
                  <td className="py-2 text-right text-xs text-slate-500">
                    {formatIST(delivery.last_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState
            title="Nothing sent yet"
            hint="Deliveries appear here as they happen — including the ones your endpoint rejected."
          />
        )}
      </Card>
    </div>
  );
}
