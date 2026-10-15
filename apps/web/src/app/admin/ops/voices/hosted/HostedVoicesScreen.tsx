"use client";

import { useId, useState } from "react";
import { AudioLines, Plus, RefreshCw, Search } from "lucide-react";

import { SavedNote, sentenceCase } from "@/components/admin/kit";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import {
  FIELD,
  FilterChip,
  NoticeBox,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  formatCount,
} from "@/components/ui";
import { BAND_LABEL, type HostedVoices } from "@/lib/api/opsHostedVoices";
import { useRefreshVoiceCatalogue } from "@/lib/api/opsVoices";
import { lookup } from "@/lib/lookup";

import { AddVoicesDrawer } from "./AddVoicesDrawer";
import { CloneVoiceDrawer } from "./CloneVoiceDrawer";
import { FILTER_SELECT, HostedVoiceList } from "./HostedVoiceList";
import { OwnModelCard } from "./OwnModelCard";
import { StudioVoicesCard } from "./StudioVoicesCard";
import { VoiceDrawer } from "./VoiceDrawer";
import {
  NO_FILTERS,
  accentOf,
  applyFilters,
  choices,
  isFiltered,
  type PreviewFilter,
  type StateFilter,
  type TierFilter,
  type VoiceFilters,
} from "./voiceFilters";

const STATE_OPTIONS: { value: StateFilter; label: string }[] = [
  { value: "active", label: "Not archived" },
  { value: "offered", label: "Offered" },
  { value: "not_offered", label: "Not offered" },
  { value: "archived", label: "Archived" },
  { value: "any", label: "Any state" },
];
const PREVIEW_OPTIONS: { value: PreviewFilter; label: string }[] = [
  { value: "any", label: "Any preview" },
  { value: "with", label: "Has a preview" },
  { value: "without", label: "No preview" },
];

/**
 * The Voices page on an engine that HOSTS its voices (D-687, ENGINE=thinnest).
 *
 * Task first: which voices clients can pick (one compact row each, filterable), adding more
 * from the platform's full list (its own flow), and getting Studio ready. Everything about one
 * voice — its ids, preview, name, agents and, for a cloned person's voice, their consent — is
 * in its detail drawer, so the list stays scannable at hundreds of rows.
 *
 * `added` is the page's probe query, so the list costs no second request; the full platform
 * list is read only when "Add voices" opens.
 */
export function HostedVoicesScreen({ added }: { added: HostedVoices }) {
  const [adding, setAdding] = useState(false);
  const [cloning, setCloning] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [deleted, setDeleted] = useState<string | null>(null);
  const [filters, setFilters] = useState<VoiceFilters>(NO_FILTERS);
  const refresh = useRefreshVoiceCatalogue();
  const searchId = useId();

  const soldBand = (added.clear_band && lookup(BAND_LABEL, added.clear_band)) ?? "ThinnestAI Studio band";
  const voices = added.voices;
  const filtered = applyFilters(voices, filters);
  const accents = choices(voices, accentOf);
  const genders = choices(voices, (v) => v.gender);
  const tierCount = (tier: TierFilter) =>
    applyFilters(voices, { ...filters, tier }).length;
  const open = openId ? voices.find((v) => v.voice_id === openId) : undefined;
  const set = (patch: Partial<VoiceFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const openAdd = () => setAdding(true);

  return (
    <div className="max-w-5xl space-y-10 pb-12">
      <PageHeader
        description="Clients choose only from the voices offered here, and can listen to each one first."
        actions={
          <>
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                className={SECONDARY_BUTTON}
                disabled={refresh.isPending}
                onClick={() => void refresh.mutateAsync().catch(() => undefined)}
              >
                <RefreshCw aria-hidden className="h-4 w-4" />
                {refresh.isPending ? <span className="text-shimmer">Reading the voice platform…</span> : "Refresh"}
              </button>
              <InfoTip label="Refresh">
                Re-reads every voice ThinnestAI lists and, once a client workspace runs Studio, the
                Cartesia voices of our key. A newly seen voice arrives not added; nothing here changes
                an agent or a call.
              </InfoTip>
            </div>
            <button type="button" className={SECONDARY_BUTTON} onClick={() => setCloning(true)}>
              <AudioLines aria-hidden className="h-4 w-4" />
              Clone a voice
            </button>
            <button type="button" className={PRIMARY_BUTTON} onClick={openAdd}>
              <Plus aria-hidden className="h-4 w-4" />
              Add voices
            </button>
          </>
        }
      />

      {refresh.data && (
        <NoticeBox tone="neutral" title="The voice platform was re-read">
          <p className="mt-1">{refresh.data.note}</p>
        </NoticeBox>
      )}
      {refresh.error != null && <ProblemNotice error={refresh.error} />}

      {added.plan_note != null && (
        <NoticeBox
          tone="warn"
          title={`No ${soldBand} voices on the voice platform`}
        >
          <p>{added.plan_note}</p>
          {added.clear_band === "studio" && (
            <p>ThinnestAI&rsquo;s Studio band is not our Studio tier: that is our Cartesia key and adds no voice to this band.</p>
          )}
        </NoticeBox>
      )}

      <section aria-labelledby="hosted-voices" className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 id="hosted-voices" className="text-heading text-ink">
            Offered voices
          </h2>
          <p className="text-meta tabular-nums text-ink-muted">
            {formatCount(added.offered)} offered{" · "}
            {formatCount(voices.length)} added{" · "}
            {formatCount(added.cached)} on the platform
          </p>
        </div>

        {deleted && <SavedNote>{deleted}</SavedNote>}

        {voices.length > 0 && (
          <div className="space-y-3">
            <div className="relative max-w-md">
              <label htmlFor={searchId} className="sr-only">
                Search offered voices by name
              </label>
              <Search
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 mt-0.5 h-4 w-4 -translate-y-1/2 text-ink-faint"
              />
              <input
                id={searchId}
                type="search"
                className={`${FIELD} pl-9`}
                placeholder="Search by name"
                value={filters.query}
                onChange={(event) => set({ query: event.target.value })}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div role="group" aria-label="Tier" className="flex flex-wrap gap-2">
                {(["all", "clear", "studio"] as const).map((tier) => (
                  <FilterChip
                    key={tier}
                    label={`${tier === "all" ? "All" : tier === "clear" ? "Clear" : "Studio"} ${formatCount(tierCount(tier))}`}
                    active={filters.tier === tier}
                    onClick={() => set({ tier })}
                  />
                ))}
              </div>
              <FilterSelect
                label="State"
                value={filters.state}
                options={STATE_OPTIONS}
                onChange={(state) => set({ state })}
              />
              <FilterSelect
                label="Preview"
                value={filters.preview}
                options={PREVIEW_OPTIONS}
                onChange={(preview) => set({ preview })}
              />
              {accents.length > 1 && (
                <FilterSelect
                  label="Accent or language"
                  value={filters.accent}
                  options={[{ value: "", label: "Any accent" }, ...accents.map((a) => ({ value: a, label: a }))]}
                  onChange={(accent) => set({ accent })}
                />
              )}
              {genders.length > 0 && (
                <FilterSelect
                  label="Gender"
                  value={filters.gender}
                  options={[{ value: "", label: "Any gender" }, ...genders.map((g) => ({ value: g, label: sentenceCase(g) }))]}
                  onChange={(gender) => set({ gender })}
                />
              )}
              {isFiltered(filters) && (
                <button type="button" className="text-meta font-medium text-brand-strong hover:underline touch:min-h-11" onClick={() => setFilters(NO_FILTERS)}>
                  Clear filters
                </button>
              )}
            </div>
          </div>
        )}

        <HostedVoiceList
          key={JSON.stringify(filters)}
          voices={filtered}
          onOpen={setOpenId}
          empty={
            voices.length === 0
              ? `No voice is added yet. Add ${soldBand} voices or Studio voices from the platform's list.`
              : "No voice matches these filters."
          }
          emptyAction={
            voices.length === 0 ? (
              <button type="button" className={PRIMARY_BUTTON_SM} onClick={openAdd}>
                <Plus aria-hidden className="h-4 w-4" />
                Add voices
              </button>
            ) : (
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setFilters(NO_FILTERS)}>
                Clear filters
              </button>
            )
          }
        />
      </section>

      <StudioVoicesCard />

      <OwnModelCard />

      {adding && <AddVoicesDrawer onClose={() => setAdding(false)} />}
      {cloning && <CloneVoiceDrawer onClose={() => setCloning(false)} />}
      {open && (
        <VoiceDrawer
          voice={open}
          onClose={() => setOpenId(null)}
          onDeleted={(said) => {
            setDeleted(said);
            setOpenId(null);
          }}
        />
      )}
    </div>
  );
}

function FilterSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <select
      aria-label={label}
      className={FILTER_SELECT}
      value={value}
      onChange={(event) => onChange(event.target.value as T)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
