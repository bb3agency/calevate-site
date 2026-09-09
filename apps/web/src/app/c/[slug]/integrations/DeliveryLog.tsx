"use client";

import {
  Card,
  EmptyState,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatIST,
} from "@/components/ui";
import type { WriteAccess } from "@/lib/api/hooks";
import { useDeliveries, useDeliveryPayload } from "@/lib/api/integrations";
import { lookup } from "@/lib/lookup";

/**
 * DELIVERIES ARE SHOWN, INCLUDING THE FAILURES. An integration that quietly stops is
 * worse than one that visibly breaks — the client needs to see the 500s their own
 * endpoint returned before they conclude we never sent anything.
 *
 * "What did you send?" is answerable, and answering it is a privileged act: the retained
 * body is the customer's own details unredacted, so the link appears only for a reader the
 * server says holds `calls:read_raw` and only where a copy still exists — opening it
 * writes an audit row, exactly like the raw transcript.
 */

/**
 * The delivery-status badges. `delivered` and `failed` keep their palette literals — a
 * badge brings its OWN ground, so it is the case `tests/contrast.test.ts` puts out of
 * scope by name ("Ink on a non-token background … the status badges") and the browser
 * axe run is what sees it. `skipped` is the neutral one, and it is written in tokens
 * because "neutral" IS the surface family: `bg-black/5 … text-ink-muted` is what the
 * do-not-call and team rows already use for a colourless pill, and a second spelling of
 * plain grey is where the two drift.
 */
const STATUS_TONE: Record<string, string> = {
  delivered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  skipped: "bg-black/5 text-ink-muted dark:bg-white/10",
};

export function DeliveryLog({
  deliveries,
  payloadAccess,
  mayReadPayload,
  openPayload,
  onTogglePayload,
  payload,
}: {
  deliveries: ReturnType<typeof useDeliveries>;
  payloadAccess: WriteAccess;
  mayReadPayload: boolean;
  openPayload: string | null;
  onTogglePayload: (deliveryId: string) => void;
  payload: ReturnType<typeof useDeliveryPayload>;
}) {
  return (
    <Card title="Recent deliveries">
      {/* Why the payload column is not here — said ONLY when the answer is ours rather
          than the server's. A staff reader who genuinely lacks `calls:read_raw` gets no
          column and no sentence, which is the deliberate design ("a permanently empty
          column is a promise the screen cannot keep"), and an impersonating operator
          already has the shell's read-only banner. `unknown` is the case that had no
          voice at all: a dead `/v1/me` withdrew the column exactly like a refusal. */}
      <RestrictionNote reason={payloadAccess.unknown ? payloadAccess.reason : null} />

      {/* A failed read AND a paused one (offline: not loading, `error === null`,
          `data === undefined`) both refuse here, so the card never falls through to
          "Nothing sent yet" — the exact wrong answer to "did my CRM get it?" — on
          either non-answer. §52, the same shape as the endpoints card above. */}
      {deliveries.isLoading ? (
        <Skeleton rows={3} />
      ) : deliveries.error || !deliveries.data ? (
        <ProblemNotice
          error={deliveries.error ?? new Error("Your recent deliveries could not be loaded.")}
          onRetry={() => deliveries.refetch()}
        />
      ) : deliveries.data.length ? (
        <ScrollRegion label="Delivery log" className="-mx-4 px-4 sm:mx-0 sm:px-0">
          <table className="w-full min-w-[500px] text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-ink-faint">
              <th className="pb-2 font-medium">Event</th>
              <th className="pb-2 font-medium">Result</th>
              <th className="pb-2 font-medium">Tries</th>
              <th className="pb-2 text-right font-medium">When</th>
              {/* Only rendered for a reader who could use it. A permanently empty
                  column is a promise the screen cannot keep. */}
              {mayReadPayload && <th className="pb-2 text-right font-medium">Sent</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {deliveries.data.map((delivery) => (
              <tr key={delivery.id}>
                <td className="py-2">
                  <code className="text-xs">{delivery.event_type}</code>
                </td>
                <td className="py-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      lookup(STATUS_TONE, delivery.status) ??
                      "bg-black/5 text-ink-muted dark:bg-white/10"
                    }`}
                  >
                    {delivery.status}
                  </span>
                </td>
                <td className="py-2 tabular-nums text-ink-muted">
                  {delivery.attempts}
                </td>
                <td className="py-2 text-right text-xs text-ink-faint">
                  {formatIST(delivery.last_at)}
                </td>
                {mayReadPayload && (
                  <td className="py-2 text-right">
                    {delivery.payload_stored ? (
                      <button
                        type="button"
                        onClick={() => onTogglePayload(delivery.id)}
                        title="Shows the exact data we sent, personal details included. The read is written to your audit log."
                        className={SECONDARY_BUTTON_SM}
                      >
                        {openPayload === delivery.id ? "Hide" : "View"}
                      </button>
                    ) : (
                      // Not a blank cell and not a zero: a copy is kept only while the
                      // lead-retention policy allows, an erasure destroys it, and the
                      // events that name no customer never had one. "—" with the
                      // reason on hover says which kind of nothing this is.
                      <span
                        className="text-xs text-ink-faint"
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
        </ScrollRegion>
      ) : (
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
        <div className="mt-4 border-t border-line pt-4">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-ink">
              What we sent
            </h3>
            <button
              type="button"
              onClick={() => onTogglePayload(openPayload)}
              className={`ml-auto ${SECONDARY_BUTTON_SM}`}
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
              <p className="mt-1 text-xs text-ink-faint">
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
              {/* Focusable for the same reason every `ScrollRegion` is, on the other
                  axis: `max-h-80` makes this a VERTICALLY scrolling container, and
                  there is no key that scrolls a non-focusable element, so a keyboard
                  reader could see the first 320px of a payload and no more. Not
                  `ScrollRegion` itself — that component is the sideways case and
                  hardcodes `overflow-x-auto`; the waiver's argument is written there. */}
              <pre
                role="region"
                aria-label="Delivered payload"
                // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- see above
                tabIndex={0}
                className="mt-2 max-h-80 overflow-auto rounded-md bg-app p-3 font-mono text-xs whitespace-pre-wrap break-all"
              >
                {payload.data.body}
              </pre>
            </>
          ) : null}
        </div>
      )}
    </Card>
  );
}
