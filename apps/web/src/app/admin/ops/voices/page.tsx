"use client";

import { useState } from "react";
import { AudioLines, RefreshCw, TriangleAlert } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import {
  Card,
  EmptyState,
  NoticeBox,
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
  ADD_A_VOICE,
  CURATION_ACTIONS,
  CURATION_MEANING,
  WITHDRAWN_MEANING,
  useCuratedVoices,
  useRefreshVoiceCatalogue,
  useSetVoiceCuration,
  type CuratedVoice,
  type CuratedVoices,
  type CurationState,
} from "@/lib/api/opsVoices";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { lookup } from "@/lib/lookup";

/**
 * WHICH VOICES THIS PLATFORM OFFERS — the console half of D-588.
 *
 * ## What this screen is, and the button it deliberately does not have
 *
 * The founder asked to "add, delete and archive voices end to end" here, with only the
 * voices added here being selectable by clients and by admins. Half of that is not
 * buildable and the reason is the vendor's API rather than our time: **the voice
 * platform's API is READ-ONLY** — two GET routes, and no create, update or delete for a
 * voice anywhere in it. A voice is ADDED in that platform's own Playground, by importing a
 * voice id or cloning a 1-2 minute sample.
 *
 * So this screen is the CURATION layer over the sync: every voice the platform offers our
 * account is listed, and the operator says which of them anybody may be put on. That
 * delivers the half that actually matters — *only what I enable is selectable* — and
 * `ADD_A_VOICE` is printed at the top where another console would put an Add button,
 * because an operator hunting for one is an operator we sent to the wrong product.
 *
 * ## Three things this screen refuses to compute
 *
 * 1. **Whether a voice is offered.** `offered` is the server's field: `state === "enabled"`
 *    AND still listed by the platform. A browser composing it from two columns would get
 *    the withdrawn case wrong, which is the case that matters — an enabled voice the vendor
 *    dropped is not offered and no click here changes that.
 * 2. **The counts.** `offered` and the row count come off the wire; the empty-state
 *    sentence is `note`, composed on the server. A screen that paraphrased "synced but
 *    nothing enabled" as "no voices" is how a working platform gets reported as broken.
 * 3. **What archiving does to a live agent.** The row shows the server's `live_agents`, and
 *    the confirmation sentence after a write is the server's `next_step`. Nothing here
 *    infers consequences.
 *
 * ## Archiving is allowed with agents on the voice, and the screen says so
 *
 * It cannot break a call: no agent row is touched, a published agent holds its voice on the
 * engine, and the id keeps resolving on the publish path. Refusing would instead make a
 * vendor's own withdrawal unfileable — the voice is gone from their platform whatever our
 * table says. So the count is shown BEFORE the click and the consequence is stated after
 * it, rather than the decision being taken away from the operator.
 *
 * ## §52 without exception
 *
 * Loading is a skeleton, a failed read is a refusal, and neither is "no voices" — which on
 * this screen is a real and meaningful state with two distinct causes, and the one thing a
 * transport failure must never be painted as.
 *
 * ## Permission
 *
 * `ops:manage`, which only `superadmin` holds (`core/rbac.py`), asked of `GET /v1/admin/me`
 * rather than derived from this screen's own 403 — and it gates the READ, because this
 * whole screen is one GET plus two writes behind the same permission, so a session the
 * server refuses has nothing left to look at. It is still a PREVIEW and never the
 * enforcement: the query runs on `!access.refused` (the unknown), so a slow or dead
 * `/v1/admin/me` cannot lock an operator out of a read the API would have served.
 *
 * No `<h1>`: the shell derives the title from the nav list it also renders the sidebar from
 * (`app/admin/layout.tsx`).
 */
export default function VoicesPage() {
  const access = useAdminAccess("ops:manage", "curate the voices this platform offers");
  const voices = useCuratedVoices(!access.refused);
  const curate = useSetVoiceCuration();
  const refresh = useRefreshVoiceCatalogue();
  /** Which row a write is in flight for — so one button spins, not all of them. */
  const [pending, setPending] = useState<string | null>(null);

  const data = voices.data;
  useCopilotSurface({
    route: "/admin/ops/voices",
    title: "Voices",
    realm: "admin",
    fields: [],
    // NOTHING ON THIS SCREEN IS FILLABLE BY THE ASSISTANT, AND THAT IS DELIBERATE. Its
    // only controls are Refresh and three curation verbs, and every one of them is a
    // platform-wide decision about what every client may choose — an act an operator makes
    // with the live-agent count in front of them, not one a model completes on their
    // behalf. `fields` is empty and `apply` is a no-op for that reason rather than because
    // nobody wired it.
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
              key: "source",
              label: "Has the voice platform's catalogue been read on this deployment",
              value: data.source === "engine" ? "yes" : "no — nobody has synced it",
            },
            {
              key: "offered",
              label: "Voices any client or admin can currently choose",
              value: String(data.offered),
            },
            {
              key: "cached",
              label: "Voices in the cache",
              value: String(data.voices.length),
            },
            {
              key: "withdrawn",
              label: "Voices the platform has stopped listing",
              value: String(data.voices.filter((row) => row.withdrawn_at !== null).length),
            },
            {
              key: "adding",
              label: "How a NEW voice is added",
              value: ADD_A_VOICE,
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
        Every voice the voice platform offers our account. Only the ones you enable here can
        be chosen for an agent &mdash; by a client for their own agent, or by an admin for
        anyone&rsquo;s.
      </p>

      {access.refused ? (
        /* The refusal INSTEAD of the table, never beside it: a row of dead buttons over a
           red "we could not read this" box describes an outage, and this is a permission
           working exactly as designed. */
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          <NoticeBox
            tone="neutral"
            icon={<AudioLines aria-hidden className="h-5 w-5" />}
            title="Adding a new voice happens on the voice platform, not here"
          >
            <p className="mt-1">{ADD_A_VOICE}</p>
          </NoticeBox>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={refresh.isPending}
              onClick={() => void refresh.mutateAsync().catch(() => undefined)}
            >
              <RefreshCw aria-hidden className="mr-1.5 inline h-3.5 w-3.5" />
              {refresh.isPending ? "Reading the voice platform…" : "Refresh"}
            </button>
            <span className="text-xs text-ink-faint">
              Re-reads the voice platform&rsquo;s own list. A newly seen voice arrives
              disabled.
            </span>
          </div>

          {/* A MUTATION's `data` is the user having asked, so rendering it is correct —
              `surfaceStatesGuard` exempts the mutation envelope for exactly this. The
              server's own sentence, printed verbatim: a partial or refused sync is a fact
              the operator has to see, and paraphrasing it is how "the catalogue is up to
              date" becomes a support ticket. */}
          {refresh.data && (
            <NoticeBox tone="neutral" title="The voice platform's catalogue was re-read">
              <p className="mt-1">{refresh.data.note}</p>
            </NoticeBox>
          )}
          {refresh.error != null && <ProblemNotice error={refresh.error} />}
          {curate.error != null && <ProblemNotice error={curate.error} />}
          {curate.data && (
            <NoticeBox tone="neutral" title={`${curate.data.voice.label} updated`}>
              <p className="mt-1">{curate.data.next_step}</p>
            </NoticeBox>
          )}

          {voices.error != null && (
            <ProblemNotice error={voices.error} onRetry={() => void voices.refetch()} />
          )}

          {/* §52. `!voices.data` covers all three ways to have no answer — in flight,
              failed, and the paused query a console tab open across a dropped connection
              produces. Only the first gets a skeleton; the other two are answered above. */}
          {!voices.data ? (
            voices.error ? null : (
              <Card>
                <Skeleton rows={6} label="Loading the voices this platform offers" />
              </Card>
            )
          ) : (
            <Catalogue
              catalogue={voices.data}
              pending={pending}
              onMove={(voice, state) => void move(voice, state)}
            />
          )}
        </>
      )}
    </div>
  );
}

/**
 * The catalogue, given one that ARRIVED.
 *
 * Takes the payload rather than the query envelope for the reason every board in this
 * console does: each sentence below is a claim about what this platform offers, and a
 * component that cannot see `undefined` cannot accidentally make one out of it.
 */
function Catalogue({
  catalogue,
  pending,
  onMove,
}: {
  catalogue: CuratedVoices;
  pending: string | null;
  onMove: (voice: CuratedVoice, state: CurationState) => void;
}) {
  const withdrawn = catalogue.voices.filter((row) => row.withdrawn_at !== null).length;
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
          label="In the cache"
          value={formatCount(catalogue.voices.length)}
          hint="Voices read from the voice platform, whatever state they are in here."
        />
        <StatTile
          label="Dropped by the platform"
          value={formatCount(withdrawn)}
          tone={withdrawn > 0 ? "strong" : undefined}
          icon={withdrawn > 0 ? <TriangleAlert aria-hidden className="h-5 w-5" /> : undefined}
          hint="Voices the platform has stopped listing on our account. They cannot be offered, and nothing here restores them."
        />
        <StatTile
          label="Catalogue read"
          value={catalogue.source === "engine" ? "Yes" : "Never"}
          hint="Whether this deployment has ever read the voice platform's own list."
        />
      </div>

      {/* ZERO OFFERED IS A STATE WITH TWO CAUSES, and the server's sentence says which.
          It sits above the table because it changes how the table should be read, and it
          is rendered as a notice rather than an empty state because the table is NOT
          empty in the second case — every voice is there, switched off. */}
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
            title="No voices have been read from the voice platform"
            hint="Press Refresh above to read the voice platform's own list for our account, then enable the voices this platform should offer. If Refresh reports nothing, the voice platform credential is the first thing to check."
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
                  <HeadCell label="Origin" gloss="Stock voice, or one we imported or cloned" />
                  <HeadCell label="Languages" />
                  <HeadCell label="Live agents" gloss="Across every client, now" />
                  <HeadCell label="State" />
                  <HeadCell label="Last read" gloss="When we last saw it on the platform" />
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
 * The map's own docstring names "a one-line badge, a table cell" as the legitimate use of
 * the classes without the component, which is exactly this — `StatusBadge` is for a LEAD or
 * CALL status and its vocabulary is not ours. Keyed by the WIRE string and read through
 * `lookup`, so a server that grew a fourth state prints the bare value rather than being
 * mislabelled as one of these three.
 */
const STATE_TONE: Record<string, string> = {
  enabled: NOTICE_TONES.ok,
  disabled: NOTICE_TONES.neutral,
  archived: NOTICE_TONES.warn,
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
     fourth state must print the bare value rather than mislabel it as one of these three
     (`lib/lookup.ts`, `tests/wireLookupGuard.test.ts`). */
  const meaning = lookup(CURATION_MEANING, voice.state);
  const tone = lookup(STATE_TONE, voice.state);
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
        {voice.source === "custom" ? "Imported or cloned by us" : "Stock voice"}
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
        {meaning && (
          <span className="mt-0.5 block text-[11px] text-ink-faint">{meaning}</span>
        )}
        {voice.curated_at === null && (
          <span className="mt-0.5 block text-[11px] text-ink-faint">Never reviewed.</span>
        )}
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
