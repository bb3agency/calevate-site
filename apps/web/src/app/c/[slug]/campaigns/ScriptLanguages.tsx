"use client";

/**
 * THE LANGUAGE PIP WRITES THE SCRIPT IN, chosen beside Generate (founder, 16 Nov 2026: "give
 * dropdown to select the language … let Pip generate in the selected language"). It is the
 * campaign's main language (`language_primary` over its agent's), which the agent also opens
 * every call in; the languages it switches to stay the agent's own.
 *
 * Saved on change; the rest of the campaign's settings are sent back unchanged, because the
 * settings save replaces them all.
 */

import { problemToast } from "@/components/arc/feedback";
import { FIELD } from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import { useCampaignSettings, useSaveCampaignSettings } from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

export function languageName(tag: string): string {
  return LANGUAGE_NAMES[tag as keyof typeof LANGUAGE_NAMES] ?? tag;
}

export function ScriptLanguagePick({
  campaignId,
  agentId,
  canWrite,
  refusal,
  onSaving,
}: {
  campaignId: string;
  agentId: string;
  canWrite: boolean;
  refusal?: string;
  /** Generate waits while a new language is being saved, so it writes in that one. */
  onSaving?: (saving: boolean) => void;
}) {
  const { session } = useClientRealm();
  const settings = useCampaignSettings(session, campaignId, agentId);
  const save = useSaveCampaignSettings(session, campaignId);
  if (!settings.data) return null;
  const { overrides, defaults, offered_languages: offered } = settings.data;
  const main = overrides.language_primary ?? defaults.language_primary ?? offered[0] ?? "";
  const extra = overrides.languages_extra ?? defaults.languages_extra ?? [];

  const choose = (tag: string) => {
    if (tag === main) return;
    const { speaking_speed, ...rest } = overrides;
    onSaving?.(true);
    save.mutate(
      {
        ...rest,
        speaking_speed: speaking_speed == null ? null : String(speaking_speed),
        language_primary: tag,
        languages_extra: [main, ...extra].filter((t): t is string => Boolean(t) && t !== tag),
      },
      { onSettled: () => onSaving?.(false) },
    );
  };

  return (
    <div className="shrink-0">
      <label className="flex items-center gap-2 text-meta font-medium text-ink">
        Language
        <select
          className={`${FIELD} w-auto`}
          value={main}
          disabled={!canWrite || save.isPending}
          title={refusal}
          onChange={(e) => choose(e.target.value)}
        >
          {offered.map((tag) => (
            <option key={tag} value={tag}>
              {languageName(tag)}
            </option>
          ))}
        </select>
      </label>
      {save.error != null && (
        <p role="alert" className="mt-1 text-meta text-danger">
          {problemToast(save.error, "The language did not save").description ?? "The language did not save"}
        </p>
      )}
    </div>
  );
}
