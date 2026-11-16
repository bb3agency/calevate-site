"use client";

import { useId } from "react";
import { Check, RefreshCw } from "lucide-react";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { FIELD_HINT, FIELD_LABEL, NoticeBox, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import { adminSession } from "@/lib/api/admin";
import { useHostedVoices, type HostedVoice } from "@/lib/api/opsHostedVoices";
import { OPS_PREVIEW_PATH } from "@/lib/api/voicePreview";

import { draftOf } from "./configControl";
// Type-only: `ConfigInput` mounts this picker, so a value import would be a cycle.
import type { ConfigInputProps } from "./ConfigInput";

const RUNG: Record<string, string> = { studio: "Studio", clear: "Clear" };

/** "Studio · woman · Telugu accent", from what the catalogue states. */
function voiceDetail(voice: HostedVoice): string {
  const gender = (voice.gender ?? "").trim().toLowerCase();
  const who = gender.startsWith("f") || gender.startsWith("w") ? "woman" : gender.startsWith("m") ? "man" : null;
  return [voice.rung ? RUNG[voice.rung] : null, who, voice.accent_label].filter(Boolean).join(" · ");
}

interface Option {
  value: string;
  title: string;
  detail: string;
  voice?: HostedVoice;
}

/**
 * The default agent's voice (`default_agent_voice_id`), picked from the voices on the client
 * picker's list: added, enabled and still listed (the Voices page's `offered`). Each has its
 * preview beside the card rather than inside it, so the play button is not a control nested
 * in the radio's label. The server refuses any other voice, so this list is a convenience and
 * not the check.
 */
export function DefaultVoicePicker({ field, draft, onChange }: ConfigInputProps) {
  const name = useId();
  const voices = useHostedVoices(true, "added");
  if (voices.error) {
    return (
      <div className="space-y-2">
        <p className={FIELD_LABEL}>New value</p>
        <ProblemNotice error={voices.error} onRetry={() => void voices.refetch()} />
      </div>
    );
  }
  if (voices.isLoading || voices.data === undefined) {
    return <Skeleton rows={2} label="Reading the voices enabled for clients…" />;
  }
  const offered = voices.data.voices.filter((voice) => voice.offered);
  const current = draftOf(field, field.value);
  const options: Option[] = offered.map((voice) => ({
    value: voice.voice_id,
    title: voice.label,
    detail: voiceDetail(voice),
    voice,
  }));
  if (current !== "" && !offered.some((voice) => voice.voice_id === current)) {
    options.unshift({
      value: current,
      title: current,
      detail: "Set now, but no longer enabled for clients. New agents get the best voice instead.",
    });
  }
  options.push({
    value: "",
    title: "Best voice for each account",
    detail: "A woman's voice in the agent's language, Studio first.",
  });

  return (
    <div className="space-y-2">
      {offered.length === 0 && (
        <NoticeBox tone="warn" title="No voice is enabled for clients">
          <p className="mt-1">Enable one on the Voices page, then refresh this list.</p>
        </NoticeBox>
      )}
      <fieldset className="min-w-0">
        <legend className={FIELD_LABEL}>Choose the first agent&apos;s voice</legend>
        <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {options.map((option) => {
            const on = option.value === draft;
            return (
              <div key={option.value || "unset"} className="flex min-w-0 items-center gap-2">
                <label className={`${CHOICE_CARD} ${on ? CHOICE_ON : CHOICE_OFF} min-w-0 flex-1`}>
                  <input
                    type="radio"
                    name={name}
                    value={option.value}
                    checked={on}
                    onChange={() => onChange(option.value)}
                    className="sr-only"
                  />
                  <span className="flex items-start justify-between gap-2">
                    <span className="min-w-0 break-words text-body font-medium text-ink">{option.title}</span>
                    {on && <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />}
                  </span>
                  {option.detail && (
                    <span className="mt-0.5 block break-words text-meta text-ink-muted">{option.detail}</span>
                  )}
                </label>
                {option.voice?.preview_available && (
                  <VoicePreviewButton
                    compact
                    session={adminSession()}
                    path={OPS_PREVIEW_PATH}
                    voiceId={option.voice.voice_id}
                    label={option.voice.label}
                  />
                )}
              </div>
            );
          })}
        </div>
      </fieldset>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={FIELD_HINT}>
          Agents already made keep their voice. An account that cannot use this voice gets the best one instead.
        </span>
        <button
          type="button"
          onClick={() => void voices.refetch()}
          disabled={voices.isFetching}
          className={SECONDARY_BUTTON_SM}
        >
          <RefreshCw aria-hidden className={`h-3.5 w-3.5 ${voices.isFetching ? "motion-safe:animate-spin" : ""}`} />
          {voices.isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>
    </div>
  );
}
