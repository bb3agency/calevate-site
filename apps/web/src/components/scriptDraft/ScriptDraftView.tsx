"use client";

import { BookOpen, CircleCheck, CircleMinus, Hand, Loader2, PenLine, Scissors, ShieldCheck, Wrench } from "lucide-react";
import { useEffect, useRef, type ReactNode, type RefObject } from "react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { RowHead, TimelineList, TimelineRow } from "@/components/copilot/TimelineRow";
import { Disclosure } from "@/components/ui";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { formatWorkTime } from "@/lib/copilot/liveEvents";
import { isTerminalPhase, type DraftPhase, type DraftStreamState } from "@/lib/scriptDraft/stream";

import { ScriptDiff } from "./ScriptDiff";

/** A button's action and the state of its last press. */
export interface DraftControl {
  status: FeedbackStatus;
  run: () => void;
  /** False when the last failure is one another press cannot cure (`ActionFeedback.retryable`). */
  retryable?: boolean;
}

/** Keep was refused because the draft is longer than calls can take. */
export interface DraftTooLong {
  /** The server's sentence ("Your script is N characters too long…"), behind Why. */
  detail: string;
  /** Ask Pip for a shorter version of the script. */
  shorter: DraftControl;
}

export type DraftOutcome = "kept" | "discarded" | null;

/** The phase in progress, as a verb in the present. */
function doing(phase: DraftPhase | null): string {
  switch (phase) {
    case "reading":
      return "Reading what it is for, and its files and notes";
    case "writing":
      return "Writing the script";
    case "checking":
      return "Checking it against the call rules";
    case "repairing":
      return "Fixing a line that broke a rule";
    default:
      return "Getting ready to write";
  }
}

/** The same phase once finished. */
function done(phase: DraftPhase): string {
  switch (phase) {
    case "reading":
      return "Read what it is for, and its files and notes";
    case "writing":
      return "Wrote the script";
    case "checking":
      return "Checked it against the call rules";
    case "repairing":
      return "Fixed a line that broke a rule";
    default:
      return "Done";
  }
}

function PhaseIcon({ phase }: { phase: DraftPhase }) {
  const glyph = "h-3.5 w-3.5";
  switch (phase) {
    case "reading":
      return <BookOpen aria-hidden className={glyph} />;
    case "writing":
      return <PenLine aria-hidden className={glyph} />;
    case "checking":
      return <ShieldCheck aria-hidden className={glyph} />;
    case "repairing":
      return <Wrench aria-hidden className={glyph} />;
    default:
      return <CircleCheck aria-hidden className={glyph} />;
  }
}

/** One sentence per phase for a screen reader; the lines themselves are not announced. */
function spoken(phase: DraftPhase | null, outcome: DraftOutcome, tooLong: boolean): string {
  if (outcome === "kept") return "Kept. The script is live.";
  if (tooLong) return TOO_LONG_SPOKEN;
  if (outcome === "discarded") return "Discarded. Your script is as it was.";
  switch (phase) {
    case "ready":
      return "The new script is ready. Keep it or discard it.";
    case "failed":
      return `${ASSISTANT_NAME} could not write the script.`;
    case "cancelled":
      return "Stopped. Nothing was saved.";
    case null:
      return "";
    default:
      return `${ASSISTANT_NAME} is writing the script.`;
  }
}

const TOO_LONG_SPOKEN = `This draft is too long to put live. Ask ${ASSISTANT_NAME} for a shorter one, or discard it.`;

/**
 * A draft whose Keep was refused as too long. A second Keep sends the same draft and meets
 * the same refusal, so Keep goes and the one way forward takes its place: Pip writes a
 * shorter one, which replaces this draft. Discard and the caller's own extras stay beside it.
 */
export function TooLongDraft({
  detail,
  shorter,
  discard,
  extra,
  headingRef,
}: DraftTooLong & {
  discard: DraftControl;
  extra?: ReactNode;
  headingRef?: RefObject<HTMLHeadingElement | null>;
}) {
  return (
    <TimelineRow as="div" icon={<Scissors aria-hidden className="h-3.5 w-3.5" />}>
      <h4 ref={headingRef} tabIndex={-1} className="text-meta font-medium text-ink focus:outline-none">
        Too long for calls
      </h4>
      <p className="text-meta text-ink-muted">This draft is longer than a call can take, so it cannot go live.</p>
      <Disclosure variant="inline" title="Why" headingLevel={4}>
        <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">{detail}</p>
      </Disclosure>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <ActionButton
          variant="primary-sm"
          status={shorter.status}
          retryable={shorter.retryable}
          pendingLabel="Asking"
          successLabel="Asked"
          disabled={discard.status === "pending"}
          onClick={shorter.run}
        >
          Ask {ASSISTANT_NAME} for a shorter one
        </ActionButton>
        <ActionButton
          variant="secondary-sm"
          status={discard.status}
          retryable={discard.retryable}
          pendingLabel="Discarding"
          successLabel="Discarded"
          disabled={shorter.status === "pending"}
          onClick={discard.run}
        >
          Discard
        </ActionButton>
        {extra}
      </div>
    </TimelineRow>
  );
}

/**
 * A script draft as Pip writes it, the same in the Pip panel and on the campaign or Inbound
 * line page: the phases as rows that turn past tense with their time, the lines as they are
 * written, then the changes against the saved script and the decision.
 *
 * Presentational: the stream and the three actions come in as props, so the panel, the
 * page and the kit render one component (`ScriptDraftLive` wires the real ones).
 */
export function ScriptDraftView({
  state,
  now,
  reduced,
  keep,
  discard,
  cancel,
  outcome,
  waitingFor = null,
  extra,
  tooLong = null,
}: {
  state: DraftStreamState;
  now: number;
  reduced: boolean;
  keep: DraftControl;
  discard: DraftControl;
  /** Offered while Pip writes. */
  cancel?: DraftControl;
  outcome: DraftOutcome;
  /** Why Keep and Discard cannot be pressed here (no permission to change the script). */
  waitingFor?: string | null;
  /** More ways to decide, beside Keep and Discard (the page's part-by-part review). */
  extra?: ReactNode;
  /** Keep was refused as too long: the decision becomes a shorter draft or Discard. */
  tooLong?: DraftTooLong | null;
}) {
  const { phase, history, lines, diff, detail } = state;
  const writing = !isTerminalPhase(phase);
  const ready = phase === "ready" && diff !== null;
  const waiting = ready && outcome === null;
  const section = useRef<HTMLDivElement>(null);
  const waitingHeading = useRef<HTMLHeadingElement>(null);

  // The decision is what this view now needs. Focus moves to it only when nothing else holds
  // focus or the focus was inside this view (Stop writing has just gone): never out of a box
  // the person is typing in.
  // Again when Keep is refused as too long: Keep has gone, and its focus with it.
  const refused = waiting && tooLong !== null;
  useEffect(() => {
    if (!waiting) return;
    const active = document.activeElement;
    const free = active === null || active === document.body || section.current?.contains(active);
    if (free) waitingHeading.current?.focus({ preventScroll: true });
  }, [waiting, refused]);

  const steps = history.filter((entry) => !isTerminalPhase(entry.phase));
  return (
    <div ref={section} role="group" aria-label={`${ASSISTANT_NAME}'s script draft`} className="min-w-0 space-y-3">
      <TimelineList label="How the draft is going">
        {steps.length === 0 && writing ? (
          <TimelineRow icon={<Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />}>
            <RowHead label={doing(null)} body={null} />
          </TimelineRow>
        ) : null}
        {steps.map((entry, index) => {
          const next = steps[index + 1] ?? history.find((later) => later.at >= entry.at && isTerminalPhase(later.phase));
          const current = writing && index === steps.length - 1;
          const until = current ? now : next?.at;
          const took = entry.at > 0 && until !== undefined && until > 0 ? formatWorkTime(until - entry.at) : null;
          return (
            <TimelineRow
              key={`${entry.phase}-${index}`}
              arrived={!reduced}
              icon={
                current ? (
                  <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />
                ) : (
                  <PhaseIcon phase={entry.phase} />
                )
              }
            >
              <RowHead
                label={current ? <span className={reduced ? undefined : "text-shimmer"}>{doing(entry.phase)}</span> : done(entry.phase)}
                trailing={took}
                body={null}
              />
              {current && entry.phase === "repairing" && detail ? (
                <p className="text-meta text-ink-muted">{detail}</p>
              ) : null}
            </TimelineRow>
          );
        })}
      </TimelineList>

      {writing && lines.length > 0 ? (
        <ol aria-label="Lines written so far" className="space-y-2 border-l border-line pl-3" data-testid="draft-lines">
          {lines.map((line, index) => (
            <li key={line.path} className={!reduced && index === lines.length - 1 ? "live-enter" : undefined}>
              <p className="text-meta text-ink-muted">{line.label}</p>
              <p className="text-sm text-ink [overflow-wrap:anywhere]">{line.text}</p>
            </li>
          ))}
        </ol>
      ) : null}

      {writing && cancel ? (
        <div className="pl-7">
          <ActionButton variant="secondary-sm" status={cancel.status} pendingLabel="Stopping" onClick={cancel.run}>
            Stop writing
          </ActionButton>
        </div>
      ) : null}

      {ready ? <ScriptDiff changes={diff.changes} /> : null}

      {phase === "failed" ? (
        <TimelineRow as="div" icon={<CircleMinus aria-hidden className="h-3.5 w-3.5" />}>
          <p className="text-meta text-ink">
            {ASSISTANT_NAME} could not write the script. Your script is unchanged.
          </p>
          {detail ? (
            <Disclosure variant="inline" title="Why" headingLevel={4}>
              <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">{detail}</p>
            </Disclosure>
          ) : null}
        </TimelineRow>
      ) : null}

      {phase === "cancelled" ? (
        <TimelineRow as="div" icon={<CircleMinus aria-hidden className="h-3.5 w-3.5" />}>
          <p className="text-meta text-ink">Stopped. Nothing was saved.</p>
        </TimelineRow>
      ) : null}

      {refused && tooLong ? (
        <TooLongDraft {...tooLong} discard={discard} extra={extra} headingRef={waitingHeading} />
      ) : waiting ? (
        <TimelineRow as="div" icon={<Hand aria-hidden className="h-3.5 w-3.5" />}>
          <h4 ref={waitingHeading} tabIndex={-1} className="text-meta font-medium text-ink focus:outline-none">
            Waiting for you
          </h4>
          <p className="text-meta text-ink-muted">Keep puts it live. Discard leaves yours as it is.</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ActionButton
              variant="primary-sm"
              status={keep.status}
              retryable={keep.retryable}
              pendingLabel="Keeping"
              successLabel="Kept"
              waitingFor={waitingFor}
              disabled={discard.status === "pending"}
              onClick={keep.run}
            >
              Keep
            </ActionButton>
            <ActionButton
              variant="secondary-sm"
              status={discard.status}
              retryable={discard.retryable}
              pendingLabel="Discarding"
              successLabel="Discarded"
              disabled={keep.status === "pending" || waitingFor !== null}
              onClick={discard.run}
            >
              Discard
            </ActionButton>
            {extra}
          </div>
        </TimelineRow>
      ) : null}

      {outcome !== null ? (
        <TimelineRow as="div" icon={<CircleCheck aria-hidden className="h-3.5 w-3.5" />}>
          <p className="text-meta text-ink">
            {outcome === "kept" ? "Kept. This script is live now." : "Discarded. Your script stays as it was."}
          </p>
        </TimelineRow>
      ) : null}

      <span role="status" className="sr-only">
        {spoken(phase, outcome, refused)}
      </span>
    </div>
  );
}
