"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ArrowRight, Check } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { PipMark } from "@/components/illustration/pip";
import { FIELD, ProblemNotice } from "@/components/ui";
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
import { briefWaitingFor, languageLabel } from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

import { BriefDocuments } from "./BriefDocuments";
import { StepScreen } from "./shell";
import { FIRST } from "../../_ui/copy";
import { Why } from "@/components/why";
import { BRIEF_MAX_CHARS } from "@/lib/textLimits";

export const HEARD_FAILURES: Record<string, string> = {
  voice_unreadable: "Couldn't make that out. Try somewhere quieter.",
  nothing_heard: "No words heard. Hold the phone closer.",
};

/**
 * STEP 1, ABOUT YOUR BUSINESS (D-855, Phase 3b): one box, in the owner's own words, which
 * become the company training's overview Pip writes the training from.
 *
 * It starts filled with the account's own AI-written brief once that exists, so the owner
 * edits rather than faces a blank box. Before it lands the box starts empty with the trade's
 * example only as a placeholder: an example kept as the box's value was saved on Continue as
 * if the owner had written it, and described a business they might not be. A microphone takes up to three
 * pieces of 30 seconds; each one's words are added to the box once heard, for the owner to
 * correct, and the audio is deleted as soon as it is heard. Files the owner already has (a
 * price list, a menu) can be added beside the words or instead of them (`BriefDocuments`).
 */
export function BriefStep({
  run,
  draft,
  onDraft,
  onBack,
  onDone,
  onPip,
  pipOff,
}: {
  run: FirstRun;
  /** What was in the box when the step was last left unsaved (Back, or Pip), or null. The
   *  screen holds it, because this step unmounts on every move away; the spoken pieces in it
   *  used up recordings that cannot be taken again. */
  draft: string | null;
  onDraft: (draft: string | null) => void;
  /** None on the first step of the run. */
  onBack?: () => void;
  onDone: () => void;
  onPip: () => void;
  /** Why Pip cannot be used here, or null when it can. */
  pipOff: string | null;
}) {
  const session = useClientSession();
  const examples = useVerticalExamples();
  const copy = useBusinessCopy(session).data;
  const offered = useAgentLanguages(session).tags;
  const ownBrief = copy?.placeholders?.script_brief?.trim() || null;
  const save = useSaveBrief(session);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const boxId = useId();
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
  const waitingFor = briefWaitingFor({ documents: run.documents, sending, hearing });
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
  // `offered` is never empty (the three every account has while the server's list loads).
  const language = run.language_primary ?? businessLanguage(copy?.language, offered) ?? "";

  return (
    <StepScreen
      title="About your business"
      hint={
        <>
          {FIRST.briefHint}
          <Why>Use your own words. Pip trains your agents from this and writes the script for your first calls.</Why>
        </>
      }
      onBack={onBack}
      primary={
        <>
          Continue
          <ArrowRight aria-hidden className="h-4 w-4" />
        </>
      }
      status={saveFeedback.status}
      waitingFor={waitingFor}
      onSubmit={() => save.mutate({ brief: text.trim() }, { onSuccess: onDone })}
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
        <label htmlFor={boxId} className="text-heading text-ink">
          About your business
        </label>
        <textarea
          id={boxId}
          ref={box}
          value={text}
          maxLength={BRIEF_MAX_CHARS}
          placeholder={examples.scriptBrief}
          onFocus={adopt}
          onChange={(event) => setBrief(event.target.value)}
          rows={7}
          className={`${FIELD} mt-2 w-full resize-y text-[16px] leading-relaxed`}
        />
        <p className="mt-1 flex justify-between gap-3 text-meta text-ink-faint">
          <span>{fromDetails ? "Written from your business details. Change anything." : ""}</span>
          <span className="tabular-nums">
            {Array.from(text).length} of {BRIEF_MAX_CHARS}
          </span>
        </p>
      </div>

      <SpokenBrief
        language={language}
        piecesLeft={run.recordings_left}
        // Added to what the box SHOWS: before the owner types, that is the account's own
        // written brief, which `brief` (still null) does not hold.
        onHeard={(words) =>
          setBrief((current) => [(current ?? ownBrief ?? "").trim(), words].filter(Boolean).join("\n"))
        }
        onTypeInstead={() => box.current?.focus()}
        onBusy={setHearing}
      />

      <BriefDocuments run={run} onBusy={setSending} />

      {pipOff !== null ? <p className="text-meta text-ink-muted">{pipOff}</p> : null}
      {save.error ? <ProblemNotice error={save.error} /> : null}
    </StepScreen>
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
    <div className="rounded-card border border-line p-4">
      <p className="text-heading text-ink">Or say it</p>
      <p className="mt-0.5 text-meta text-ink-muted">{FIRST.sayIt(languageLabel(language), piecesLeft)}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {piecesLeft > 0 ? (
          <VoiceButton
            label={current === null ? "Record" : "Record another piece"}
            why="Tell your agent about your business. Your browser will ask to use the microphone; choose Allow."
            disabled={busy}
            onRecorded={(audio) =>
              record.mutate({ audio, language }, { onSuccess: (started) => setCurrent(started.id) })
            }
            onTypeInstead={onTypeInstead}
          />
        ) : (
          <p className="text-meta text-ink-muted">{FIRST.briefDone}</p>
        )}
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
      </div>
      {status === "failed" ? (
        <p role="alert" className="mt-2 text-meta text-ink">
          {lookup(HEARD_FAILURES, heard.data?.error_code ?? "") ?? "Couldn't hear that. Type it instead."}
        </p>
      ) : null}
      {record.error ? <ProblemNotice error={record.error} /> : null}
      <p className="mt-3 text-meta text-ink-faint">{FIRST.audioNotKept}</p>
    </div>
  );
}
