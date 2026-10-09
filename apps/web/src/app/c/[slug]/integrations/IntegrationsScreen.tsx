"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { PageHeader } from "@/components/console/pageHeader";
import { PRIMARY_BUTTON, ProblemNotice, RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useDeactivateEndpoint,
  useDeliveries,
  useDeliveryPayload,
  useEndpointOptions,
  useEndpoints,
  type Endpoint,
} from "@/lib/api/integrations";
import { useClientSession } from "@/lib/api/session";

import { AddDestinationDrawer } from "./AddDestinationDrawer";
import { ConnectedAccounts } from "./ConnectedAccounts";
import { DeliveryLog } from "./DeliveryLog";
import { EndpointList } from "./EndpointList";
import { useIntegrationsCopilot } from "./copilot";

/**
 * The account's connections (D-700: the accounts agents act in during calls) and outbound
 * sync (D-23) with its delivery log (SURFACES §2b).
 *
 * PRIMARY JOB: send leads and call results to the client's own system, and see that they
 * arrive. The destinations are rows; adding one opens a drawer, so the list stays the
 * screen. What stays here is the state the panels share: which endpoint is being
 * stopped, which delivered body is open.
 *
 * **The signing secret appears once**, in the drawer's success step, and is never
 * re-fetchable: a settings page that re-displays a shared secret turns every screenshot
 * into a key disclosure. The list shows a fingerprint so two endpoints can be told apart.
 *
 * No `<h1>`: the shell prints "Integrations".
 */
export function IntegrationsScreen() {
  const session = useClientSession();
  const endpoints = useEndpoints(session);
  const deliveries = useDeliveries(session);
  const deactivate = useDeactivateEndpoint(session);
  const options = useEndpointOptions(session);
  const write = useWriteAccess(session, "org:manage", "change where events are sent");
  const [adding, setAdding] = useState(false);
  const [stopping, setStopping] = useState<Endpoint | null>(null);

  /**
   * Opening a delivered body is gated on reading RAW call data, not on managing the
   * integration: the body can carry the unredacted transcript, so the column exists only
   * for a reader the server would serve.
   */
  const payloadAccess = useWriteAccess(session, "calls:read_raw", "open a delivered payload");
  const mayReadPayload = payloadAccess.allowed;
  const [openPayload, setOpenPayload] = useState<string | null>(null);
  const payload = useDeliveryPayload(session);

  useIntegrationsCopilot({ endpoints, deliveries, options, write, mayReadPayload });

  /** Each open asks again, so every look at a raw body is audited server-side. */
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
    <div className="space-y-5 pb-12">
      <PageHeader
        description="Connect the accounts your agents use on calls, and send leads and call results to your own systems."
        actions={
          <button
            type="button"
            onClick={() => setAdding(true)}
            // Both forms are built from the options read: no answer, no forms.
            disabled={!write.allowed || !options.data}
            title={write.reason ?? undefined}
            className={PRIMARY_BUTTON}
          >
            Add destination
          </button>
        }
      />
      <RestrictionNote reason={write.reason} />

      <ConnectedAccounts session={session} canWrite={write.allowed} />

      <section className="space-y-1" aria-labelledby="any-crm">
        <h2 id="any-crm" className="text-base font-semibold text-ink">
          Send to your own system, or any CRM
        </h2>
        <p className="text-sm text-ink-muted">
          Each destination below receives your leads and call results as they happen, signed so
          your system can tell they came from us. To reach a CRM we do not connect to directly,
          create a webhook in Zapier, Make or Pabbly, add its address here as a destination, and
          map the fields there.
        </p>
      </section>

      {/* §52: the forms are withheld until the options read answers, and a failed (or
          paused) read is a refusal here rather than four plausible checkboxes. */}
      {!options.isLoading && (options.error || !options.data) && (
        <ProblemNotice
          error={options.error ?? new Error("We could not load the list of events you can subscribe to.")}
          onRetry={() => void options.refetch()}
        />
      )}
      {deactivate.error && !stopping && <ProblemNotice error={deactivate.error} />}

      <EndpointList endpoints={endpoints} write={write} busy={deactivate.isPending} onStop={setStopping} />
      <DeliveryLog
        deliveries={deliveries}
        payloadAccess={payloadAccess}
        mayReadPayload={mayReadPayload}
        openPayload={openPayload}
        onTogglePayload={togglePayload}
        payload={payload}
      />

      {options.data && (
        <AddDestinationDrawer
          open={adding}
          onClose={() => setAdding(false)}
          session={session}
          options={options.data}
          write={write}
        />
      )}

      {/* WHICH endpoint, that the feed stops at once, and what coming back costs. The
          refusal renders inside the dialog, and it closes only on success: a failed
          DELETE leaves the endpoint live. */}
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
          onConfirm={() => deactivate.mutate(stopping.id, { onSuccess: () => setStopping(null) })}
        >
          <p>
            Your system at <span className="break-all font-mono text-ink">{stopping.url}</span>{" "}
            will stop receiving leads and call results immediately.
          </p>
          <p>
            <strong className="font-semibold text-ink">This cannot be undone here.</strong> There
            is no way to switch this endpoint back on — you would add the address again, and that
            issues a NEW signing secret, so your CRM has to be reconfigured with it.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
