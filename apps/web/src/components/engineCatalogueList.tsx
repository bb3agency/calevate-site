"use client";

import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { PRIMARY_BUTTON_SM, ProblemNotice, Skeleton } from "@/components/ui";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import { viewAsSession } from "@/lib/api/admin";
import { useAgent, useUpdateAgent, type Agent, type AgentUpdateIn } from "@/lib/api/agents";
import type { Session } from "@/lib/api/client";
import {
  useEngineCatalogue,
  useTenantEngineCatalogue,
  type EngineCatalogue,
} from "@/lib/api/engineCatalogue";
import { CLIENT_PREVIEW_PATH } from "@/lib/api/voicePreview";

/** The two rungs, in the order a client reads them. Names only — never a vendor (D-679). */
const RUNGS = [
  { value: "clear", label: "Clear", blurb: "Natural voices for everyday calls." },
  { value: "studio", label: "Studio", blurb: "Our most lifelike voices, billed at the Studio rate." },
] as const;

/** The two fields this picker writes through `PATCH /v1/agents/{id}`. */
export type EngineChoicePatch = Pick<AgentUpdateIn, "engine_voice_id" | "engine_model_id">;

/** What the picker needs to save. Absent, the list is read-only. */
export interface EngineChoiceControl {
  voiceId: string | null;
  modelId: string | null;
  /** Why this reader may not change it, or null when they may. */
  disabledReason: string | null;
  saving: boolean;
  error: Error | null;
  onSave: (patch: EngineChoicePatch) => void;
}

/** The value a radio carries for "the platform's own default". Never a catalogue id: the
 *  server bounds ids to non-whitespace, and this has a space. */
const DEFAULT = "platform default";

/**
 * The voice platform's own voices and models, each with whether it can be used today, and —
 * given `choice` — a picker that saves this agent's voice and model.
 *
 * Shown where the voice picker says the platform supplies its own voices (D-678). The voices
 * are the ones an operator added and enabled (D-687), grouped by rung — Clear, then Studio,
 * which is explained rather than listed while the account cannot have it
 * (`studio_available`) — each with a preview the reader can play before choosing. Every entry
 * is rendered; one the server says cannot be used is disabled with the server's own sentence
 * (an unpriced rung, a model too slow for a phone call, a model the plan does not include),
 * and a Studio voice beside a model that cannot run with one is disabled with that reason. The server checks the choice again when it saves and when it publishes, so this
 * screen composes no refusal of its own. "Platform default" sends `null`, which the server
 * refuses by name once a choice has been published, because the platform keeps the last
 * voice it was given. Where the account runs on its own keys the server says `choosable: false`
 * and the picker locks on its `choice_note`. Renders nothing on a platform that publishes no
 * catalogue of its own.
 */
export function EngineCatalogueList({
  catalogue,
  choice,
  previewSession,
}: {
  catalogue: UseQueryResult<EngineCatalogue>;
  choice?: EngineChoiceControl;
  /** The session the preview clips are read through: the reader's own, or view-as. */
  previewSession?: Session;
}) {
  const [voice, setVoice] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);

  if (catalogue.isLoading) return <Skeleton rows={2} />;
  if (catalogue.error || !catalogue.data) {
    return (
      <ProblemNotice
        error={catalogue.error ?? new Error("The voice platform's own voices did not load.")}
        onRetry={() => void catalogue.refetch()}
      />
    );
  }
  const data = catalogue.data;
  if (!data.available) return null;

  const savedVoice = choice?.voiceId ?? DEFAULT;
  const savedModel = choice?.modelId ?? DEFAULT;
  const selectedVoice = voice ?? savedVoice;
  const selectedModel = model ?? savedModel;
  const patch: EngineChoicePatch = {};
  if (selectedVoice !== savedVoice) {
    patch.engine_voice_id = selectedVoice === DEFAULT ? null : selectedVoice;
  }
  if (selectedModel !== savedModel) {
    patch.engine_model_id = selectedModel === DEFAULT ? null : selectedModel;
  }
  const changed = Object.keys(patch).length > 0;
  // The platform's own lock (the account runs on its own keys) before this reader's.
  const lockReason = !data.choosable
    ? (data.choice_note ?? null)
    : (choice?.disabledReason ?? null);
  const locked = !choice || lockReason !== null || choice.saving;
  // A Studio voice and the model must agree, and the server refuses the pair by name
  // (`engine_model_not_with_studio_voice`). The picker says so before the save: the model
  // in the selection blocks Studio voices, and a Studio voice in the selection blocks the
  // models that cannot run beside it.
  const chosenModel = data.models.find((entry) => entry.model_id === selectedModel);
  const studioBlockedBy =
    chosenModel && !chosenModel.usable_with_studio_voice ? chosenModel.label : null;
  const studioVoiceChosen =
    data.voices.find((entry) => entry.voice_id === selectedVoice)?.rung === "studio";

  const body = (
    <>
      <p className="text-xs text-ink-muted">
        {data.note}
        {!data.complete && " The platform's list was cut short, so some may be missing."}
      </p>
      {choice && lockReason && <p className="text-xs text-ink-muted">{lockReason}</p>}
      {choice?.error && <ProblemNotice error={choice.error} />}
      {choice && (
        <ul className="border-y border-line" aria-label="Default voice">
          <Option
            name="engine-voice"
            value={DEFAULT}
            label="Platform default"
            detail="The voice the platform picks when none is chosen."
            checked={selectedVoice === DEFAULT}
            current={savedVoice === DEFAULT}
            disabled={locked}
            onChange={setVoice}
          />
        </ul>
      )}
      {data.voices.length === 0 ? (
        <p className="text-sm text-ink-muted">No voice is offered yet.</p>
      ) : (
        RUNGS.map((rung) => {
          const voices = data.voices.filter((entry) => entry.rung === rung.value);
          if (rung.value === "studio" && !data.studio_available && voices.length === 0) return null;
          return (
            <fieldset key={rung.value} className="space-y-1">
              <legend className="text-meta font-semibold text-ink-muted">
                {rung.label} voices
              </legend>
              <p className="text-xs text-ink-muted">{rung.blurb}</p>
              {rung.value === "studio" && !data.studio_available ? (
                <p className="mt-1 text-sm text-ink-muted">
                  Studio voices are not available on this account yet.
                </p>
              ) : voices.length === 0 ? (
                <p className="mt-1 text-sm text-ink-muted">No {rung.label} voice is offered yet.</p>
              ) : (
                <ul className="mt-1 divide-y divide-line border-y border-line">
                  {voices.map((entry) => {
                    const blocked =
                      entry.rung === "studio" && studioBlockedBy !== null
                        ? `The language model chosen below, ${studioBlockedBy}, cannot be used with a Studio voice. Choose another model to use this voice.`
                        : null;
                    return (
                      <Option
                        key={entry.voice_id}
                        name="engine-voice"
                        value={choice ? entry.voice_id : null}
                        label={entry.label}
                        suffix={entry.is_custom ? "made for this platform" : undefined}
                        detail={entry.language_note}
                        reason={entry.offerable ? blocked : entry.reason}
                        checked={selectedVoice === entry.voice_id}
                        current={savedVoice === entry.voice_id}
                        disabled={locked || !entry.offerable || blocked !== null}
                        onChange={setVoice}
                        extra={
                          entry.preview_available && previewSession ? (
                            <VoicePreviewButton
                              session={previewSession}
                              path={CLIENT_PREVIEW_PATH}
                              voiceId={entry.voice_id}
                              label={entry.label}
                            />
                          ) : undefined
                        }
                      />
                    );
                  })}
                </ul>
              )}
            </fieldset>
          );
        })
      )}
      <fieldset className="space-y-1">
        <legend className="text-meta font-semibold text-ink-muted">
          The platform&apos;s language models
        </legend>
        {data.models.length === 0 ? (
          <p className="mt-1 text-sm text-ink-muted">The platform listed no models.</p>
        ) : (
          <ul className="mt-1 divide-y divide-line border-y border-line">
            {choice && (
              <Option
                name="engine-model"
                value={DEFAULT}
                label="Platform default"
                detail="The model the platform picks when none is chosen."
                checked={selectedModel === DEFAULT}
                current={savedModel === DEFAULT}
                disabled={locked}
                onChange={setModel}
              />
            )}
            {data.models.map((entry) => {
              const clash =
                studioVoiceChosen && !entry.usable_with_studio_voice
                  ? "This model cannot be used with a Studio voice. Choose a Clear voice to use it."
                  : null;
              return (
                <Option
                  key={entry.model_id}
                  name="engine-model"
                  value={choice ? entry.model_id : null}
                  label={entry.label}
                  reason={entry.offerable ? clash : entry.reason}
                  checked={selectedModel === entry.model_id}
                  current={savedModel === entry.model_id}
                  disabled={locked || !entry.offerable || clash !== null}
                  onChange={setModel}
                />
              );
            })}
          </ul>
        )}
      </fieldset>
    </>
  );

  if (!choice) return <div className="space-y-4">{body}</div>;
  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (changed) choice.onSave(patch);
      }}
    >
      {body}
      <button type="submit" disabled={locked || !changed} className={PRIMARY_BUTTON_SM}>
        {choice.saving ? "Saving…" : "Save voice and model"}
      </button>
    </form>
  );
}

/**
 * One row: a radio when the list is a picker (`value` set), plain text when it is not.
 * `extra` (the preview button) sits OUTSIDE the label, so pressing play never changes the
 * selection. `current` marks what is saved now, which a moved radio no longer shows.
 */
function Option({
  name,
  value,
  label,
  suffix,
  detail,
  reason,
  checked,
  current = false,
  disabled,
  onChange,
  extra,
}: {
  name: string;
  value: string | null;
  label: string;
  suffix?: string;
  detail?: string;
  reason?: string | null;
  checked: boolean;
  current?: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
  extra?: ReactNode;
}) {
  const text = (
    <>
      <span className="font-medium text-ink">{label}</span>
      {suffix && <span className="text-ink-muted">{` · ${suffix}`}</span>}
      {current && (
        <span className="ml-2 inline-flex rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-medium text-brand-strong">
          In use
        </span>
      )}
      {reason ? (
        <span className="mt-0.5 block text-xs font-medium text-warn">
          Cannot be used — {reason}
        </span>
      ) : (
        <span className="mt-0.5 block text-xs text-ink-muted">{detail ?? "Available"}</span>
      )}
    </>
  );
  return (
    <li className="flex flex-wrap items-start justify-between gap-2 px-3 py-2 text-sm">
      {value === null ? (
        <span className="min-w-0 flex-1">{text}</span>
      ) : (
        <label className="flex min-w-0 flex-1 items-start gap-2">
          <input
            type="radio"
            name={name}
            value={value}
            checked={checked}
            disabled={disabled}
            onChange={() => onChange(value)}
            className="mt-1"
          />
          <span className="min-w-0">{text}</span>
        </label>
      )}
      {extra}
    </li>
  );
}

function control(
  agent: Agent | undefined,
  save: ReturnType<typeof useUpdateAgent>,
  disabledReason: string | null,
  onSaved?: () => void,
): EngineChoiceControl | undefined {
  if (!agent) return undefined;
  return {
    voiceId: agent.engine_voice_id ?? null,
    modelId: agent.engine_model_id ?? null,
    disabledReason,
    saving: save.isPending,
    error: save.error,
    onSave: (patch) => save.mutate(patch, { onSuccess: onSaved }),
  };
}

/** The picker, through the console's view-as session for one tenant. Mounted only where the
 *  voice picker has already said the platform supplies its own voices. */
export function TenantEngineCatalogue({
  slug,
  agent,
  disabledReason = null,
}: {
  slug: string;
  agent?: Agent;
  disabledReason?: string | null;
}) {
  const client = useQueryClient();
  const save = useUpdateAgent(viewAsSession(slug), agent?.id ?? "");
  // The console reads this agent from its own roster query, which the client hook's refresh
  // does not know about.
  const refreshRoster = () =>
    void client.invalidateQueries({ queryKey: ["admin", "agents", slug] });
  return (
    <EngineCatalogueList
      catalogue={useTenantEngineCatalogue(slug)}
      choice={control(agent, save, disabledReason, refreshRoster)}
      previewSession={viewAsSession(slug)}
    />
  );
}

/** The picker, through a client's own session. Mounted under the same condition. */
export function ClientEngineCatalogue({ session, agentId }: { session: Session; agentId: string }) {
  const agent = useAgent(session, agentId);
  const save = useUpdateAgent(session, agentId);
  return (
    <EngineCatalogueList
      catalogue={useEngineCatalogue(session)}
      choice={control(agent.data, save, null)}
      previewSession={session}
    />
  );
}
