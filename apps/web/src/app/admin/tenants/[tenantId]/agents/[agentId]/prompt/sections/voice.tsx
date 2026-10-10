"use client";

import { useState } from "react";

import { InfoTip } from "@/components/console/infoTip";
import { TenantEngineCatalogue } from "@/components/engineCatalogueList";
import { VoicePicker } from "@/components/voicePicker";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import type { Agent } from "@/lib/api/agents";
import type { AgentVoice, AgentVoiceState, PendingState } from "@/lib/api/publishing";
import {
  useSetAgentVoice,
  useTenantVoiceCatalogue,
  voiceTierRate,
  type OfferedVoice,
  type VoiceTierRates,
} from "@/lib/api/voices";

/**
 * Which voice this agent speaks in — TWO QUALITIES at two per-minute rates (D-547),
 * selectable, priced, and READABLE.
 *
 * **Why this screen.** Voice is agent CONFIGURATION and the write is admin-realm
 * `agents:write` (`agents/voice_routes.py`, D-21: which voice speaks Telugu well is an ear
 * test, so it routes through us). This is the only per-agent operator screen in the
 * console and it already holds every other `agents:write` control — script, apply/undo,
 * call cap, A/B — behind one `useAdminAccess` gate. A second per-agent screen for one
 * dropdown would be a second place to look for the same class of setting.
 *
 * **CONFIGURED IS NOT LIVE, and this panel is built around that rather than around the
 * dropdown.** The write touches our row only; `publish_agent` re-reads the column, so a
 * live agent keeps its old voice until the next publish. `GET /v1/agents/{id}/pending`
 * therefore answers with TWO voices — `voice.configured` and `voice.live` — and both are
 * rendered as labelled data, side by side, exactly as `PendingRow` renders the two script
 * pointers on the client screen. The reasoning is the same and it has been earned twice:
 * a sentence can be read the wrong way round, two `dt`/`dd` pairs under "Callers hear
 * now" and "Configured" cannot. Where the panel cannot report a fact, the fix is to make
 * the server answer it rather than to guess.
 *
 * **The picker pre-selects `voice.configured`** and nothing else. Not `voice.live` (the
 * operator edits the configuration, not the past), not the first row of the catalogue
 * (D-588 deleted the compiled default persona, so there is no `is_default` to fall back
 * to and the order is whatever the voice platform returned), and not a blank when the server
 * answered — a picker that reopens on "choose a voice" over a configured agent invites
 * the operator to re-pick a value that is already set.
 *
 * `verified` is rendered, not hidden. Since D-585/D-588 it is TRUE on every entry and
 * means one narrow thing — the voice platform's own API listed this voice on our account
 * for a model we offer. It is not an ear test: which voice suits Telugu best is
 * OPERATIONS §2 gate 3's listening half, still open. And
 * an operator picking an unverified voice should know that is what they are doing.
 *
 * **EVERY catalogue voice is rendered, including the ones this deployment cannot offer**
 * (`agents/voice_offer.py::offerable_voices`) — disabled, with the server's own reason. The
 * refusal here is an OPERATOR's sentence naming a key, a price or a cap, which is exactly
 * who is reading this screen; the tier NAME beside it is the client's word for the quality
 * ("Clear", "Studio") because a vendor is never a product tier a human reads.
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
  const catalogue = useTenantVoiceCatalogue(slug);
  const save = useSetAgentVoice({ tenantId, agentId, slug });
  // `null` means "not edited on this visit" — the select then shows the server's
  // configured voice. Same shape, and the same reason, as the call-cap field above: an
  // explicit "" is a real (invalid) choice and must not be confused with "unchanged".
  const [choice, setChoice] = useState<string | null>(null);
  const state = pending?.voice;
  const selected = choice ?? state?.configured?.voice_id ?? "";
  // THE RATE IS THIS CLIENT'S, PER TIER, off the pending read this panel already has.
  // `voice_tier_rates` is generated and REQUIRED (`PendingOut`), so it is read as a field
  // rather than through the hand validator that stood in while the lots API was in flight.
  // Never a constant and never the rate card: under D-547 the price of the next minute is
  // the one frozen on this account's oldest open credit lot. `undefined` here means the
  // pending read itself has not answered yet.
  const rates = pending?.voice_tier_rates;

  return (
    <div>
      <div className="flex max-w-prose items-start gap-1 text-body text-ink-muted">
        <span>
          A price as well as a persona: each quality bills at the rate shown. On a live
          agent, callers hear a new voice from their next call.
        </span>
        <InfoTip label="How a voice change lands">
          Two voice qualities, at two different per-minute rates, and the rate shown
          against each quality is the one frozen on this client&apos;s oldest unspent credit.
          Setting a voice on a LIVE agent re-publishes it in the same transaction — a
          call in progress finishes as it started, and if the calling system refuses the
          change nothing is saved. A draft or paused agent is written but not published; the
          next publish carries the voice.
        </InfoTip>
      </div>
      <div className="mt-4 space-y-5">
        <RestrictionNote reason={write.reason} />
        {save.error && <ProblemNotice error={save.error} />}

        {/* §52: the catalogue is a read like any other. A skeleton while it is in flight,
            a refusal when it failed — never an empty `<select>`, which reads as "this
            agent has no voices available" and is a claim about the product. The tenant
            and pending reads gate it too: the catalogue request goes through that
            tenant's impersonation session, and pre-selecting before the pending read
            lands would flash "choose a voice" over a configured agent. */}
        {tenantLoading || catalogue.isLoading ? (
          <Skeleton rows={2} />
        ) : catalogue.error || !catalogue.data ? (
          <ProblemNotice
            error={
              catalogue.error ??
              new Error("The voice catalogue did not load, so there is nothing to choose from.")
            }
            onRetry={() => void catalogue.refetch()}
          />
        ) : !catalogue.data.selectable ? (
          /* THE ENGINE SUPPLIES ITS OWN VOICES (D-93), which is a product fact and not a
             fault — so it is stated, in the server's own words, and NOT rendered through
             `ProblemNotice`. An error card here would send an operator to a runbook for
             a deployment that is working exactly as intended.

             The picker is not rendered at all rather than rendered-and-disabled: a
             disabled list of our own personas still tells the reader those are the
             voices this agent might speak, and they are not. That is a DIFFERENT case
             from a voice this platform cannot offer, which IS rendered and disabled with
             its reason — there the row is real and one action away. `voices` is empty from the
             server for the same reason. What IS still shown is `VoiceInForce`, because
             "what do callers hear right now" remains a fair question — the answer is just
             not ours to change here. */
          <>
            <VoiceInForce state={state} published={pending?.published} />
            <p className="text-meta text-ink-muted">{catalogue.data.note}</p>
            <TenantEngineCatalogue
              slug={slug}
              agent={agent}
              disabledReason={write.allowed ? null : write.reason}
            />
          </>
        ) : (
          <>
            <VoiceInForce state={state} published={pending?.published} />

            <form
              className="space-y-3"
              // A radio group with a value always chosen — no rule to word. `noValidate` so
              // a rule added later cannot be answered by the browser in its own language.
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                save.mutate(selected);
              }}
            >
              <VoicePicker
                name="agent-voice"
                legend="Voice"
                /* THE SERVER'S OWN SENTENCE, not a hardcoded one. It used to read "Every
                   voice this deployment knows about…", which is still true of a synced and
                   curated platform and says nothing at all on the two states where the list
                   is EMPTY (D-588): nobody has synced, or nobody has enabled anything. Those
                   need different actions — one is fixed by Refresh and the other is not —
                   and `VoiceCatalogueOut.note` is the one place that forks on which it is. */
                hint={catalogue.data.note}
                voices={catalogue.data.voices}
                value={selected}
                rates={rates}
                /* See `VoiceTierAvailability`: a tier with no rows renders no heading, so
                   without this the operator reads a shorter list and no statement (D-617). */
                tiers={catalogue.data.tiers}
                disabled={!write.allowed}
                onChange={setChoice}
              />
              <button
                type="submit"
                disabled={save.isPending || selected === "" || !write.allowed}
                className={PRIMARY_BUTTON}
              >
                {save.isPending ? "Saving…" : "Set voice"}
              </button>
            </form>

            <VoiceDetail
              voice={catalogue.data.voices.find((entry) => entry.id === selected)}
              rates={rates}
            />
          </>
        )}

        {save.data && (
          <p className="text-meta text-ink-muted">
            Saved — {save.data.voice.label} ({save.data.voice.tts_model}).{" "}
            {save.data.next_step}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * The two voices, named, with the gap between them stated where there is one.
 *
 * Modelled on `PendingRow` on the client agents screen, deliberately: that component
 * exists because showing the STAGED script as the one callers hear was shipped once and
 * `agents/publishing.py` opens by recording it. A voice has the same two-pointer shape
 * for the same reason — our row moves, the engine does not until a publish — so it gets
 * the same treatment: the server's headline, and both values as labelled data underneath
 * so no one has to parse a sentence correctly to know which is which.
 *
 * `published` decides how a null `live` reads, and it is genuinely two different facts:
 * an unpublished agent has nothing live, while a published one with nothing recorded is
 * an agent whose voice we cannot name. The second is not "no voice" and must not be
 * rendered as one — the server says `republish_required` for it either way.
 *
 * Nothing at all is rendered while the pending read is unavailable: the panel below still
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
        /* A RAW ENGINE REF IS NEVER PRINTED WITHOUT THIS SENTENCE (D-617). `voiceName`
           degrades an unrecognised id to the id itself on purpose — an operator can search
           for an id, and "unknown" reads as a fault rather than as a voice the platform no
           longer lists — but the degradation was silent, so this panel showed
           `sonic-3.5:b6dafaa0-…` under both labels with nothing saying what it was. The
           sentence is the server's, composed where the catalogue is
           (`publishing.VOICE_NOT_IN_CATALOGUE_NOTE`), because there are two consoles and a
           paragraph written twice in TypeScript comes to say two things. */
        <p className="mt-2 text-meta text-ink-muted">{state.unnamed_note}</p>
      )}
      {state.republish_required && (
        /* Amber, and only when the server says so. The two values above are already
           different at this point, but "different" is not the operator's question —
           "does a caller hear the wrong thing until I act" is, and only the server can
           answer it (an unpublished agent has two different values and no problem). */
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
 *  `catalog` is null for a voice the API no longer offers, and the id is then all we
 *  have. Printing it beats printing "unknown": an operator can search for an id. */
function voiceName(voice: AgentVoice): string {
  return voice.catalog ? `${voice.catalog.label} (${voice.catalog.tts_model})` : voice.voice_id;
}

/**
 * What the operator is about to choose, before they choose it.
 *
 * The picker row carries the persona, its languages and the note; this block is what the
 * operator is about to COMMIT — the one voice, its quality and its model, gathered under the
 * button that saves it. Nothing is rendered when nothing is selected, which now only happens on
 * an agent with no voice configured: the block above has already said so, and repeating it
 * here would be two answers to one question.
 */
function VoiceDetail({
  voice,
  rates,
}: {
  voice: OfferedVoice | undefined;
  rates: VoiceTierRates | undefined;
}) {
  if (!voice) return null;
  // The TIER's name, never the vendor's (founder, 7 Sep 2026): `provider` is what the wire
  // and the ledger call it, and this line used to print it at a person. The label is the
  // server's (`billing/rates.py::VOICE_TIER_LABELS`) and is simply omitted when this build's
  // API does not send it — a quality named by nobody is better than one named by us twice.
  const tier = voiceTierRate(rates, voice.voice_tier);
  const quality = voice.tier_label ?? tier?.label ?? null;
  return (
    <div className="border-l-2 border-line pl-3 text-meta text-ink-muted">
      <p>
        <span className="font-semibold text-ink">{voice.label}</span>
        {quality ? ` · ${quality} voice` : ""} · {voice.tts_model}
        {voice.gender ? ` · ${voice.gender}` : ""} · {voice.languages.join(", ")}
      </p>
      <p className="mt-1">{voice.note}</p>
      {!voice.verified && (
        // Stated, not hidden: the catalogue marks an entry verified only once the pilot
        // has confirmed the engine accepts the string (OPERATIONS §2 gate 3). Setting an
        // unverified one is allowed and is a decision the operator should make knowingly.
        <p className="mt-1 text-warn">
          Not yet confirmed against the voice platform — we have not heard this one on a
          live call. Expect to verify it before a client hears it.
        </p>
      )}
    </div>
  );
}
