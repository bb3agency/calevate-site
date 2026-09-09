"use client";

import { useState } from "react";

import {
  Card,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  useDeactivateEndpoint,
  useDeliveries,
  useDeliveryPayload,
  useEndpointOptions,
  useEndpoints,
  type Endpoint,
} from "@/lib/api/integrations";

import { DeliveryLog } from "./DeliveryLog";
import { EndpointList } from "./EndpointList";
import { SheetsForm, SheetsUnavailable } from "./SheetsForm";
import { WebhookForm } from "./WebhookForm";
import { useIntegrationsCopilot } from "./copilot";

/**
 * Outbound sync (D-23) and its delivery log (SURFACES §2b).
 *
 * The route is chrome and this is the screen (UX-DOCTRINE §6). Each panel is its own
 * module by subject: the two registration forms, the endpoint list, and the delivery log
 * with the privileged payload panel inside it. What stays here is the state they share —
 * which secret is on screen, which endpoint is being stopped, which body is open.
 *
 * **The signing secret appears once.** It is rendered on creation and never re-fetchable,
 * because a settings page that re-displays a shared secret turns every screenshot and
 * screen-share into a key disclosure. The list shows a fingerprint so two endpoints can
 * still be told apart.
 */
export function IntegrationsScreen() {
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
   * The endpoint a client has ASKED to stop, held until they confirm it.
   *
   * The control used to fire `DELETE /v1/integrations/endpoints/{id}` on one click, under
   * a label ("Turn off") that promised a switch the product does not have: there is no
   * re-activate route, and registering the address again mints a NEW signing secret, so a
   * mis-click stops the client's live CRM feed AND costs them a CRM reconfiguration. That
   * is the shape NN/g reserves a confirmation for and GOV.UK reserves a warning button
   * for; both are cited in `components/confirmDialog.tsx`.
   *
   * The whole endpoint rather than its id, so the dialog can name the URL that is about
   * to stop receiving leads — a confirmation that cannot say WHICH one confirms intent
   * and not target.
   */
  const [stopping, setStopping] = useState<Endpoint | null>(null);

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

  useIntegrationsCopilot({ endpoints, deliveries, options, write, mayReadPayload });

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
        {/* No <h1>: the app shell prints the page title from the nav list (layout.tsx),
            and a second "Integrations" beside it is a visible duplicate that keeps the
            old name when the nav entry is renamed (ux-audit INT-3). */}
        {/* `text-ink-muted`, not `text-ink-faint`: this is the screen's opening
            paragraph at `text-sm`, the same slot every other route in this lane writes in
            muted (`settings/team`, `settings/alerts`). Faint is for a 12px hint beside a
            control, and the raw slate literal this replaced was neither. (Naming the
            class here would trip the guard in `tests/contrast.test.ts`, which scans lines
            and cannot tell a class from prose about one.) */}
        <p className="mt-0.5 text-sm text-ink-muted">
          Send your leads and call results to your own CRM or spreadsheet as they happen.
        </p>
      </div>

      <RestrictionNote reason={write.reason} />

      {/* The endpoints READ failure is refused inside the "Your endpoints" card below —
          together with the paused read, so a non-answer never renders as "No endpoints
          yet" (§52). A page-level copy here would double the refusal on a failure. */}
      {deactivate.error && !stopping && <ProblemNotice error={deactivate.error} />}

      {revealed && (
        <Card title="Your signing secret">
          <p className="text-sm text-ink-muted">
            Copy this now — we will not show it again.
          </p>
          <code className="mt-2 block break-all rounded-md bg-app p-3 font-mono text-xs">
            {revealed}
          </code>
          <p className="mt-2 text-xs text-ink-faint">
            Your system should check the <code>X-Calevate-Signature</code> header on each
            request: it is the HMAC-SHA256 of <code>{"{timestamp}.{body}"}</code> using this
            secret. Reject anything older than five minutes.
          </p>
          <button
            type="button"
            onClick={() => setRevealed(null)}
            className={`mt-3 ${SECONDARY_BUTTON_SM}`}
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
               The words are ours because the server sent a boolean and not a sentence,
               and they name the remediation the API names in its own refusal so a client
               who meets both hears one story. */
            <SheetsUnavailable
              headline="Google Sheets delivery is not switched on for your account."
              remediation="Set up a delivery to your own system above instead, or ask us to switch Google Sheets on for you."
              footnote="There is nothing to fill in here yet — this form appears on its own once Sheets is enabled for your account."
            />
          )}
        </>
      )}

      <EndpointList
        endpoints={endpoints}
        write={write}
        busy={deactivate.isPending}
        onStop={setStopping}
      />

      <DeliveryLog
        deliveries={deliveries}
        payloadAccess={payloadAccess}
        mayReadPayload={mayReadPayload}
        openPayload={openPayload}
        onTogglePayload={togglePayload}
        payload={payload}
      />

      {/* The confirmation, with the three facts the button could not carry: WHICH
          endpoint, that the lead feed stops immediately, and what coming back costs.
          `deactivate.error` renders inside the dialog rather than in the page-level
          notice above while the dialog is open, so a refusal is read where the decision
          is being made. The dialog closes only on success — a failed DELETE leaves the
          endpoint live, and closing would imply otherwise. */}
      {stopping && (
        <ConfirmDialog
          title="Stop sending events to this endpoint?"
          confirmLabel="Stop sending events"
          pendingLabel="Stopping…"
          cancelLabel="Keep sending"
          pending={deactivate.isPending}
          error={deactivate.error}
          onCancel={() => {
            deactivate.reset();
            setStopping(null);
          }}
          onConfirm={() =>
            deactivate.mutate(stopping.id, { onSuccess: () => setStopping(null) })
          }
        >
          <p>
            Your system at <span className="break-all font-mono text-ink">{stopping.url}</span>{" "}
            will stop receiving leads and call results immediately.
          </p>
          <p>
            <strong className="font-semibold text-ink">This cannot be undone here.</strong>{" "}
            There is no way to switch this endpoint back on — you would add the address
            again, and that issues a NEW signing secret, so your CRM has to be
            reconfigured with it.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
