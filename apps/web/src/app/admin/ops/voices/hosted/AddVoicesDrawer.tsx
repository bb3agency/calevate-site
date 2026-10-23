"use client";

import { useId, useMemo, useState } from "react";

import { SavedNote, sentenceCase } from "@/components/admin/kit";
import { ActionButton, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import { SearchField } from "@/components/arc/search-field";
import { Disclosure } from "@/components/ui";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
} from "@/components/ui";
import { useAddHostedVoice, useHostedVoices, type HostedVoice } from "@/lib/api/opsHostedVoices";

import { FILTER_SELECT, PAGE_SIZE, PlayCell, TierChips, tierText } from "./HostedVoiceList";
import { NO_FILTERS, accentOf, applyFilters, choices, findByVoiceId, metaLine, type VoiceFilters } from "./voiceFilters";

/** A voice not yet added has no offer state worth filtering on. */
const ALL_STATES: VoiceFilters = { ...NO_FILTERS, state: "any" };

type Outcome = { added: string[]; failed: { voiceId: string; label: string }[] };

/**
 * ADD VOICES (D-687): pick from every voice the platform lists for us, in one flow — search
 * and filter, listen where a clip is stored, tick several, add them. Only voices in a band we
 * sell can be added; the rest are counted, not listed, so the list is the choice. A voice
 * arrives switched off, so adding never reaches a client.
 */
export function AddVoicesDrawer({ onClose }: { onClose: () => void }) {
  const everything = useHostedVoices(true, "all");
  const add = useAddHostedVoice();
  // Each voice is its own request; the per-voice refusal is printed in the outcome below,
  // so this hook raises no toast. The button's state is the batch's (`batch` below).
  useActionFeedback(add, { errorDisplay: "inline" });
  const [filters, setFilters] = useState<VoiceFilters>(ALL_STATES);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState(PAGE_SIZE);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [pasted, setPasted] = useState("");
  const lookupId = useId();

  const all = useMemo(() => everything.data?.voices ?? [], [everything.data]);
  const candidates = useMemo(() => all.filter((v) => v.sold && !v.added && v.withdrawn_at === null), [all]);
  const unsold = all.filter((v) => !v.sold && v.withdrawn_at === null).length;
  const filtered = applyFilters(candidates, filters);
  const accents = choices(candidates, accentOf);
  const genders = choices(candidates, (v) => v.gender);
  const visible = filtered.slice(0, shown);
  const found = pasted.trim() ? findByVoiceId(all, pasted) : null;

  const set = (patch: Partial<VoiceFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setShown(PAGE_SIZE);
  };
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function addSelected() {
    const result: Outcome = { added: [], failed: [] };
    // One request per voice: the route adds one, idempotently, and audits each.
    for (const voice of candidates.filter((v) => selected.has(v.voice_id))) {
      try {
        await add.mutateAsync(voice.voice_id);
        result.added.push(voice.label);
      } catch {
        result.failed.push({ voiceId: voice.voice_id, label: voice.label });
      }
    }
    // What failed stays ticked, so a second press retries exactly those.
    setSelected(new Set(result.failed.map((f) => f.voiceId)));
    setOutcome(result);
    // A partial failure is the batch's failure, so the button offers "Try again".
    if (result.failed.length > 0) throw new Error(`${result.failed.length} not added`);
  }
  const batch = useAsyncAction(addSelected, { errorDisplay: "inline" });
  const busy = batch.status === "pending";

  const count = selected.size;
  return (
    <Drawer
      open
      onClose={onClose}
      title="Add voices"
      description="Voices the platform lists that clients could be offered. Added voices arrive switched off."
      width="lg"
      dirty={count > 0 && !busy}
      footer={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose}>
            {outcome && count === 0 ? "Done" : "Cancel"}
          </button>
          <ActionButton
            status={batch.status}
            disabled={count === 0 && !busy}
            pendingLabel="Adding…"
            successLabel="Added"
            onClick={() => batch.run()}
          >
            {count === 0 ? "Add voices" : `Add ${formatCount(count)} ${count === 1 ? "voice" : "voices"}`}
          </ActionButton>
        </>
      }
    >
      {everything.error != null ? (
        <ProblemNotice error={everything.error} onRetry={() => void everything.refetch()} />
      ) : !everything.data ? (
        <Skeleton rows={6} label="Loading every voice on the platform" />
      ) : (
        <div className="space-y-4">
          {outcome && (
            <div className="space-y-2" role="status">
              {outcome.added.length > 0 && (
                <SavedNote>
                  {`Added ${outcome.added.join(", ")}. Give each a preview, then switch it on.`}
                </SavedNote>
              )}
              {outcome.failed.length > 0 && (
                <p className="text-meta text-warn">
                  {`Not added: ${outcome.failed.map((f) => f.label).join(", ")}. They stay ticked to try again.`}
                </p>
              )}
              {/* The last refusal in full: its title, detail and remediation. */}
              {add.error != null && <ProblemNotice error={add.error} />}
            </div>
          )}

          <div className="space-y-3">
            <SearchField
              label="Search voices by name"
              hideLabel
              placeholder="Search by name"
              value={filters.query}
              onValueChange={(query) => set({ query })}
            />
            <div className="flex flex-wrap items-center gap-2">
              <TierChips value={filters.tier} onChange={(tier) => set({ tier })} />
              {accents.length > 1 && (
                <select
                  aria-label="Accent or language"
                  className={FILTER_SELECT}
                  value={filters.accent}
                  onChange={(event) => set({ accent: event.target.value })}
                >
                  <option value="">Any accent</option>
                  {accents.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              )}
              {genders.length > 0 && (
                <select
                  aria-label="Gender"
                  className={FILTER_SELECT}
                  value={filters.gender}
                  onChange={(event) => set({ gender: event.target.value })}
                >
                  <option value="">Any gender</option>
                  {genders.map((g) => (
                    <option key={g} value={g}>
                      {sentenceCase(g)}
                    </option>
                  ))}
                </select>
              )}
            </div>
            <p className="text-meta tabular-nums text-ink-muted">
              {formatCount(filtered.length)} of {formatCount(candidates.length)} voices you can add
              {unsold > 0 && ` · ${formatCount(unsold)} more are in bands we do not sell`}
            </p>
          </div>

          <Disclosure variant="inline" title="Find a voice by its id" headingLevel={3}>
            <div className="space-y-2 pt-2">
              <label htmlFor={lookupId} className={FIELD_LABEL}>
                Voice id
              </label>
              <input
                id={lookupId}
                className={`${FIELD} font-mono`}
                value={pasted}
                onChange={(event) => setPasted(event.target.value)}
                placeholder="Paste a Cartesia or platform voice id"
              />
              {pasted.trim() !== "" &&
                (found ? (
                  <FoundVoice voice={found} checked={selected.has(found.voice_id)} onToggle={() => toggle(found.voice_id)} />
                ) : (
                  <p className="text-body text-ink-muted" role="status">
                    This voice isn&rsquo;t in the list the voice platform returned for our key. If it is a
                    voice in our own Cartesia account, the platform may only be returning part of the
                    list; we&rsquo;ve asked them.
                  </p>
                ))}
              <p className={FIELD_HINT}>Searched in the platform&rsquo;s last list. A voice it did not list cannot be added.</p>
            </div>
          </Disclosure>

          {filtered.length === 0 ? (
            candidates.length === 0 ? (
              <EmptyState message="Every voice we can sell is already added." />
            ) : (
              <EmptyState
                variant="filtered"
                message="No voice matches. Try fewer filters."
                onClear={() => set(ALL_STATES)}
              />
            )
          ) : (
            <ul className="divide-y divide-line border-y border-line" aria-label="Voices you can add">
              {visible.map((voice) => (
                <CandidateRow
                  key={voice.voice_id}
                  voice={voice}
                  checked={selected.has(voice.voice_id)}
                  onToggle={() => toggle(voice.voice_id)}
                />
              ))}
            </ul>
          )}
          {filtered.length > shown && (
            <div className="flex flex-wrap items-center justify-between gap-3 text-meta text-ink-muted">
              <span className="tabular-nums">
                Showing {formatCount(shown)} of {formatCount(filtered.length)}
              </span>
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setShown((n) => n + PAGE_SIZE)}>
                Show {formatCount(Math.min(PAGE_SIZE, filtered.length - shown))} more
              </button>
            </div>
          )}

        </div>
      )}
    </Drawer>
  );
}

function CandidateRow({ voice, checked, onToggle }: { voice: HostedVoice; checked: boolean; onToggle: () => void }) {
  const id = useId();
  const meta = [metaLine(voice), tierText(voice).tier].filter(Boolean).join(" · ");
  return (
    <li className="flex items-center gap-3 py-2">
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 shrink-0 accent-brand touch:h-5 touch:w-5"
        checked={checked}
        onChange={onToggle}
      />
      {voice.preview_available && <PlayCell voice={voice} />}
      <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer py-1 touch:min-h-11">
        <span className="block truncate text-body font-medium text-ink">{voice.label}</span>
        <span className="block text-meta text-ink-muted">
          {meta}
        </span>
      </label>
    </li>
  );
}

/** The voice a pasted id names: already added, or one to tick. */
function FoundVoice({ voice, checked, onToggle }: { voice: HostedVoice; checked: boolean; onToggle: () => void }) {
  if (voice.added) return <p className="text-body text-ink-muted">{`${voice.label} is already added.`}</p>;
  if (!voice.sold) return <p className="text-body text-ink-muted">{voice.not_sold_reason ?? `${voice.label} is in a band we do not sell.`}</p>;
  return (
    <ul className="border-y border-line" aria-label="Found voice">
      <CandidateRow voice={voice} checked={checked} onToggle={onToggle} />
    </ul>
  );
}
