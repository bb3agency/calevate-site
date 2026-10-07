"use client";

import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useState } from "react";

import { PRIMARY_BUTTON_SM, ProblemNotice, Skeleton } from "@/components/ui";
import { viewAsSession } from "@/lib/api/admin";
import { useAgent, useUpdateAgent, type Agent, type AgentUpdateIn } from "@/lib/api/agents";
import type { Session } from "@/lib/api/client";
import {
  useEngineCatalogue,
  useTenantEngineCatalogue,
  type EngineCatalogue,
} from "@/lib/api/engineCatalogue";

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
 * Shown where the voice picker says the platform supplies its own voices (D-678). Every entry
 * is rendered; one the server says cannot be used is disabled with the server's own sentence
 * (an unpriced voice band, a model too slow for a phone call, a model the plan does not
 * include). The server checks the choice again when it saves and when it publishes, so this
 * screen composes no refusal of its own. "Platform default" sends `null`, which the server
 * refuses by name once a choice has been published, because the platform keeps the last
 * voice it was given. Where the account runs on its own keys the server says `choosable: false`
 * and the picker locks on its `choice_note`. Renders nothing on a platform that publishes no
 * catalogue of its own.
 */
export function EngineCatalogueList({
  catalogue,
  choice,
}: {
  catalogue: UseQueryResult<EngineCatalogue>;
  choice?: EngineChoiceControl;
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

  const body = (
    <>
      <p className="text-xs text-ink-muted">
        {data.note}
        {!data.complete && " The platform's list was cut short, so some may be missing."}
      </p>
      {choice && lockReason && <p className="text-xs text-ink-muted">{lockReason}</p>}
      {choice?.error && <ProblemNotice error={choice.error} />}
      <fieldset className="space-y-1">
        <legend className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
          The platform&apos;s voices
        </legend>
        {data.voices.length === 0 ? (
          <p className="mt-1 text-sm text-ink-muted">The platform listed no voices.</p>
        ) : (
          <ul className="mt-1 divide-y divide-line rounded-card border border-line">
            {choice && (
              <Option
                name="engine-voice"
                value={DEFAULT}
                label="Platform default"
                detail="The voice the platform picks when none is chosen."
                checked={selectedVoice === DEFAULT}
                disabled={locked}
                onChange={setVoice}
              />
            )}
            {data.voices.map((entry) => (
              <Option
                key={entry.voice_id}
                name="engine-voice"
                value={choice ? entry.voice_id : null}
                label={entry.label}
                suffix={`${entry.price_band}${entry.is_custom ? " · cloned for this account" : ""}`}
                reason={entry.offerable ? null : entry.reason}
                checked={selectedVoice === entry.voice_id}
                disabled={locked || !entry.offerable}
                onChange={setVoice}
              />
            ))}
          </ul>
        )}
      </fieldset>
      <fieldset className="space-y-1">
        <legend className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
          The platform&apos;s language models
        </legend>
        {data.models.length === 0 ? (
          <p className="mt-1 text-sm text-ink-muted">The platform listed no models.</p>
        ) : (
          <ul className="mt-1 divide-y divide-line rounded-card border border-line">
            {choice && (
              <Option
                name="engine-model"
                value={DEFAULT}
                label="Platform default"
                detail="The model the platform picks when none is chosen."
                checked={selectedModel === DEFAULT}
                disabled={locked}
                onChange={setModel}
              />
            )}
            {data.models.map((entry) => (
              <Option
                key={entry.model_id}
                name="engine-model"
                value={choice ? entry.model_id : null}
                label={entry.label}
                reason={entry.offerable ? null : entry.reason}
                checked={selectedModel === entry.model_id}
                disabled={locked || !entry.offerable}
                onChange={setModel}
              />
            ))}
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

/** One row: a radio when the list is a picker (`value` set), plain text when it is not. */
function Option({
  name,
  value,
  label,
  suffix,
  detail,
  reason,
  checked,
  disabled,
  onChange,
}: {
  name: string;
  value: string | null;
  label: string;
  suffix?: string;
  detail?: string;
  reason?: string | null;
  checked: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const text = (
    <>
      <span className="font-medium text-ink">{label}</span>
      {suffix && <span className="text-ink-muted">{` · ${suffix}`}</span>}
      {reason ? (
        <span className="mt-0.5 block text-xs font-medium text-amber-700 dark:text-amber-400">
          Cannot be used — {reason}
        </span>
      ) : (
        <span className="mt-0.5 block text-xs text-ink-muted">{detail ?? "Available"}</span>
      )}
    </>
  );
  if (value === null) return <li className="px-3 py-2 text-sm">{text}</li>;
  return (
    <li className="px-3 py-2 text-sm">
      <label className="flex items-start gap-2">
        <input
          type="radio"
          name={name}
          value={value}
          checked={checked}
          disabled={disabled}
          onChange={() => onChange(value)}
          className="mt-1"
        />
        <span>{text}</span>
      </label>
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
    />
  );
}
