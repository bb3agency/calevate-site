"use client";

import { InfoTip } from "@/components/console/infoTip";
import { TenantEngineVoices } from "@/components/engineCatalogueList";
import { RestrictionNote, Skeleton } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import type { Agent } from "@/lib/api/agents";
import type { AgentVoice, AgentVoiceState, PendingState } from "@/lib/api/publishing";

import { VoiceTuningPanel } from "./voiceTuning";

/**
 * Which voice this agent speaks in: the voice platform's own voices, grouped by rung (Clear,
 * Studio), chosen and saved through `TenantEngineVoices`.
 *
 * **CONFIGURED IS NOT LIVE.** The write touches our row only and the voice platform keeps the
 * voice it was last published with, so `GET /v1/agents/{id}/pending` answers with two voices,
 * `voice.configured` and `voice.live`, and both are rendered as labelled data side by side,
 * the way `PendingRow` renders the two script pointers on the client screen. Two `dt`/`dd`
 * pairs cannot be read the wrong way round; a sentence can.
 */
export function VoicePanel({
  tenantId,
  agentId,
  slug,
  agent,
  pending,
  tenantLoading,
  write,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  /** The roster row, for the engine-catalogue picker's saved choice. */
  agent: Agent | undefined;
  pending: PendingState | undefined;
  tenantLoading: boolean;
  write: ReturnType<typeof useAdminAccess>;
}) {
  return (
    <div>
      <div className="flex max-w-prose items-start gap-1 text-body text-ink-muted">
        <span>
          A price as well as a persona: each quality bills at its own rate. Callers hear a new
          voice from their next call.
        </span>
        <InfoTip label="How a voice change lands">
          Two voice qualities, Clear and Studio, at two different per-minute rates. A call in
          progress finishes as it started.
        </InfoTip>
      </div>
      <div className="mt-4 space-y-5">
        <RestrictionNote reason={write.reason} />
        {/* The tenant and pending reads gate the picker: the catalogue request goes through
            that tenant's impersonation session, and rendering before the pending read lands
            would show "None set" over a configured agent. */}
        {tenantLoading ? (
          <Skeleton rows={2} />
        ) : (
          <>
            <VoiceInForce state={pending?.voice} published={pending?.published} />
            <TenantEngineVoices
              slug={slug}
              agent={agent}
              disabledReason={write.allowed ? null : write.reason}
            />
          </>
        )}
      </div>
      {!tenantLoading && (
        <VoiceTuningPanel
          tenantId={tenantId}
          agentId={agentId}
          voiceId={agent?.engine_voice_id ?? null}
          write={write}
        />
      )}
    </div>
  );
}

/**
 * The two voices, named, with the gap between them stated where there is one.
 *
 * `published` decides how a null `live` reads, and it is genuinely two different facts: an
 * unpublished agent has nothing live, while a published one with nothing recorded is an agent
 * whose voice we cannot name. The second is not "no voice" and must not be rendered as one;
 * the server says `republish_required` for it either way.
 *
 * Nothing at all is rendered while the pending read is unavailable: the picker below still
 * SETS a voice, and a missing "in force" block is a smaller lie than an invented one.
 */
function VoiceInForce({
  state,
  published,
}: {
  state: AgentVoiceState | undefined;
  published: boolean | undefined;
}) {
  if (!state) return null;
  return (
    <div className="border-y border-line py-3">
      <p className="text-body text-ink">{state.headline}</p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <dt className="text-meta font-medium text-ink-muted">
            Callers hear now
          </dt>
          <dd className="text-body font-medium text-ink">
            {state.live
              ? voiceName(state.live)
              : published
                ? "Not recorded — publish to be sure"
                : "Nothing — not on the voice platform yet"}
          </dd>
        </div>
        <div>
          <dt className="text-meta font-medium text-ink-muted">
            Configured
          </dt>
          <dd className="text-body font-medium text-ink">
            {state.configured ? voiceName(state.configured) : "None set"}
          </dd>
        </div>
      </dl>
      {state.unnamed_note && (
        /* A raw engine ref is never printed without this sentence: `voiceName` degrades an
           unrecognised id to the id itself, and this says what it is. The sentence is the
           server's (`publishing.VOICE_NOT_IN_CATALOGUE_NOTE`), so the two consoles cannot
           come to say two things. */
        <p className="mt-2 text-meta text-ink-muted">{state.unnamed_note}</p>
      )}
      {state.republish_required && (
        /* Amber, and only when the server says so: "does a caller hear the wrong thing until
           I act" is a question only the server can answer (an unpublished agent has two
           different values and no problem). */
        <p className="mt-2 text-meta text-warn">
          Publishing this agent is what moves the voice callers hear. Nothing else on this
          screen does it.
        </p>
      )}
    </div>
  );
}

/** A stored voice in the words an operator recognises, degrading to the raw id.
 *
 *  `catalog` is null for a voice the platform no longer lists, and the id is then all we
 *  have. Printing it beats printing "unknown": an operator can search for an id. */
function voiceName(voice: AgentVoice): string {
  return voice.catalog ? `${voice.catalog.label} (${voice.catalog.tts_model})` : voice.voice_id;
}
