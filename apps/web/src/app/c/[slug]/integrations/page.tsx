"use client";

import { useState } from "react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  EVENT_LABELS,
  useCreateEndpoint,
  useDeactivateEndpoint,
  useDeliveries,
  useDeliveryPayload,
  useEndpoints,
  type OutboundEvent,
} from "@/lib/api/integrations";
import { lookup } from "@/lib/lookup";

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
 * 3. **"What did you send?" is answerable, and answering it is a privileged act.** The
 *    retained body is the customer's own details unredacted, so the link appears only
 *    for an owner (`calls:read_raw`) and only where a copy still exists — opening it
 *    writes an audit row, exactly like the raw transcript. Everyone else sees the
 *    delivery record and no offer, rather than a button that 403s.
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

export default function IntegrationsPage() {
  const session = useClientSession();

  const endpoints = useEndpoints(session);
  const deliveries = useDeliveries(session);
  const create = useCreateEndpoint(session);
  const deactivate = useDeactivateEndpoint(session);

  /**
   * D-22 read-only. Registering and turning off an endpoint are both `org:manage`
   * (integrations/routes.py) — mutating, so refused while impersonating. The two READS
   * on this screen deliberately sit on `org:read` so support keeps them: "did my CRM
   * get it?" is the question this screen exists to answer, and it is the question
   * support is asked.
   *
   * Turning an endpoint off is also where read-only earns its keep — an operator who
   * did it wearing the client's face would leave an audit trail saying the client
   * stopped their own integration.
   */
  const write = useWriteAccess(session, "org:manage", "change where events are sent");

  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<OutboundEvent[]>(["lead.created"]);
  const [revealed, setRevealed] = useState<string | null>(null);

  /**
   * The delivery whose body the client asked to see, or null.
   *
   * `calls:read_raw` gates the offer, read off `/v1/me` — the SERVER's answer about this
   * session — the same inline way the leads export does, and REFUSED while the answer is
   * in flight so the screen never offers an action it is about to withdraw. The
   * permission covers D-22 without a second condition: `operator` does not hold
   * `calls:read_raw` at all (core/rbac.py), so an impersonating support user keeps the
   * delivery log — which answers "did it arrive?" — and is never offered the payload.
   */
  const me = useMe(session);
  const mayReadPayload = me.data?.permissions?.includes("calls:read_raw") ?? false;
  const [openPayload, setOpenPayload] = useState<string | null>(null);
  const payload = useDeliveryPayload(session, openPayload);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Integrations</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Send your leads and call results to your own CRM or spreadsheet as they happen.
          Every request we send is signed so your system can verify it came from us.
        </p>
      </div>

      <RestrictionNote reason={write.reason} />

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
            disabled={!write.allowed || create.isPending || !url || events.length === 0}
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
                    disabled={!write.allowed || deactivate.isPending}
                    onClick={() => deactivate.mutate(endpoint.id)}
                    className="rounded-md border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-50 dark:border-slate-600"
                  >
                    Turn off
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : endpoints.error ? null : (
          <EmptyState
            title="No endpoints yet"
            hint="Add your CRM's webhook URL and we'll start sending leads the moment they arrive."
          />
        )}
      </Card>

      <Card title="Recent deliveries">
        {/* Without this the card falls through to "Nothing sent yet" on a 4xx —
            which is the exact wrong answer to "did my CRM get it?". */}
        {deliveries.error && (
          <div className="mb-3">
            <ProblemNotice error={deliveries.error} onRetry={() => deliveries.refetch()} />
          </div>
        )}
        {deliveries.isLoading ? (
          <Skeleton rows={3} />
        ) : deliveries.data?.length ? (
          <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[500px] text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="pb-2 font-medium">Event</th>
                <th className="pb-2 font-medium">Result</th>
                <th className="pb-2 font-medium">Tries</th>
                <th className="pb-2 text-right font-medium">When</th>
                {/* Only rendered for a reader who could use it. A permanently empty
                    column is a promise the screen cannot keep. */}
                {mayReadPayload && <th className="pb-2 text-right font-medium">Sent</th>}
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
                        lookup(STATUS_TONE, delivery.status) ?? "bg-slate-100 text-slate-600"
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
                  {mayReadPayload && (
                    <td className="py-2 text-right">
                      {delivery.payload_stored ? (
                        <button
                          type="button"
                          onClick={() =>
                            setOpenPayload((current) =>
                              current === delivery.id ? null : delivery.id,
                            )
                          }
                          title="Shows the exact data we sent, personal details included. The read is written to your audit log."
                          className="rounded-md border border-slate-300 px-2 py-0.5 text-xs dark:border-slate-600"
                        >
                          {openPayload === delivery.id ? "Hide" : "View"}
                        </button>
                      ) : (
                        // Not a blank cell and not a zero: a copy is kept only while the
                        // lead-retention policy allows, an erasure destroys it, and the
                        // events that name no customer never had one. "—" with the
                        // reason on hover says which kind of nothing this is.
                        <span
                          className="text-xs text-slate-400"
                          title="No copy is kept for this delivery — it has aged out under your retention policy, was erased, or the event carried no customer record."
                        >
                          —
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ) : deliveries.error ? null : (
          <EmptyState
            title="Nothing sent yet"
            hint="Deliveries appear here as they happen — including the ones your endpoint rejected."
          />
        )}

        {/* What we sent, for the one delivery someone opened.
            §52: loading is a skeleton, failure is a refusal in the client's own words
            (ProblemNotice renders the problem+json — including
            `delivery_body_not_retained`, which is a real answer and not an empty
            state), and neither is ever a number or a blank box. */}
        {openPayload && (
          <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-slate-900 dark:text-slate-50">
                What we sent
              </h3>
              <button
                type="button"
                onClick={() => setOpenPayload(null)}
                className="ml-auto rounded-md border border-slate-300 px-2 py-0.5 text-xs dark:border-slate-600"
              >
                Close
              </button>
            </div>
            {payload.isPending ? (
              <div className="mt-2">
                <Skeleton rows={3} />
              </div>
            ) : payload.error ? (
              <div className="mt-2">
                <ProblemNotice error={payload.error} />
              </div>
            ) : payload.data ? (
              <>
                <p className="mt-1 text-xs text-slate-500">
                  The exact request body your endpoint received. It contains your
                  customer&apos;s details, and this view was written to your audit log.
                </p>
                {payload.data.truncated && (
                  <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
                    Only the first part of this body is kept — it was{" "}
                    {payload.data.original_bytes.toLocaleString("en-IN")} bytes when we
                    sent it, and what you see below is where our copy stops.
                  </p>
                )}
                <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-slate-100 p-3 font-mono text-xs whitespace-pre-wrap break-all dark:bg-slate-800">
                  {payload.data.body}
                </pre>
              </>
            ) : null}
          </div>
        )}
      </Card>
    </div>
  );
}
