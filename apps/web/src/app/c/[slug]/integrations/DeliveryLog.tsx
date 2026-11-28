"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { CARD } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import type { WriteAccess } from "@/lib/api/hooks";
import {
  DELIVERY_STATUSES,
  EVENT_LABELS,
  eventLabel,
  useDeliveries,
  useDeliveryPayload,
  useEndpoints,
  useResumeEndpoint,
  useSendTestDelivery,
  type DeliveryStatus,
  type Endpoint,
  type OutboundEvent,
  type useResendDelivery,
} from "@/lib/api/integrations";
import { useClientSession } from "@/lib/api/session";
import { hasKey, lookup } from "@/lib/lookup";
import { StatusPill } from "@/components/console/statusPill";
import type { NoticeTone } from "@/components/ui";

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
const STATUS_TONE: Record<string, NoticeTone> = {
  delivered: "ok",
  failed: "stop",
  // Waiting for its next scheduled attempt (the webhook retry schedule, about a day).
  retrying: "warn",
  skipped: "neutral",
  // Kept while its destination is paused (D-1049); Resume sends it.
  held: "warn",
};

const ANY = "";

/** The Result filter's words: what the pill says, as a choice. */
const STATUS_WORDS: Record<DeliveryStatus, string> = {
  delivered: "Arrived",
  retrying: "Trying again",
  failed: "Did not arrive",
  skipped: "Not sent",
  held: "Kept while paused",
};

/**
 * Narrow the log, and act on a paused destination (D-1049). The filters go to the server
 * (`?endpoint_id=&status=&event=`), so a narrowed list is the last 50 of THAT kind, not the
 * matching few of the last 50. A webhook destination chosen here can be sent a test.
 */
function useLogControls(canResend: boolean) {
  const session = useClientSession();
  const endpoints = useEndpoints(session);
  const [endpointId, setEndpointId] = useState(ANY);
  const [status, setStatus] = useState<DeliveryStatus | typeof ANY>(ANY);
  const [event, setEvent] = useState<OutboundEvent | typeof ANY>(ANY);
  const filtered = Boolean(endpointId || status || event);
  const narrowed = useDeliveries(
    session,
    {
      endpointId: endpointId || undefined,
      status: status || undefined,
      event: event || undefined,
    },
    { enabled: filtered },
  );
  const test = useSendTestDelivery(session);
  const resume = useResumeEndpoint(session);
  // Both outcomes are said in place (the ProblemNotice and the status line below the
  // control), so the toast stack stays quiet.
  const testFeedback = useActionFeedback(test, { errorDisplay: "inline" });
  const resumeFeedback = useActionFeedback(resume, { errorDisplay: "inline" });
  // Undefined until the destinations arrive: a failed or parked read is never a list with
  // no destinations in it.
  const all = endpoints.data;
  const endpointsRead = endpoints.isLoading ? "loading" : endpoints.error || !all ? "failed" : "ready";
  return {
    endpointsRead,
    all,
    paused: canResend && all ? all.filter((e) => e.active && e.paused_at) : [],
    chosen: all?.find((e) => e.id === endpointId),
    endpointId,
    setEndpointId,
    status,
    setStatus,
    event,
    setEvent,
    filtered,
    narrowed,
    test,
    testFeedback,
    resume,
    resumeFeedback,
  };
}

function destinationName(endpoint: Endpoint): string {
  if (endpoint.kind === "google_sheets") return "Google Sheet";
  if (endpoint.kind === "leadsquared") return "LeadSquared";
  try {
    return new URL(endpoint.url ?? "").host || "Webhook";
  } catch {
    return "Webhook";
  }
}
export function DeliveryLog({
  deliveries,
  payloadAccess,
  mayReadPayload,
  openPayload,
  onTogglePayload,
  payload,
  payloadStatus,
  canResend,
  resend,
}: {
  deliveries: ReturnType<typeof useDeliveries>;
  payloadAccess: WriteAccess;
  mayReadPayload: boolean;
  openPayload: string | null;
  onTogglePayload: (deliveryId: string) => void;
  payload: ReturnType<typeof useDeliveryPayload>;
  /** The open request's state, shown on the row's View button. */
  payloadStatus: FeedbackStatus;
  /** May this reader send a failed delivery again (`org:manage`). */
  canResend: boolean;
  resend: ReturnType<typeof useResendDelivery>;
}) {
  const controls = useLogControls(canResend);
  const shown = controls.filtered ? controls.narrowed : deliveries;
  return (
    <Section title="Recent deliveries" description="What we sent to your destinations, and whether it arrived.">
      {controls.paused.map((endpoint) => (
        <div
          key={endpoint.id}
          role="status"
          className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-muted p-3 text-body"
        >
          <span className="text-ink">
            Paused: {destinationName(endpoint)} failed for three days.
            <span className="block text-meta text-ink-muted">Nothing is lost. Fix it, then resume.</span>
          </span>
          <ActionButton
            variant="secondary-sm"
            className="ml-auto"
            status={controls.resume.variables === endpoint.id ? controls.resumeFeedback.status : "idle"}
            retryable={controls.resumeFeedback.retryable}
            pendingLabel="Resuming…"
            disabled={controls.resume.isPending && controls.resume.variables !== endpoint.id}
            onClick={() => controls.resumeFeedback.run(endpoint.id)}
          >
            Resume
          </ActionButton>
        </div>
      ))}
      {controls.resume.error && <ProblemNotice error={controls.resume.error} />}
      {controls.resume.data?.resumed && (
        <p role="status" className="mb-3 text-meta text-ink-muted">
          Resumed. Sending {formatCount(controls.resume.data.replayed)} kept{" "}
          {controls.resume.data.replayed === 1 ? "delivery" : "deliveries"}, oldest first.
        </p>
      )}

      <div className="mb-3 flex flex-wrap items-end gap-2">
        {/* The destinations card above refuses a failed read with its retry; here the
            filter only steps aside, so the refusal is said once. */}
        {controls.endpointsRead === "ready" ? (
          <label className="min-w-40 flex-1">
            <span className={FIELD_LABEL}>Destination</span>
            <select
              className={FIELD}
              value={controls.endpointId}
              onChange={(e) => controls.setEndpointId(e.target.value)}
            >
              <option value={ANY}>All</option>
              {controls.all?.map((endpoint) => (
                <option key={endpoint.id} value={endpoint.id}>
                  {destinationName(endpoint)}
                  {endpoint.active ? "" : " (off)"}
                </option>
              ))}
            </select>
          </label>
        ) : controls.endpointsRead === "loading" ? (
          <div className="min-w-40 flex-1">
            <Skeleton rows={1} label="Loading your destinations…" />
          </div>
        ) : (
          <p className="min-w-40 flex-1 text-meta text-ink-muted">Your destinations did not load.</p>
        )}
        <label className="min-w-32 flex-1">
          <span className={FIELD_LABEL}>Result</span>
          <select
            className={FIELD}
            value={controls.status}
            onChange={(e) => {
              const next = DELIVERY_STATUSES.find((s) => s === e.target.value);
              controls.setStatus(next ?? ANY);
            }}
          >
            <option value={ANY}>Any</option>
            {DELIVERY_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_WORDS[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-40 flex-1">
          <span className={FIELD_LABEL}>Event</span>
          <select
            className={FIELD}
            value={controls.event}
            onChange={(e) => {
              const next = e.target.value;
              controls.setEvent(hasKey(EVENT_LABELS, next) ? next : ANY);
            }}
          >
            <option value={ANY}>Any</option>
            {Object.entries(EVENT_LABELS).map(([name, label]) => (
              <option key={name} value={name}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {canResend && controls.chosen?.kind === "webhook" && controls.chosen.active && (
          <ActionButton
            variant="secondary-sm"
            status={controls.testFeedback.status}
            retryable={controls.testFeedback.retryable}
            pendingLabel="Sending…"
            title="Sends one signed delivery with made-up data."
            onClick={() => controls.chosen && controls.testFeedback.run(controls.chosen.id)}
          >
            Send a test
          </ActionButton>
        )}
      </div>
      {controls.test.error && <ProblemNotice error={controls.test.error} />}
      {controls.test.isSuccess && (
        <p role="status" className="mb-3 text-meta text-ink-muted">
          Test sent. It shows below in a few seconds.
        </p>
      )}

      {/* Why the payload column is not here — said ONLY when the answer is ours rather
          than the server's. A staff reader who genuinely lacks `calls:read_raw` gets no
          column and no sentence, which is the deliberate design ("a permanently empty
          column is a promise the screen cannot keep"), and an impersonating operator
          already has the shell's read-only banner. `unknown` is the case that had no
          voice at all: a dead `/v1/me` withdrew the column exactly like a refusal. */}
      <RestrictionNote reason={payloadAccess.unknown ? payloadAccess.reason : null} />
      {resend.error && <ProblemNotice error={resend.error} />}

      {/* A failed read AND a paused one (offline: not loading, `error === null`,
          `data === undefined`) both refuse here, so the card never falls through to
          "Nothing sent yet" — the exact wrong answer to "did my CRM get it?" — on
          either non-answer. §52, the same shape as the endpoints card above. */}
      {shown.isLoading ? (
        <Skeleton rows={3} />
      ) : shown.error || !shown.data ? (
        <ProblemNotice
          error={shown.error ?? new Error("Your recent deliveries could not be loaded.")}
          onRetry={() => shown.refetch()}
        />
      ) : shown.data.length ? (
        <ScrollRegion label="Delivery log" className="scroll-shadow-x">
          {/* Stacked rows below `sm` (the DataTable card pattern): a 500px floor in a 360px
              phone left the result and its resend button off the right edge. */}
          <table className={`w-full text-body sm:min-w-[500px] ${CARD.table}`}>
          <thead className={CARD.head}>
            <tr className="text-left text-xs text-ink-faint">
              <th className="pb-2 font-semibold">Event</th>
              <th className="pb-2 font-semibold">Result</th>
              <th className="pb-2 font-semibold">Tries</th>
              <th className="pb-2 text-right font-semibold">When</th>
              {/* Only rendered for a reader who could use it. A permanently empty
                  column is a promise the screen cannot keep. */}
              {mayReadPayload && <th className="pb-2 text-right font-semibold">Sent</th>}
            </tr>
          </thead>
          <tbody className={`divide-y divide-line ${CARD.body}`}>
            {shown.data.map((delivery) => (
              <tr key={delivery.id} className={`${CARD.row} max-sm:px-0`}>
                <td className={`py-2 ${CARD.title}`}>
                  <span className="text-meta text-ink">
                    {delivery.event_type ? (eventLabel(delivery.event_type) ?? delivery.event_type) : "—"}
                  </span>
                  {delivery.is_test && <span className="ml-2 text-xs text-ink-muted">Test</span>}
                </td>
                <td data-label="Result" className={`py-2 ${CARD.field}`}>
                  <span className="max-sm:flex max-sm:flex-col max-sm:items-end">
                  <StatusPill tone={lookup(STATUS_TONE, delivery.status) ?? "neutral"} className="capitalize">
                    {delivery.status}
                  </StatusPill>
                  {delivery.next_attempt_at && (
                    <span className="mt-1 block text-xs text-ink-muted">
                      next try {formatIST(delivery.next_attempt_at)}
                    </span>
                  )}
                  {delivery.resendable && canResend && (
                    <ActionButton
                      variant="secondary-sm"
                      status={resend.isPending && resend.variables === delivery.id ? "pending" : "idle"}
                      pendingLabel="Sending…"
                      onClick={() => resend.mutate(delivery.id)}
                      // One resend at a time; the row being sent spins, the others hold.
                      disabled={resend.isPending && resend.variables !== delivery.id}
                      aria-label={`Send this ${eventLabel(delivery.event_type ?? "") ?? "delivery"} again`}
                      className="mt-1"
                    >
                      Send again
                    </ActionButton>
                  )}
                  </span>
                </td>
                <td data-label="Tries" className={`py-2 tabular-nums text-ink-muted ${CARD.field}`}>
                  {delivery.attempts}
                </td>
                <td data-label="When" className={`py-2 text-right text-xs text-ink-faint ${CARD.field}`}>
                  {formatIST(delivery.last_at)}
                </td>
                {mayReadPayload && (
                  <td data-label="Sent" className={`py-2 text-right ${CARD.field}`}>
                    {delivery.payload_stored ? (
                      <ActionButton
                        variant="secondary-sm"
                        status={openPayload === delivery.id && payloadStatus !== "success" ? payloadStatus : "idle"}
                        onClick={() => onTogglePayload(delivery.id)}
                        title="Shows the exact data we sent, personal details included."
                        pendingLabel="Opening…"
                      >
                        {openPayload === delivery.id ? "Hide" : "View"}
                      </ActionButton>
                    ) : (
                      // Not a blank cell and not a zero: a copy is kept only while the
                      // lead-retention policy allows, an erasure destroys it, and the
                      // events that name no customer never had one. "—" with the
                      // reason on hover says which kind of nothing this is.
                      <span
                        className="text-xs text-ink-faint"
                        title="No copy kept: too old, erased, or no customer in it."
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
          illustration={<EmptySketch kind="deliveries" />}
          message="Nothing sent yet."
          hint="Every delivery shows here, even refused ones."
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
            <h3 className="text-body font-semibold text-ink">
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
                Exactly what it received. Holds customer details.
              </p>
              {payload.data.truncated && (
                <p className="mt-2 text-xs text-warn">
                  Only the first part of this body is kept. The full body was{" "}
                  {formatCount(payload.data.original_bytes)} bytes.
                </p>
              )}
              {/* Focusable for the same reason every `ScrollRegion` is, on the other
                  axis: `max-h-80` makes this a VERTICALLY scrolling container, and
                  there is no key that scrolls a non-focusable element, so a keyboard
                  reader could see the first 320px of a payload and no more. Not
                  `ScrollRegion` itself — that component is the sideways case and
                  hardcodes `overflow-x-auto`; the waiver's argument is written there.
                  Plain text, not the kit's JSON tree: this is the forensic record of what
                  the endpoint received, so it is shown byte for byte, and a tree would
                  re-render escapes, spacing and a truncated tail. */}
              <pre
                role="region"
                aria-label="Delivered payload"
                // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- see above
                tabIndex={0}
                className="mt-2 max-h-80 overflow-auto rounded-md bg-surface-muted p-3 font-mono text-xs whitespace-pre-wrap break-all"
              >
                {payload.data.body}
              </pre>
            </>
          ) : null}
        </div>
      )}
    </Section>
  );
}
