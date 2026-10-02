"use client";

import type { DataColumn } from "@/components/console/dataTable";
import { InfoTip } from "@/components/console/infoTip";
import { MonoValue, formatCount, formatIST } from "@/components/ui";
import { CURATION_MEANING, WITHDRAWN_MEANING, type CuratedVoice } from "@/lib/api/opsVoices";
import { lookup } from "@/lib/lookup";

/**
 * Keyed by the WIRE string and read through `lookup`, so a server that grew a fourth state
 * prints the bare value rather than being mislabelled as one of these three.
 */
const STATE_TONE: Record<string, string> = {
  enabled: "bg-brand-soft text-brand-strong",
  disabled: "bg-ink/[0.06] text-ink-muted",
  archived: "border border-warn-line bg-warn-soft text-warn",
};

const ORIGIN_MEANING: Record<string, string> = {
  operator: "Added here, and checked against the voice platform",
  synced: "Read off the voice platform's own list",
};

/** A column header with its gloss behind an ⓘ; the visible word is the column's name. */
function GlossedHeader({ label, gloss }: { label: string; gloss: string }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      <span aria-hidden>{label}</span>
      <InfoTip label={label}>{gloss}</InfoTip>
    </span>
  );
}

function VoiceCell({ voice }: { voice: CuratedVoice }) {
  const origin = lookup(ORIGIN_MEANING, voice.origin);
  return (
    <div className="max-w-xs sm:min-w-[10rem]">
      <span className="font-medium text-ink">{voice.label}</span>
      <MonoValue className="mt-0.5 block break-all text-[11px] text-ink-muted">{voice.voice_id}</MonoValue>
      <span className="mt-0.5 block text-[11px] text-ink-faint">
        {origin ?? <MonoValue>{voice.origin}</MonoValue>}
        {voice.source === "custom" && " · A voice we cloned or imported"}
      </span>
      {voice.withdrawn_at !== null && (
        // The server's sentence when it has one: what un-withdraws a voice depends on
        // whether the engine keeps a catalogue of its own, which only the server knows.
        <span className="mt-0.5 block text-[11px] text-warn">
          {voice.withdrawn_note ?? WITHDRAWN_MEANING}
        </span>
      )}
    </div>
  );
}

export function voiceColumns(keepSpeaking: string): DataColumn<CuratedVoice>[] {
  return [
    {
      id: "voice",
      header: "Voice",
      sort: { value: (voice) => voice.label },
      cell: (voice) => <VoiceCell voice={voice} />,
    },
    {
      id: "quality",
      header: "Quality",
      hideBelow: "sm",
      cell: (voice) => (
        <>
          {voice.tier_label}
          {/* The vendor, on the one console that may name one: an operator reconciling an
              invoice needs it, and a client never sees this screen. */}
          <span className="mt-0.5 block text-[11px] text-ink-faint">
            {voice.provider} · <MonoValue>{voice.tts_model}</MonoValue>
          </span>
        </>
      ),
    },
    {
      id: "languages",
      header: "Languages",
      hideBelow: "md",
      cell: (voice) => <span className="text-ink-muted">{voice.languages.join(", ")}</span>,
    },
    {
      id: "live",
      header: "Live agents",
      renderHeader: () => <GlossedHeader label="Live agents" gloss="Across every client, now." />,
      cell: (voice) => (
        <div className="max-w-[12rem] tabular-nums">
          {formatCount(voice.live_agents)}
          {voice.live_agents > 0 && voice.state === "enabled" && (
            <span className="mt-0.5 block text-[11px] text-ink-faint">{keepSpeaking}</span>
          )}
        </div>
      ),
    },
    {
      id: "state",
      header: "State",
      cell: (voice) => {
        const tone = lookup(STATE_TONE, voice.state);
        const meaning = lookup(CURATION_MEANING, voice.state);
        return (
          <div className="max-w-[12rem]">
            {tone ? (
              <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>
                {voice.state}
              </span>
            ) : (
              <MonoValue>{voice.state}</MonoValue>
            )}
            {meaning && <span className="mt-0.5 block text-[11px] text-ink-faint">{meaning}</span>}
          </div>
        );
      },
    },
    {
      id: "seen",
      header: "Last seen",
      hideBelow: "lg",
      renderHeader: () => (
        <GlossedHeader label="Last seen" gloss="When we last saw it on the voice platform's list." />
      ),
      cell: (voice) => (
        <span className="whitespace-nowrap text-ink-muted">{formatIST(voice.synced_at)}</span>
      ),
    },
  ];
}
