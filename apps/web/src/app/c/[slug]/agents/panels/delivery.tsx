"use client";

/**
 * HOW THE AGENT SOUNDS, AND HOW LONG ONE CALL MAY RUN — the two settings D-586 put in the
 * account's own hands, as controls. The state they change (`panels/publishing.tsx`) is a
 * read; these are the decision.
 *
 * ## Both apply to the NEXT call, and the copy says so
 *
 * The server writes the row and re-publishes a live agent in the SAME transaction
 * (`agents/publishing.py`), so neither has an Apply step. What a client must still be told
 * is the one thing a transaction cannot decide: a call already in progress finishes as it
 * started. "Applies immediately" without that sentence is how somebody comes to believe a
 * shorter cap cuts off the call they are listening to.
 *
 * ## Nothing here composes a refusal of its own
 *
 * An unofferable voice carries the server's own sentence in the client's language
 * (`agents/voice_offer.py::client_unofferable_reason`); a cap outside the range is refused
 * with `call_cap_out_of_range` and the bounds come from `GET /v1/agents/lanes`. A vendor
 * refusal on the re-publish arrives as a `dependency` problem with NOTHING saved, and
 * `ProblemNotice` says so in the server's words.
 *
 * No permission gate: `agents:write` is held by `owner` and `staff`, every role that can
 * open this screen, so the server's 403 rendered by `ProblemNotice` is the enforcement.
 */

import { useState } from "react";

import { FieldMessage, useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCallCap,
} from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { ClientEngineCatalogue } from "@/components/engineCatalogueList";
import { useLanes, useSetMyCallCap, type PendingState } from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";
import { useSetMyAgentVoice, useVoiceCatalogue } from "@/lib/api/voices";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { VoiceCards } from "./voiceCards";

/** One sentence, shared by both controls, because it is one promise. */
const NEXT_CALL_NOTE =
  "Saved changes reach the calling system straight away and apply from the next call. " +
  "A call already in progress finishes exactly as it started.";

/**
 * The voice cards, and a save that appears only once the choice differs from the saved
 * voice — the write re-publishes a live agent, so a mis-tap must not be the save.
 */
export function VoiceChoice({ agentId, state }: { agentId: string; state: PendingState }) {
  const session = useClientSession();
  const catalogue = useVoiceCatalogue(session);
  const save = useSetMyAgentVoice(session, agentId);
  const [choice, setChoice] = useState<string | null>(null);
  const saved = state.voice.configured?.voice_id ?? "";
  const selected = choice ?? saved;
  const changed = selected !== "" && selected !== saved;
  useUnsavedGuard(changed);

  // THE VOICE SECTION, DECLARED TO THE ASSISTANT: which voice callers hear, and the choice
  // as a field it can fill ("use a female Telugu voice"). Nothing changes until the owner
  // presses "Use this voice".
  const offered = catalogue.data?.selectable ? catalogue.data.voices.filter((v) => v.offerable) : [];
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: "Agent: voice",
    realm: "client",
    fields:
      offered.length > 0
        ? [
            {
              id: "agent-voice",
              label: "Voice callers hear",
              type: "select",
              value: selected,
              options: offered.map((v) => ({ value: v.id, label: `${v.label} (${v.tier_label})` })),
            },
          ]
        : [],
    facts: [
      { key: "voice_now", label: "What callers hear now", value: state.voice.headline },
      {
        key: "state",
        label: "What is on screen",
        value: catalogue.data ? "the voices have loaded" : catalogue.error ? "the voices failed to load" : "still loading",
      },
      { key: "unsaved", label: "A different voice is picked but not saved", value: changed ? "yes" : "no" },
    ],
    unsaved: changed,
    apply: (items) => {
      for (const item of items) {
        const id = asText(item.value);
        if (item.field_id === "agent-voice" && offered.some((v) => v.id === id)) setChoice(id);
      }
    },
  });

  // A read like any other: a skeleton in flight and a refusal on failure — never an empty
  // list, which would be a claim about the product rather than about a request.
  if (catalogue.isLoading) return <Skeleton rows={3} />;
  if (catalogue.error || !catalogue.data) {
    return (
      <ProblemNotice
        error={catalogue.error ?? new Error("The voices did not load, so there is nothing to choose from.")}
        onRetry={() => void catalogue.refetch()}
      />
    );
  }
  if (!catalogue.data.selectable) {
    // The deployment working as intended, so the server's own words and not an error card.
    return (
      <div className="space-y-3">
        <p className="text-sm text-ink-muted">{catalogue.data.note}</p>
        <ClientEngineCatalogue session={session} agentId={agentId} />
      </div>
    );
  }

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(selected, { onSuccess: () => setChoice(null) });
      }}
    >
      {catalogue.data.note && <p className="text-sm text-ink-muted">{catalogue.data.note}</p>}
      {save.error && <ProblemNotice error={save.error} />}
      <VoiceCards
        name="my-agent-voice"
        voices={catalogue.data.voices}
        value={selected}
        rates={state.voice_tier_rates}
        tiers={catalogue.data.tiers}
        onChange={setChoice}
      />
      {(changed || save.isPending) && (
        <div className="settings-enter sticky bottom-0 -mx-1 flex flex-wrap items-center gap-3 border-t border-line bg-surface/95 px-1 py-3 backdrop-blur-sm">
          <button type="submit" disabled={save.isPending} className={PRIMARY_BUTTON_SM}>
            {save.isPending ? "Saving…" : "Use this voice"}
          </button>
          <button
            type="button"
            disabled={save.isPending}
            onClick={() => setChoice(null)}
            className={SECONDARY_BUTTON_SM}
          >
            Cancel
          </button>
          <span className="text-xs text-ink-muted">{NEXT_CALL_NOTE}</span>
        </div>
      )}
    </form>
  );
}

/** The longest one call may run, as one row: the limit in force, and an inline edit. */
export function CallCapChoice({ agentId, state }: { agentId: string; state: PendingState }) {
  const session = useClientSession();
  const lanes = useLanes(session);
  const save = useSetMyCallCap(session, agentId);
  const valid = useFormValidation();
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
            ? "The standard limit we put on every agent."
            : "Set specifically for this agent."
        }
        info={
          <p>
            A limit on how long a single call may go on — the guard against one call that
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
          onSubmit={valid.onSubmit(() => {
            save.mutate({ max_call_duration_s: parsed }, { onSuccess: close });
          })}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="my-call-cap" className="text-xs text-ink-muted">
              Seconds
            </label>
            <input
              id="my-call-cap"
              {...valid.track("seconds", "Enter how many seconds a call may run.")}
              type="number"
              inputMode="numeric"
              value={field}
              min={lanes.data?.call_cap_min_s}
              max={lanes.data?.call_cap_max_s}
              onChange={(event) => setSeconds(event.target.value)}
              placeholder={lanes.data ? String(lanes.data.call_cap_default_s) : "standard limit"}
              className={`w-32 tabular-nums ${FIELD}`}
              aria-invalid={valid.message("seconds") ? true : undefined}
              aria-describedby={valid.message("seconds") ? "my-call-cap-error" : undefined}
            />
            {valid.message("seconds") ? (
              <FieldMessage id="my-call-cap-error">{valid.message("seconds")}</FieldMessage>
            ) : null}
          </div>
          <button type="submit" disabled={save.isPending} className={PRIMARY_BUTTON_SM}>
            {save.isPending ? "Saving…" : "Set limit"}
          </button>
          <button type="button" onClick={close} disabled={save.isPending} className={SECONDARY_BUTTON_SM}>
            Cancel
          </button>
          <span className="basis-full text-xs text-ink-muted">
            {parsed === null
              ? "Empty — the standard limit applies."
              : `${formatCallCap(parsed)} per call.`}
            {/* A failed `lanes` read removes this input's bounds, so it says so. */}
            {lanes.isError
              ? " The allowed range could not be read, so this box is unbounded here; the" +
                " server will still refuse a value outside it."
              : ""}{" "}
            {NEXT_CALL_NOTE}
          </span>
        </form>
      )}
    </div>
  );
}
