"use client";

import { useState } from "react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  ScrollRegion,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ApiProblem, type Session } from "@/lib/api/client";
import { useWriteAccess, type WriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  EVENT_LABELS,
  SHEETS_UNAVAILABLE_CODE,
  SHEET_KIND,
  eventLabel,
  useCreateEndpoint,
  useCreateSheetsEndpoint,
  useDeactivateEndpoint,
  useDeliveries,
  useDeliveryPayload,
  useEndpointOptions,
  useEndpoints,
  type OutboundEvent,
} from "@/lib/api/integrations";
import { hasKey, lookup } from "@/lib/lookup";

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

const STATUS_TONE: Record<string, string> = {
  delivered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  skipped: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

export default function IntegrationsPage() {
  const session = useClientSession();

  const endpoints = useEndpoints(session);
  const deliveries = useDeliveries(session);
  const deactivate = useDeactivateEndpoint(session);
  /**
   * The two facts both forms are built from, in one read: the SERVER's list of
   * subscribable events (this screen used to carry its own copy) and whether this
   * deployment can deliver to a Google Sheet at all.
   *
   * One read, shared, so the two forms can never offer different events — and so the
   * screen can never hold the events without the capability and render half a decision.
   */
  const options = useEndpointOptions(session);

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

  const [revealed, setRevealed] = useState<string | null>(null);

  /**
   * The delivery whose body the client asked to see, or null.
   *
   * `calls:read_raw` gates the offer, read off `/v1/me` — the SERVER's answer about this
   * session — and REFUSED while the answer is in flight so the screen never offers an
   * action it is about to withdraw. It used to say more than that: `operator` held no raw
   * permission at all, so an impersonating support user was never offered the payload by
   * construction. The founder's correction to D-457 moved `calls:read_raw` into the
   * normal admin tier, so BOTH tiers are now offered it inside a view-as session — which
   * is the same answer this line already gave for a `superadmin`, and it is still the
   * server's answer rather than this screen's guess. What stands behind the offer is
   * unchanged: the API checks the permission, and the handler writes an `audit_log` row
   * before the body is fetched.
   *
   * Through `useWriteAccess` rather than inline, which is the whole of the fix: the line
   * this replaced was `me.data?.permissions?.includes("calls:read_raw") ?? false`, and
   * `me.data` is undefined while `/v1/me` is in flight AND after it fails. So a request
   * that never landed withdrew the column and said nothing — an owner who holds the
   * permission shown a screen implying a refusal they never received. `useWriteAccess`
   * fails closed the same way and answers "We could not check whether you can …", which
   * is the difference between a refusal and a silence. (Not a mutating permission, so
   * "write" is the helper's name rather than this call's meaning; it is the one place
   * this console asks "may this session do X", and a second way to ask would be the
   * drift CLAUDE.md's "one way per problem" is about.)
   */
  const payloadAccess = useWriteAccess(session, "calls:read_raw", "open a delivered payload");
  const mayReadPayload = payloadAccess.allowed;
  const [openPayload, setOpenPayload] = useState<string | null>(null);
  const payload = useDeliveryPayload(session);
  /**
   * Open = ask the server for THIS delivery. Close, or switch to another row, = throw the
   * previous answer away first.
   *
   * Both halves matter. Asking every time is what makes the audit trail count looks
   * rather than sessions (`useDeliveryPayload`). Resetting is what stops the panel showing
   * the last body for the instant before the new request lands — which on a SWITCH would
   * be a different customer's details under the new row's heading.
   */
  const togglePayload = (deliveryId: string) => {
    payload.reset();
    if (openPayload === deliveryId) {
      setOpenPayload(null);
      return;
    }
    setOpenPayload(deliveryId);
    payload.mutate(deliveryId);
  };

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

      {/* The endpoints READ failure is refused inside the "Your endpoints" card below —
          together with the paused read, so a non-answer never renders as "No endpoints
          yet" (§52). A page-level copy here would double the refusal on a failure. */}
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
            Your system should check the <code>X-Calevate-Signature</code> header on each
            request: it is the HMAC-SHA256 of <code>{"{timestamp}.{body}"}</code> using this
            secret. Reject anything older than five minutes. This is how your system confirms a
            request really came from us.
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

      {/* Both forms are built from ONE read, so neither can be rendered from a list we do
          not have. §52: a skeleton while it is in flight, the refusal when it failed —
          and NOT a fallback list, which would offer a subscription the server may no
          longer accept and would hide the failure behind four plausible checkboxes.
          The Sheets branch below is inside the SUCCESS arm on purpose: "Sheets is not
          available here" is a fact the server told us, never something we conclude from
          not having heard. */}
      {options.isLoading ? (
        <Card title="Where to send events">
          <Skeleton rows={4} />
        </Card>
      ) : options.error || !options.data ? (
        <Card title="Where to send events">
          <ProblemNotice
            error={
              options.error ??
              new Error("We could not load the list of events you can subscribe to.")
            }
            onRetry={() => void options.refetch()}
          />
        </Card>
      ) : (
        <>
          <WebhookForm
            session={session}
            catalogue={options.data.events}
            write={write}
            onSecret={setRevealed}
          />
          {options.data.sheets_delivery_available ? (
            <SheetsForm session={session} catalogue={options.data.events} write={write} />
          ) : (
            /* The form is GONE, not disabled — the state every deployment is in today.
               `sheets_delivery_available` is the server's own selector, so this is not a
               client-side guess about a server rule; it is the server's answer, rendered.
               The words are ours because the server sent a boolean and not a sentence
               (the shape `KycRecordOut.number_purchase_available` set, and the shape the
               verification screen's "Buying a phone number" card renders from), and they
               name the remediation the API names in its own refusal so a client who meets
               both hears one story. */
            <SheetsUnavailable
              headline="Google Sheets delivery is not switched on for your account."
              remediation="Set up a delivery to your own system above instead, or ask us to switch Google Sheets on for you."
              footnote="There is nothing to fill in here yet — this form appears on its own once Sheets is enabled for your account."
            />
          )}
        </>
      )}

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
                {endpoint.kind === SHEET_KIND && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    Google Sheet
                  </span>
                )}
                <span className="text-xs text-slate-500">{endpoint.events.join(", ")}</span>
                {/* The fingerprint answers a different question per kind, so it says a
                    different thing per kind. For a webhook it identifies WHICH signing
                    secret this is; for a sheet `secret_ref` holds a secrets-manager
                    reference, so its presence means only "a Google credential is attached
                    yet or not" — and the row this screen can now CREATE always starts
                    without one. Printing `key ···null` there, which is what a single line
                    for both kinds produced, is the defect that would have shipped with the
                    sheets form. */}
                <span className="ml-auto text-xs text-slate-400">
                  {endpoint.kind === SHEET_KIND
                    ? endpoint.secret_fingerprint
                      ? "Google connection ready"
                      : "not connected to Google yet — deliveries will fail until we connect it"
                    : `key ···${endpoint.secret_fingerprint ?? "—"}`}
                </span>
                {endpoint.active && (
                  <button
                    type="button"
                    disabled={!write.allowed || deactivate.isPending}
                    onClick={() => deactivate.mutate(endpoint.id)}
                    className="rounded-md border border-slate-300 px-2 py-1.5 text-xs disabled:opacity-50 dark:border-slate-600"
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
            hint="Add the web address your CRM gives you and we'll start sending leads the moment they arrive."
          />
        )}
      </Card>

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
                          onClick={() => togglePayload(delivery.id)}
                          title="Shows the exact data we sent, personal details included. The read is written to your audit log."
                          className="rounded-md border border-slate-300 px-2 py-1.5 text-xs dark:border-slate-600"
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
          <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-slate-900 dark:text-slate-50">
                What we sent
              </h3>
              <button
                type="button"
                onClick={() => togglePayload(openPayload)}
                className="ml-auto rounded-md border border-slate-300 px-2 py-1.5 text-xs dark:border-slate-600"
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
                  className="mt-2 max-h-80 overflow-auto rounded-md bg-slate-100 p-3 font-mono text-xs whitespace-pre-wrap break-all dark:bg-slate-800"
                >
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

/** The form language of this screen, in one place rather than per control. */
const INPUT =
  "mt-1 w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950";
const FIELD_LABEL = "text-xs font-medium text-slate-600 dark:text-slate-300";
const SUBMIT =
  "rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900";

/**
 * The event checkboxes, from the catalogue the SERVER published.
 *
 * One component for both forms, because two copies of a list is where the two transports
 * start offering different subscriptions.
 *
 * An entry the catalogue names and this build has no copy for is rendered rather than
 * hidden — but NOT as a checkbox: `CreateEndpointIn.events` is a generated literal union,
 * so a name outside it cannot be put in a typed request body, and a checkbox that could
 * only produce a 422 is the dead control this whole slice exists to remove. It means our
 * OpenAPI snapshot is behind the deployment, which is a fact worth saying on screen once
 * rather than a checkbox worth faking.
 */
function EventChoices({
  catalogue,
  selected,
  onToggle,
  disabled,
}: {
  catalogue: string[];
  selected: OutboundEvent[];
  onToggle: (event: OutboundEvent, on: boolean) => void;
  disabled: boolean;
}) {
  const unknown = catalogue.filter((name) => !hasKey(EVENT_LABELS, name));
  return (
    <fieldset className="space-y-1.5">
      <legend className={FIELD_LABEL}>Send when…</legend>
      {catalogue.filter((name) => hasKey(EVENT_LABELS, name)).map((name) => (
        <label key={name} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={hasKey(EVENT_LABELS, name) && selected.includes(name)}
            disabled={disabled}
            onChange={(e) => {
              if (hasKey(EVENT_LABELS, name)) onToggle(name, e.target.checked);
            }}
          />
          <span className="text-slate-700 dark:text-slate-300">{eventLabel(name)}</span>
          <code className="text-xs text-slate-400">{name}</code>
        </label>
      ))}
      {unknown.length > 0 && (
        <p className="text-xs text-slate-500">
          This account can also receive {unknown.join(", ")}, which this version of the
          console cannot subscribe to yet. Tell us and we will set it up.
        </p>
      )}
    </fieldset>
  );
}

/**
 * Register a webhook. Unchanged in behaviour; it now draws its events from the catalogue
 * and lives in its own component so the Sheets form beside it can hold its own state.
 */
function WebhookForm({
  session,
  catalogue,
  write,
  onSecret,
}: {
  session: Session;
  catalogue: string[];
  write: WriteAccess;
  onSecret: (secret: string) => void;
}) {
  const create = useCreateEndpoint(session);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<OutboundEvent[]>(["lead.created"]);
  // The three `call.completed` opt-ins. All start OFF, matching the server default and
  // the base contract (summary and outcome only). `includeRawTranscript` is layered on
  // `includeTranscript` — the server refuses raw without redacted — so the checkbox is
  // disabled until the redacted transcript is on, and turning that off clears raw too.
  const [includeRecordingUrl, setIncludeRecordingUrl] = useState(false);
  const [includeTranscript, setIncludeTranscript] = useState(false);
  const [includeRawTranscript, setIncludeRawTranscript] = useState(false);
  // Only meaningful when the client subscribes to `call.completed`; otherwise nothing
  // carries them. Shown regardless so the choice is visible, but the copy says so.
  const callCompletedSelected = events.includes("call.completed");

  return (
    <Card title="Send events to your own system">
      {create.error && (
        <div className="mb-3">
          <ProblemNotice error={create.error} />
        </div>
      )}
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            {
              url,
              events,
              include_recording_url: includeRecordingUrl,
              include_transcript: includeTranscript,
              // Never send raw without redacted, matching the server's own rule; the UI
              // already keeps them in step, and this is the belt to that braces.
              include_raw_transcript: includeTranscript && includeRawTranscript,
            },
            {
              onSuccess: (data) => {
                onSecret(data.secret);
                setUrl("");
              },
            },
          );
        }}
      >
        {/* A PERSISTENT label, not the placeholder alone. axe's `label` rule accepts a
            placeholder as an accessible name (tests/a11y.ts says so, and it is why this
            defect survived the sweep going green), but the text disappears the moment
            somebody types — which is WCAG 3.3.2's entire complaint, and worst for the
            reader who most needs to re-check what a field wanted. The rest of the
            console labels its fields this way; this input was the exception. */}
        <label className="block">
          <span className={FIELD_LABEL}>Where should we send them?</span>
          <input
            required
            type="url"
            value={url}
            disabled={!write.allowed}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-crm.example.com/calevate"
            className={INPUT}
          />
        </label>
        <EventChoices
          catalogue={catalogue}
          selected={events}
          disabled={!write.allowed}
          onToggle={(event, on) =>
            setEvents((current) =>
              on ? [...current, event] : current.filter((x) => x !== event),
            )
          }
        />
        {/* The `call.completed` extras. Off by default: the base body is the summary and
            the outcome, and each of these sends more of the customer's own data to your
            endpoint, so each is a deliberate choice. */}
        <fieldset className="space-y-1.5 rounded-md border border-slate-200 p-3 dark:border-slate-700">
          <legend className={`${FIELD_LABEL} px-1`}>When a call finishes, also send…</legend>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={includeRecordingUrl}
              disabled={!write.allowed}
              onChange={(e) => setIncludeRecordingUrl(e.target.checked)}
            />
            <span className="text-slate-700 dark:text-slate-300">
              A link to the call recording
              <span className="block text-xs text-slate-500">
                A short-lived, signed link to our copy of the audio — not the audio itself.
                It expires within minutes, so fetch it as soon as you receive it.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={includeTranscript}
              disabled={!write.allowed}
              onChange={(e) => {
                const on = e.target.checked;
                setIncludeTranscript(on);
                // Raw can never outlive redacted — the server refuses that pairing.
                if (!on) setIncludeRawTranscript(false);
              }}
            />
            <span className="text-slate-700 dark:text-slate-300">
              The transcript, redacted
              <span className="block text-xs text-slate-500">
                The conversation with personal details (numbers, IDs, OTPs) masked — the
                same text your team sees on the call screen.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={includeRawTranscript}
              // The second opt-in only makes sense on top of the first, and the server
              // requires it — so the control is dead until the redacted transcript is on.
              disabled={!write.allowed || !includeTranscript}
              onChange={(e) => setIncludeRawTranscript(e.target.checked)}
            />
            <span className="text-slate-700 dark:text-slate-300">
              The transcript, unredacted
              <span className="block text-xs text-amber-700 dark:text-amber-400">
                Sends the FULL transcript — every phone number, ID and OTP spoken on the
                call — to your endpoint in the clear. Only turn this on if your system is
                allowed to hold that data. Turning it on needs the same permission as
                reading a raw transcript, and every delivery that carries it is written to
                your audit log.
              </span>
            </span>
          </label>
          {!callCompletedSelected && (includeRecordingUrl || includeTranscript) && (
            <p className="px-1 text-xs text-slate-500">
              These only take effect when you also subscribe to “A call finishes” above.
            </p>
          )}
        </fieldset>
        <button
          type="submit"
          disabled={!write.allowed || create.isPending || !url || events.length === 0}
          className={SUBMIT}
        >
          {create.isPending ? "Adding…" : "Add endpoint"}
        </button>
      </form>
    </Card>
  );
}

/**
 * "You cannot send to a Google Sheet from this account" — rendered ONCE, for the two
 * different moments the screen can learn it.
 *
 * One component, because two copies of this card is how the pre-emptive state and the
 * post-refusal state start telling a client two different stories about one fact. The
 * words differ, and only the words: when the server has spoken they are the SERVER's
 * (`title`/`detail` and `remediation` verbatim), and when it has only sent a boolean they
 * are ours, saying the same thing.
 *
 * Deliberately NOT an error: `tone="neutral"`, no `role="alert"`, no retry. This is a
 * founder/ops decision, and "try again" is not the remediation for a capability the
 * deployment does not have. Deliberately NOT a disabled button either — a dead control
 * costs a client a support ticket to learn what one sentence tells them, which is the
 * argument the verification screen's "Buying a phone number" card already makes.
 */
function SheetsUnavailable({
  headline,
  remediation,
  footnote,
}: {
  headline: string;
  remediation: string;
  footnote: string;
}) {
  return (
    <Card title="Send events to a Google Sheet">
      <NoticeBox tone="neutral" title={headline}>
        <p className="mt-1">{remediation}</p>
        <p className="mt-2 text-xs opacity-80">{footnote}</p>
      </NoticeBox>
    </Card>
  );
}

/**
 * Deliver events to a Google Sheet — D-23's second transport, reachable from a screen at
 * last.
 *
 * THE REFUSAL IS STILL THE INTERESTING PART. `create_sheets_endpoint` checks
 * `sheets_delivery_available()` before it writes anything, and on a deployment with no
 * Google service account it refuses with `sheets_delivery_unavailable`. That is a
 * FOUNDER/OPS decision — the route's own argument is that a checkbox for a transport that
 * cannot deliver recreates the "silently never delivers" defect the sheets work removed —
 * and it is the state EVERY deployment is in today.
 *
 * Three ways to render it were on the table:
 *
 * 1. Hide the form until a capability flag says otherwise.
 * 2. Disable the button with a locally-written reason. That is a second copy of a server
 *    rule, and the copy is what drifts.
 * 3. Offer it, and when the server refuses, REPLACE the form with the server's own words.
 *
 * This screen used to do (3) alone, because (1) had nothing to read: no endpoint published
 * `sheets_delivery_available`, so hiding would have been a guess. It now does (1) AND (3),
 * and they are not two answers to one question — they are the answers to two:
 *
 * - (1) decides whether to OFFER the form, from the server's own selector on
 *   `EndpointOptions`. Where the capability is false this component is not rendered at
 *   all; the page puts `SheetsUnavailable` in its place.
 * - (3) below stays because the capability is a HINT and never the check. It is read once
 *   and cached for half an hour, so an operator turning Sheets off mid-session leaves this
 *   screen optimistic and wrong — and the server refuses anyway, which is what the branch
 *   below renders. Deleting it would make the screen's optimism the check.
 *
 * (2) is still refused. Every OTHER refusal this route can produce — an unparseable sheet
 * reference, an event with no column layout — keeps the form on screen and renders through
 * `ProblemNotice`, because those the client can fix in the field they are looking at.
 */
function SheetsForm({
  session,
  catalogue,
  write,
}: {
  session: Session;
  catalogue: string[];
  write: WriteAccess;
}) {
  const create = useCreateSheetsEndpoint(session);
  const [spreadsheet, setSpreadsheet] = useState("");
  const [worksheet, setWorksheet] = useState("");
  const [events, setEvents] = useState<OutboundEvent[]>(["lead.created"]);

  // The one refusal that is a statement about the DEPLOYMENT rather than about this
  // request, read off the problem's stable machine code rather than off its prose.
  //
  // Reachable only when the published capability said `true` and the server disagreed —
  // a capability read before an operator switched Sheets off, or a console talking to a
  // deployment that changed under it. Rare, and kept precisely because it is the seam
  // where the server, not this screen, is proved to be the authority.
  const unavailable =
    create.error instanceof ApiProblem && create.error.code === SHEETS_UNAVAILABLE_CODE
      ? create.error
      : null;

  if (unavailable) {
    return (
      <SheetsUnavailable
        headline={unavailable.message}
        remediation={
          unavailable.remediation ??
          "Set up a delivery to your own system above instead, or ask us to enable Google Sheets for your account."
        }
        footnote="Nothing was created, so there is nothing to undo. Reload this page once we have told you Sheets is switched on for your account."
      />
    );
  }

  return (
    <Card title="Send events to a Google Sheet">
      <p className="-mt-2 text-xs text-slate-500">
        We append a row per event. Share the sheet with the Google account we give you —
        until we connect it on our side, deliveries appear as failures below
        rather than quietly doing nothing.
      </p>
      {create.error && (
        <div className="mt-3">
          <ProblemNotice error={create.error} />
        </div>
      )}
      {create.data && (
        <div className="mt-3">
          <NoticeBox tone={create.data.credential_attached ? "ok" : "warn"} title="Sheet added">
            <p className="mt-1">
              Writing to sheet <code>{create.data.spreadsheet_id}</code>, tab{" "}
              <strong>{create.data.worksheet}</strong>.{" "}
              {create.data.credential_attached
                ? "The Google connection is ready, so the next event lands in it."
                : "We haven't connected to Google yet, so deliveries will be recorded as failures until we connect it — that is us, not you."}
            </p>
          </NoticeBox>
        </div>
      )}
      <form
        className="mt-3 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            {
              spreadsheet,
              events,
              // An empty tab name is not a tab name. The server strips it to the same
              // effect; sending null says what we mean.
              worksheet: worksheet.trim() === "" ? null : worksheet.trim(),
            },
            { onSuccess: () => setSpreadsheet("") },
          );
        }}
      >
        {/* The hint sits OUTSIDE the label on purpose. A `<label>` wrapping both the
            field and a sentence of guidance makes the whole paragraph the field's
            accessible name, which is what a screen reader then announces on focus. The
            visible label stays one short phrase; the guidance is a sibling. */}
        <label className="block">
          <span className={FIELD_LABEL}>Which sheet?</span>
          <input
            required
            value={spreadsheet}
            disabled={!write.allowed}
            onChange={(e) => setSpreadsheet(e.target.value)}
            placeholder="https://docs.google.com/spreadsheets/d/…"
            className={INPUT}
          />
        </label>
        <p className="-mt-2 text-xs text-slate-500">
          Paste the address bar while the sheet is open, or just the document id.
        </p>
        <label className="block">
          <span className={FIELD_LABEL}>Which tab? (optional)</span>
          <input
            value={worksheet}
            disabled={!write.allowed}
            onChange={(e) => setWorksheet(e.target.value)}
            maxLength={100}
            placeholder="Leads"
            className={INPUT}
          />
        </label>
        <EventChoices
          catalogue={catalogue}
          selected={events}
          disabled={!write.allowed}
          onToggle={(event, on) =>
            setEvents((current) =>
              on ? [...current, event] : current.filter((x) => x !== event),
            )
          }
        />
        <button
          type="submit"
          disabled={!write.allowed || create.isPending || !spreadsheet || events.length === 0}
          className={SUBMIT}
        >
          {create.isPending ? "Adding…" : "Add sheet"}
        </button>
      </form>
    </Card>
  );
}
