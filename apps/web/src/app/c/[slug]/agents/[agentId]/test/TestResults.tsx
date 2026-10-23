"use client";

/**
 * The tests of a finished run, grouped by what fixes them rather than by verdict: the script,
 * a missing answer, or a setting (D-823's owners). Each group says in one line what to do,
 * and each test closes to one scannable row (its name, verdict and the judge's reason) and
 * opens to the actions and the conversation.
 *
 * Then what needs no action from the owner: tests to read themselves, the ones right every
 * time (folded), our side (a note outside the score, D-828) and tests marked wrong.
 */

import Link from "next/link";

import { InfoTip } from "@/components/console/infoTip";
import { StatusPill } from "@/components/console/statusPill";
import { PipMark } from "@/components/illustration/pip";
import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { TestResult, TestRun } from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { lookup } from "@/lib/lookup";

import { TriesAndConversation } from "./TestConversation";
import {
  CHANGE,
  FIX_GROUP,
  MOSTLY_RIGHT,
  SETTING_LINK,
  STANDING,
  WHAT_TO_DO,
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

export function Results({ run, actions }: { run: TestRun; actions: RowActions }) {
  const by = (place: string) => run.results.filter((r) => standingOf(r) === place);
  const groups = fixGroups(run.results);
  const read = by("check");
  const works = by("works");
  const ours = by("ours");
  const wrong = by("wrong");
  const quiet = { ...actions, canFix: false, canMarkWrong: false };
  const note = oursNote(run);
  return (
    <div className="space-y-8">
      {groups.map(({ group, rows }) => (
        <section key={group} aria-labelledby={`tests-${group}-heading`}>
          <h5 id={`tests-${group}-heading`} className="text-heading text-ink">
            {FIX_GROUP[group].title} <span className="font-normal text-ink-muted">{rows.length}</span>
          </h5>
          <p className="mt-0.5 max-w-prose text-meta text-ink-muted">{FIX_GROUP[group].hint}</p>
          <ResultList rows={rows} actions={actions} />
        </section>
      ))}
      {read.length > 0 && (
        <section aria-labelledby="tests-read-heading">
          <h5 id="tests-read-heading" className="text-heading text-ink">
            Read these yourself <span className="font-normal text-ink-muted">{read.length}</span>
          </h5>
          <p className="mt-0.5 max-w-prose text-meta text-ink-muted">
            A test chat cannot show these, so nobody judged them. Open one to read what your agent said.
          </p>
          <ResultList rows={read} actions={quiet} />
        </section>
      )}
      {works.length > 0 && (
        <Folded title="Right every time" rows={works} actions={quiet} open={groups.length === 0 && read.length === 0} />
      )}
      {note && (
        <section aria-labelledby="tests-ours-heading" className="border-l-2 border-chart-neutral pl-3">
          <h5 id="tests-ours-heading" className="text-meta font-semibold text-ink">
            On our side
          </h5>
          <p className="mt-1 max-w-prose text-meta text-ink-muted">{note}</p>
          {ours.length > 0 && (
            <details className="group/fold mt-1">
              <summary className="flex touch:min-h-11 cursor-pointer list-none items-center gap-1.5 text-meta font-medium text-ink [&::-webkit-details-marker]:hidden">
                <Chevron className="group-open/fold:rotate-90" />
                See {ours.length === 1 ? "the test" : `the ${ours.length} tests`}
              </summary>
              <ResultList rows={ours} actions={quiet} />
            </details>
          )}
        </section>
      )}
      {wrong.length > 0 && <Folded title="Marked wrong" rows={wrong} actions={quiet} open={false} />}
    </div>
  );
}

function ResultList({ rows, actions }: { rows: TestResult[]; actions: RowActions }) {
  return (
    <ul className="mt-2 divide-y divide-line border-y border-line">
      {rows.map((r) => (
        <ResultRow key={r.key} result={r} actions={actions} />
      ))}
    </ul>
  );
}

function Folded({ title, rows, actions, open }: { title: string; rows: TestResult[]; actions: RowActions; open: boolean }) {
  return (
    <details open={open} className="group/fold">
      <summary className="flex touch:min-h-11 cursor-pointer list-none items-center gap-2 text-heading text-ink [&::-webkit-details-marker]:hidden">
        <Chevron className="group-open/fold:rotate-90" />
        {title} <span className="font-normal text-ink-muted">{rows.length}</span>
      </summary>
      <ResultList rows={rows} actions={actions} />
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

const CHANGE_TONE: Record<string, string> = {
  fixed: "font-medium text-brand-strong",
  broken: "font-medium text-danger",
};

/**
 * One test. Closed, it is one scannable row: its name; its verdict, how often it was right
 * and what changed since the last test; and, for a test that needs the owner, the judge's
 * reason, so the problem reads without opening anything. Open, the reason in full, what a
 * good answer does, the actions as buttons, then the conversation. Native `details`, so it
 * opens by keyboard and needs no script.
 */
function ResultRow({ result, actions }: { result: TestResult; actions: RowActions }) {
  const place = standingOf(result);
  const look = STANDING[place];
  const change = result.change ? CHANGE[result.change] : null;
  const owner = ownerOf(result);
  const tag = result.probe ? PROBE_TAG : (lookup(TAG, result.source) ?? null);
  const attention = isFailing(result);
  const fixable = attention && isFixable(result);
  const todo =
    place === "unreliable" && !isFixable(result)
      ? MOSTLY_RIGHT
      : owner && place !== "works" && place !== "check"
        ? WHAT_TO_DO[owner]
        : undefined;
  const setting = owner === "setting" ? result.setting : null;
  const tries =
    result.tries && result.tries.length > 0
      ? result.tries
      : [{ verdict: result.verdict, reason: result.reason, turns: result.turns }];
  const howOften = triesLine(result);
  const meta = [tag, howOften].filter((part): part is string => Boolean(part));
  const canFix = fixable && actions.canFix;
  const openScript = attention && result.fix === "script_step";
  const canMarkWrong = attention && actions.canMarkWrong;

  return (
    <li>
      <details className="group/row">
        <summary className="flex touch:min-h-11 cursor-pointer list-none items-start gap-3 py-3 [&::-webkit-details-marker]:hidden">
          <span className="min-w-0 flex-1 space-y-1">
            <span className="block text-body font-medium text-ink [overflow-wrap:anywhere]">{result.title}</span>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-meta text-ink-muted">
              <StatusPill tone={look.tone}>{look.label}</StatusPill>
              {change && (
                <span className={lookup(CHANGE_TONE, result.change ?? "") ?? ""}>
                  {change}
                </span>
              )}
              {meta.map((part) => (
                <span key={part}>
                  {part}
                </span>
              ))}
            </span>
            {attention && result.reason && (
              <span className="line-clamp-2 block text-meta text-ink group-open/row:hidden">{result.reason}</span>
            )}
          </span>
          <Chevron className="mt-1.5 group-open/row:rotate-90" />
        </summary>

        <div className="space-y-4 pb-5">
          {(result.reason || result.expect || todo) && (
            <div className="space-y-1.5">
              {result.reason && (
                <p className="flex flex-wrap items-center gap-x-1.5 text-body font-medium text-ink">
                  <span>{result.reason}</span>
                  {result.limit && (
                    <InfoTip label="what a test cannot show">
                      <p>{result.limit}</p>
                    </InfoTip>
                  )}
                </p>
              )}
              {result.expect && attention && (
                <p className="max-w-prose text-meta text-ink">
                  <span className="font-medium">A good answer: </span>
                  {result.expect}
                </p>
              )}
              {setting && setting.reason !== result.reason && <p className="text-meta text-ink">{setting.reason}</p>}
              {todo && <p className="max-w-prose text-meta text-ink-muted">{todo}</p>}
            </div>
          )}

          {(setting || canFix || openScript || canMarkWrong) && (
            <div className="flex flex-wrap items-center gap-2">
              {setting && (
                <Link href={actions.links[setting.area]} className={SECONDARY_BUTTON_SM}>
                  {SETTING_LINK[setting.area].label}
                </Link>
              )}
              {canFix && (
                <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => actions.onFix(result.key)}>
                  <PipMark size={14} className="shrink-0" />
                  Let {ASSISTANT_NAME} suggest a fix
                </button>
              )}
              {openScript && (
                <Link href={actions.links.script} className={SECONDARY_BUTTON_SM}>
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

          <TriesAndConversation tries={tries} />
        </div>
      </details>
    </li>
  );
}

/**
 * Quieter than the row's buttons (it overrides the judge rather than fixing the agent), so it
 * keeps its link look and carries the action's state in its words rather than as a filled
 * `ActionButton`. The name stays "This test is wrong"; the state is spoken beside it.
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
        This test is wrong
        {busy ? <span aria-hidden className="ml-1 no-underline">(marking…)</span> : null}
        {status === "error" ? <span aria-hidden className="ml-1 text-danger no-underline">(try again)</span> : null}
      </button>
      <span role="status" className="sr-only">
        {status === "success" ? "Marked" : status === "error" ? "Did not work" : ""}
      </span>
    </>
  );
}


const MARK_WRONG =
  "press ml-1 inline-flex touch:min-h-11 items-center rounded-sm text-meta font-medium text-ink-muted underline underline-offset-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand";
