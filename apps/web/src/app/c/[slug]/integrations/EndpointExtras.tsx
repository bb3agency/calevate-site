"use client";

import { FIELD_LABEL } from "@/components/ui";
import type { OutboundEvent } from "@/lib/api/integrations";

/** What a webhook endpoint carries beyond the base body, and the events it rides on. */
export interface ExtrasState {
  includeRecordingUrl: boolean;
  includeTranscript: boolean;
  includeRawTranscript: boolean;
}

/**
 * The opt-ins exactly as the server will store them. The transcript extras ride on
 * `call.completed` only; the recording link also rides on `call.recording_ready`, which
 * exists to send it, so choosing that event holds the link on. Raw never outlives
 * redacted (the server refuses the pairing).
 */
export function wireExtras(events: OutboundEvent[], extras: ExtrasState) {
  const completed = events.includes("call.completed");
  const ready = events.includes("call.recording_ready");
  return {
    include_recording_url: ready || (completed && extras.includeRecordingUrl),
    include_transcript: completed && extras.includeTranscript,
    include_raw_transcript: completed && extras.includeTranscript && extras.includeRawTranscript,
  };
}

/**
 * The `call.completed` / `call.recording_ready` extras, shared by the add form and the edit
 * drawer so the two cannot offer different rules. Shown only once an event that carries
 * them is chosen. Each sends more of the customer's own data to the endpoint, so each is
 * off until chosen.
 */
export function EndpointExtras({
  events,
  extras,
  onChange,
  disabled,
}: {
  events: OutboundEvent[];
  extras: ExtrasState;
  onChange: (next: ExtrasState) => void;
  disabled: boolean;
}) {
  const completed = events.includes("call.completed");
  const ready = events.includes("call.recording_ready");
  if (!completed && !ready) return null;
  const sendsRecordingUrl = ready || (completed && extras.includeRecordingUrl);
  return (
    <fieldset className="settings-enter space-y-1.5 border-l-2 border-line pl-4">
      <legend className={FIELD_LABEL}>
        {completed ? "When a call finishes, also send…" : "Also send…"}
      </legend>
      <label className="flex items-start gap-2 text-body">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={sendsRecordingUrl}
          disabled={disabled || ready}
          onChange={(e) => onChange({ ...extras, includeRecordingUrl: e.target.checked })}
        />
        <span className="text-ink-muted">
          A link to the call recording
          <span className="block text-meta text-ink-faint">
            A short-lived, signed link to our copy of the audio — not the audio itself. It
            expires within minutes, so fetch it as soon as you receive it.
            {ready && " Always on with “A call recording is ready”, which exists to send this link."}
          </span>
        </span>
      </label>
      {completed && (
        <>
          <label className="flex items-start gap-2 text-body">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={extras.includeTranscript}
              disabled={disabled}
              onChange={(e) => {
                const on = e.target.checked;
                onChange({
                  ...extras,
                  includeTranscript: on,
                  includeRawTranscript: on && extras.includeRawTranscript,
                });
              }}
            />
            <span className="text-ink-muted">
              The transcript, redacted
              <span className="block text-meta text-ink-faint">
                The conversation with personal details (numbers, IDs, OTPs) masked — the same
                text your team sees on the call screen.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-body">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={extras.includeRawTranscript}
              disabled={disabled || !extras.includeTranscript}
              onChange={(e) => onChange({ ...extras, includeRawTranscript: e.target.checked })}
            />
            <span className="text-ink-muted">
              The transcript, unredacted
              <span className="block text-meta text-warn">
                Sends the FULL transcript — every phone number, ID and OTP spoken on the call —
                to your endpoint in the clear. Only turn this on if your system is allowed to
                hold that data. Turning it on needs the same permission as reading a raw
                transcript.
              </span>
            </span>
          </label>
        </>
      )}
    </fieldset>
  );
}
