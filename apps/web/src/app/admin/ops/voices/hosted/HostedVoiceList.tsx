"use client";

import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { LIST_HEAD, ROW_HOVER, StatusPill } from "@/components/admin/kit";
import { ChipGroup } from "@/components/arc/chip-group";
import { useActionFeedback } from "@/components/arc/feedback";
import { EmptyState } from "@/components/console/emptyState";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import { ProblemNotice, SECONDARY_BUTTON_SM, ToggleSwitch, formatCount } from "@/components/ui";
import { adminSession } from "@/lib/api/admin";
import {
  BAND_LABEL,
  HOSTED_STATE,
  RUNG_LABEL,
  useSetHostedState,
  type HostedVoice,
} from "@/lib/api/opsHostedVoices";
import { OPS_PREVIEW_PATH } from "@/lib/api/voicePreview";
import { lookup } from "@/lib/lookup";

import { metaLine, type TierFilter } from "./voiceFilters";

/** A filter-bar select drawn like `FilterChip`, so the bar reads as one row of filters. */
export const FILTER_SELECT =
  "rounded-full border border-line bg-surface py-1.5 pl-3 pr-2 text-xs font-medium text-ink-muted touch:min-h-11 hover:bg-black/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 dark:hover:bg-white/5";

/** The tier filter both voice lists share: "All tiers", Clear, Studio, each with its count when given. */
export function TierChips({
  value,
  onChange,
  countOf,
}: {
  value: TierFilter;
  onChange: (tier: TierFilter) => void;
  countOf?: (tier: TierFilter) => number;
}) {
  const named = (word: string, tier: TierFilter) => (countOf ? `${word} ${formatCount(countOf(tier))}` : word);
  return (
    <ChipGroup
      mode="single"
      label="Tier"
      allLabel={countOf ? named("All", "all") : "All tiers"}
      chips={[
        { value: "clear", label: named("Clear", "clear") },
        { value: "studio", label: named("Studio", "studio") },
      ]}
      value={value === "all" ? null : value}
      onChange={(next) => onChange(next === "clear" || next === "studio" ? next : "all")}
    />
  );
}

/** How many rows a list shows before "Show more": enough to scan, few enough to stay quick. */
export const PAGE_SIZE = 25;

/** "Used by 3 agents" — live agents across every client. */
export function usedBy(count: number): string {
  if (count === 0) return "Not in use";
  return `${formatCount(count)} live ${count === 1 ? "agent" : "agents"}`;
}

/** The tier as a row prints it: ours first, the platform's band as its detail. */
export function tierText(voice: HostedVoice): { tier: string; detail: string | null } {
  const tier = voice.rung ? (lookup(RUNG_LABEL, voice.rung) ?? voice.rung) : "Not sold";
  const detail =
    voice.source === "byok"
      ? "Our Cartesia key"
      : voice.band
        ? (lookup(BAND_LABEL, voice.band) ?? voice.band)
        : null;
  return { tier, detail };
}

/**
 * Why the Offered switch cannot be moved, or null. Said beside the switch rather than letting
 * the click be refused.
 */
export function switchBlocked(voice: HostedVoice): string | null {
  if (voice.withdrawn_at !== null) return "No longer on the platform";
  if (!voice.sold) return "In a band we do not sell";
  if (voice.clone_blocker && voice.state !== "enabled") return voice.clone_blocker;
  return null;
}

/**
 * The offered voices, one compact row each: play, name and facts, tier, use, and the Offered
 * switch. Everything else about a voice is in its detail (`VoiceDrawer`), opened from its name.
 */
export function HostedVoiceList({
  voices,
  empty,
  emptyAction,
  onClearFilters,
  onOpen,
}: {
  voices: HostedVoice[];
  empty: ReactNode;
  emptyAction?: ReactNode;
  /** Set while filters narrow the list: an empty list is then "nothing matches", with a way back. */
  onClearFilters?: () => void;
  onOpen: (voiceId: string) => void;
}) {
  const [shown, setShown] = useState(PAGE_SIZE);
  if (voices.length === 0) {
    return onClearFilters ? (
      <EmptyState variant="filtered" message={empty} onClear={onClearFilters} />
    ) : (
      <EmptyState message={empty} action={emptyAction} />
    );
  }
  const visible = voices.slice(0, shown);
  return (
    <div>
      <div
        aria-hidden
        className={`hidden grid-cols-[2.75rem_minmax(0,1fr)_6rem_8rem_3rem] items-center gap-3 border-b border-line px-2 pb-2 md:grid ${LIST_HEAD}`}
      >
        <span />
        <span>Voice</span>
        <span>Tier</span>
        <span>Used by</span>
        <span className="text-right">Offered</span>
      </div>
      <ul className="divide-y divide-line border-b border-line md:border-t-0 border-t" aria-label="Voices">
        {visible.map((voice) => (
          <VoiceRow key={voice.voice_id} voice={voice} onOpen={onOpen} />
        ))}
      </ul>
      {voices.length > shown && (
        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 text-meta text-ink-muted">
          <span className="tabular-nums">
            Showing {formatCount(shown)} of {formatCount(voices.length)}
          </span>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setShown((n) => n + PAGE_SIZE)}>
            Show {formatCount(Math.min(PAGE_SIZE, voices.length - shown))} more
          </button>
        </div>
      )}
    </div>
  );
}

/** The play control, or a quiet placeholder of the same size so names stay aligned. */
export function PlayCell({ voice }: { voice: HostedVoice }) {
  if (voice.preview_available) {
    return (
      <VoicePreviewButton
        compact
        session={adminSession()}
        path={OPS_PREVIEW_PATH}
        voiceId={voice.voice_id}
        label={voice.label}
      />
    );
  }
  return (
    <span
      aria-hidden
      className="inline-block h-9 w-9 shrink-0 rounded-full border border-dashed border-line touch:h-11 touch:w-11"
    />
  );
}

/** Small state words under a name: only the ones that ask for attention. */
export function VoicePills({ voice }: { voice: HostedVoice }) {
  return (
    <>
      {!voice.preview_available && <StatusPill tone="warn">No preview</StatusPill>}
      {voice.state === "archived" && <StatusPill>Archived</StatusPill>}
      {voice.withdrawn_at !== null && <StatusPill tone="stop">Gone from the platform</StatusPill>}
      {voice.person_clone && <StatusPill>Real person&rsquo;s clone</StatusPill>}
      {voice.clone_blocker && <StatusPill tone="warn">{voice.clone_blocker}</StatusPill>}
      {voice.is_custom && <StatusPill>Our clone</StatusPill>}
    </>
  );
}

function VoiceRow({ voice, onOpen }: { voice: HostedVoice; onOpen: (voiceId: string) => void }) {
  const setState = useSetHostedState();
  // The switch's own position is the success; a refusal is printed under the name.
  const setStateFeedback = useActionFeedback(setState, { errorDisplay: "inline" });
  const { tier } = tierText(voice);
  const blocked = switchBlocked(voice);
  const meta = metaLine(voice);
  const metaId = `meta-${voice.voice_id.replace(/[^A-Za-z0-9_-]/g, "-")}`;

  return (
    <li
      aria-label={voice.label}
      className={`grid grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-2 py-2.5 md:grid-cols-[2.75rem_minmax(0,1fr)_6rem_8rem_3rem] ${ROW_HOVER}`}
    >
      <PlayCell voice={voice} />
      <div className="min-w-0">
        <button
          type="button"
          onClick={() => onOpen(voice.voice_id)}
          aria-describedby={metaId}
          className="group inline-flex max-w-full items-center gap-1 rounded-sm text-left text-body font-medium text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          <span className="truncate">{voice.label}</span>
          <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
        </button>
        <p id={metaId} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-meta text-ink-muted">
          {meta && <span>{meta}</span>}
          {/* On a phone the tier and use columns fold into this line. */}
          <span className="md:hidden">
            {tier}
            {" · "}
            {usedBy(voice.live_agents)}
          </span>
          <VoicePills voice={voice} />
        </p>
        {setState.error != null && (
          <div className="mt-2">
            <ProblemNotice error={setState.error} />
          </div>
        )}
      </div>
      {/* The platform band is the same on every Clear row, so it is in the detail, not here. */}
      <p className="hidden text-body text-ink md:block">{tier}</p>
      <p className="hidden text-body tabular-nums text-ink-muted md:block">{usedBy(voice.live_agents)}</p>
      <div className="flex justify-end">
        <ToggleSwitch
          label={
            <span className="sr-only">
              {`${lookup(HOSTED_STATE, voice.state)?.label ?? voice.state}: ${voice.label}`}
              {blocked ? `. ${blocked}` : ""}
            </span>
          }
          checked={voice.state === "enabled"}
          disabled={setStateFeedback.status === "pending" || blocked !== null}
          onChange={(on) => setStateFeedback.run({ voice_id: voice.voice_id, state: on ? "enabled" : "disabled" })}
        />
      </div>
    </li>
  );
}
