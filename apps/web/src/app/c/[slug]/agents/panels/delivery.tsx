"use client";

/**
 * HOW THE AGENT SOUNDS, AND HOW LONG ONE CALL MAY RUN — the two settings D-586 put in the
 * account's own hands, as controls. The state they change (`panels/publishing.tsx`) is a
 * read; these are the decision.
 *
 * ## Both apply to the NEXT call, and the copy says so
 *
 * What a client must be told is the one thing a save cannot decide: a call already in
 * progress finishes as it started. "Applies immediately" without that sentence is how
 * somebody comes to believe a shorter cap cuts off the call they are listening to.
 *
 * ## Nothing here composes a refusal of its own
 *
 * A voice that cannot be chosen carries the server's own sentence; a cap outside the range is
 * refused with `call_cap_out_of_range` and the bounds come from `GET /v1/agents/lanes`. A
 * vendor refusal on the re-publish arrives as a `dependency` problem with NOTHING saved, and
 * `ProblemNotice` says so in the server's words.
 *
 * No permission gate: `agents:write` is held by `owner` and `staff`, every role that can
 * open this screen, so the server's 403 rendered by `ProblemNotice` is the enforcement.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NumberField } from "@/components/arc/number-field";
import { ProblemNotice, SECONDARY_BUTTON_SM, formatCallCap } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { ClientEngineVoices } from "@/components/engineCatalogueList";
import { useEngineCatalogue } from "@/lib/api/engineCatalogue";
import { useLanes, useSetMyCallCap, type PendingState } from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useCopilotSurface } from "@/lib/copilot/registry";

/** The call cap's promise: a save applies from the next call. */
const NEXT_CALL_NOTE =
  "Saved changes reach the calling system straight away and apply from the next call. " +
  "A call already in progress finishes exactly as it started.";

/**
 * The voice platform's own voices as cards, with a save that appears only once the choice
 * differs from the saved voice (`ClientEngineVoices`).
 */
export function VoiceChoice({ agentId, state }: { agentId: string; state: PendingState }) {
  const session = useClientSession();
  const catalogue = useEngineCatalogue(session);

  // THE VOICE SECTION, DECLARED TO THE ASSISTANT: which voice callers hear. The choice itself
  // is made on the cards; nothing changes until the owner saves it.
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: "Agent: voice",
    realm: "client",
    fields: [],
    facts: [
      { key: "voice_now", label: "What callers hear now", value: state.voice.headline },
      {
        key: "state",
        label: "What is on screen",
        value: catalogue.data ? "the voices have loaded" : catalogue.error ? "the voices failed to load" : "still loading",
      },
    ],
    unsaved: false,
    apply: () => undefined,
  });

  return <ClientEngineVoices session={session} agentId={agentId} />;
}

/** The longest one call may run, as one row: the limit in force, and an inline edit. */
export function CallCapChoice({ agentId, state }: { agentId: string; state: PendingState }) {
  const session = useClientSession();
  const lanes = useLanes(session);
  const save = useSetMyCallCap(session, agentId);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const [editing, setEditing] = useState(false);
  const [seconds, setSeconds] = useState<string | null>(null);
  const field =
    seconds ?? (state.call_cap_is_platform_default ? "" : String(state.effective_call_cap_s));
  const trimmed = field.trim();
  const parsed = trimmed === "" ? null : Number(trimmed);
  useUnsavedGuard(editing && seconds !== null);

  const close = () => {
    setEditing(false);
    setSeconds(null);
  };

  return (
    <div>
      <SettingRow
        label="Longest one call may run"
        hint={
          state.call_cap_is_platform_default
            ? "Calevate default"
            : "Just this agent"
        }
        info={
          <p>
            A limit on how long a single call may go on, the guard against one call that
            never ends. It cannot change a word the agent says. Leave it empty to use the
            standard limit
            {lanes.data ? ` (${formatCallCap(lanes.data.call_cap_default_s)})` : ""}; there is
            no way to make a call unlimited, deliberately.
          </p>
        }
        value={formatCallCap(state.effective_call_cap_s)}
        action={
          editing ? undefined : (
            <button type="button" onClick={() => setEditing(true)} className={TEXT_ACTION}>
              Change
            </button>
          )
        }
      />
      {save.error && <ProblemNotice error={save.error} />}
      {editing && (
        <form
          className="settings-enter flex flex-wrap items-end gap-3 pb-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (save.isPending) return;
            save.mutate({ max_call_duration_s: parsed }, { onSuccess: close });
          }}
        >
          {/* The box keeps the limits it is given: typing past one is pulled back to it and
              said under the box, so an out-of-range number never reaches the server. */}
          <NumberField
            label="Seconds"
            unit="seconds"
            optional
            min={lanes.data?.call_cap_min_s ?? 1}
            max={lanes.data?.call_cap_max_s}
            largeStep={60}
            value={parsed !== null && Number.isFinite(parsed) ? parsed : null}
            onChange={(next) => setSeconds(next === null ? "" : String(next))}
          />
          <ActionButton type="submit" variant="primary-sm" status={saveFeedback.status} successLabel="Saved">
            Set limit
          </ActionButton>
          <button type="button" onClick={close} disabled={save.isPending} className={SECONDARY_BUTTON_SM}>
            Cancel
          </button>
          <span className="basis-full text-xs text-ink-muted">
            {parsed === null
              ? "Empty: the standard limit applies."
              : `${formatCallCap(parsed)} per call.`}
            {/* A failed `lanes` read removes this input's bounds, so it says so. */}
            {lanes.isError
              ? " The allowed range did not load, so this box shows no limit; a value outside" +
                " it will still be refused when you save."
              : ""}{" "}
            {NEXT_CALL_NOTE}
          </span>
        </form>
      )}
    </div>
  );
}
