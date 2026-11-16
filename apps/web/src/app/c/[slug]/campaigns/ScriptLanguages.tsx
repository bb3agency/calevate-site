"use client";

/**
 * THE SCRIPT'S LANGUAGES (founder, 16 Nov 2026: "one script, agent switches"). The owner picks
 * one or more; the first picked is the main language, which Pip writes the script and the
 * opening line in and the agent opens every call in. The others are the languages the agent
 * switches to when a caller answers in one, following the same steps and answers.
 *
 * They are this campaign's settings over its agent's (`language_primary`, `languages_extra`),
 * saved on each press; the rest of the campaign's settings are sent back unchanged, because
 * the settings save replaces them all.
 */

import { Check } from "lucide-react";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
import { Skeleton } from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import { useCampaignSettings, useSaveCampaignSettings } from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

export function ScriptLanguages({
  campaignId,
  agentId,
  canWrite,
  refusal,
}: {
  campaignId: string;
  agentId: string;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const settings = useCampaignSettings(session, campaignId, agentId);
  const save = useSaveCampaignSettings(session, campaignId);
  useActionFeedback(save, { errorDisplay: "inline" });
  if (!settings.data) return settings.isLoading ? <Skeleton rows={1} label="Loading the languages" /> : null;
  const { overrides, defaults, offered_languages: offered } = settings.data;
  const main = overrides.language_primary ?? defaults.language_primary ?? offered[0];
  const extra = overrides.languages_extra ?? defaults.languages_extra ?? [];
  const chosen = [main, ...extra.filter((tag) => tag !== main)].filter(
    (tag): tag is string => typeof tag === "string",
  );

  const toggle = (tag: string) => {
    const next = chosen.includes(tag) ? chosen.filter((t) => t !== tag) : [...chosen, tag];
    if (next.length === 0) return;
    const { speaking_speed, ...rest } = overrides;
    save.mutate({
      ...rest,
      speaking_speed: speaking_speed == null ? null : String(speaking_speed),
      language_primary: next[0],
      languages_extra: next.slice(1),
    });
  };

  const name = (tag: string) => LANGUAGE_NAMES[tag as keyof typeof LANGUAGE_NAMES] ?? tag;
  return (
    <fieldset className="mb-4">
      <legend className="text-body font-semibold text-ink">Languages</legend>
      <p className="mt-0.5 text-meta text-ink-muted">
        Pip writes the script in the first one. The agent opens in it and switches when a caller speaks another.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {offered.map((tag) => {
          const on = chosen.includes(tag);
          const isMain = chosen[0] === tag;
          return (
            <button
              key={tag}
              type="button"
              role="checkbox"
              aria-checked={on}
              disabled={!canWrite || save.isPending || (on && chosen.length === 1)}
              title={on && chosen.length === 1 ? "Keep at least one language" : refusal}
              onClick={() => toggle(tag)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-meta font-medium transition-colors ${
                on
                  ? "border-series-2 bg-series-2 text-white"
                  : "border-line bg-surface text-ink-muted hover:border-series-2 hover:text-ink"
              }`}
            >
              {on && <Check aria-hidden className="h-3.5 w-3.5" />}
              {name(tag)}
              {isMain && <span className="rounded-full bg-white/25 px-1.5 text-[11px]">main</span>}
            </button>
          );
        })}
      </div>
      {save.error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {problemToast(save.error, "The languages did not save").description ?? "The languages did not save"}
        </p>
      )}
    </fieldset>
  );
}
