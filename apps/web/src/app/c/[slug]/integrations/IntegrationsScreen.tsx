"use client";

import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  formatIST,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useDeactivateEndpoint,
  useDeliveries,
  useDeliveryPayload,
  useEndpointOptions,
  useEndpoints,
  useResendDelivery,
  useRotateEndpointSecret,
  type Endpoint,
  type SecretRotation,
} from "@/lib/api/integrations";
import { useClientSession } from "@/lib/api/session";

import { CopyRow } from "../lead-sources/IssuedSecretNotice";
import { AddDestinationDrawer } from "./AddDestinationDrawer";
import { ConnectedAccounts } from "./ConnectedAccounts";
import { DeliveryLog } from "./DeliveryLog";
import { EditEndpointDrawer } from "./EditEndpointDrawer";
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
  // The dialog shows the refusal while open, the notice above the list after it closes.
  const deactivateFeedback = useActionFeedback(deactivate, { errorDisplay: "inline" });
  const options = useEndpointOptions(session);
  const write = useWriteAccess(session, "org:manage", "change where events are sent");
  const [adding, setAdding] = useState(false);
  const [stopping, setStopping] = useState<Endpoint | null>(null);
  const [editing, setEditing] = useState<Endpoint | null>(null);
  // A new signing secret: which endpoint is being asked about, then the secret, shown once.
  const rotate = useRotateEndpointSecret(session);
  const rotateFeedback = useActionFeedback(rotate, { errorDisplay: "inline" });
  const [rotating, setRotating] = useState<Endpoint | null>(null);
  const [issued, setIssued] = useState<SecretRotation | null>(null);
  // "Send again" on a delivery that finally failed; the refusal shows above the log.
  const resend = useResendDelivery(session);
  useActionFeedback(resend, { errorDisplay: "inline", successToast: "Sending it again" });

  /**
   * Opening a delivered body is gated on reading RAW call data, not on managing the
   * integration: the body can carry the unredacted transcript, so the column exists only
   * for a reader the server would serve.
   */
  const payloadAccess = useWriteAccess(session, "calls:read_raw", "open a delivered payload");
  const mayReadPayload = payloadAccess.allowed;
  const [openPayload, setOpenPayload] = useState<string | null>(null);
  const payload = useDeliveryPayload(session);
  // The body's own panel shows a refusal in place of the body, so nothing toasts.
  const payloadFeedback = useActionFeedback(payload, { errorDisplay: "inline" });

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
    <div className="max-w-4xl space-y-10 pb-12">
      <PageHeader description="Accounts your agents use, and where your leads are sent." />
      <RestrictionNote reason={write.reason} />

      <ConnectedAccounts session={session} canWrite={write.allowed} />

      <Section
        title="Send to your own system"
        description="Each destination gets your leads and call results as they happen, signed so your system knows they came from us."
        action={
          <button
            type="button"
            onClick={() => setAdding(true)}
            // Both forms are built from the options read: no answer, no forms.
            disabled={!write.allowed || !options.data}
            title={write.reason ?? undefined}
            className={SECONDARY_BUTTON_SM}
          >
            Add destination
          </button>
        }
      >
        {/* §52: the forms are withheld until the options read answers, and a failed (or
            paused) read is a refusal here rather than four plausible checkboxes. */}
        {!options.isLoading && (options.error || !options.data) && (
          <ProblemNotice
            error={options.error ?? new Error("We could not load the list of events you can subscribe to.")}
            onRetry={() => void options.refetch()}
          />
        )}
        {deactivate.error && !stopping && <ProblemNotice error={deactivate.error} />}
        <EndpointList
          endpoints={endpoints}
          write={write}
          busy={deactivate.isPending || rotate.isPending}
          onStop={setStopping}
          onRotate={setRotating}
          onEdit={setEditing}
        />
        <p className="mt-3 max-w-prose text-meta text-ink-muted">
          Another CRM? Add a Zapier, Make or Pabbly webhook here and map the fields there.
        </p>
      </Section>

      <DeliveryLog
        deliveries={deliveries}
        payloadAccess={payloadAccess}
        mayReadPayload={mayReadPayload}
        openPayload={openPayload}
        onTogglePayload={togglePayload}
        payload={payload}
        payloadStatus={payloadFeedback.status}
        canResend={write.allowed}
        resend={resend}
      />

      {rotating && (
        <ConfirmDialog
          title="Issue a new signing secret?"
          confirmLabel="Issue a new secret"
          pendingLabel="Issuing…"
          cancelLabel="Keep the current one"
          status={rotateFeedback.status}
          error={rotate.error}
          onCancel={() => {
            rotate.reset();
            setRotating(null);
          }}
          onConfirm={() =>
            rotate.mutate(
              { endpointId: rotating.id },
              {
                onSuccess: (result) => {
                  setRotating(null);
                  setIssued(result);
                },
              },
            )
          }
        >
          <p>
            Your system at <span className="break-all font-mono text-ink">{rotating.url}</span>{" "}
            gets a new secret to check our signature with.
          </p>
          <p>
            For the next 24 hours every delivery is signed with both the old and the new
            secret, so it keeps verifying while you switch. After that only the new one signs.
          </p>
        </ConfirmDialog>
      )}

      <Drawer
        open={issued !== null}
        onClose={() => setIssued(null)}
        title="Your new signing secret"
        width="lg"
        footer={
          <button type="button" onClick={() => setIssued(null)} className={PRIMARY_BUTTON}>
            I&apos;ve saved it
          </button>
        }
      >
        {issued && (
          <div className="space-y-3 text-body">
            <p className="font-medium text-ink">Copy this now — we will not show it again.</p>
            <CopyRow label="Signing secret" value={issued.secret} copyLabel="Copy signing secret" />
            <p className="text-meta text-ink-muted">
              {issued.previous_secret_expires_at
                ? `The old secret also signs every delivery until ${formatIST(issued.previous_secret_expires_at)}. Switch your system to the new one before then.`
                : "The old secret has stopped signing. Switch your system to the new one now."}
            </p>
          </div>
        )}
      </Drawer>

      {editing && options.data && (
        <EditEndpointDrawer
          endpoint={editing}
          catalogue={options.data.events}
          session={session}
          write={write}
          onClose={() => setEditing(null)}
        />
      )}

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
          successLabel="Stopped"
          cancelLabel="Keep sending"
          status={deactivateFeedback.status}
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
