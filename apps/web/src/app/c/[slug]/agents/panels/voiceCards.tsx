"use client";

/**
 * THE CLIENT'S VOICE PICKER — one card per voice, grouped by quality, the rate on the group.
 *
 * A client-only twin of `components/voicePicker.tsx` rather than a prop on it, because the
 * two readers want different rows: the operator's row carries the vendor's model note and a
 * "verify it before a client does" line that is addressed to staff, while an owner choosing
 * a persona needs its name, its languages and whether they can have it. The keyboard and
 * refusal behaviour is the shared picker's, kept: a refused card stays in the tab order with
 * `aria-disabled` and its reason attached by `aria-describedby`, and the `onChange` guard is
 * what keeps it unselectable by click, arrow key or anything else.
 *
 * There is no sample to play: the catalogue carries no sample or preview URL.
 */

import { Check } from "lucide-react";

import { InfoTip } from "@/components/console/infoTip";
import { tierRateReading } from "@/components/voicePicker";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import type { OfferedVoice, VoiceTierAvailability, VoiceTierRates } from "@/lib/api/voices";
import { lookup } from "@/lib/lookup";

const GENDER_COPY: Record<string, string> = {
  female: "Female",
  male: "Male",
  neutral: "Neutral",
};

function languageNames(codes: readonly string[]): string {
  return codes.map((code) => lookup(LANGUAGE_NAMES, code) ?? code).join(" · ");
}

export function VoiceCards({
  name,
  voices,
  value,
  rates,
  tiers,
  disabled,
  onChange,
}: {
  name: string;
  voices: readonly OfferedVoice[];
  value: string;
  rates?: VoiceTierRates;
  tiers?: readonly VoiceTierAvailability[];
  disabled?: boolean;
  onChange: (voiceId: string) => void;
}) {
  // A voice withdrawn from offer is still shown when it is the one this agent has, so the
  // owner can see what they are on; otherwise it is not a choice and is not drawn.
  const shown = voices.filter((voice) => !voice.not_on_offer || voice.id === value);
  const groups: { label: string; voiceTier: string; rows: OfferedVoice[] }[] = [];
  for (const voice of shown) {
    const label = voice.tier_label || "Other";
    const group = groups.find((candidate) => candidate.label === label);
    if (group) group.rows.push(voice);
    else groups.push({ label, voiceTier: voice.voice_tier, rows: [voice] });
  }
  // A tier's server sentence ("none of these is available on your account") hangs off its
  // group heading when the group has cards, and stands as its own line when it has none.
  const notes = (tiers ?? []).filter((tier) => tier.note !== null);
  const noteFor = (label: string) => notes.find((tier) => tier.label === label);
  const empties = notes.filter((tier) => !groups.some((group) => group.label === tier.label));

  return (
    <fieldset className="space-y-6">
      <legend className="sr-only">Voice</legend>
      {shown.length === 0 && (
        <p className="text-sm text-ink-muted">No voice is available to choose.</p>
      )}
      {groups.map((group) => {
        const money = tierRateReading(rates, group.voiceTier);
        const headingId = `${name}-tier-${group.voiceTier}`;
        return (
          <div key={group.label} role="group" aria-labelledby={headingId}>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <span className="flex items-center gap-1">
                <h3 id={headingId} className="text-sm font-semibold text-ink">
                  {group.label} voice
                </h3>
                {noteFor(group.label) && (
                  <InfoTip label={`${group.label} voice`}>
                    <p>{noteFor(group.label)?.note}</p>
                  </InfoTip>
                )}
              </span>
              {money && (
                <span className="flex items-center gap-1 text-sm tabular-nums text-ink">
                  {money.rate}
                  <InfoTip label={`${group.label} rate`} align="end">
                    <p>{money.note}.</p>
                  </InfoTip>
                </span>
              )}
            </div>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {group.rows.map((voice) => (
                <VoiceCard
                  key={voice.id}
                  name={name}
                  voice={voice}
                  checked={voice.id === value}
                  disabled={disabled}
                  onChange={onChange}
                />
              ))}
            </div>
          </div>
        );
      })}
      {empties.map((tier) => (
        <p key={tier.provider} className="flex items-center gap-1 text-sm text-ink-muted">
          <span>
            <span className="font-medium text-ink">{tier.label} voice</span> · none available
          </span>
          {/* The server's sentence, whole: it says whose next action this is. */}
          <InfoTip label={`${tier.label} voice`}>
            <p>{tier.note}</p>
          </InfoTip>
        </p>
      ))}
    </fieldset>
  );
}

function VoiceCard({
  name,
  voice,
  checked,
  disabled,
  onChange,
}: {
  name: string;
  voice: OfferedVoice;
  checked: boolean;
  disabled?: boolean;
  onChange: (voiceId: string) => void;
}) {
  const blocked = voice.unavailable_reason != null || !voice.offerable;
  const reasonId = `${name}-${voice.id}-reason`;
  const gender = voice.gender ? (lookup(GENDER_COPY, voice.gender) ?? voice.gender) : null;
  return (
    <div
      className={`relative flex items-start gap-3 rounded-card border p-3 transition-colors duration-(--duration-fast) ${
        checked ? "border-brand bg-brand-soft" : "border-line bg-surface"
      } ${blocked || disabled ? "" : "hover:border-ink/25"}`}
    >
      <label
        className={`flex min-w-0 flex-1 items-start gap-3 rounded-md touch:min-h-11 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app ${
          blocked || disabled ? "cursor-not-allowed" : "cursor-pointer"
        }`}
      >
        <input
          type="radio"
          name={name}
          value={voice.id}
          className="sr-only"
          checked={checked}
          disabled={disabled}
          aria-disabled={blocked || undefined}
          aria-describedby={blocked ? reasonId : undefined}
          onChange={() => {
            if (!blocked) onChange(voice.id);
          }}
        />
        <span
          aria-hidden
          className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
            checked ? "bg-brand-strong text-white" : "border border-ink/25"
          }`}
        >
          {checked && <Check className="h-3 w-3" strokeWidth={3} />}
        </span>
        <span className={`min-w-0 flex-1 ${blocked ? "opacity-60" : ""}`}>
          <span className="block text-sm font-semibold text-ink">{voice.label}</span>
          <span className="block text-xs text-ink-muted">
            {[gender, languageNames(voice.languages)].filter(Boolean).join(" · ")}
          </span>
          {blocked && (
            <span id={reasonId} className="mt-1 block text-xs font-medium text-warn">
              {voice.unavailable_reason ?? "This voice is not available here."}
            </span>
          )}
        </span>
      </label>
      {blocked && voice.note && (
        <InfoTip label={`About ${voice.label}`} align="end" className="-mr-1 -mt-1">
          <p>{voice.note}</p>
        </InfoTip>
      )}
    </div>
  );
}
