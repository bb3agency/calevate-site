"use client";

/**
 * HOW IT SOUNDS — speed, loudness and emotion for an agent's Studio voice (D-843).
 *
 * The two sliders put Normal (1.0, the voice's own) in the MIDDLE although neither range is
 * centred on it (speed 0.6-1.5, loudness 0.5-2.0): each half of the track is scaled to its
 * own side, so "slower" and "faster" get the same travel. Normal is sent as null, which is
 * the voice's own setting rather than a value on top of it.
 *
 * "Hear it" speaks a fixed sample line with the settings as they are on screen, unsaved; each
 * press uses one of the account's samples for the day, so it plays only on a press. A voice
 * that keeps the pace it was recorded at refuses speed; that refusal is said as a sentence
 * and the other settings stay usable. Nothing here names the voice provider (D-679).
 */

import { useEffect, useId, useRef, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD, FIELD_LABEL, NoticeBox, ProblemNotice, Skeleton } from "@/components/ui";
import { Slider as KitSlider } from "@/components/arc/slider";
import { TEXT_ACTION } from "@/components/console/section";
import { ApiProblem } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import {
  tuningNumber,
  useClientVoiceTuning,
  useClientVoiceTuningPreview,
  useSetClientVoiceTuning,
  type ClientVoiceTuning,
  type ClientVoiceTuningIn,
} from "@/lib/api/voiceTuning";

/** Slider positions either side of Normal. */
const HALF = 50;
const NORMAL = 1;

/** A value (min..max) as a slider position (0..2×HALF), Normal at HALF. */
export function positionOf(value: number, min: number, max: number): number {
  const clamped = Math.min(Math.max(value, min), max);
  const position =
    clamped <= NORMAL
      ? (HALF * (clamped - min)) / (NORMAL - min)
      : HALF + (HALF * (clamped - NORMAL)) / (max - NORMAL);
  return Math.round(position);
}

/** A slider position as a value in hundredths, the precision the server keeps. */
export function valueOf(position: number, min: number, max: number): number {
  const raw =
    position <= HALF
      ? min + ((NORMAL - min) * position) / HALF
      : NORMAL + ((max - NORMAL) * (position - HALF)) / HALF;
  return Math.round(raw * 100) / 100;
}

export function multiplierLabel(value: number): string {
  return value === NORMAL ? "Normal" : `${value.toFixed(2)}×`;
}

const EMOTION_LABELS: Record<string, string> = {
  neutral: "Neutral",
  calm: "Calm",
  content: "Content",
  sad: "Sad",
  angry: "Angry",
  scared: "Scared",
  happy: "Happy",
  excited: "Excited",
};

function emotionLabel(emotion: string): string {
  return lookup(EMOTION_LABELS, emotion) ?? emotion.charAt(0).toUpperCase() + emotion.slice(1);
}

interface Draft {
  speed: number;
  volume: number;
  /** "" is none: the words decide. */
  emotion: string;
}

function draftOf(held: ClientVoiceTuning): Draft {
  return {
    speed: tuningNumber(held.speed) ?? NORMAL,
    volume: tuningNumber(held.volume) ?? NORMAL,
    emotion: held.emotion ?? "",
  };
}

/** Every field stated, Normal and none as null: a save sets the voice exactly as shown. */
function bodyOf(draft: Draft): ClientVoiceTuningIn {
  return {
    speed: draft.speed === NORMAL ? null : draft.speed,
    volume: draft.volume === NORMAL ? null : draft.volume,
    emotion: draft.emotion || null,
  };
}

function sameDraft(a: Draft, b: Draft): boolean {
  return a.speed === b.speed && a.volume === b.volume && a.emotion === b.emotion;
}

function codeOf(error: Error | null): string | null {
  return error instanceof ApiProblem ? error.code : null;
}

function Slider({
  id,
  label,
  slower,
  faster,
  value,
  min,
  max,
  onChange,
}: {
  id: string;
  label: string;
  slower: string;
  faster: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  // The track runs over positions, not values (each half is scaled to its own side), so the
  // words are read from `value` rather than from the position the slider hands back.
  return (
    <KitSlider
      id={id}
      label={label}
      min={0}
      max={2 * HALF}
      step={1}
      value={positionOf(value, min, max)}
      onChange={(position) => onChange(valueOf(position, min, max))}
      valueText={() => multiplierLabel(value)}
      spokenText={() => (value === NORMAL ? "Normal" : `${value.toFixed(2)} times normal`)}
      scale={[slower, "Normal", faster]}
      marks={[HALF]}
      labelAction={
        <button
          type="button"
          className={TEXT_ACTION}
          disabled={value === NORMAL}
          onClick={() => onChange(NORMAL)}
          aria-label={`Reset ${label.toLowerCase()} to normal`}
        >
          Reset
        </button>
      }
    />
  );
}

function PreviewRefusal({ error }: { error: Error }) {
  if (codeOf(error) === "voice_speed_not_for_this_voice") {
    return (
      <NoticeBox tone="warn" role="status">
        This voice keeps the pace it was recorded at, so its speed cannot be changed. Set
        speed back to Normal; loudness and emotion still work.
      </NoticeBox>
    );
  }
  return <ProblemNotice error={error} />;
}

export function ClientVoiceTuning({
  agentId,
  voiceId,
}: {
  agentId: string;
  voiceId: string | null;
}) {
  const session = useClientSession();
  const held = useClientVoiceTuning(session, agentId, voiceId);
  const save = useSetClientVoiceTuning(session, agentId, voiceId);
  const preview = useClientVoiceTuningPreview(session, agentId, voiceId);
  // Both refusals are drawn under the form (a used-up day and a voice that keeps its pace
  // each have their own sentence), so neither is toasted.
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const previewFeedback = useActionFeedback(preview, { errorDisplay: "inline" });
  // Null follows the saved settings; set only by an edit, so a sample's refetch of the count
  // left today never throws away settings being tried.
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const id = useId();

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

  if (held.isLoading) return <Skeleton rows={3} />;
  if (held.error || !held.data) {
    return (
      <ProblemNotice
        error={held.error ?? new Error("How this agent sounds could not be read just now.")}
        onRetry={() => void held.refetch()}
      />
    );
  }
  const data = held.data;
  const options = data.options;
  if (!data.studio) {
    return (
      <section aria-labelledby={`${id}-heading`} className="space-y-2">
        <h3 id={`${id}-heading`} className="text-heading text-ink">
          How it sounds
        </h3>
        <p className="max-w-prose text-body text-ink-muted">
          Speed, loudness and emotion can be set when the agent speaks a Studio voice.
        </p>
      </section>
    );
  }
  const form = draft ?? draftOf(data);
  const dirty = !sameDraft(form, draftOf(data));
  const set = (patch: Partial<Draft>) => {
    setSaved(false);
    setDraft({ ...form, ...patch });
  };
  const speedMin = tuningNumber(options.speed_min) ?? 0.6;
  const speedMax = tuningNumber(options.speed_max) ?? 1.5;
  const volumeMin = tuningNumber(options.volume_min) ?? 0.5;
  const volumeMax = tuningNumber(options.volume_max) ?? 2;
  const left = data.previews_left_today;
  const usedUp = left === 0;

  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-3">
      <h3 id={`${id}-heading`} className="text-heading text-ink">
        How it sounds
      </h3>
      <p className="max-w-prose text-body text-ink-muted">
        For this agent alone. Normal is the voice as it was made. Listen before relying on a
        setting: the voice treats these as guidance.
      </p>
      <form
        className="grid max-w-xl gap-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!dirty || save.isPending) return;
          save.mutate(bodyOf(form), {
            onSuccess: () => {
              setDraft(null);
              setSaved(true);
            },
          });
        }}
      >
        <Slider
          id={`${id}-speed`}
          label="Speed"
          slower="Slower"
          faster="Faster"
          value={form.speed}
          min={speedMin}
          max={speedMax}
          onChange={(speed) => set({ speed })}
        />
        <Slider
          id={`${id}-volume`}
          label="Loudness"
          slower="Quieter"
          faster="Louder"
          value={form.volume}
          min={volumeMin}
          max={volumeMax}
          onChange={(volume) => set({ volume })}
        />
        <div>
          <label htmlFor={`${id}-emotion`} className={FIELD_LABEL}>
            Emotion
          </label>
          <select
            id={`${id}-emotion`}
            className={FIELD}
            value={form.emotion}
            onChange={(event) => set({ emotion: event.target.value })}
          >
            <option value="">None (the words decide)</option>
            {options.emotions.map((emotion) => (
              <option key={emotion} value={emotion}>
                {emotionLabel(emotion)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            variant="secondary-sm"
            status={previewFeedback.status}
            pendingLabel="Getting it…"
            successLabel="Playing"
            disabled={usedUp}
            onClick={() => previewFeedback.run(bodyOf(form))}
          >
            Hear it
          </ActionButton>
          <ActionButton
            type="submit"
            variant="primary-sm"
            status={saveFeedback.status}
            successLabel="Saved"
            disabled={saveFeedback.status === "idle" && !dirty}
          >
            Save
          </ActionButton>
          {left !== null && (
            <span className="text-meta text-ink-muted">
              {left} of {options.previews_per_day} samples left today
            </span>
          )}
          {saved && (
            <span role="status" className="basis-full text-meta text-ink-muted">
              Saved. A call already in progress finishes as it started; the next call uses
              these.
            </span>
          )}
        </div>
      </form>
      {src && (
        <audio ref={audio} src={src} controls className="w-full max-w-xl">
          <track kind="captions" />
        </audio>
      )}
      {usedUp || codeOf(preview.error) === "voice_preview_daily_cap" ? (
        <NoticeBox tone="neutral" role="status">
          You have heard all {options.previews_per_day} samples for today. You can hear more
          tomorrow, and your saved settings still apply to calls.
        </NoticeBox>
      ) : (
        preview.error && <PreviewRefusal error={preview.error} />
      )}
      {save.error && <ProblemNotice error={save.error} />}
    </section>
  );
}
