"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  tuningNumber,
  useSetVoiceTuning,
  useVoiceTuning,
  useVoiceTuningPreview,
  type VoiceTuning,
  type VoiceTuningIn,
} from "@/lib/api/voiceTuning";

/** One labelled control with its hint read out with it (`aria-describedby`). */
function Field({
  id,
  label,
  hint,
  wide = false,
  children,
}: {
  id: string;
  label: string;
  hint: string;
  wide?: boolean;
  children: (props: { id: string; "aria-describedby": string }) => ReactNode;
}) {
  return (
    <div className={wide ? "sm:col-span-2" : undefined}>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children({ id, "aria-describedby": `${id}-hint` })}
      <span id={`${id}-hint`} className={FIELD_HINT}>
        {hint}
      </span>
    </div>
  );
}

function range(low: string, high: string): string {
  return `${String(tuningNumber(low))} to ${String(tuningNumber(high))}`;
}

/** The form's own copy of the settings: what the inputs hold, as typed. */
interface Draft {
  speed: string;
  volume: string;
  emotion: string;
  model: string;
  dictionaryId: string;
}

function draftOf(held: VoiceTuning): Draft {
  return {
    speed: held.speed == null ? "" : String(tuningNumber(held.speed)),
    volume: held.volume == null ? "" : String(tuningNumber(held.volume)),
    emotion: held.emotion ?? "",
    model: held.model ?? "",
    dictionaryId: held.dictionary_id ?? "",
  };
}

/** Every field stated, an empty one as null: a save sets the form exactly as shown. */
function bodyOf(draft: Draft): VoiceTuningIn {
  return {
    speed: draft.speed.trim() === "" ? null : Number(draft.speed),
    volume: draft.volume.trim() === "" ? null : Number(draft.volume),
    emotion: draft.emotion || null,
    model: draft.model || null,
    dictionary_id: draft.dictionaryId.trim() || null,
  };
}

/**
 * How it sounds: speed, volume, emotion, the voice model and a pronunciation dictionary for
 * this agent's Studio voice. The client sets speed, loudness and emotion on its own screen
 * too (D-843); the voice model and dictionary are set only here.
 *
 * "Hear it" speaks a short line with the settings as they are in the form, unsaved, on our
 * voice key (charged per character, so only on a press). "Save settings" stores them and the
 * server brings a live agent up to date before its next call.
 */
export function VoiceTuningPanel({
  tenantId,
  agentId,
  write,
}: {
  tenantId: string;
  agentId: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const held = useVoiceTuning(tenantId, agentId);
  const save = useSetVoiceTuning(tenantId, agentId);
  const preview = useVoiceTuningPreview(tenantId, agentId);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const id = useId();

  useEffect(() => {
    if (held.data) setDraft(draftOf(held.data));
  }, [held.data]);

  useEffect(() => {
    if (!preview.data) return;
    const url = URL.createObjectURL(preview.data);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [preview.data]);

  useEffect(() => {
    if (!src) return;
    // A browser that refuses autoplay leaves the controls for a press.
    const started = audio.current?.play();
    if (started) void started.catch(() => undefined);
  }, [src]);

  if (held.isLoading) return <Skeleton rows={2} />;
  if (held.error || !held.data) {
    return (
      <ProblemNotice
        error={held.error ?? new Error("This agent's voice settings could not be read just now.")}
        onRetry={() => void held.refetch()}
      />
    );
  }
  const data = held.data;
  const options = data.options;
  if (!data.studio) {
    return (
      <section aria-labelledby="voice-tuning-heading" className="mt-8 space-y-2">
        <h3 id="voice-tuning-heading" className="text-heading text-ink">
          How it sounds
        </h3>
        <p className="max-w-prose text-body text-ink-muted">
          Speed, volume, emotion and pronunciation can be set for a Studio voice. This agent
          does not speak one.
        </p>
      </section>
    );
  }
  const form = draft ?? draftOf(data);
  const oldModel = form.model === options.old_model;
  const set = (patch: Partial<Draft>) => {
    setSaved(false);
    setDraft({ ...form, ...patch });
  };
  const disabled = !write.allowed;

  return (
    <section aria-labelledby="voice-tuning-heading" className="mt-8 space-y-3">
      <h3 id="voice-tuning-heading" className="text-heading text-ink">
        How it sounds
      </h3>
      <p className="max-w-prose text-body text-ink-muted">
        For this agent alone. Empty leaves the voice as it is. The voice treats these as
        guidance, so listen before relying on a value.
      </p>
      <form
        className="grid grid-cols-1 max-w-xl gap-3 sm:grid-cols-2"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(bodyOf(form), { onSuccess: () => setSaved(true) });
        }}
      >
        <Field id={`${id}-speed`} label="Speed" hint={`${range(options.speed_min, options.speed_max)}; 1 is the voice's own pace. A voice cloned from a long recording keeps its own.`}>
          {(props) => (
            <input
              {...props}
              className={FIELD}
              type="number"
              inputMode="decimal"
              step="0.05"
              min={tuningNumber(options.speed_min) ?? undefined}
              max={tuningNumber(options.speed_max) ?? undefined}
              value={form.speed}
              disabled={disabled}
              onChange={(event) => set({ speed: event.target.value })}
            />
          )}
        </Field>
        <Field id={`${id}-volume`} label="Volume" hint={`${range(options.volume_min, options.volume_max)}; raise it if calls sound quiet.`}>
          {(props) => (
            <input
              {...props}
              className={FIELD}
              type="number"
              inputMode="decimal"
              step="0.05"
              min={tuningNumber(options.volume_min) ?? undefined}
              max={tuningNumber(options.volume_max) ?? undefined}
              value={form.volume}
              disabled={disabled}
              onChange={(event) => set({ volume: event.target.value })}
            />
          )}
        </Field>
        <Field id={`${id}-emotion`} label="Emotion" hint="Empty lets the words decide.">
          {(props) => (
            <select
              {...props}
              className={FIELD}
              value={form.emotion}
              disabled={disabled}
              onChange={(event) => set({ emotion: event.target.value })}
            >
              <option value="">Let the words decide</option>
              {options.emotions.map((emotion) => (
                <option key={emotion} value={emotion}>
                  {emotion}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field
          id={`${id}-model`}
          label="Voice model"
          hint={
            oldModel
              ? `${options.old_model} takes no speed, volume or emotion: clear them to save.`
              : "For this agent alone."
          }
        >
          {(props) => (
            <select
              {...props}
              className={FIELD}
              value={form.model}
              disabled={disabled}
              onChange={(event) => set({ model: event.target.value })}
            >
              <option value="">The voice key&apos;s own model</option>
              {options.models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field
          id={`${id}-dictionary`}
          label="Pronunciation dictionary id"
          hint="As our voice account shows it; empty for none."
          wide
        >
          {(props) => (
            <input
              {...props}
              className={FIELD}
              type="text"
              spellCheck={false}
              autoComplete="off"
              maxLength={80}
              value={form.dictionaryId}
              disabled={disabled}
              onChange={(event) => set({ dictionaryId: event.target.value })}
            />
          )}
        </Field>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={disabled || preview.isPending}
            onClick={() => preview.mutate(bodyOf(form))}
          >
            {preview.isPending ? "Speaking…" : "Hear it"}
          </button>
          <button type="submit" className={PRIMARY_BUTTON_SM} disabled={disabled || save.isPending}>
            {save.isPending ? "Saving…" : "Save settings"}
          </button>
          {saved && (
            <span role="status" className="text-meta text-ink-muted">
              Saved. A live agent uses them from its next call.
            </span>
          )}
        </div>
      </form>
      {src && (
        <audio ref={audio} src={src} controls className="w-full max-w-xl">
          <track kind="captions" />
        </audio>
      )}
      {preview.error && <ProblemNotice error={preview.error} />}
      {save.error && <ProblemNotice error={save.error} />}
    </section>
  );
}
