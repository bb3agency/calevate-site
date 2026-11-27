"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ArrowRight, Check, Lightbulb, Plus } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { PipMark } from "@/components/illustration/pip";
import { FIELD, FIELD_INLINE, ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import { VoiceButton } from "@/components/voiceButton";
import { useAgentLanguages } from "@/lib/api/agentLanguages";
import { useBusinessCopy } from "@/lib/api/businessCopy";
import {
  isRecordingBusy,
  useRecordBrief,
  useRecording,
  useSaveBrief,
  type FirstRun,
} from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { businessLanguage } from "@/lib/businessCapabilities";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import {
  FIRST_WORKS,
  briefWaitingFor,
  holdCardPick,
  isFirstWorkJob,
  jobCard,
  jobFromBrief,
  languageLabel,
  languageShortLabel,
  readCardPick,
  type FirstWorkJob,
  type JobCard,
} from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useBriefExamples, useVerticalExamples, type BriefExample } from "@/lib/useVerticalExamples";

import { AddFileButton, BriefDocumentList, BriefFileDrop, FilesWhy, useBriefDocuments } from "./BriefDocuments";
import { StepScreen } from "./shell";
import { FIRST } from "../../_ui/copy";
import { Why } from "@/components/why";
import { BRIEF_MAX_CHARS } from "@/lib/textLimits";

export const HEARD_FAILURES: Record<string, string> = {
  voice_unreadable: "Couldn't make that out. Try somewhere quieter.",
  nothing_heard: "No words heard. Hold the phone closer.",
};

/** The card's question, which also names the box. */
export const BRIEF_TITLE = "What should your agent do?";

/**
 * STEP 1, THE FIRST CARD (D-855; one card since the redesign of 28 Nov 2026, PLAN §5): the
 * owner's own words about the business, the language it speaks first, and what it does
 * first, on one card, so the owner says what they want once instead of over two screens.
 *
 * The box starts filled with the account's own AI-written brief once that exists, so the
 * owner edits rather than faces a blank box. Before it lands the box starts empty with the
 * neutral example only as a placeholder: an example kept as the box's value was saved on
 * Continue as if the owner had written it. The microphone takes up to three pieces of 30
 * seconds; each one's words are added to the box once heard, for the owner to correct, and
 * the audio is deleted as soon as it is heard. Files (a price list, a menu) are added beside
 * the words or instead of them, by the button or by dropping one on the card.
 *
 * Only the brief is saved on Continue. The job and a changed language are held in the
 * browser (`holdCardPick`) and sent after the agent is made; see `CardPick` for why.
 */
export function BriefStep({
  run,
  slug,
  startLanguage,
  draft,
  onDraft,
  onDone,
  onPip,
  pipOff,
}: {
  run: FirstRun;
  slug: string;
  /** The profile's first offered language, or null before the profile has been read. */
  startLanguage: string | null;
  /** What was in the box when the step was last left unsaved (Pip), or null. The screen
   *  holds it, because this step unmounts on every move away; the spoken pieces in it used
   *  up recordings that cannot be taken again. */
  draft: string | null;
  onDraft: (draft: string | null) => void;
  onDone: () => void;
  onPip: () => void;
  /** Why Pip cannot be used here, or null when it can. */
  pipOff: string | null;
}) {
  const session = useClientSession();
  const examples = useVerticalExamples();
  const copy = useBusinessCopy(session).data;
  const languages = useAgentLanguages(session);
  const ownBrief = copy?.placeholders?.script_brief?.trim() || null;
  const save = useSaveBrief(session);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const titleId = useId();
  const box = useRef<HTMLTextAreaElement>(null);
  const [brief, setBrief] = useState<string | null>(draft ?? run.brief);
  // What the box showed when the owner first put the cursor in it (`adopt`): until they
  // change it, it is the account's own brief, not unsaved typing.
  const [seed, setSeed] = useState<string | null>(null);
  const unsaved = brief !== null && brief !== seed && brief.trim() !== (run.brief ?? "").trim();
  // The screen is told what was typed only when this step goes away, not on every key: a
  // keystroke that re-rendered the whole screen (the card, the meter, the rail) made fast
  // typing on a slow phone the most expensive thing on the page.
  const leaving = useRef<string | null>(null);
  leaving.current = unsaved ? brief : null;
  useEffect(() => () => onDraft(leaving.current), [onDraft]);
  // A reload or a closed tab would lose it too.
  useUnsavedGuard(unsaved);
  const [sending, setSending] = useState(false);
  const [hearing, setHearing] = useState(false);
  const files = useBriefDocuments(run, setSending);

  // The account's own brief fills the box only while the owner has not touched it. It is
  // written by a job after sign-up and can land seconds into the step; once the box has
  // focus, what it shows is fixed as the owner's (`adopt`), so a late brief never lands
  // in front of what they are typing.
  const text = brief ?? ownBrief ?? "";
  const adopt = () => {
    if (brief !== null) return;
    setBrief(text);
    setSeed(text);
  };
  const fromDetails = ownBrief !== null && text === ownBrief && (brief === null || brief === seed);
  /** Added to what the box SHOWS: before the owner types, that is the account's own written
   *  brief, which `brief` (still null) does not hold. */
  const append = (words: string) =>
    setBrief((current) => [(current ?? ownBrief ?? "").trim(), words.trim()].filter(Boolean).join("\n"));

  const [held, setHeld] = useState(() => readCardPick(slug));
  const serverJob = isFirstWorkJob(run.jobs[0]) ? run.jobs[0] : null;
  const picked = held.job ?? serverJob;
  // Until the owner picks, the job the brief plainly asks for is ticked, and follows the box.
  const suggested = picked === null ? jobFromBrief(text) : null;
  const job = picked ?? suggested;
  const pickJob = (next: FirstWorkJob) => setHeld(holdCardPick(slug, { job: next }));

  // `choices` is never empty (the three every account has while the server's list loads).
  const language =
    held.language ?? run.language_primary ?? startLanguage ?? businessLanguage(copy?.language, languages.tags) ?? "";
  const pickLanguage = (next: string) => setHeld(holdCardPick(slug, { language: next }));

  const waitingFor = briefWaitingFor({ documents: run.documents, sending, hearing, noJob: job === null });
  const submit = () => {
    if (job === null) return;
    holdCardPick(slug, { job });
    save.mutate({ brief: text.trim() }, { onSuccess: onDone });
  };

  return (
    <div onDragOver={(event) => event.preventDefault()} onDrop={files.onDrop}>
      <StepScreen
        framed
        title={BRIEF_TITLE}
        titleId={titleId}
        titleAside={<LanguagePick value={language} choices={languages.choices} onChange={pickLanguage} />}
        hint={
          <>
            {FIRST.briefHint}{" "}
            <Why inline>Use your own words. Pip trains your agents from this and writes the script for your first calls.</Why>
          </>
        }
        primary={
          <>
            Continue
            <ArrowRight aria-hidden className="h-4 w-4" />
          </>
        }
        status={saveFeedback.status}
        waitingFor={waitingFor}
        onSubmit={submit}
        aside={
          pipOff === null ? (
            <button type="button" className={TEXT_ACTION} onClick={onPip}>
              <PipMark size={16} className="shrink-0" />
              Talk it through with {ASSISTANT_NAME} instead
            </button>
          ) : null
        }
      >
        <div>
          <textarea
            ref={box}
            aria-labelledby={titleId}
            value={text}
            maxLength={BRIEF_MAX_CHARS}
            placeholder={examples.scriptBrief}
            onFocus={adopt}
            onChange={(event) => setBrief(event.target.value)}
            rows={5}
            className={`${FIELD} mt-0 w-full resize-y text-[16px] leading-relaxed`}
          />
          <p className="mt-1 flex justify-between gap-3 text-meta text-ink-faint">
            <span>{fromDetails ? "Written from your business details. Change anything." : ""}</span>
            <span className="tabular-nums">
              {Array.from(text).length} of {BRIEF_MAX_CHARS}
            </span>
          </p>
        </div>

        <BriefTools
          run={run}
          language={language}
          files={files}
          text={text}
          onHeard={append}
          onExample={append}
          onTypeInstead={() => box.current?.focus()}
          onHearing={setHearing}
        />

        <BriefDocumentList files={files} />

        <JobPick job={job} suggested={suggested !== null} onPick={pickJob} />

        {pipOff !== null ? <p className="text-meta text-ink-muted">{pipOff}</p> : null}
        {save.error ? <ProblemNotice error={save.error} /> : null}
      </StepScreen>
    </div>
  );
}

/** The language it speaks first, on the card's title line. The agent's step starts from it. */
function LanguagePick({
  value,
  choices,
  onChange,
}: {
  value: string;
  choices: readonly { value: string }[];
  onChange: (tag: string) => void;
}) {
  const id = useId();
  // A held or saved language the server no longer offers stays shown rather than jumping.
  const options = choices.some((choice) => choice.value === value) || value === "" ? choices : [{ value }, ...choices];
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-meta text-ink-muted">
        Speaks first in
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`${FIELD_INLINE} py-1 pr-7 text-[16px] sm:text-sm`}
      >
        {options.map((choice) => (
          <option key={choice.value} value={choice.value} lang={choice.value}>
            {languageShortLabel(choice.value)}
          </option>
        ))}
      </select>
    </div>
  );
}

/** The card's one row of tools: speak it, add a file, and the account's own examples. */
function BriefTools({
  run,
  language,
  files,
  text,
  onHeard,
  onExample,
  onTypeInstead,
  onHearing,
}: {
  run: FirstRun;
  language: string;
  files: ReturnType<typeof useBriefDocuments>;
  text: string;
  onHeard: (words: string) => void;
  onExample: (words: string) => void;
  onTypeInstead: () => void;
  onHearing: (busy: boolean) => void;
}) {
  const examples = useBriefExamples();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SpokenBrief
          language={language}
          piecesLeft={run.recordings_left}
          onHeard={onHeard}
          onTypeInstead={onTypeInstead}
          onBusy={onHearing}
        />
        <AddFileButton files={files} />
        {examples.length > 0 ? (
          <button
            type="button"
            className={SECONDARY_BUTTON}
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((was) => !was)}
          >
            <Lightbulb aria-hidden className="h-4 w-4" />
            Examples
          </button>
        ) : null}
      </div>
      <p className="text-meta text-ink-faint">
        {run.recordings_left > 0 ? FIRST.sayIt(languageLabel(language), run.recordings_left) : FIRST.briefDone}{" "}
        {FIRST.audioNotKept} <FilesWhy run={run} />
      </p>
      <BriefFileDrop files={files} />
      {open && examples.length > 0 ? (
        <ExampleList id={panelId} examples={examples} text={text} onPick={onExample} />
      ) : null}
    </div>
  );
}

/** The account's own example sentences; each one tapped is added to the box, once. */
function ExampleList({
  id,
  examples,
  text,
  onPick,
}: {
  id: string;
  examples: readonly BriefExample[];
  text: string;
  onPick: (words: string) => void;
}) {
  return (
    <ul id={id} aria-label="Examples for your business" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {examples.map((example) => {
        const inBox = text.includes(example.text);
        return (
          <li key={example.id}>
            <button
              type="button"
              disabled={inBox}
              onClick={() => onPick(example.text)}
              className={`press flex h-full w-full items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors duration-(--duration-fast) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-default ${
                inBox ? "border-line bg-surface-muted" : "border-line bg-surface hover:border-ink-faint"
              }`}
            >
              {inBox ? (
                <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong" />
              ) : (
                <Plus aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" />
              )}
              <span className="min-w-0">
                <span className="block text-meta font-medium text-ink">
                  {example.label}
                  {inBox ? <span className="font-normal text-ink-muted"> · in the box</span> : null}
                </span>
                <span className="line-clamp-2 block text-meta text-ink-muted">{example.text}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** What it does first: two rows, each with its job as three small pictures. */
function JobPick({
  job,
  suggested,
  onPick,
}: {
  job: FirstWorkJob | null;
  suggested: boolean;
  onPick: (job: FirstWorkJob) => void;
}) {
  return (
    <fieldset>
      <legend className="text-body font-medium text-ink">What it does first</legend>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {FIRST_WORKS.map((entry) => {
          const card = jobCard(entry);
          return card ? <JobRow key={entry} card={card} checked={job === entry} onChange={() => onPick(entry)} /> : null;
        })}
      </div>
      {suggested ? <p className="mt-2 text-meta text-ink-muted">{FIRST.workSuggested}</p> : null}
    </fieldset>
  );
}

function JobRow({ card, checked, onChange }: { card: JobCard; checked: boolean; onChange: () => void }) {
  const Icon = card.icon;
  return (
    <label
      className={`press flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1.5 rounded-card border px-3 py-2.5 transition-[border-color,box-shadow] duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app ${
        checked ? CHOICE_ON : CHOICE_OFF
      }`}
    >
      <input type="radio" name="first-job" value={card.job} checked={checked} onChange={onChange} className="sr-only" />
      <span
        aria-hidden
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg transition-colors duration-(--duration-fast) ${
          checked ? "bg-brand-strong text-white" : "bg-brand-soft text-brand-strong"
        }`}
      >
        <Icon className="h-4 w-4" strokeWidth={1.75} />
      </span>
      <span className="min-w-0 text-body font-semibold text-ink">{card.title}</span>
      {/* The pictures say the job's line again, so they are hidden from the radio's name. */}
      <span aria-hidden className="flex basis-full flex-wrap items-center gap-1">
        {/* No arrows between them: in half a card the three wrap, and an arrow left at the
            start of a line reads as a fourth step. */}
        {card.flow.map((link) => {
          const LinkIcon = link.icon;
          return (
            <span
              key={link.label}
              className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-1.5 py-px text-[11px] leading-5 text-ink-muted"
            >
              <LinkIcon className="h-3 w-3 shrink-0 text-brand-strong" />
              {link.label}
            </span>
          );
        })}
      </span>
    </label>
  );
}

/**
 * The microphone: up to three pieces, each heard in turn. The words go into the box; the
 * owner reads and corrects them there.
 */
function SpokenBrief({
  language,
  piecesLeft,
  onHeard,
  onTypeInstead,
  onBusy,
}: {
  language: string;
  piecesLeft: number;
  onHeard: (words: string) => void;
  onTypeInstead: () => void;
  /** Whether a piece is still being turned into words, for the step's Continue. */
  onBusy: (busy: boolean) => void;
}) {
  const session = useClientSession();
  const record = useRecordBrief(session);
  // The working line and "Added to the box" below are this action's pending and success.
  useActionFeedback(record, { errorDisplay: "inline" });
  const [current, setCurrent] = useState<string | null>(null);
  const heard = useRecording(session, current);
  const added = useRef(new Set<string>());
  const status = heard.data?.status;

  useEffect(() => {
    const data = heard.data;
    if (!data || data.status !== "heard" || !data.words || added.current.has(data.id)) return;
    added.current.add(data.id);
    onHeard(data.words);
  }, [heard.data, onHeard]);

  const busy = record.isPending || isRecordingBusy(status);
  useEffect(() => onBusy(busy), [busy, onBusy]);
  return (
    <>
      {piecesLeft > 0 ? (
        <VoiceButton
          label={current === null ? "Say it" : "Say more"}
          why="Tell your agent about your business. Your browser will ask to use the microphone; choose Allow."
          disabled={busy}
          onRecorded={(audio) => record.mutate({ audio, language }, { onSuccess: (started) => setCurrent(started.id) })}
          onTypeInstead={onTypeInstead}
        />
      ) : null}
      {busy ? (
        <span role="status" className="text-meta text-ink-muted">
          <span className="text-shimmer">Turning your words into text…</span>
        </span>
      ) : status === "heard" ? (
        <span role="status" className="inline-flex items-center gap-1 text-meta text-ink-muted">
          <Check aria-hidden className="h-3.5 w-3.5 text-brand-strong" />
          Added to the box
        </span>
      ) : null}
      {status === "failed" ? (
        <p role="alert" className="basis-full text-meta text-ink">
          {lookup(HEARD_FAILURES, heard.data?.error_code ?? "") ?? "Couldn't hear that. Type it instead."}
        </p>
      ) : null}
      {record.error ? (
        <div className="basis-full">
          <ProblemNotice error={record.error} />
        </div>
      ) : null}
    </>
  );
}
