"use client";

/**
 * The tests of a finished run, as cards. Each test that needs the owner is one short card:
 * its title, ONE status, and the one or two buttons that act on it ("Fix it", "Add answer",
 * the setting, "See the chat"). The judge's reason, the good answer and "Not a problem" wait
 * behind "Why?" (progressive disclosure: the default view shows only what is acted on,
 * docs/evidence/simple-ui-research-2026-10-28.md row 6).
 *
 * Cards rather than grouped rows under explanatory headings: the owner learns what to do
 * from the buttons on the card, not from a sentence above a group, and a group heading with
 * its hint was two more lines to read per kind of problem.
 *
 * After them, folded: the tests that were OK and those the owner said were not a problem.
 * Our side is one muted line, outside the score (D-828); what it holds is in the assistant's
 * facts, not on the screen.
 */

import Link from "next/link";
import { useId, useState } from "react";
import { BookOpen } from "lucide-react";

import { TEXT_ACTION_SM } from "@/components/console/section";
import { InfoTip } from "@/components/console/infoTip";
import { StatusPill } from "@/components/console/statusPill";
import { PipMark } from "@/components/illustration/pip";
import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { TestResult, TestRun } from "@/lib/api/script";
import { lookup } from "@/lib/lookup";

import { TriesAndConversation } from "./TestConversation";
import {
  CHANGE,
  MOSTLY_RIGHT,
  SETTING_LINK,
  STANDING,
  fixGroups,
  isFailing,
  isFixable,
  oursNote,
  ownerOf,
  standingOf,
  triesLine,
} from "./testCopy";

const TAG: Record<string, string> = {
  real: "From a real call",
  saved: "Your saved test",
  generated: "Practice caller",
};
const PROBE_TAG = "A rule every agent keeps";

export interface ResultLinks {
  script: string;
  handover: string;
  agreements: string;
  /** What the business's agents know, where a missing answer is taught. */
  knowledge: string;
}

export interface RowActions {
  canFix: boolean;
  onFix: (key: string) => void;
  canMarkWrong: boolean;
  onMarkWrong: (key: string) => void;
  /** The mark's state for one row, so only the pressed row shows it. */
  markWrongStatus?: (key: string) => "idle" | "pending" | "success" | "error";
  links: ResultLinks;
}

const count = (n: number) => `${n} ${n === 1 ? "test" : "tests"}`;

/** A card's buttons share a phone's width and wrap whole rather than break a label; their own width above. */
const CARD_BUTTON = `${SECONDARY_BUTTON_SM} flex-1 justify-center whitespace-nowrap sm:flex-none`;

export function Results({ run, actions }: { run: TestRun; actions: RowActions }) {
  const by = (place: string) => run.results.filter((r) => standingOf(r) === place);
  // What Pip can fix first, then a missing answer, then a setting (`FIX_GROUP_ORDER`).
  const failing = fixGroups(run.results).flatMap((group) => group.rows);
  const read = by("check");
  const works = by("works");
  const wrong = by("wrong");
  const quiet = { ...actions, canFix: false, canMarkWrong: false };
  const note = oursNote(run);
  return (
    <div className="space-y-4">
      {failing.length + read.length > 0 && (
        <ul aria-label="Tests to look at" className="space-y-3">
          {failing.map((r) => (
            <TestCard key={r.key} result={r} actions={actions} />
          ))}
          {read.map((r) => (
            <TestCard key={r.key} result={r} actions={quiet} />
          ))}
        </ul>
      )}
      {works.length > 0 && <Folded title="OK" rows={works} actions={quiet} />}
      {wrong.length > 0 && <Folded title="Not a problem" rows={wrong} actions={quiet} />}
      {note && <p className="text-meta text-ink-muted">{note.line}</p>}
    </div>
  );
}

function Folded({ title, rows, actions }: { title: string; rows: TestResult[]; actions: RowActions }) {
  return (
    <details className="group/fold">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-sm text-heading text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand [&::-webkit-details-marker]:hidden">
        <Chevron className="group-open/fold:rotate-90" />
        {title}
        <span className="text-meta font-normal text-ink-muted">{count(rows.length)}</span>
      </summary>
      <ul className="mt-2 space-y-3">
        {rows.map((r) => (
          <TestCard key={r.key} result={r} actions={actions} compact />
        ))}
      </ul>
    </details>
  );
}

function Chevron({ className = "" }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className={`h-3.5 w-3.5 shrink-0 text-ink-muted transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none ${className}`}
    >
      <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * One test as a card. Closed: the title (the server's words, at most two lines), one status
 * and the buttons. "Why?" opens the judge's reason, a good answer, how often it was OK and
 * "Not a problem"; "See the chat" opens the conversation. Both are plain toggles
 * (`aria-expanded`), so the card's buttons stay buttons and are never nested in a summary.
 */
function TestCard({ result, actions, compact = false }: { result: TestResult; actions: RowActions; compact?: boolean }) {
  const [why, setWhy] = useState(false);
  const [chat, setChat] = useState(false);
  const id = useId();
  const place = standingOf(result);
  const look = STANDING[place];
  const owner = ownerOf(result);
  const attention = isFailing(result);
  const setting = owner === "setting" ? result.setting : null;
  const canFix = attention && isFixable(result) && actions.canFix;
  const teach = attention && owner === "knowledge";
  const openScript = attention && result.fix === "script_step";
  const canMarkWrong = attention && actions.canMarkWrong;
  // Pip leaves a mostly-right test alone; "Why?" says so, in place of a fix button.
  const leftAlone = place === "unreliable" && !isFixable(result);
  const tries =
    result.tries && result.tries.length > 0
      ? result.tries
      : [{ verdict: result.verdict, reason: result.reason, turns: result.turns }];
  // A test that broke since the last run says so in its one status; it is why Undo leads.
  const status = result.change === "broken" ? { label: CHANGE.broken ?? look.label, tone: "stop" as const } : look;
  const hasWhy = !compact || Boolean(result.reason);

  return (
    <li className="rounded-card border border-line bg-surface p-3 sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <p data-user-text className="line-clamp-2 min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">
          {result.title}
        </p>
        {!compact && (
          <StatusPill tone={status.tone} className="mt-0.5">
            {status.label}
          </StatusPill>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {canFix && (
          <button type="button" className={CARD_BUTTON} onClick={() => actions.onFix(result.key)}>
            <PipMark size={14} className="shrink-0" />
            Fix it
          </button>
        )}
        {teach && (
          <Link href={actions.links.knowledge} className={CARD_BUTTON}>
            <BookOpen aria-hidden className="h-3.5 w-3.5" />
            Add answer
          </Link>
        )}
        {setting && (
          <Link href={actions.links[setting.area]} className={CARD_BUTTON}>
            {SETTING_LINK[setting.area].label}
          </Link>
        )}
        <button
          type="button"
          className={CARD_BUTTON}
          aria-expanded={chat}
          aria-controls={`${id}-chat`}
          onClick={() => setChat((open) => !open)}
        >
          {chat ? "Hide the chat" : "See the chat"}
        </button>
        {hasWhy && (
          <button
            type="button"
            className={TEXT_ACTION_SM}
            aria-expanded={why}
            aria-controls={`${id}-why`}
            onClick={() => setWhy((open) => !open)}
          >
            Why?
          </button>
        )}
      </div>

      {why && (
        <div id={`${id}-why`} className="mt-3 space-y-2.5 border-t border-line pt-3 text-body">
          <WhyDetails result={result} attention={attention} leftAlone={leftAlone} setting={setting} />
          {(openScript || canMarkWrong) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {openScript && (
                <Link href={actions.links.script} className={TEXT_ACTION_SM}>
                  Open the script
                </Link>
              )}
              {canMarkWrong && (
                <MarkWrongButton
                  status={actions.markWrongStatus?.(result.key) ?? "idle"}
                  onClick={() => actions.onMarkWrong(result.key)}
                />
              )}
            </div>
          )}
        </div>
      )}
      {chat && (
        <div id={`${id}-chat`} className="mt-3 border-t border-line pt-3">
          <TriesAndConversation tries={tries} />
        </div>
      )}
    </li>
  );
}

/** What is behind "Why?": the judge's reason, a good answer, the setting, and the small facts. */
function WhyDetails({
  result,
  attention,
  leftAlone,
  setting,
}: {
  result: TestResult;
  attention: boolean;
  leftAlone: boolean;
  setting: TestResult["setting"] | null;
}) {
  const change = result.change ? CHANGE[result.change] : null;
  const tag = result.probe ? PROBE_TAG : (lookup(TAG, result.source) ?? null);
  const facts = [triesLine(result), change, tag].filter((part): part is string => Boolean(part));
  return (
    <>
      {(result.reason || (result.expect && attention) || setting) && (
        <dl className="max-w-prose space-y-2.5">
          {result.reason && (
            <div>
              <dt className="text-meta font-medium text-ink-muted">What happened</dt>
              <dd className="text-ink [overflow-wrap:anywhere]">
                {result.reason}
                {result.limit && (
                  <span className="ml-1 inline-flex align-middle">
                    <InfoTip label="what a test cannot show">
                      <p>{result.limit}</p>
                    </InfoTip>
                  </span>
                )}
              </dd>
            </div>
          )}
          {result.expect && attention && (
            <div>
              <dt className="text-meta font-medium text-ink-muted">A good answer</dt>
              <dd className="text-ink [overflow-wrap:anywhere]">{result.expect}</dd>
            </div>
          )}
          {setting && setting.reason !== result.reason && (
            <div>
              <dt className="text-meta font-medium text-ink-muted">The setting</dt>
              <dd className="text-ink">{setting.reason}</dd>
            </div>
          )}
        </dl>
      )}
      {leftAlone && <p className="text-meta text-ink-muted">{MOSTLY_RIGHT}</p>}
      {facts.length > 0 && <p className="text-meta text-ink-muted">{facts.join(" · ")}</p>}
    </>
  );
}

/**
 * "Not a problem": the owner overrides the judge (the test, not the agent, was wrong). Quieter
 * than a fix, so a muted text action that carries its state in words.
 */
function MarkWrongButton({
  status,
  onClick,
}: {
  status: "idle" | "pending" | "success" | "error";
  onClick: () => void;
}) {
  const busy = status === "pending";
  return (
    <>
      <button
        type="button"
        className={MARK_WRONG}
        aria-busy={busy || undefined}
        aria-disabled={busy || undefined}
        onClick={() => {
          if (!busy) onClick();
        }}
      >
        Not a problem
        {busy ? <span aria-hidden className="ml-1">(saving…)</span> : null}
        {status === "error" ? <span aria-hidden className="ml-1 text-danger">(try again)</span> : null}
      </button>
      <span role="status" className="sr-only">
        {status === "success" ? "Saved" : status === "error" ? "Did not work" : ""}
      </span>
    </>
  );
}

const MARK_WRONG =
  "press inline-flex min-h-8 touch:min-h-11 items-center rounded-md px-2 text-meta font-medium text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand";
