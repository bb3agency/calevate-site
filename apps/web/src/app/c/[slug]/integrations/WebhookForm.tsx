"use client";

import { useState } from "react";

import { Card, FIELD_LABEL, PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import type { Session } from "@/lib/api/client";
import type { WriteAccess } from "@/lib/api/hooks";
import { useCreateEndpoint, type OutboundEvent } from "@/lib/api/integrations";

import { EventChoices, INPUT } from "./EventChoices";

const SUBMIT = PRIMARY_BUTTON;


/**
 * Register a webhook. Unchanged in behaviour; it now draws its events from the catalogue
 * and lives in its own component so the Sheets form beside it can hold its own state.
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
  const [url, setUrl] = useState("");
  const valid = useFormValidation();
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
        noValidate
        onSubmit={valid.onSubmit(() => {
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
        })}
      >
        {/* A PERSISTENT label, not the placeholder alone. axe's `label` rule accepts a
            placeholder as an accessible name (tests/a11y.ts says so, and it is why this
            defect survived the sweep going green), but the text disappears the moment
            somebody types — which is WCAG 3.3.2's entire complaint, and worst for the
            reader who most needs to re-check what a field wanted. The rest of the
            console labels its fields this way; this input was the exception. */}
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
          {/* Outside the label for the reason the comment above it gives about the hint:
              enclosed, the sentence becomes part of the field's accessible name. */}
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
        {/* The `call.completed` extras. Off by default: the base body is the summary and
            the outcome, and each of these sends more of the customer's own data to your
            endpoint, so each is a deliberate choice. */}
        <fieldset className="space-y-1.5 rounded-md border border-line p-3">
          <legend className={`${FIELD_LABEL} px-1`}>When a call finishes, also send…</legend>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={includeRecordingUrl}
              disabled={!write.allowed}
              onChange={(e) => setIncludeRecordingUrl(e.target.checked)}
            />
            <span className="text-ink-muted">
              A link to the call recording
              <span className="block text-xs text-ink-faint">
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
            <span className="text-ink-muted">
              The transcript, redacted
              <span className="block text-xs text-ink-faint">
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
            <span className="text-ink-muted">
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
            <p className="px-1 text-xs text-ink-faint">
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
