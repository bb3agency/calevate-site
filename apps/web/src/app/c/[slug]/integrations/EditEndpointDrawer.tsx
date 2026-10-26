"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Drawer } from "@/components/console/drawer";
import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import type { WriteAccess } from "@/lib/api/hooks";
import {
  EVENT_LABELS,
  SHEET_KIND,
  useUpdateEndpoint,
  type Endpoint,
  type OutboundEvent,
} from "@/lib/api/integrations";
import { hasKey } from "@/lib/lookup";

import { EndpointExtras, wireExtras, type ExtrasState } from "./EndpointExtras";
import { EventChoices } from "./EventChoices";

/**
 * CHANGE WHAT A DESTINATION IS SENT: its events, and for your own system the recording
 * link and transcripts. The address is shown, not editable — sending somewhere new is a
 * new destination, which issues its own secret behind its emailed code.
 *
 * Opens on what the endpoint holds now, so pressing Save with nothing changed changes
 * nothing. A spreadsheet takes events only: it writes a row, never a recording or a
 * transcript.
 */
export function EditEndpointDrawer({
  endpoint,
  catalogue,
  session,
  write,
  onClose,
}: {
  endpoint: Endpoint;
  catalogue: string[];
  session: Session;
  write: WriteAccess;
  onClose: () => void;
}) {
  const update = useUpdateEndpoint(session);
  const feedback = useActionFeedback(update, { errorDisplay: "inline", successToast: "Saved" });
  const sheet = endpoint.kind === SHEET_KIND;
  const [events, setEvents] = useState<OutboundEvent[]>(
    endpoint.events.filter((name): name is OutboundEvent => hasKey(EVENT_LABELS, name)),
  );
  const [extras, setExtras] = useState<ExtrasState>({
    includeRecordingUrl: endpoint.include_recording_url,
    includeTranscript: endpoint.include_transcript,
    includeRawTranscript: endpoint.include_raw_transcript,
  });
  // A sheet cannot carry the recording link, so the one event that exists to send it is
  // not offered for one.
  const offered = sheet ? catalogue.filter((name) => name !== "call.recording_ready") : catalogue;

  const save = () =>
    update.mutate(
      {
        endpointId: endpoint.id,
        change: sheet
          ? {
              events,
              include_recording_url: false,
              include_transcript: false,
              include_raw_transcript: false,
            }
          : { events, ...wireExtras(events, extras) },
      },
      { onSuccess: onClose },
    );

  return (
    <Drawer
      open
      onClose={onClose}
      title="Change what is sent"
      width="lg"
      footer={
        <div className="flex flex-wrap gap-2">
          <ActionButton
            type="button"
            status={feedback.status}
            disabled={!write.allowed || events.length === 0}
            pendingLabel="Saving…"
            successLabel="Saved"
            onClick={save}
          >
            Save
          </ActionButton>
          <button type="button" onClick={onClose} className={SECONDARY_BUTTON}>
            Cancel
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-body text-ink-muted">
          {sheet ? "Your spreadsheet" : "Your system at"}{" "}
          <span className="break-all font-mono text-ink">{endpoint.url}</span>
        </p>
        {update.error && <ProblemNotice error={update.error} />}
        <EventChoices
          catalogue={offered}
          selected={events}
          disabled={!write.allowed}
          onToggle={(event, on) =>
            setEvents((current) =>
              on ? [...current, event] : current.filter((x) => x !== event),
            )
          }
        />
        {events.length === 0 && (
          <p className="text-meta text-warn">
            Choose at least one, or stop sending to this destination instead.
          </p>
        )}
        {!sheet && (
          <EndpointExtras
            events={events}
            extras={extras}
            onChange={setExtras}
            disabled={!write.allowed}
          />
        )}
      </div>
    </Drawer>
  );
}
