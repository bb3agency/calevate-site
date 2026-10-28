"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ArrowRight, Check } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { PipMark } from "@/components/illustration/pip";
import { FIELD, ProblemNotice } from "@/components/ui";
import { VoiceButton } from "@/components/voiceButton";
import { useMe } from "@/lib/api/hooks";
import {
  isRecordingBusy,
  useRecordBrief,
  useRecording,
  useSaveBrief,
  type FirstRun,
} from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { BUSINESS_TYPES } from "@/lib/businessTypes";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { languageLabel } from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";
import { examplesFor } from "@/lib/verticalExamples";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

import { StepScreen } from "./shell";
import { FIRST } from "../../setup/_ui/copy";
import { Why } from "@/components/why";

/** The server's cap (`first_run/models.MAX_BRIEF_CHARS`). */
const MAX_BRIEF_CHARS = 4000;

export const HEARD_FAILURES: Record<string, string> = {
  voice_unreadable: "Couldn't make that out. Try somewhere quieter.",
  nothing_heard: "No words heard. Hold the phone closer.",
};

/**
 * STEP 2, TELL IT ABOUT YOU (D-855): one box, in the owner's own words.
 *
 * It starts filled with the brief for the trade given at sign-up (the account's own
 * AI-written one once it exists, else the trade's example), so the owner edits rather than
 * faces a blank box. Other trades' examples are a tap away. A microphone takes up to three
 * pieces of 30 seconds; each one's words are added to the box once heard, for the owner to
 * correct, and the audio is deleted as soon as it is heard.
 */
export function BriefStep({
  run,
  onBack,
  onDone,
  onPip,
  pipOff,
}: {
  run: FirstRun;
  onBack: () => void;
  onDone: () => void;
  onPip: () => void;
  /** Why Pip cannot be used here, or null when it can. */
  pipOff: string | null;
}) {
  const session = useClientSession();
  const me = useMe(session);
  const examples = useVerticalExamples();
  const ownTrade = me.data?.organization?.vertical_template ?? null;
  const save = useSaveBrief(session);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const boxId = useId();
  const box = useRef<HTMLTextAreaElement>(null);
  const [brief, setBrief] = useState<string | null>(run.brief);
  const [undo, setUndo] = useState<string | null>(null);
  const text = brief ?? examples.scriptBrief;
  const language = run.language_primary ?? "te-IN";

  const pickTrade = (vertical: string) => {
    setUndo(text);
    setBrief(examplesFor(vertical).scriptBrief);
    box.current?.focus();
  };

  return (
    <StepScreen
      title="Tell it about your business"
      hint={
        <>
          {FIRST.briefHint}
          <Why>Use your own words. Your agent&apos;s script is written from this.</Why>
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
          maxLength={MAX_BRIEF_CHARS}
          onChange={(event) => {
            setBrief(event.target.value);
            setUndo(null);
          }}
          rows={7}
          className={`${FIELD} mt-2 w-full resize-y text-[16px] leading-relaxed`}
        />
        <p className="mt-1 flex justify-between gap-3 text-meta text-ink-faint">
          <span>{brief === null ? "An example for your kind of business. Change anything." : ""}</span>
          <span className="tabular-nums">
            {Array.from(text).length} of {MAX_BRIEF_CHARS}
          </span>
        </p>
        {undo !== null ? (
          <button
            type="button"
            className={TEXT_ACTION}
            onClick={() => {
              setBrief(undo);
              setUndo(null);
            }}
          >
            Undo
          </button>
        ) : null}
      </div>

      <SpokenBrief
        language={language}
        piecesLeft={run.recordings_left}
        onHeard={(words) => setBrief((current) => [(current ?? "").trim(), words].filter(Boolean).join("\n"))}
        onTypeInstead={() => box.current?.focus()}
      />

      <div>
        <h3 className="text-heading text-ink">Start from another example</h3>
        <ul className="mt-2 flex flex-wrap gap-2">
          {BUSINESS_TYPES.filter((type) => type.value !== ownTrade).map((type) => (
            <li key={type.value}>
              <button
                type="button"
                onClick={() => pickTrade(type.value)}
                className="press inline-flex min-h-11 items-center rounded-full border border-line px-4 text-body text-ink hover:border-ink/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                {type.label}
              </button>
            </li>
          ))}
        </ul>
      </div>

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
}: {
  language: string;
  piecesLeft: number;
  onHeard: (words: string) => void;
  onTypeInstead: () => void;
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
