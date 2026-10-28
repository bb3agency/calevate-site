"use client";

/**
 * The tests of a finished run, grouped by what fixes them rather than by verdict: the script,
 * a missing answer, or a setting (D-823's owners). Each group says in one line what to do,
 * and each test closes to one scannable row (its name, ONE status and the judge's reason)
 * and opens to what went wrong, what a good answer does, the actions and the conversation.
 *
 * Then what needs no action from the owner: tests to read themselves, the ones right every
 * time (folded), our side (one line, details on demand, D-828) and tests marked wrong. Inside
 * those groups the heading already says the status, so a row does not say it again.
 */

import Link from "next/link";

import { TEXT_ACTION_SM } from "@/components/console/section";
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

const count = (n: number) => `${n} ${n === 1 ? "test" : "tests"}`;

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
    <div className="space-y-8 border-t border-line pt-6">
      {groups.map(({ group, rows }) => (
        <section key={group} aria-labelledby={`tests-${group}-heading`}>
          <GroupHeading id={`tests-${group}-heading`} title={FIX_GROUP[group].title} n={rows.length} />
          <p className="mt-0.5 max-w-prose text-meta text-ink-muted">{FIX_GROUP[group].hint}</p>
          <ResultList rows={rows} actions={actions} showStatus />
        </section>
      ))}
      {read.length > 0 && (
        <section aria-labelledby="tests-read-heading">
          <GroupHeading id="tests-read-heading" title="Read these yourself" n={read.length} />
          <p className="mt-0.5 max-w-prose text-meta text-ink-muted">
            A test chat cannot show these, so nobody judged them. Open one to read what your agent said.
          </p>
          <ResultList rows={read} actions={quiet} />
        </section>
      )}
      {works.length > 0 && (
        <Folded title="Right every time" rows={works} actions={quiet} open={false} />
      )}
      {note && (
        <section aria-labelledby="tests-ours-heading" className="space-y-1">
          <GroupHeading id="tests-ours-heading" title="On our side" n={ours.length} />
          <p className="max-w-prose text-meta text-ink-muted">{note.line}</p>
          <details className="group/fold">
            <summary className={`${TEXT_ACTION_SM} -mx-2 cursor-pointer list-none [&::-webkit-details-marker]:hidden`}>
              <Chevron className="group-open/fold:rotate-90" />
              <span className="group-open/fold:hidden">Show details</span>
              <span className="hidden group-open/fold:inline">Hide details</span>
            </summary>
            <ul className="mt-1 space-y-1 border-l-2 border-line pl-3 text-meta text-ink-muted">
              {note.details.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {ours.length > 0 && <ResultList rows={ours} actions={quiet} />}
          </details>
        </section>
      )}
      {wrong.length > 0 && <Folded title="Marked wrong" rows={wrong} actions={quiet} open={false} />}
    </div>
  );
}

/** A group's name and how many tests it holds, as a quiet count rather than a bare digit. */
function GroupHeading({ id, title, n }: { id: string; title: string; n: number }) {
  return (
    <h5 id={id} className="flex flex-wrap items-baseline gap-x-2 text-heading text-ink">
      {title}
      {n > 0 && <span className="text-meta font-normal text-ink-muted">{count(n)}</span>}
    </h5>
  );
}

function ResultList({ rows, actions, showStatus = false }: { rows: TestResult[]; actions: RowActions; showStatus?: boolean }) {
  return (
    <ul className="mt-2 divide-y divide-line border-y border-line">
      {rows.map((r) => (
        <ResultRow key={r.key} result={r} actions={actions} showStatus={showStatus} />
      ))}
    </ul>
  );
}

function Folded({ title, rows, actions, open }: { title: string; rows: TestResult[]; actions: RowActions; open: boolean }) {
  return (
    <details open={open} className="group/fold">
      <summary className="flex touch:min-h-11 cursor-pointer list-none items-baseline gap-2 rounded-sm text-heading text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand [&::-webkit-details-marker]:hidden">
        <Chevron className="translate-y-0.5 group-open/fold:rotate-90" />
        {title}
        <span className="text-meta font-normal text-ink-muted">{count(rows.length)}</span>
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
 * One test. Closed, it is one scannable row: its name; its status (only where the group does
 * not already say it), what changed since the last test and where it came from; and, for a
 * test that needs the owner, the judge's reason in two lines. Open: what went wrong and what a
 * good answer does as two labelled lines, the actions, then the conversation. Native
 * `details`, so it opens by keyboard and needs no script.
 */
function ResultRow({ result, actions, showStatus }: { result: TestResult; actions: RowActions; showStatus: boolean }) {
  const place = standingOf(result);
  const look = STANDING[place];
  const change = result.change ? CHANGE[result.change] : null;
  const owner = ownerOf(result);
  const tag = result.probe ? PROBE_TAG : (lookup(TAG, result.source) ?? null);
  const attention = isFailing(result);
  const fixable = attention && isFixable(result);
  const setting = owner === "setting" ? result.setting : null;
  const tries =
    result.tries && result.tries.length > 0
      ? result.tries
      : [{ verdict: result.verdict, reason: result.reason, turns: result.turns }];
  const howOften = triesLine(result);
  const canFix = fixable && actions.canFix;
  const openScript = attention && result.fix === "script_step";
  const canMarkWrong = attention && actions.canMarkWrong;
  // Pip leaves a mostly-right test alone; the row says why there is no "suggest a fix" on it.
  const leftAlone = place === "unreliable" && !isFixable(result);

  return (
    <li>
      <details className="group/row">
        <summary className="flex touch:min-h-11 cursor-pointer list-none items-start gap-3 rounded-sm py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand [&::-webkit-details-marker]:hidden">
          <span className="min-w-0 flex-1 space-y-1">
            <span className="block text-body font-medium text-ink [overflow-wrap:anywhere]">{result.title}</span>
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-meta text-ink-muted">
              {showStatus && <StatusPill tone={look.tone}>{look.label}</StatusPill>}
              {howOften && <span>{howOften}</span>}
              {change && <span className={lookup(CHANGE_TONE, result.change ?? "") ?? ""}>{change}</span>}
              {tag && <span>{tag}</span>}
            </span>
            {attention && result.reason && (
              <span className="line-clamp-2 block text-meta text-ink [overflow-wrap:anywhere] group-open/row:hidden">
                {result.reason}
              </span>
            )}
          </span>
          <Chevron className="mt-1.5 group-open/row:rotate-90" />
        </summary>

        <div className="min-w-0 space-y-4 pb-5">
          {(result.reason || (result.expect && attention) || setting) && (
            <dl className="max-w-prose space-y-2.5 text-body">
              {result.reason && (
                <div>
                  <dt className="text-meta font-medium text-ink-muted">{attention ? "What went wrong" : "Why"}</dt>
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
                <div className="border-l-2 border-brand pl-3">
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
          {leftAlone && <p className="max-w-prose text-meta text-ink-muted">{MOSTLY_RIGHT}</p>}

          {(setting || canFix || openScript || canMarkWrong) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
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

          <TriesAndConversation tries={tries} />
        </div>
      </details>
    </li>
  );
}

/**
 * Quieter than the row's buttons (it overrides the judge rather than fixing the agent), so it
 * is a muted text action and carries the action's state in its words rather than as a filled
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
        {busy ? <span aria-hidden className="ml-1">(marking…)</span> : null}
        {status === "error" ? <span aria-hidden className="ml-1 text-danger">(try again)</span> : null}
      </button>
      <span role="status" className="sr-only">
        {status === "success" ? "Marked" : status === "error" ? "Did not work" : ""}
      </span>
    </>
  );
}

const MARK_WRONG =
  "press inline-flex min-h-8 touch:min-h-11 items-center rounded-md px-2 text-meta font-medium text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand";
