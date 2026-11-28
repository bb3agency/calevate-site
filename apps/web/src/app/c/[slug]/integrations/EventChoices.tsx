"use client";

import { FIELD, FIELD_LABEL, SECONDARY_BUTTON_SM } from "@/components/ui";
import {
  EVENT_LABELS,
  WEBHOOK_ONLY_EVENTS,
  eventLabel,
  type OutboundEvent,
} from "@/lib/api/integrations";
import { hasKey } from "@/lib/lookup";

/**
 * The form language of this screen is the CONSOLE's, not this screen's.
 *
 * `INPUT`, `FIELD_LABEL` and `SUBMIT` were three private copies of primitives
 * `components/ui.tsx` already exports, written in raw slate literals — which is how this
 * one route missed the design-token migration and ended up rendering hints at 2.56:1 in
 * light and 3.75:1 in dark (`globals.css:39,88`). `INPUT` is `FIELD`, which also carries
 * the `touch:min-h-11` tap-target floor this file's inputs did not have; `SUBMIT` is
 * `PRIMARY_BUTTON`, so "Send to this address" is the same button as every other primary action in
 * the console rather than the only near-black one.
 */
export const INPUT = FIELD;

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
export function EventChoices({
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
  const offered = catalogue.filter((name): name is OutboundEvent => hasKey(EVENT_LABELS, name));
  // Not the recording event: it needs its own opt-in, and ticking it alone is refused.
  const missing = offered.filter(
    (name) => !selected.includes(name) && !WEBHOOK_ONLY_EVENTS.includes(name),
  );
  return (
    <fieldset className="space-y-1.5">
      <legend className={FIELD_LABEL}>Send when…</legend>
      {/* Ticks every event offered now. A later event is not ticked for you: the
          destination has never seen its shape (D-1049). */}
      {missing.length > 1 && (
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={disabled}
          onClick={() => missing.forEach((name) => onToggle(name, true))}
        >
          Tick all
        </button>
      )}
      {catalogue.filter((name) => hasKey(EVENT_LABELS, name)).map((name) => (
        <label key={name} className="flex items-center gap-2 text-body">
          <input
            type="checkbox"
            checked={hasKey(EVENT_LABELS, name) && selected.includes(name)}
            disabled={disabled}
            onChange={(e) => {
              if (hasKey(EVENT_LABELS, name)) onToggle(name, e.target.checked);
            }}
          />
          <span className="text-ink-muted">{eventLabel(name)}</span>
          <code className="text-meta text-ink-faint">{name}</code>
        </label>
      ))}
      {unknown.length > 0 && (
        <p className="text-meta text-ink-faint">
          <span className="block">This account can also receive {unknown.join(", ")}.</span>
          <span className="block">We cannot subscribe to it yet. Tell us to set it up.</span>
        </p>
      )}
    </fieldset>
  );
}
