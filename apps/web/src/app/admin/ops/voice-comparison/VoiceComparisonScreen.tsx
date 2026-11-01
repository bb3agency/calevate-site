"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Download, LoaderCircle, Pause, Play } from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatIST,
} from "@/components/ui";
import {
  MAX_PAIRS,
  MAX_VOICES_PER_PROVIDER,
  downloadRoundCsv,
  pairCount,
  sentenceLines,
  useComparisonClip,
  useComparisonRound,
  useComparisonRounds,
  useComparisonSentences,
  useComparisonSetup,
  useComparisonSummary,
  useComparisonVoices,
  useFinishRound,
  useRateTrial,
  useSetUpSarvam,
  useStartRound,
  type ComparisonCandidate,
  type ComparisonRound,
  type ComparisonTrial,
} from "@/lib/api/opsVoiceComparison";

const PROVIDER_NAME: Record<string, string> = {
  cartesia: "Cartesia",
  sarvam: "Sarvam",
};
const SCORES = [1, 2, 3, 4, 5] as const;

export function VoiceComparisonScreen({ enabled }: { enabled: boolean }) {
  const [roundId, setRoundId] = useState<string | null>(null);
  return (
    <>
      <SetupCard enabled={enabled} />
      {roundId ? (
        <RoundPanel roundId={roundId} onClose={() => setRoundId(null)} />
      ) : (
        <>
          <NewRoundCard enabled={enabled} onStarted={setRoundId} />
          <RoundsCard enabled={enabled} onOpen={setRoundId} />
        </>
      )}
    </>
  );
}

// --- set-up ---------------------------------------------------------------------------

function SetupCard({ enabled }: { enabled: boolean }) {
  const setup = useComparisonSetup(enabled);
  const setUp = useSetUpSarvam();
  const data = setup.data;
  return (
    <Card title="Set-up">
      {setup.error ? (
        <ProblemNotice
          error={setup.error}
          onRetry={() => void setup.refetch()}
        />
      ) : !data ? (
        <Skeleton rows={2} label="Checking the set-up" />
      ) : (
        <div className="space-y-3 text-sm">
          <ul className="space-y-1">
            <li>Sarvam key stored: {data.sarvam_key_stored ? "yes" : "no"}</li>
            <li>Sarvam voices ready: {data.sarvam_ready ? "yes" : "no"}</li>
            <li>Cartesia voices ready: {data.cartesia_ready ? "yes" : "no"}</li>
          </ul>
          {data.steps.length > 0 && (
            <ol className="list-decimal space-y-1 pl-5 text-ink-muted">
              {data.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}
          <p className="text-ink-muted">
            Sarvam gets a workspace of its own on the voice platform, with no
            agents in it.
          </p>
          {setUp.error && <ProblemNotice error={setUp.error} />}
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={!data.sarvam_key_stored || setUp.isPending}
            onClick={() => setUp.mutate()}
          >
            {setUp.isPending ? "Setting up…" : "Set up Sarvam voices"}
          </button>
        </div>
      )}
    </Card>
  );
}

// --- a new round ----------------------------------------------------------------------

function VoicePicks({
  legend,
  voices,
  picked,
  onChange,
}: {
  legend: string;
  voices: ComparisonCandidate[];
  picked: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className={FIELD_LABEL}>{legend}</legend>
      <span className={FIELD_HINT}>Up to {MAX_VOICES_PER_PROVIDER}.</span>
      {voices.length === 0 ? (
        <p className="mt-2 text-sm text-ink-muted">None listed yet.</p>
      ) : (
        <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto">
          {voices.map((voice) => {
            const checked = picked.includes(voice.vendor_id);
            const full = !checked && picked.length >= MAX_VOICES_PER_PROVIDER;
            return (
              <li key={voice.vendor_id}>
                <label className="flex items-center gap-2 text-sm touch:min-h-11">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={full}
                    onChange={() =>
                      onChange(
                        checked
                          ? picked.filter((id) => id !== voice.vendor_id)
                          : [...picked, voice.vendor_id],
                      )
                    }
                  />
                  <span className="min-w-0 break-words">
                    {voice.label}
                    {voice.gender ? (
                      <span className="text-ink-faint"> · {voice.gender}</span>
                    ) : null}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}

function NewRoundCard({
  enabled,
  onStarted,
}: {
  enabled: boolean;
  onStarted: (id: string) => void;
}) {
  const voices = useComparisonVoices(enabled);
  const defaults = useComparisonSentences(enabled);
  const start = useStartRound();
  const [title, setTitle] = useState("");
  const [cartesia, setCartesia] = useState<string[]>([]);
  const [sarvam, setSarvam] = useState<string[]>([]);
  const [text, setText] = useState<string | null>(null);

  // The default sentences fill the box once; after that it is the listener's.
  const sentences = text ?? (defaults.data?.sentences ?? []).join("\n");
  const lines = sentenceLines(sentences);
  const pairs = pairCount(cartesia.length, sarvam.length, lines.length);
  const tooMany = pairs > MAX_PAIRS;
  const canStart =
    cartesia.length > 0 && sarvam.length > 0 && lines.length > 0 && !tooMany;

  return (
    <Card title="New round">
      {voices.error ? (
        <ProblemNotice
          error={voices.error}
          onRetry={() => void voices.refetch()}
        />
      ) : !voices.data ? (
        <Skeleton rows={4} label="Loading the voices" />
      ) : (
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canStart) return;
            start.mutate(
              {
                title,
                language: "te-IN",
                cartesia_voice_ids: cartesia,
                sarvam_voice_ids: sarvam,
                sentences: lines,
              },
              { onSuccess: (round) => onStarted(round.id) },
            );
          }}
        >
          <label className="block">
            <span className={FIELD_LABEL}>Name (optional)</span>
            <input
              className={FIELD}
              value={title}
              maxLength={80}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <div className="grid gap-5 sm:grid-cols-2">
            <VoicePicks
              legend="Cartesia voices"
              voices={voices.data.cartesia}
              picked={cartesia}
              onChange={setCartesia}
            />
            <VoicePicks
              legend="Sarvam voices"
              voices={voices.data.sarvam}
              picked={sarvam}
              onChange={setSarvam}
            />
          </div>
          {voices.data.sarvam_note && (
            <NoticeBox tone="warn" title="Sarvam voices are not listed">
              <p className="mt-1">{voices.data.sarvam_note}</p>
            </NoticeBox>
          )}
          <label className="block">
            <span className={FIELD_LABEL}>Sentences, one per line</span>
            <span className={FIELD_HINT}>
              From our Telugu spoken style. Up to 20, each at most 200
              characters.
            </span>
            <textarea
              className={`${FIELD} min-h-48 resize-y`}
              value={sentences}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <p className="text-sm text-ink-muted" aria-live="polite">
            {pairs} pair{pairs === 1 ? "" : "s"} to rate
            {tooMany
              ? ` — at most ${MAX_PAIRS}. Choose fewer voices or sentences.`
              : "."}
          </p>
          {start.error && <ProblemNotice error={start.error} />}
          <button
            type="submit"
            className={PRIMARY_BUTTON}
            disabled={!canStart || start.isPending}
          >
            {start.isPending ? "Starting…" : "Start the round"}
          </button>
        </form>
      )}
    </Card>
  );
}

function RoundsCard({
  enabled,
  onOpen,
}: {
  enabled: boolean;
  onOpen: (id: string) => void;
}) {
  const rounds = useComparisonRounds(enabled);
  return (
    <Card title="Rounds">
      {rounds.error ? (
        <ProblemNotice
          error={rounds.error}
          onRetry={() => void rounds.refetch()}
        />
      ) : !rounds.data ? (
        <Skeleton rows={2} label="Loading the rounds" />
      ) : rounds.data.rounds.length === 0 ? (
        <p className="text-sm text-ink-muted">No rounds yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {rounds.data.rounds.map((round) => (
            <li
              key={round.id}
              className="flex flex-wrap items-center justify-between gap-2 py-2"
            >
              <span className="min-w-0 break-words text-sm">
                {round.title}{" "}
                <span className="text-ink-faint">
                  · {formatIST(round.created_at)} · {round.rated} of{" "}
                  {round.pairs} rated
                  {round.finished_at ? " · finished" : ""}
                </span>
              </span>
              <button
                type="button"
                className={SECONDARY_BUTTON}
                onClick={() => onOpen(round.id)}
              >
                Open
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --- listening --------------------------------------------------------------------------

/** The one clip playing: pressing play on the other side pauses the first. */
let playing: HTMLAudioElement | null = null;

function ClipButton({ trialId, side }: { trialId: string; side: "a" | "b" }) {
  const name = side === "a" ? "Voice A" : "Voice B";
  const [requested, setRequested] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const clip = useComparisonClip(trialId, side, requested);

  useEffect(() => {
    if (!clip.data) return;
    const url = URL.createObjectURL(clip.data);
    setSrc(url);
    return () => {
      URL.revokeObjectURL(url);
      setSrc(null);
    };
  }, [clip.data]);

  useEffect(() => {
    const element = audio.current;
    if (src && element && requested) {
      if (playing && playing !== element) playing.pause();
      playing = element;
      void element.play().catch(() => setIsPlaying(false));
    }
  }, [src, requested]);

  function toggle() {
    const element = audio.current;
    if (!requested) {
      setRequested(true);
      return;
    }
    // A failed load leaves the element with no source, so play() would reject silently.
    if (clip.error) {
      void clip.refetch();
      return;
    }
    if (!element) return;
    if (element.paused) {
      if (playing && playing !== element) playing.pause();
      playing = element;
      void element.play().catch(() => setIsPlaying(false));
    } else {
      element.pause();
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className={SECONDARY_BUTTON}
        aria-label={`${isPlaying ? "Pause" : "Play"} ${name}`}
        onClick={toggle}
        disabled={clip.isFetching}
      >
        {clip.isFetching ? (
          <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
        ) : isPlaying ? (
          <Pause aria-hidden className="h-4 w-4" />
        ) : (
          <Play aria-hidden className="h-4 w-4" />
        )}
        {name}
      </button>
      {clip.error && (
        <span className="text-xs text-danger" role="alert">
          Could not load {name}. Press it to try again.
        </span>
      )}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- The clip exists to be HEARD:
          how the voice sounds is a sensory experience no caption carries (WCAG 1.2.1's
          sensory exception); the words spoken are printed above it. */}
      <audio
        ref={audio}
        src={src ?? undefined}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
      />
    </div>
  );
}

function ScoreChoice({
  name,
  legend,
  value,
  onChange,
}: {
  name: string;
  legend: string;
  value: number | null;
  onChange: (score: number) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className={FIELD_LABEL}>{legend}</legend>
      <div className="mt-1 flex flex-wrap gap-3">
        {SCORES.map((score) => (
          <label
            key={score}
            className="flex items-center gap-1 text-sm touch:min-h-11"
          >
            <input
              type="radio"
              name={name}
              checked={value === score}
              onChange={() => onChange(score)}
            />
            {score}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function PairCard({
  roundId,
  trial,
  total,
  onSaved,
}: {
  roundId: string;
  trial: ComparisonTrial;
  total: number;
  onSaved: () => void;
}) {
  const rate = useRateTrial(roundId);
  const [a, setA] = useState<number | null>(trial.rating_a);
  const [b, setB] = useState<number | null>(trial.rating_b);
  const [preference, setPreference] = useState<"a" | "b" | "none" | null>(
    trial.preference,
  );
  const complete = a !== null && b !== null && preference !== null;

  return (
    <section aria-labelledby={`pair-${trial.id}`} className="space-y-4">
      <h3 id={`pair-${trial.id}`} className="text-sm font-semibold">
        Pair {trial.position} of {total}
      </h3>
      <p
        lang="te"
        className="break-words rounded-md bg-ink/[0.03] p-3 text-base"
      >
        {trial.sentence}
      </p>
      <div className="flex flex-col gap-4 sm:flex-row sm:gap-8">
        <div className="space-y-2">
          <ClipButton trialId={trial.id} side="a" />
          <ScoreChoice
            name={`a-${trial.id}`}
            legend="Voice A: how natural?"
            value={a}
            onChange={setA}
          />
        </div>
        <div className="space-y-2">
          <ClipButton trialId={trial.id} side="b" />
          <ScoreChoice
            name={`b-${trial.id}`}
            legend="Voice B: how natural?"
            value={b}
            onChange={setB}
          />
        </div>
      </div>
      <fieldset className="min-w-0">
        <legend className={FIELD_LABEL}>
          Which would you rather a caller heard?
        </legend>
        <div className="mt-1 flex flex-wrap gap-4">
          {(
            [
              ["a", "Voice A"],
              ["b", "Voice B"],
              ["none", "No preference"],
            ] as const
          ).map(([value, label]) => (
            <label
              key={value}
              className="flex items-center gap-1 text-sm touch:min-h-11"
            >
              <input
                type="radio"
                name={`pref-${trial.id}`}
                checked={preference === value}
                onChange={() => setPreference(value)}
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <span className={FIELD_HINT}>1 is robotic, 5 sounds like a person.</span>
      {rate.error && <ProblemNotice error={rate.error} />}
      <button
        type="button"
        className={PRIMARY_BUTTON}
        disabled={!complete || rate.isPending}
        onClick={() => {
          if (a === null || b === null || preference === null) return;
          rate.mutate(
            {
              trialId: trial.id,
              body: { rating_a: a, rating_b: b, preference },
            },
            { onSuccess: onSaved },
          );
        }}
      >
        {rate.isPending ? "Saving…" : "Save and next"}
      </button>
    </section>
  );
}

function RoundPanel({
  roundId,
  onClose,
}: {
  roundId: string;
  onClose: () => void;
}) {
  const round = useComparisonRound(roundId);
  const finish = useFinishRound(roundId);
  const [index, setIndex] = useState<number | null>(null);
  const data = round.data;

  // Open on the first pair not yet rated.
  const firstOpen = useMemo(
    () =>
      data
        ? Math.max(
            0,
            data.trials.findIndex((t) => !t.rated),
          )
        : 0,
    [data],
  );
  const current = data?.trials[index ?? firstOpen];

  return (
    <Card
      title={data?.title ?? "Round"}
      action={
        <button type="button" className={SECONDARY_BUTTON} onClick={onClose}>
          Back to rounds
        </button>
      }
    >
      {round.error ? (
        <ProblemNotice
          error={round.error}
          onRetry={() => void round.refetch()}
        />
      ) : !data ? (
        <Skeleton rows={4} label="Loading the round" />
      ) : data.finished_at ? (
        <Reveal round={data} />
      ) : (
        <div className="space-y-6">
          <p className="text-sm text-ink-muted" aria-live="polite">
            {data.rated} of {data.pairs} rated. {data.cartesia_voices} Cartesia
            and {data.sarvam_voices} Sarvam voice(s); which is which stays
            hidden until you finish.
          </p>
          {current && (
            <PairCard
              key={current.id}
              roundId={roundId}
              trial={current}
              total={data.pairs}
              onSaved={() => {
                const next = (index ?? firstOpen) + 1;
                setIndex(next < data.pairs ? next : (index ?? firstOpen));
              }}
            />
          )}
          <nav aria-label="Pairs" className="flex flex-wrap gap-2">
            {data.trials.map((trial, i) => (
              <button
                key={trial.id}
                type="button"
                aria-current={trial.id === current?.id ? "true" : undefined}
                aria-label={`Pair ${trial.position}${trial.rated ? ", rated" : ""}`}
                className={`h-9 min-w-9 rounded-md border px-2 text-xs touch:h-11 touch:min-w-11 ${
                  trial.id === current?.id
                    ? "border-brand text-ink"
                    : trial.rated
                      ? "border-line bg-ink/[0.05] text-ink-muted"
                      : "border-line text-ink"
                }`}
                onClick={() => setIndex(i)}
              >
                {trial.position}
              </button>
            ))}
          </nav>
          {finish.error && <ProblemNotice error={finish.error} />}
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={data.rated < data.pairs || finish.isPending}
            onClick={() => finish.mutate()}
          >
            {finish.isPending ? "Finishing…" : "Finish and show providers"}
          </button>
        </div>
      )}
    </Card>
  );
}

// --- the reveal -----------------------------------------------------------------------

function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

function Reveal({ round }: { round: ComparisonRound }) {
  const summary = useComparisonSummary(round.id, true);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const data = summary.data;
  if (summary.error) {
    return (
      <ProblemNotice
        error={summary.error}
        onRetry={() => void summary.refetch()}
      />
    );
  }
  if (!data) return <Skeleton rows={4} label="Loading the results" />;
  return (
    <div className="space-y-6 text-sm">
      <ul className="space-y-2">
        {data.providers.map((p) => (
          <li key={p.provider}>
            <strong>{PROVIDER_NAME[p.provider]}</strong>: naturalness{" "}
            {score(p.mean_naturalness)} of 5, preferred in {p.preferred} of{" "}
            {data.pairs} pairs · {p.characters} characters spoken
          </li>
        ))}
        <li>No preference: {data.no_preference}</li>
      </ul>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <caption className="sr-only">Each voice, revealed</caption>
          <thead>
            <tr className="text-xs text-ink-muted">
              <th scope="col" className="py-1 pr-3">
                Voice
              </th>
              <th scope="col" className="py-1 pr-3">
                Provider
              </th>
              <th scope="col" className="py-1 pr-3">
                Naturalness
              </th>
              <th scope="col" className="py-1">
                Preferred
              </th>
            </tr>
          </thead>
          <tbody>
            {data.voices.map((v) => (
              <tr
                key={`${v.provider}-${v.vendor_id}`}
                className="border-t border-line"
              >
                <td className="py-1 pr-3 break-words">{v.label}</td>
                <td className="py-1 pr-3">{PROVIDER_NAME[v.provider]}</td>
                <td className="py-1 pr-3">{score(v.mean_naturalness)}</td>
                <td className="py-1">
                  {v.preferred} of {v.heard}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-ink-muted">{data.cost_note}</p>
      {downloadError ? <ProblemNotice error={downloadError} /> : null}
      <button
        type="button"
        className={SECONDARY_BUTTON}
        onClick={() => {
          setDownloadError(null);
          downloadRoundCsv(round.id).catch(setDownloadError);
        }}
      >
        <Download aria-hidden className="h-4 w-4" />
        Download CSV
      </button>
    </div>
  );
}
