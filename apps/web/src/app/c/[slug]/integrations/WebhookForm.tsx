"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD_LABEL, ProblemNotice } from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import type { Session } from "@/lib/api/client";
import type { WriteAccess } from "@/lib/api/hooks";
import { useCreateEndpoint, type OutboundEvent } from "@/lib/api/integrations";

import { EndpointExtras, wireExtras, type ExtrasState } from "./EndpointExtras";
import { EventChoices, INPUT } from "./EventChoices";

/**
 * Register a webhook. Its events come from the catalogue and its extras from
 * `EndpointExtras`, the same controls the edit drawer uses.
 */
export function WebhookForm({
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
  const createFeedback = useActionFeedback(create, { errorDisplay: "inline" });
  const [url, setUrl] = useState("");
  const valid = useFormValidation();
  const [events, setEvents] = useState<OutboundEvent[]>(["lead.created"]);
  const [extras, setExtras] = useState<ExtrasState>({
    includeRecordingUrl: false,
    includeTranscript: false,
    includeRawTranscript: false,
  });

  return (
    <div className="space-y-3">
      {create.error && (
        <div className="mb-3">
          <ProblemNotice error={create.error} />
        </div>
      )}
      <form
        className="space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          create.mutate(
            { url, events, ...wireExtras(events, extras) },
            {
              onSuccess: (data) => {
                onSecret(data.secret);
                setUrl("");
              },
            },
          );
        })}
      >
        {/* A persistent label, not the placeholder alone (WCAG 3.3.2): the placeholder
            disappears the moment somebody types. */}
        <div>
          <label className="block">
            <span className={FIELD_LABEL}>Where should we send them?</span>
            <input
              {...valid.field("url", "Enter the web address to send events to.")}
              required
              type="url"
              value={url}
              disabled={!write.allowed}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://your-crm.example.com/calevate"
              className={INPUT}
            />
          </label>
          {/* Outside the label, so the sentence is not part of the field's name. */}
          {valid.error("url")}
        </div>
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
        <EndpointExtras
          events={events}
          extras={extras}
          onChange={setExtras}
          disabled={!write.allowed}
        />
        <ActionButton
          type="submit"
          status={createFeedback.status}
          disabled={!write.allowed || !url || events.length === 0}
          pendingLabel="Adding…"
          successLabel="Added"
        >
          Add endpoint
        </ActionButton>
      </form>
    </div>
  );
}
