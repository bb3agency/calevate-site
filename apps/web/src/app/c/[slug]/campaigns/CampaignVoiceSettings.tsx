"use client";

/**
 * VOICE & CALL SETTINGS FOR THIS CAMPAIGN (D-994). The agent holds the defaults; each row shows
 * the agent's value and lets this campaign use its own instead. Blank means "same as the
 * agent". Start and Test call put them on the agent with the script; while this campaign
 * holds the agent, a save reaches its calls at once.
 */

import { useEffect, useState } from "react";

import { problemToast } from "@/components/arc/feedback";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import {
  useCampaignSettings,
  useSaveCampaignSettings,
  type CampaignSettingsInput,
  type CampaignSettingsValues,
} from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

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
      return LANGUAGE_NAMES[v as keyof typeof LANGUAGE_NAMES] ?? String(v);
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
      return AMBIENCE[String(v)] ?? String(v);
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
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (settings.data) setDraft(toDraft(settings.data.overrides));
  }, [settings.data]);

  if (settings.isLoading || (!draft && !settings.error)) return <Skeleton rows={3} label="Loading the voice settings" />;
  if (!settings.data || !draft) return <ProblemNotice error={settings.error} onRetry={() => settings.refetch()} />;
  const data = settings.data;
  const saved = toDraft(data.overrides);
  const dirty = KEYS.some((k) => draft[k] !== saved[k]);
  const set = (key: Key, value: string) => setDraft({ ...draft, [key]: value });

  const submit = () => {
    setError(null);
    save.mutate(fromDraft(draft), { onError: setError });
  };

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

  return (
    <section
      aria-labelledby={`${campaignId}-voice-settings`}
      className="rounded-card border border-line border-l-4 border-l-info bg-surface p-4 shadow-card sm:p-5"
    >
      <h3 id={`${campaignId}-voice-settings`} className="text-body font-semibold text-ink">
        Voice &amp; call settings
      </h3>
      <p className="mt-0.5 text-meta text-ink-muted">
        {data.agent_name}&apos;s own settings, and what this campaign uses instead. Leave a box empty to keep the
        agent&apos;s. {data.applied_now ? "Saving puts them on the agent's calls at once." : "They go on the agent at Start or a test call."}
      </p>
      <div className="mt-3 divide-y divide-line">
        {ROWS.map(({ key, label, hint }) => (
          <div key={key} className="grid gap-2 py-2.5 sm:grid-cols-[minmax(0,1fr)_9rem_minmax(0,14rem)] sm:items-center">
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
      {error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {problemToast(error, "The settings did not save").description ?? "The settings did not save"}
        </p>
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
    </section>
  );
}
