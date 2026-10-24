"use client";

import { useState, type ReactNode } from "react";

import { type FeedbackStatus } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { SaveBar } from "@/components/console/saveBar";
import { SavedTick } from "@/components/console/savedTick";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { ModelPicker, type ModelChoice } from "@/components/llmModelPicker";
import { ProblemNotice, RestrictionNote } from "@/components/ui";
import {
  tierOption,
  tierUnavailableReason,
  type ClientLlmDefaults,
  type LlmTier,
} from "@/lib/api/llmModels";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/**
 * THE MODEL TIER SETTING, for one agent or for the whole account (D-680): the client's one
 * way to choose Standard, Plus or Pro. The agent's Model section and Settings → Models are
 * the same component in two modes, so they cannot drift apart again.
 *
 * It is laid out like the Voice section: a summary row saying what runs now and where that
 * comes from, the options as cards, and a save bar that appears only once the choice differs
 * from what is saved. Following the level above is the first card ("Organisation default" on
 * an agent, "Calevate's default" on the account) and sends `null`; a tier card pins that tier.
 *
 * Every figure is the server's (`client_surcharge_inr_per_minute`, hard rule 7). A tier, never
 * a model or the company behind it (D-679).
 */
export type ModelTierMode = "agent" | "organisation";

const COPY: Record<
  ModelTierMode,
  {
    row: string;
    legend: string;
    follow: string;
    follows: (label: string) => string;
    note: string;
  }
> = {
  agent: {
    row: "Model it thinks with",
    legend: "Model for this agent",
    follow: "Organisation default",
    follows: (label) =>
      `${label} now. Follows your organisation default when it changes.`,
    note: "Takes effect on this agent's next call. Calls already running finish on the model they started on.",
  },
  organisation: {
    row: "Model your agents use",
    legend: "Model for all your agents",
    follow: "Calevate's default",
    follows: (label) =>
      `${label} now. Follows Calevate's default when it changes.`,
    note: "Takes effect on the next call. Calls already running finish on the model they started on.",
  },
};

type ModelTierSettingProps = {
  mode: ModelTierMode;
  /** Scopes the radio group. */
  name: string;
  catalogue: ClientLlmDefaults;
  /** The tier stored at THIS level, or `null` when it follows the level above. */
  saved: LlmTier | null;
  /** The server's word for the tier running now. */
  inForceLabel: string;
  /** Where that tier comes from, as one line under the summary. */
  source: ReactNode;
  /** The tier following the level above resolves to today. */
  followLabel: string;
  /** What following the level above adds per minute, as the server sent it. */
  followSurcharge: string | null;
  /** What the tier in force adds per minute; every row is compared with it. */
  baselineSurcharge: string | null;
  write: { allowed: boolean; reason: string | null };
  /** The caller's `useActionFeedback` status, drawn on the save bar. */
  status: FeedbackStatus;
  error: unknown;
  /** The save's `submittedAt` once it succeeded, 0 otherwise. */
  savedAt: number;
  onSave: (tier: LlmTier | null, done: () => void) => void;
  /** Replaces the options when nothing may be changed (a deleted agent). */
  readOnly?: ReactNode;
  /** A notice about what runs now, under the summary. */
  notice?: ReactNode;
};

export function ModelTierSetting(props: ModelTierSettingProps) {
  // On a voice platform that runs its own models the model is included in the per-minute
  // price and chosen by Calevate (D-750): no picker that would change nothing.
  if (props.catalogue.tier_choosable === false) {
    return <IncludedModel note={props.catalogue.tier_note} />;
  }
  return <TierChoice {...props} />;
}

function TierChoice({
  mode,
  name,
  catalogue,
  saved,
  inForceLabel,
  source,
  followLabel,
  followSurcharge,
  baselineSurcharge,
  write,
  status,
  error,
  savedAt,
  onSave,
  readOnly,
  notice,
}: ModelTierSettingProps) {
  const saving = status === "pending";
  const copy = COPY[mode];
  // Wrapped, because `null` is a real choice here ("follow"), not "nothing picked yet".
  const [picked, setPicked] = useState<{ tier: LlmTier | null } | null>(null);
  const selected = picked ? picked.tier : saved;
  const changed = readOnly === undefined && selected !== saved;
  useUnsavedGuard(changed);

  const choices: ModelChoice[] = [
    {
      value: null,
      label: copy.follow,
      detail: copy.follows(followLabel),
      surcharge: followSurcharge,
      baseline: saved === null,
    },
    ...catalogue.available.map<ModelChoice>((option) => ({
      value: option.tier,
      label: option.label,
      detail: option.description,
      surcharge: option.client_surcharge_inr_per_minute,
      baseline: saved !== null && option.tier === saved,
      unavailable: tierUnavailableReason(option),
    })),
  ];

  return (
    <div className="space-y-6">
      <SettingRows className="border-y border-line">
        <SettingRow
          label={copy.row}
          hint={source}
          value={inForceLabel}
          action={<SavedTick at={savedAt} />}
        />
      </SettingRows>
      {notice}

      {readOnly ?? (
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (changed) onSave(selected, () => setPicked(null));
          }}
        >
          <RestrictionNote reason={write.reason} />
          {/* The server's own refusal, with its remediation. */}
          {error != null && <ProblemNotice error={error} />}
          <ModelPicker
            name={name}
            legend={copy.legend}
            hint="Figures are what a tier adds to every minute you are charged for."
            choices={choices}
            value={selected}
            baselineSurcharge={baselineSurcharge}
            disabled={!write.allowed || saving}
            // Narrowed through the server's own rows: anything else is the follow row.
            onChange={(next) =>
              setPicked({
                tier: tierOption(catalogue.available, next)?.tier ?? null,
              })
            }
            audience="client"
          />
          {(changed || saving) && (
            <SaveBar
              label="Save model"
              status={status}
              disabled={!write.allowed}
              title={write.reason ?? undefined}
              onCancel={() => setPicked(null)}
              note={copy.note}
            />
          )}
        </form>
      )}
    </div>
  );
}

/** The one quiet line shown where there is no model to choose. No vendor or model name (D-679). */
function IncludedModel({ note }: { note: string | null | undefined }) {
  return (
    <div className="flex items-center gap-1 text-body text-ink-muted">
      <p>
        {note ?? "The language model is included in your per-minute price."}
      </p>
      <InfoTip label="the language model">
        <p>
          Calevate picks the language model your agents think with. It is part
          of the price of each minute, so there is nothing to choose and nothing
          extra to pay.
        </p>
      </InfoTip>
    </div>
  );
}
