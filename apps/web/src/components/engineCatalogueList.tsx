"use client";

import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { InfoTip } from "@/components/console/infoTip";
import { ModelLogo } from "@/components/console/modelLogo";
import { SaveBar } from "@/components/console/saveBar";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import { viewAsSession } from "@/lib/api/admin";
import { useAgent, useUpdateAgent, type Agent } from "@/lib/api/agents";
import type { Session } from "@/lib/api/client";
import {
  clientCatalogueAudience,
  useEngineCatalogue,
  useHeldVoice,
  useTenantEngineCatalogue,
  type EngineCatalogue,
  type EngineCatalogueModel,
  type EngineCatalogueVoice,
} from "@/lib/api/engineCatalogue";
import { CLIENT_PREVIEW_PATH } from "@/lib/api/voicePreview";
import { StatusPill } from "@/components/console/statusPill";

/**
 * THE VOICE PLATFORM'S OWN VOICES, AND (FOR AN OPERATOR) ITS MODELS (D-678, D-687).
 *
 * Two pickers, each with its own save, because a voice and a model are two decisions and the
 * founder split them (11 Oct 2026): a client chooses a voice here and a model TIER on the
 * agent's Model section; only an operator sees the platform's real models (D-679).
 *
 * The voices are the ones an operator added and enabled, grouped by rung, Clear then Studio,
 * as cards, with a quiet treatment for a voice that cannot be chosen and a save bar that
 * appears only once the choice differs from the saved one.
 *
 * "Platform default" sends `null`, which the server refuses by name once a choice has been
 * published, because the platform keeps the last voice it was given. Where the account runs
 * on its own keys the server says `choosable: false` and both pickers lock on `choice_note`.
 */

/** The two rungs, in the order a client reads them. Names only, never a vendor (D-679). */
const RUNGS = [
  { value: "clear", label: "Clear", blurb: "Natural voices for everyday calls." },
  { value: "studio", label: "Studio", blurb: "Our most lifelike voices, billed at the Studio rate." },
] as const;

/** The value a radio carries for "the platform's own default". Never a catalogue id: the
 *  server bounds ids to non-whitespace, and this has a space. */
const DEFAULT = "platform default";

/** One sentence, shared with the client voice picker, because it is one promise. */
const NEXT_CALL_NOTE = "Applies from the next call. A call in progress finishes as it started.";

/** What a picker needs to save one field. Absent, the list is read-only. */
interface SaveControl {
  /** Why this reader may not change it, or null when they may. */
  disabledReason: string | null;
  /** The mount's `useActionFeedback` status, drawn on the save bar. */
  status: FeedbackStatus;
  error: Error | null;
  onSave: (value: string | null, done: () => void) => void;
}

/** The first clause of a server reason, for the plain line; the whole sentence goes in an ⓘ. */
function shortReason(reason: string): string {
  const cut = reason.search(/[.;:]\s/);
  return cut > 0 ? reason.slice(0, cut) : reason.replace(/[.;:]$/, "");
}

/** The catalogue read as a picker states it: a skeleton, a refusal, or the data. */
function loadedState(catalogue: UseQueryResult<EngineCatalogue>, what: string) {
  if (catalogue.isLoading) return { node: <Skeleton rows={2} /> };
  if (catalogue.error || !catalogue.data) {
    return {
      node: (
        <ProblemNotice
          error={catalogue.error ?? new Error(`The voice platform's own ${what} did not load.`)}
          onRetry={() => void catalogue.refetch()}
        />
      ),
    };
  }
  return { data: catalogue.data };
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * VOICES
 * ═══════════════════════════════════════════════════════════════════════════════════ */

export function EngineVoiceList({
  catalogue,
  voiceId,
  modelId,
  control,
  previewSession,
  audience,
  held = null,
}: {
  catalogue: UseQueryResult<EngineCatalogue>;
  /** The agent's own voice when the list does not offer it (`useHeldVoice`), shown selected. */
  held?: EngineCatalogueVoice | null;
  /** Who reads it: a client is never shown a model's name (D-679). */
  audience: "client" | "operator";
  /** The saved voice, or null for the platform default. */
  voiceId: string | null;
  /** The saved model, for the Studio rule. A client's catalogue lists no models. */
  modelId: string | null;
  control?: SaveControl;
  /** The session the preview clips are read through: the reader's own, or view-as. */
  previewSession?: Session;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const loaded = loadedState(catalogue, "voices");
  const saved = voiceId ?? DEFAULT;
  const selected = picked ?? saved;
  const changed = selected !== saved;
  if (!loaded.data) return loaded.node;
  const data = loaded.data;
  if (!data.available) return null;
  const listed = held && !data.voices.some((entry) => entry.voice_id === held.voice_id) ? [...data.voices, held] : data.voices;

  const lockReason = !data.choosable ? (data.choice_note ?? null) : (control?.disabledReason ?? null);
  const locked = !control || lockReason !== null || control.status === "pending";
  // A Studio voice runs only beside a model the platform allows with it; the server refuses
  // the pair by name (`engine_model_not_with_studio_voice`) and this says so before the save.
  const savedModel = data.models.find((entry) => entry.model_id === modelId);
  // A client never reads a model name (D-679); an operator needs it to know what to change.
  const studioBlocked =
    savedModel === undefined || savedModel.usable_with_studio_voice
      ? null
      : audience === "client"
        ? "Not available with the model this agent runs on."
        : `This agent's model, ${savedModel.label}, cannot run with a Studio voice. Choose another model to use this voice.`;

  const cards = (
    <div className="space-y-6">
      <p className="text-meta text-ink-muted">
        {data.note}
        {!data.complete && " The platform's list was cut short, so some may be missing."}
      </p>
      {control && lockReason && <p className="text-meta text-ink-muted">{lockReason}</p>}
      {control?.error && <ProblemNotice error={control.error} />}
      {control && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <ChoiceCard
            name="engine-voice"
            value={DEFAULT}
            label="Platform default"
            detail="The voice the platform picks when none is chosen."
            checked={selected === DEFAULT}
            current={saved === DEFAULT}
            disabled={locked}
            onChange={setPicked}
          />
        </div>
      )}
      {listed.length === 0 ? (
        <p className="text-body text-ink-muted">No voice is offered yet.</p>
      ) : (
        RUNGS.map((rung) => {
          // A voice off the picker is listed only while it is the one this agent holds
          // (D-880): once switched away from, a cached copy must not offer it back.
          const voices = listed.filter(
            (entry) => entry.rung === rung.value && (entry.standing === "offered" || entry.voice_id === voiceId),
          );
          if (rung.value === "studio" && !data.studio_available && voices.length === 0) return null;
          const studioClosed = rung.value === "studio" && !data.studio_available;
          // With Studio closed to the account, only the agent's own Studio voice is shown.
          const cardVoices = studioClosed ? voices.filter((entry) => entry.standing !== "offered") : voices;
          const headingId = `engine-voice-${rung.value}`;
          return (
            <div key={rung.value} role="group" aria-labelledby={headingId}>
              <h3 id={headingId} className="text-sm font-semibold text-ink">
                {rung.label} voices
              </h3>
              <p className="text-meta text-ink-muted">{rung.blurb}</p>
              {studioClosed && (
                <p className="mt-2 text-body text-ink-muted">
                  {data.studio_note ?? "Studio voices are not available on this account yet."}
                </p>
              )}
              {!studioClosed && cardVoices.length === 0 ? (
                <p className="mt-2 text-body text-ink-muted">No {rung.label} voice is offered yet.</p>
              ) : cardVoices.length === 0 ? null : (
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {cardVoices.map((entry) => {
                    const blocked = entry.rung === "studio" ? studioBlocked : null;
                    // The agent's own voice off the picker: shown selected, with the server's
                    // whole sentence (kept, or choose another now).
                    const ownOffPicker = entry.standing !== "offered";
                    return (
                      <ChoiceCard
                        key={entry.voice_id}
                        name="engine-voice"
                        value={control ? entry.voice_id : null}
                        label={entry.label}
                        suffix={entry.is_custom ? "made for this platform" : undefined}
                        detail={entry.language_note}
                        reason={ownOffPicker ? null : entry.offerable ? blocked : entry.reason}
                        note={
                          ownOffPicker && entry.reason
                            ? { text: entry.reason, stop: entry.standing === "unavailable" }
                            : null
                        }
                        checked={selected === entry.voice_id}
                        current={saved === entry.voice_id}
                        disabled={locked || !entry.offerable || blocked !== null}
                        onChange={setPicked}
                        extra={
                          entry.preview_available && previewSession ? (
                            <VoicePreviewButton
                              session={previewSession}
                              path={CLIENT_PREVIEW_PATH}
                              voiceId={entry.voice_id}
                              label={entry.label}
                              compact
                            />
                          ) : undefined
                        }
                      />
                    );
                  })}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );

  if (!control) return cards;
  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (changed) control.onSave(selected === DEFAULT ? null : selected, () => setPicked(null));
      }}
    >
      {cards}
      {(changed || control.status === "pending") && (
        <SaveBar
          label="Use this voice"
          status={control.status}
          disabled={locked && control.status !== "pending"}
          onCancel={() => setPicked(null)}
          note={NEXT_CALL_NOTE}
        />
      )}
    </form>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * MODELS, for an operator only. A client is sent none (D-679, D-750).
 * ═══════════════════════════════════════════════════════════════════════════════════ */

/** Whether a model costs extra, in the operator's words, with the platform's own tier and
 * price for a call minute when it states them (W8). A paid one is never listed (D-750). */
export function bandLine(entry: EngineCatalogueModel): string {
  const band = entry.price_band === "none" ? "No extra charge" : "Not checked yet";
  const parts = [band];
  if (entry.platform_call_tier) {
    const currency = entry.platform_currency;
    const unit = currency == null || currency === "INR" ? "₹" : `${currency} `;
    const price =
      entry.platform_price_per_minute != null
        ? `, ${unit}${entry.platform_price_per_minute} a minute`
        : "";
    parts.push(`platform lists it as ${entry.platform_call_tier}${price}`);
  }
  if (entry.latency_ms) parts.push(`replies in about ${entry.latency_ms} ms`);
  return parts.join(" · ");
}

/** The recorded band and the platform's own tier disagree: the record needs re-checking. */
export const BAND_DISAGREES_NOTE =
  "The recorded charge band disagrees with the tier the platform lists for this model. Check it in the platform console and record it again.";

export function EngineModelList({
  catalogue,
  voiceId,
  modelId,
  control,
  bandControl,
}: {
  catalogue: UseQueryResult<EngineCatalogue>;
  /** The agent's saved voice, which decides the models it may run (Studio or Clear). */
  voiceId: string | null;
  /** The saved model, or null for the platform default. */
  modelId: string | null;
  control?: SaveControl;
  /** The per-model band control, rendered at the end of each row. */
  bandControl?: (entry: EngineCatalogueModel) => ReactNode;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const loaded = loadedState(catalogue, "models");
  const saved = modelId ?? DEFAULT;
  const selected = picked ?? saved;
  const changed = selected !== saved;
  if (!loaded.data) return loaded.node;
  const data = loaded.data;
  if (!data.available) return null;

  const lockReason = !data.choosable ? (data.choice_note ?? null) : (control?.disabledReason ?? null);
  const locked = !control || lockReason !== null || control.status === "pending";
  // On a Studio voice the platform runs only the models it allows beside our own voice key;
  // the rest are not offered at all rather than listed as refusals (founder, 11 Oct 2026).
  const studio = data.voices.find((entry) => entry.voice_id === voiceId)?.rung === "studio";
  // Calevate offers only models included in the per-minute price (D-750). The server already
  // leaves a paid model out; this keeps a stale cache from showing one.
  const free = data.models.filter((entry) => entry.price_band !== "premium");
  const models = studio ? free.filter((entry) => entry.usable_with_studio_voice) : free;
  const hidden = free.length - models.length;

  const list = (
    <div className="space-y-4">
      {control && lockReason && <p className="text-meta text-ink-muted">{lockReason}</p>}
      {control?.error && <ProblemNotice error={control.error} />}
      {studio && hidden > 0 && (
        <p className="flex items-center gap-1 text-meta text-ink-muted">
          More models are available with a Clear voice.
          <InfoTip label="Models on a Studio voice">
            <p>
              This agent speaks a Studio voice, which runs on our own voice key. The platform
              allows only {models.length} of its {free.length} models beside that key, so
              only those are listed. Choose a Clear voice to use the others.
            </p>
          </InfoTip>
        </p>
      )}
      <div role="radiogroup" aria-label="Language model" className="space-y-2">
        {control && (
          <ChoiceCard
            name="engine-model"
            value={DEFAULT}
            label="Platform default"
            detail={
              data.default_model_label
                ? `${data.default_model_label} on Clear voices. Studio voices use the platform's standard model.`
                : "The model the platform picks when none is chosen."
            }
            checked={selected === DEFAULT}
            current={saved === DEFAULT}
            disabled={locked}
            onChange={setPicked}
          />
        )}
        {models.length === 0 ? (
          <p className="text-body text-ink-muted">The platform listed no models it can run here.</p>
        ) : (
          models.map((entry) => (
            <ChoiceCard
              key={entry.model_id}
              name="engine-model"
              value={control ? entry.model_id : null}
              label={entry.label}
              icon={<ModelLogo label={entry.label} />}
              detail={bandLine(entry)}
              reason={
                entry.offerable ? (entry.band_disagrees ? BAND_DISAGREES_NOTE : null) : entry.reason
              }
              checked={selected === entry.model_id}
              current={saved === entry.model_id}
              disabled={locked || !entry.offerable}
              onChange={setPicked}
              extra={bandControl?.(entry)}
            />
          ))
        )}
      </div>
    </div>
  );

  if (!control) return list;
  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (changed) control.onSave(selected === DEFAULT ? null : selected, () => setPicked(null));
      }}
    >
      {list}
      {(changed || control.status === "pending") && (
        <SaveBar
          label="Save model"
          status={control.status}
          disabled={locked && control.status !== "pending"}
          onCancel={() => setPicked(null)}
          note={NEXT_CALL_NOTE}
        />
      )}
    </form>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * ONE OPTION
 * ═══════════════════════════════════════════════════════════════════════════════════ */

/**
 * One option as the kit's choice card: a radio when the list is a picker (`value` set), plain
 * text when it is not. `extra` (a preview button, a band control) sits OUTSIDE the label, so
 * pressing it never changes the selection. `current` marks what is saved now, which a moved
 * radio no longer shows. A reason is a plain muted line with the whole sentence behind an ⓘ.
 * A `note` is a whole sentence said in full and the card is not dimmed: it is about the
 * option the agent holds now, which the reader must read rather than skip.
 */
function ChoiceCard({
  name,
  value,
  label,
  icon,
  suffix,
  detail,
  reason,
  note,
  checked,
  current = false,
  disabled,
  onChange,
  extra,
}: {
  name: string;
  value: string | null;
  label: string;
  icon?: ReactNode;
  suffix?: string;
  detail?: string;
  reason?: string | null;
  note?: { text: string; stop: boolean } | null;
  checked: boolean;
  current?: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
  extra?: ReactNode;
}) {
  const reasonText = reason ? shortReason(reason) : null;
  // The whole sentence goes behind an ⓘ only when the plain line had to leave some out.
  const reasonCut =
    reason != null && reasonText !== null && reasonText.length < reason.replace(/[.;:]\s*$/, "").length;
  const text = (
    <span className={`min-w-0 flex-1 ${reason ? "opacity-60" : ""}`}>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {icon}
        <span className="text-sm font-semibold text-ink">{label}</span>
        {suffix && <span className="text-xs text-ink-muted">{suffix}</span>}
        {current && (
          <StatusPill tone="ok">In use</StatusPill>
        )}
      </span>
      {detail && <span className="mt-0.5 block text-xs text-ink-muted">{detail}</span>}
      {reasonText && <span className="mt-0.5 block text-xs text-ink-muted">{reasonText}</span>}
      {note && (
        <span className={`mt-1 block text-xs ${note.stop ? "text-danger" : "text-ink-muted"}`}>{note.text}</span>
      )}
    </span>
  );
  return (
    <div
      className={`relative flex items-start gap-3 rounded-card border p-3 transition-colors ${
        checked ? CHOICE_ON : CHOICE_OFF
      }`}
    >
      {value === null ? (
        text
      ) : (
        <label
          className={`flex min-w-0 flex-1 items-start gap-3 rounded-md touch:min-h-11 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app ${
            disabled ? "cursor-not-allowed" : "cursor-pointer"
          }`}
        >
          <input
            type="radio"
            name={name}
            value={value}
            className="sr-only"
            checked={checked}
            disabled={disabled}
            onChange={() => onChange(value)}
          />
          {checked ? (
            <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong" />
          ) : (
            <span aria-hidden className="mt-0.5 h-4 w-4 shrink-0 rounded-full border border-ink/25" />
          )}
          {text}
        </label>
      )}
      {reason && reasonCut && (
        <InfoTip label={`Why ${label} cannot be chosen`} align="end" className="-mr-1 -mt-1">
          <p>{reason}</p>
        </InfoTip>
      )}
      {extra}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════════
 * MOUNTS
 * ═══════════════════════════════════════════════════════════════════════════════════ */

/**
 * Each mount passes its write through `useActionFeedback` with `errorDisplay: "inline"`: the
 * list draws the save bar's faces and the refusal itself (`SaveControl`). The bar closes on
 * success, so the success is a toast.
 */
function saveControl(
  save: ReturnType<typeof useUpdateAgent>,
  status: FeedbackStatus,
  disabledReason: string | null,
  field: "engine_voice_id" | "engine_model_id",
  onSaved?: () => void,
): SaveControl {
  return {
    disabledReason,
    status,
    error: save.error,
    onSave: (value, done) =>
      save.mutate({ [field]: value }, {
        onSuccess: () => {
          done();
          onSaved?.();
        },
      }),
  };
}

/** The voices, through the console's view-as session for one tenant. */
export function TenantEngineVoices({
  slug,
  agent,
  disabledReason = null,
}: {
  slug: string;
  agent?: Agent;
  disabledReason?: string | null;
}) {
  const client = useQueryClient();
  const save = useUpdateAgent(viewAsSession(slug), agent?.id ?? "");
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Voice saved" });
  // The console reads this agent from its own roster query, which the client hook's refresh
  // does not know about.
  const refreshRoster = () => void client.invalidateQueries({ queryKey: ["admin", "agents", slug] });
  const catalogue = useTenantEngineCatalogue(slug);
  const voiceId = agent?.engine_voice_id ?? null;
  const held = useHeldVoice(viewAsSession(slug), `operator:${slug}`, agent?.id, voiceId, catalogue.data);
  return (
    <EngineVoiceList
      catalogue={catalogue}
      held={held}
      voiceId={voiceId}
      modelId={agent?.engine_model_id ?? null}
      control={agent ? saveControl(save, feedback.status, disabledReason, "engine_voice_id", refreshRoster) : undefined}
      previewSession={viewAsSession(slug)}
      audience="operator"
    />
  );
}

/** The models with their makers' marks, through the console's view-as session. */
export function TenantEngineModels({
  slug,
  agent,
  disabledReason = null,
  bandControl,
}: {
  slug: string;
  agent?: Agent;
  disabledReason?: string | null;
  bandControl?: (entry: EngineCatalogueModel) => ReactNode;
}) {
  const client = useQueryClient();
  const save = useUpdateAgent(viewAsSession(slug), agent?.id ?? "");
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Model saved" });
  const refreshRoster = () => void client.invalidateQueries({ queryKey: ["admin", "agents", slug] });
  return (
    <EngineModelList
      catalogue={useTenantEngineCatalogue(slug)}
      voiceId={agent?.engine_voice_id ?? null}
      modelId={agent?.engine_model_id ?? null}
      control={agent ? saveControl(save, feedback.status, disabledReason, "engine_model_id", refreshRoster) : undefined}
      bandControl={bandControl}
    />
  );
}

/** The voices, through a client's own session. A client never sees the models (D-679). */
export function ClientEngineVoices({ session, agentId }: { session: Session; agentId: string }) {
  const agent = useAgent(session, agentId);
  const save = useUpdateAgent(session, agentId);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Voice saved" });
  const catalogue = useEngineCatalogue(session);
  const voiceId = agent.data?.engine_voice_id ?? null;
  const held = useHeldVoice(session, clientCatalogueAudience(session), agentId, voiceId, catalogue.data);
  return (
    <EngineVoiceList
      catalogue={catalogue}
      held={held}
      voiceId={voiceId}
      modelId={agent.data?.engine_model_id ?? null}
      control={agent.data ? saveControl(save, feedback.status, null, "engine_voice_id") : undefined}
      previewSession={session}
      audience="client"
    />
  );
}
