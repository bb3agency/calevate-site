"use client";

import { useState } from "react";
import { AudioLines, Plus, RefreshCw, TriangleAlert } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  ScrollRegion,
  SECONDARY_BUTTON_SM,
  NOTICE_TONES,
  Skeleton,
  StatTile,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  ADD_FIELD_HINTS,
  CLONE_FIRST,
  CURATION_ACTIONS,
  CURATION_MEANING,
  WITHDRAWN_MEANING,
  useAddVoice,
  useCuratedVoices,
  useRefreshVoiceCatalogue,
  useSetVoiceCuration,
  type AddVoiceForm,
  type CuratedVoice,
  type CuratedVoices,
  type CurationState,
  type VoiceScope,
} from "@/lib/api/opsVoices";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { lookup } from "@/lib/lookup";

/**
 * THE VOICES THIS PLATFORM HAS ADDED — the console half of D-590.
 *
 * ## What changed, and why the Add button now exists
 *
 * D-588 made this a CURATION screen: "Offered 4 of 418", and 414 vendor personas to switch
 * off one at a time. The founder's answer was that none of those will ever be used — only
 * voices they have cloned — and that what they want is to ADD those, by providing the facts.
 *
 * The old screen said an Add button could not exist because the voice platform's API is
 * read-only. That premise is still true and the conclusion was wrong: nothing here can clone
 * a voice ON THAT PLATFORM, but adding one to THIS product's catalogue needs only the
 * operator's facts and one read to check them. So the form is the primary action, the table
 * below it holds the voices somebody decided about, and the vendor's full list is one
 * control away instead of being the screen.
 *
 * ## The form refuses nothing in the browser, and that is deliberate
 *
 * Every field is verified on the SERVER against the voice platform's own list — the id, the
 * name, the languages — and every refusal comes back as a problem naming the field and what
 * the platform actually says. A duplicate check here would be a second, weaker copy of a
 * check that has to happen server-side anyway, and it would be the copy that disagreed.
 * `ProblemNotice` prints the server's sentence as written.
 *
 * The one thing the browser does render is the ELEVENLABS refusal, and it renders it from
 * the server's own `form.providers` list: an option that is present, disabled, and carries
 * the reason. An operator who has just spent a voice sample cloning on ElevenLabs must not
 * find the option missing and conclude the console is broken.
 *
 * ## Three things this screen still refuses to compute
 *
 * 1. **Whether a voice is offered.** `offered` is the server's field. A browser composing it
 *    from two columns would get the withdrawn case wrong, which is the case that matters.
 * 2. **The counts and the sentences.** `offered`, `cached` and `note` come off the wire.
 * 3. **What archiving does to a live agent.** The row shows the server's `live_agents` and
 *    the confirmation is the server's `next_step`. Nothing here infers consequences.
 *
 * ## §52 without exception
 *
 * Loading is a skeleton, a failed read is a refusal, and neither is "no voices" — which here
 * is a real state with one cause and one action, and the one thing a transport failure must
 * never be painted as.
 *
 * ## Permission
 *
 * `ops:manage`, which only `superadmin` holds, asked of `GET /v1/admin/me` rather than
 * derived from this screen's own 403 — and it gates the READ, because the whole screen is
 * one GET plus three writes behind the same permission. It is still a PREVIEW and never the
 * enforcement: the query runs on `!access.refused`.
 *
 * No `<h1>`: the shell derives the title from the nav list (`app/admin/layout.tsx`).
 */
export default function VoicesPage() {
  const access = useAdminAccess("ops:manage", "add and manage the voices this platform offers");
  const [scope, setScope] = useState<VoiceScope>("decided");
  const voices = useCuratedVoices(!access.refused, scope);
  const curate = useSetVoiceCuration();
  const add = useAddVoice();
  const refresh = useRefreshVoiceCatalogue();
  /** Which row a write is in flight for — so one button spins, not all of them. */
  const [pending, setPending] = useState<string | null>(null);

  const data = voices.data;
  useCopilotSurface({
    route: "/admin/ops/voices",
    title: "Voices",
    realm: "admin",
    fields: [],
    // NOTHING ON THIS SCREEN IS FILLABLE BY THE ASSISTANT, AND THAT IS DELIBERATE — now
    // including the Add form. Every field on it is a fact about a voice on another company's
    // platform that the operator has in front of them and the model does not; a completed
    // guess would be verified against that platform and refused, or (worse) would be a
    // plausible id belonging to a different voice. `apply` is a no-op for that reason rather
    // than because nobody wired it.
    apply: () => undefined,
    facts: access.refused
      ? [
          {
            key: "voices",
            label: "The voice catalogue",
            value: "withheld — this admin account may not read it",
          },
        ]
      : data
        ? [
            {
              key: "offered",
              label: "Voices any client or admin can currently choose",
              value: String(data.offered),
            },
            {
              key: "added",
              label: "Voices this platform has decided about",
              value: String(data.voices.length),
            },
            {
              key: "cached",
              label: "Voices the voice platform lists for our account",
              value: String(data.cached),
            },
            {
              key: "withdrawn",
              label: "Voices the platform has stopped listing",
              value: String(data.voices.filter((row) => row.withdrawn_at !== null).length),
            },
            {
              key: "adding",
              label: "How a NEW voice is added",
              value: CLONE_FIRST,
            },
          ]
        : [
            {
              key: "voices",
              label: "The voice catalogue",
              value: voices.error ? "could not be read" : "still loading",
            },
          ],
  });

  async function move(voice: CuratedVoice, state: CurationState) {
    setPending(voice.voice_id);
    try {
      await curate.mutateAsync({ voice_id: voice.voice_id, state });
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        The voices this platform offers. Only the ones added here can be chosen for an agent
        &mdash; by a client for their own agent, or by an admin for anyone&rsquo;s.
      </p>

      {access.refused ? (
        /* The refusal INSTEAD of the screen, never beside it: a dead form over a red "we
           could not read this" box describes an outage, and this is a permission working
           exactly as designed. */
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          {/* §52. `!voices.data` covers all three ways to have no answer — in flight, failed,
              and the paused query a console tab open across a dropped connection produces.
              The FORM needs the server's options, so it waits with the table rather than
              rendering a picker of nothing. */}
          {voices.error != null && (
            <ProblemNotice error={voices.error} onRetry={() => void voices.refetch()} />
          )}

          {!voices.data ? (
            voices.error ? null : (
              <Card>
                <Skeleton rows={8} label="Loading the voices this platform offers" />
              </Card>
            )
          ) : (
            <>
              <AddVoiceCard
                form={voices.data.form}
                busy={add.isPending}
                error={add.error}
                result={add.data?.next_step ?? null}
                onAdd={(body) => void add.mutateAsync(body).catch(() => undefined)}
              />

              {curate.error != null && <ProblemNotice error={curate.error} />}
              {curate.data && (
                <NoticeBox tone="neutral" title={`${curate.data.voice.label} updated`}>
                  <p className="mt-1">{curate.data.next_step}</p>
                </NoticeBox>
              )}

              <Catalogue
                catalogue={voices.data}
                scope={scope}
                pending={pending}
                onScope={setScope}
                onMove={(voice, state) => void move(voice, state)}
              />

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={refresh.isPending}
                  onClick={() => void refresh.mutateAsync().catch(() => undefined)}
                >
                  <RefreshCw aria-hidden className="mr-1.5 inline h-3.5 w-3.5" />
                  {refresh.isPending ? "Reading the voice platform…" : "Refresh from the platform"}
                </button>
                <span className="text-xs text-ink-faint">
                  Re-reads the voice platform&rsquo;s own list. It does not add anything &mdash;
                  it keeps the &ldquo;last seen&rdquo; column honest and marks voices that
                  platform has stopped listing.
                </span>
              </div>

              {/* A MUTATION's `data` is the user having asked, so rendering it is correct —
                  `surfaceStatesGuard` exempts the mutation envelope for exactly this. The
                  server's own sentence, printed verbatim. */}
              {refresh.data && (
                <NoticeBox tone="neutral" title="The voice platform's catalogue was re-read">
                  <p className="mt-1">{refresh.data.note}</p>
                </NoticeBox>
              )}
              {refresh.error != null && <ProblemNotice error={refresh.error} />}
            </>
          )}
        </>
      )}
    </div>
  );
}

/**
 * THE PRIMARY ACTION: five fields for one cloned voice.
 *
 * The provider is RADIO BUTTONS rather than a `<select>`, and that is the one layout
 * decision here worth defending. A disabled `<option>` cannot be chosen and, on most
 * platforms, cannot be focused either — so the ElevenLabs refusal would be a greyed line
 * nobody could read the reason for. As radios, the unusable provider is visible, disabled,
 * and carries the server's sentence underneath it.
 *
 * The model follows the provider because the server says which models belong to it; the
 * operator never has to know the pairing, and a provider with two models still renders a
 * choice rather than a hidden default.
 */
function AddVoiceCard({
  form,
  busy,
  error,
  result,
  onAdd,
}: {
  form: AddVoiceForm;
  busy: boolean;
  error: Error | null;
  result: string | null;
  onAdd: (body: {
    provider: string;
    tts_model: string;
    engine_voice_id: string;
    label: string;
    languages: ("te-IN" | "hi-IN" | "en-IN")[];
  }) => void;
}) {
  const selectable = form.providers.filter((option) => option.selectable);
  const [provider, setProvider] = useState(selectable[0]?.provider ?? "");
  const models = form.providers.find((o) => o.provider === provider)?.models ?? [];
  const [model, setModel] = useState<string>(models[0] ?? "");
  const [voiceId, setVoiceId] = useState("");
  const [label, setLabel] = useState("");
  const [languages, setLanguages] = useState<string[]>(form.languages.slice(0, 1));

  /* The model belongs to the provider, so changing one moves the other. Kept in the handler
     rather than in an effect: this is a consequence of a click, not of a render. */
  function pickProvider(next: string) {
    setProvider(next);
    const first: string = form.providers.find((o) => o.provider === next)?.models[0] ?? "";
    setModel(first);
  }

  const complete = provider && model && voiceId.trim() && label.trim() && languages.length > 0;

  return (
    <Card title="Add a voice">
      <p className="text-sm text-ink-muted">{CLONE_FIRST}</p>
      <p className="mt-1 text-xs text-ink-faint">
        The Voice Lab is at <MonoValue>{form.voice_lab_url}</MonoValue>.
      </p>

      <form
        // `noValidate`: every refusal on this form is the SERVER's — the voice platform
        // either lists this voice or it does not — and a browser bubble saying "please fill
        // in this field" is a second, weaker validator in a different voice
        // (`tests/formValidation.test.tsx` holds every form in both realms to it).
        noValidate
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          onAdd({
            provider,
            tts_model: model,
            engine_voice_id: voiceId.trim(),
            label: label.trim(),
            languages: languages as ("te-IN" | "hi-IN" | "en-IN")[],
          });
        }}
      >
        <fieldset>
          <legend className={FIELD_LABEL}>Who you cloned it on</legend>
          <span className={FIELD_HINT}>{ADD_FIELD_HINTS.provider}</span>
          <div className="mt-2 space-y-2">
            {form.providers.map((option) => (
              <div key={option.provider}>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="voice-provider"
                    value={option.provider}
                    checked={provider === option.provider}
                    disabled={!option.selectable}
                    onChange={() => pickProvider(option.provider)}
                  />
                  <span className={option.selectable ? "" : "text-ink-faint"}>
                    {option.provider}
                    {option.tier_label && (
                      <span className="ml-1 text-xs text-ink-faint">
                        &mdash; the {option.tier_label} tier
                      </span>
                    )}
                  </span>
                </label>
                {/* THE ELEVENLABS SENTENCE, from the server. It is the whole reason an
                    unusable provider is rendered at all. */}
                {option.unavailable_reason && (
                  <p className="ml-6 mt-0.5 text-xs text-amber-700 dark:text-amber-400">
                    {option.unavailable_reason}
                  </p>
                )}
              </div>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className={FIELD_LABEL}>Speech model</span>
            <select
              className={FIELD}
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              {models.map((each) => (
                <option key={each} value={each}>
                  {each}
                </option>
              ))}
            </select>
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.tts_model}</span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Voice ID</span>
            <input
              className={`${FIELD} font-mono`}
              value={voiceId}
              maxLength={128}
              onChange={(event) => setVoiceId(event.target.value)}
            />
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.engine_voice_id}</span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Name, exactly as the Voice Lab shows it</span>
            <input
              className={FIELD}
              value={label}
              maxLength={200}
              onChange={(event) => setLabel(event.target.value)}
            />
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.label}</span>
          </label>

          <fieldset>
            <legend className={FIELD_LABEL}>Languages</legend>
            <div className="mt-1 flex flex-wrap gap-3">
              {form.languages.map((language) => (
                <label key={language} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={languages.includes(language)}
                    onChange={(event) =>
                      setLanguages((held) =>
                        event.target.checked
                          ? [...held, language]
                          : held.filter((each) => each !== language),
                      )
                    }
                  />
                  {language}
                </label>
              ))}
            </div>
            <span className={FIELD_HINT}>{ADD_FIELD_HINTS.languages}</span>
          </fieldset>
        </div>

        <button type="submit" className={PRIMARY_BUTTON} disabled={busy || !complete}>
          <Plus aria-hidden className="h-4 w-4" />
          {busy ? "Checking it against the voice platform…" : "Add this voice"}
        </button>
      </form>

      {/* The server's refusal, verbatim — it names the field and what the platform actually
          says, which is more than this screen could work out. */}
      {error != null && (
        <div className="mt-4">
          <ProblemNotice error={error} />
        </div>
      )}
      {result && (
        <div className="mt-4">
          <NoticeBox tone="neutral" title="Voice added">
            <p className="mt-1">{result}</p>
          </NoticeBox>
        </div>
      )}
    </Card>
  );
}

/**
 * The table, given a catalogue that ARRIVED.
 *
 * Takes the payload rather than the query envelope for the reason every board in this
 * console does: each sentence below is a claim about what this platform offers, and a
 * component that cannot see `undefined` cannot accidentally make one out of it.
 */
function Catalogue({
  catalogue,
  scope,
  pending,
  onScope,
  onMove,
}: {
  catalogue: CuratedVoices;
  scope: VoiceScope;
  pending: string | null;
  onScope: (scope: VoiceScope) => void;
  onMove: (voice: CuratedVoice, state: CurationState) => void;
}) {
  const withdrawn = catalogue.voices.filter((row) => row.withdrawn_at !== null).length;
  const undecided = Math.max(catalogue.cached - catalogue.voices.length, 0);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Offered"
          value={`${formatCount(catalogue.offered)} of ${formatCount(catalogue.voices.length)}`}
          tone={catalogue.offered === 0 ? "strong" : undefined}
          icon={<AudioLines aria-hidden className="h-5 w-5" />}
          hint="Voices any client or admin can currently choose for an agent. Zero means nobody can set a voice at all."
        />
        <StatTile
          label="Added"
          value={formatCount(catalogue.voices.length)}
          hint="Voices this platform has decided about — added here, or moved off the arrival state."
        />
        <StatTile
          label="Dropped by the platform"
          value={formatCount(withdrawn)}
          tone={withdrawn > 0 ? "strong" : undefined}
          icon={withdrawn > 0 ? <TriangleAlert aria-hidden className="h-5 w-5" /> : undefined}
          hint="Voices the platform has stopped listing on our account. They cannot be offered, and nothing here restores them."
        />
        <StatTile
          label="On the platform"
          value={formatCount(catalogue.cached)}
          hint="Voices the voice platform lists for our account, as of the last read. You do not have to do anything with these."
        />
      </div>

      {/* ZERO OFFERED IS A STATE WITH TWO CAUSES, and the server's sentence says which.
          It sits above the table because it changes how the table should be read. */}
      {catalogue.offered === 0 && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="No voice can be chosen for any agent right now"
        >
          <p className="mt-1">{catalogue.note}</p>
        </NoticeBox>
      )}

      {catalogue.voices.length === 0 ? (
        <Card title="The voices this platform offers">
          <EmptyState
            title="No voice has been added yet"
            hint="Use the form above. You will need the voice's ID and its name from the voice platform's Voice Lab — we check both against that platform's own list before adding it."
          />
        </Card>
      ) : (
        <Card title="The voices this platform offers" bodyClassName="p-2">
          <ScrollRegion label="The voices this platform offers">
            <table className="w-full text-left text-xs">
              <thead className="text-ink-muted">
                <tr>
                  <HeadCell label="Voice" gloss="What the voice platform calls it" />
                  <HeadCell label="Quality" gloss="Who synthesises it, and the tier a client is told" />
                  <HeadCell label="Model" />
                  <HeadCell label="Added how" gloss="Typed here, or read off the platform's list" />
                  <HeadCell label="Languages" />
                  <HeadCell label="Live agents" gloss="Across every client, now" />
                  <HeadCell label="State" />
                  <HeadCell label="Last seen" gloss="When we last saw it on the platform" />
                  <HeadCell label="Change" />
                </tr>
              </thead>
              <tbody>
                {catalogue.voices.map((voice) => (
                  <VoiceRow
                    key={voice.voice_id}
                    voice={voice}
                    pending={pending === voice.voice_id}
                    onMove={onMove}
                  />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        </Card>
      )}

      {/* THE VENDOR'S FULL LIST IS ONE CONTROL AWAY AND IS NOT THE SCREEN (D-590). It is a
          reference — a voice does not have to be cached before it can be added — so the
          control says what it opens rather than implying a to-do list. */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          onClick={() => onScope(scope === "decided" ? "all" : "decided")}
        >
          {scope === "decided"
            ? `Show every voice the platform lists (${formatCount(catalogue.cached)})`
            : "Show only the voices this platform has added"}
        </button>
        {scope === "decided" && undecided > 0 && (
          <span className="text-xs text-ink-faint">
            {formatCount(undecided)} more are on the platform and have not been added. Nothing
            needs to be done with them.
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * One column header: a plain label, and an optional one-line gloss beneath it.
 *
 * The same component and the same argument as `/admin/ops/engine-latency`: the operator
 * reading this screen is not the person who wrote the wire contract, so a column whose name
 * is jargon carries a sentence saying what it actually means.
 */
function HeadCell({ label, gloss }: { label: string; gloss?: string }) {
  return (
    <th scope="col" className="py-1 pr-3 align-top font-medium">
      {label}
      {gloss && (
        <span className="mt-0.5 block text-[11px] font-normal text-ink-faint">{gloss}</span>
      )}
    </th>
  );
}

/**
 * How each state is painted, from the palette `NOTICE_TONES` already defines.
 *
 * Keyed by the WIRE string and read through `lookup`, so a server that grew a fourth state
 * prints the bare value rather than being mislabelled as one of these three.
 */
const STATE_TONE: Record<string, string> = {
  enabled: NOTICE_TONES.ok,
  disabled: NOTICE_TONES.neutral,
  archived: NOTICE_TONES.warn,
};

/** What each provenance means to a reader. Through `lookup`, for `STATE_TONE`'s reason. */
const ORIGIN_MEANING: Record<string, string> = {
  operator: "Added here, and checked against the voice platform",
  synced: "Read off the voice platform's own list",
};

/**
 * One voice, and the three buttons that move it.
 *
 * The button for the state a voice is ALREADY in is disabled rather than hidden: three
 * controls that appear and disappear as you click them is a row that moves under the
 * pointer, and an operator scanning a column of rows reads a fixed set of affordances
 * faster than a varying one. It is also how the current state is legible a second way.
 */
function VoiceRow({
  voice,
  pending,
  onMove,
}: {
  voice: CuratedVoice;
  pending: boolean;
  onMove: (voice: CuratedVoice, state: CurationState) => void;
}) {
  /* Through `lookup`, never indexed: these keys are wire strings, and a server that grew a
     fourth value must print the bare string rather than mislabel it (`lib/lookup.ts`,
     `tests/wireLookupGuard.test.ts`). */
  const meaning = lookup(CURATION_MEANING, voice.state);
  const tone = lookup(STATE_TONE, voice.state);
  const origin = lookup(ORIGIN_MEANING, voice.origin);
  return (
    <tr className="border-t border-line align-top">
      <td className="py-1.5 pr-3">
        <span className="font-medium">{voice.label}</span>
        <MonoValue className="mt-0.5 block text-[11px]">{voice.voice_id}</MonoValue>
        {voice.withdrawn_at !== null && (
          <span className="mt-0.5 block text-[11px] text-amber-700 dark:text-amber-400">
            {WITHDRAWN_MEANING}
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3">
        {voice.tier_label}
        {/* The VENDOR, on the one console that may name one: an operator reconciling an
            invoice needs it, and a client never sees this screen. */}
        <span className="mt-0.5 block text-[11px] text-ink-faint">{voice.provider}</span>
      </td>
      <td className="py-1.5 pr-3">
        <MonoValue>{voice.tts_model}</MonoValue>
      </td>
      <td className="py-1.5 pr-3">
        {origin ?? <MonoValue>{voice.origin}</MonoValue>}
        {voice.source === "custom" && (
          <span className="mt-0.5 block text-[11px] text-ink-faint">
            A voice we cloned or imported
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3">{voice.languages.join(", ")}</td>
      <td className="py-1.5 pr-3 tabular-nums">
        {formatCount(voice.live_agents)}
        {voice.live_agents > 0 && voice.state === "enabled" && (
          <span className="mt-0.5 block text-[11px] text-ink-faint">
            Disabling or archiving will not affect them &mdash; they keep speaking it.
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3">
        {tone ? (
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${tone}`}
          >
            {voice.state}
          </span>
        ) : (
          <MonoValue>{voice.state}</MonoValue>
        )}
        {meaning && <span className="mt-0.5 block text-[11px] text-ink-faint">{meaning}</span>}
      </td>
      <td className="py-1.5 pr-3">{formatIST(voice.synced_at)}</td>
      <td className="py-1.5 pr-3">
        <div className="flex flex-wrap gap-1">
          {CURATION_ACTIONS.map((action) => (
            <button
              key={action.state}
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={pending || voice.state === action.state}
              onClick={() => onMove(voice, action.state)}
              aria-label={`${action.label} ${voice.label}`}
            >
              {action.label}
            </button>
          ))}
        </div>
      </td>
    </tr>
  );
}
