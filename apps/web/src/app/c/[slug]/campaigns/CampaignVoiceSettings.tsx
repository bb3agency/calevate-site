"use client";

/**
 * VOICE & CALL SETTINGS FOR THIS CAMPAIGN (D-994). The agent holds the defaults; each row shows
 * the agent's value and lets this campaign use its own instead. Blank means "same as the
 * agent". Start and Test call put them on the agent with the script; while this campaign
 * holds the agent, a save reaches its calls at once.
 */

import { useEffect, useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import { lookup } from "@/lib/lookup";
import {
  useCampaignSettings,
  useSaveCampaignSettings,
  type CampaignSettingsInput,
  type CampaignSettingsValues,
} from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

import { FoldSection } from "./FoldSection";

type Key =
  | "language_primary"
  | "speaking_speed"
  | "max_call_duration_s"
  | "nudge_after_seconds"
  | "end_after_silence_seconds"
  | "reask_after_ms"
  | "ambience"
  | "ambience_volume_pct"
  | "filler_lines";
type Draft = Record<Key, string>;

const AMBIENCE: Record<string, string> = { off: "Off", office: "Office", "office-quiet": "Quiet office" };

const KEYS: (Key)[] = [
  "language_primary",
  "speaking_speed",
  "max_call_duration_s",
  "nudge_after_seconds",
  "end_after_silence_seconds",
  "reask_after_ms",
  "ambience",
  "ambience_volume_pct",
  "filler_lines",
];

/** Stored units to what a person types: minutes for the call cap, seconds for the re-ask wait. */
function toDraft(values: CampaignSettingsValues): Draft {
  const out = {} as Draft;
  for (const key of KEYS) {
    const v = values[key];
    if (v === null || v === undefined) out[key] = "";
    else if (key === "max_call_duration_s") out[key] = String(Math.round(Number(v) / 60));
    else if (key === "reask_after_ms") out[key] = String(Math.round(Number(v) / 1000));
    else if (key === "filler_lines") out[key] = (v as string[]).join("\n");
    else out[key] = String(v);
  }
  return out;
}

function fromDraft(draft: Draft): CampaignSettingsInput {
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  return {
    language_primary: draft.language_primary || null,
    speaking_speed: draft.speaking_speed.trim() === "" ? null : draft.speaking_speed.trim(),
    max_call_duration_s: draft.max_call_duration_s.trim() === "" ? null : Number(draft.max_call_duration_s) * 60,
    nudge_after_seconds: num(draft.nudge_after_seconds),
    end_after_silence_seconds: num(draft.end_after_silence_seconds),
    reask_after_ms: draft.reask_after_ms.trim() === "" ? null : Number(draft.reask_after_ms) * 1000,
    ambience: draft.ambience || null,
    ambience_volume_pct: num(draft.ambience_volume_pct),
    filler_lines:
      draft.filler_lines.trim() === ""
        ? null
        : draft.filler_lines
            .split("\n")
            .map((l) => l.trim())
            .filter(Boolean),
  };
}

function defaultLabel(key: Key, d: CampaignSettingsValues): string {
  const v = d[key];
  if (v === null || v === undefined || (Array.isArray(v) && v.length === 0)) return "Platform default";
  switch (key) {
    case "language_primary":
      return lookup(LANGUAGE_NAMES, String(v)) ?? String(v);
    case "speaking_speed":
      return `${v}×`;
    case "max_call_duration_s":
      return `${Math.round(Number(v) / 60)} min`;
    case "nudge_after_seconds":
      return Number(v) === 0 ? "Never" : `${v} s`;
    case "end_after_silence_seconds":
      return `${v} s`;
    case "reask_after_ms":
      return `${Math.round(Number(v) / 1000)} s`;
    case "ambience":
      return lookup(AMBIENCE, String(v)) ?? String(v);
    case "ambience_volume_pct":
      return `${v}%`;
    case "filler_lines":
      return `${(v as string[]).length} lines`;
  }
}

const ROWS: { key: Key; label: string; hint?: string }[] = [
  { key: "language_primary", label: "Language" },
  { key: "speaking_speed", label: "Speaking speed", hint: "0.6 to 1.5; 1 is normal" },
  { key: "max_call_duration_s", label: "Longest call", hint: "minutes" },
  { key: "nudge_after_seconds", label: "Ask “are you still there?” after", hint: "seconds of silence; 0 never" },
  { key: "end_after_silence_seconds", label: "Hang up after silence", hint: "seconds" },
  { key: "reask_after_ms", label: "Ask an unanswered question again after", hint: "seconds" },
  { key: "ambience", label: "Background sound" },
  { key: "ambience_volume_pct", label: "Background volume", hint: "%" },
  { key: "filler_lines", label: "Filler lines", hint: "one per line, said while it thinks" },
];

export function CampaignVoiceSettings({
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
  const [draft, setDraft] = useState<Draft | null>(null);

  useEffect(() => {
    if (settings.data) setDraft(toDraft(settings.data.overrides));
  }, [settings.data]);

  if (settings.isLoading || (!draft && !settings.error)) return <Skeleton rows={3} label="Loading the voice settings" />;
  if (!settings.data || !draft) return <ProblemNotice error={settings.error} onRetry={() => settings.refetch()} />;
  const data = settings.data;
  const saved = toDraft(data.overrides);
  const dirty = KEYS.some((k) => draft[k] !== saved[k]);
  const set = (key: Key, value: string) => setDraft({ ...draft, [key]: value });

  const submit = () => save.mutate(fromDraft(draft));

  const input = (key: Key) => {
    const common = {
      id: `${campaignId}-${key}`,
      disabled: !canWrite,
      className: `${FIELD} w-full`,
      value: draft[key],
    };
    if (key === "language_primary")
      return (
        <select {...common} onChange={(e) => set(key, e.target.value)}>
          <option value="">Same as the agent</option>
          {Object.entries(LANGUAGE_NAMES).map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      );
    if (key === "ambience")
      return (
        <select {...common} onChange={(e) => set(key, e.target.value)}>
          <option value="">Same as the agent</option>
          {Object.entries(AMBIENCE).map(([v, name]) => (
            <option key={v} value={v}>
              {name}
            </option>
          ))}
        </select>
      );
    if (key === "filler_lines")
      return (
        <textarea
          {...common}
          className={`${FIELD} min-h-20 w-full resize-y`}
          placeholder="Same as the agent"
          onChange={(e) => set(key, e.target.value)}
        />
      );
    return (
      <input
        {...common}
        type="number"
        inputMode="decimal"
        step={key === "speaking_speed" ? 0.05 : 1}
        placeholder="Same as the agent"
        onChange={(e) => set(key, e.target.value)}
      />
    );
  };

  const changed = KEYS.filter((k) => saved[k] !== "").length;
  return (
    <FoldSection
      title="Voice & call settings"
      defaultOpen={false}
      aside={
        <span className="text-ink-muted">
          {changed === 0
            ? "Same as the agent"
            : changed === 1
              ? "1 changed for this campaign"
              : `${changed} changed for this campaign`}
        </span>
      }
    >
      <p className="flex items-center gap-1 text-meta text-ink-muted">
        <span className="block">Leave a box empty to keep the agent&apos;s.</span>
        <InfoTip label="voice and call settings" align="start">
          <p>{data.agent_name}&apos;s own settings, and what this campaign uses instead.</p>
          <p>
            {data.applied_now
              ? "Saving puts them on the agent's calls at once."
              : "They go on the agent at Start or a test call."}
          </p>
        </InfoTip>
      </p>
      <div className="mt-3 divide-y divide-line">
        {ROWS.map(({ key, label, hint }) => (
          <div key={key} className="grid grid-cols-1 gap-2 py-2.5 sm:grid-cols-[minmax(0,1fr)_9rem_minmax(0,14rem)] sm:items-center">
            <label htmlFor={`${campaignId}-${key}`} className="text-meta font-medium text-ink">
              {label}
              {hint && <span className="block font-normal text-ink-faint">{hint}</span>}
            </label>
            <span className="text-meta text-ink-muted">
              <span className="sm:hidden">Agent: </span>
              {defaultLabel(key, data.defaults)}
            </span>
            {input(key)}
          </div>
        ))}
      </div>
      {save.error != null && (
        <div className="mt-2">
          <ProblemNotice error={save.error} />
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className={PRIMARY_BUTTON_SM}
          disabled={!canWrite || !dirty || save.isPending}
          title={refusal}
          onClick={submit}
        >
          {save.isPending ? "Saving…" : "Save settings"}
        </button>
        {dirty && (
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setDraft(saved)}>
            Cancel
          </button>
        )}
      </div>
    </FoldSection>
  );
}
