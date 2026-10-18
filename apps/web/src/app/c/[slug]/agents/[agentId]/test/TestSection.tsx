"use client";

/**
 * PRACTICE CALLERS — the agent callers hear now is asked what real callers asked, the owner's
 * saved tests and the four rules every agent keeps, and the failures become fixes the owner
 * reviews (D-724, given its own section by D-748, rebuilt by D-823). Since D-825 it sits
 * behind a closed disclosure at the foot of the Training tab, under the real-call work, and
 * declares its copilot surface only while open (`declare`), so a closed panel never answers
 * for the teach box above it.
 *
 * Every failure says who can fix it (D-823): the script or the knowledge (Pip suggests the
 * fix), a setting (a link to it, with why), our side ("we're fixing this"), or the test
 * itself, once the owner marks it wrong.
 *
 * Order on the screen is the order of the job: what happened (the summary and the trend),
 * what to do next (run again, or ask Pip for suggested fixes and see each change before keeping
 * it, D-820),
 * then every test as the conversation it was, failures first. Explanations sit behind ⓘ;
 * notices are one quiet line each.
 *
 * Kept script changes go to the draft (or live, when the owner presses "Keep and put live"
 * with no other draft waiting); the builder is one link away.
 */

import Link from "next/link";
import { useState } from "react";

import { InfoTip } from "@/components/console/infoTip";
import { PipMark } from "@/components/illustration/pip";
import {
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useMarkTestWrong,
  useRunTestConversations,
  useTestConversations,
  type TestResult,
  type TestRun,
  type TestTurn,
} from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { ImprovementReview } from "../script/ImprovementReview";
import { CALL_HANDLING_ANCHOR } from "../sections/settingsTab";
import {
  ACTION_LABEL,
  VERDICT,
  SETTING_LINK,
  WHAT_TO_DO,
  countsOf,
  isFailing,
  isFixable,
  languageOf,
  ownerOf,
  trendLine,
} from "./testCopy";

const PROBE_TAG = "A rule every agent keeps";

/** What Pip is asked for the fixes, in the words the owner sees in its ask box (D-820). */
export const FIX_ALL_REQUEST = "Suggest fixes for the tests this agent failed.";
export const fixOneRequest = (title: string) => `Suggest a fix for this agent's failed test “${title}”.`;

export function TestSection({
  agent,
  slug,
  declare = true,
}: {
  agent: Pick<Agent, "id">;
  slug: string;
  /** Whether this panel is on screen and so the one the assistant should see. */
  declare?: boolean;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const tests = useTestConversations(session, agent.id);
  const run = useRunTestConversations(session, agent.id);
  const markWrong = useMarkTestWrong(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "test and improve this agent");
  const [auto, setAuto] = useState(false);
  const [closed, setClosed] = useState<string | null>(null);

  const data = tests.data;
  const latest = data?.latest ?? null;
  const testing = latest?.status === "queued" || latest?.status === "running" || run.isPending;
  const done = latest?.status === "done" ? latest : null;
  const failing = done ? done.results.filter(isFailing) : [];
  const fixable = failing.filter(isFixable);
  const counts = done ? countsOf(done.results) : null;
  const improving = done?.improving === true;
  const proposal = done?.improvement ?? null;
  const showReview = done !== null && proposal !== null && !improving && closed !== proposal.created_at;

  useCopilotSurface(declare ? {
    route: "/c/{slug}/agents/{id}",
    title: "Agent: practice callers",
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      {
        key: "state",
        label: "What is on screen",
        value: counts
          ? `the latest test: ${counts.passed} passed, ${counts.failing} need a fix, ${counts.unchecked} for the owner to read`
          : testing
            ? "a test is running"
            : "no finished test yet",
      },
      {
        key: "what_is_here",
        label: "What this section does",
        value:
          "the agent callers hear now is asked what real callers asked, saved tests and the rules every agent keeps; failures the script or knowledge can fix become suggested fixes",
      },
      // Pip's `agent_tests_fix` names the failures to fix by these keys: only those the script
      // or the knowledge owns.
      ...(fixable.length > 0
        ? [{ key: "failed_tests", label: "Tests the script can fix (key: title)", value: fixable.map((r) => `${r.key}: ${r.title}`).join("; ") }]
        : []),
      ...(failing.length > fixable.length
        ? [
            {
              key: "not_the_scripts",
              label: "Failed tests the script cannot fix (title: who can)",
              value: failing
                .filter((r) => !isFixable(r))
                .map((r) => `${r.title}: ${ownerOf(r) ?? "unknown"}`)
                .join("; "),
            },
          ]
        : []),
    ],
    apply: noFill,
  } : null);

  const start = () =>
    run.mutate(
      done && failing.length > 0 ? { retest_of: done.id, auto_improve: auto || done.auto_improve } : { auto_improve: auto },
    );
  // Pip works the fixes out (D-820): this prefills its ask box, and the fixes come back here.
  const askForFixes = (key?: string) => {
    setClosed(null);
    const title = key ? fixable.find((r) => r.key === key)?.title : undefined;
    openAssistant({ prompt: title ? fixOneRequest(title) : FIX_ALL_REQUEST });
  };

  const canRun = data?.available === true && write.allowed && !testing;
  // Once a test fails the next step is fixing it, so "Test again" steps back beside it.
  const nextIsFixing = failing.length > 0;

  return (
    <div className="max-w-3xl space-y-8">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="max-w-prose text-body text-ink-muted">
            Your agent is asked what real callers asked, and every answer is checked.
          </p>
          <InfoTip label="how testing works">
            <p>
              Each run asks the questions your agent could not answer on real calls, your saved tests, and
              the four questions every agent must answer right: is this a person, is the call recorded,
              stop calling me, and let me talk to someone. Those four are checked by rules, not by AI.
            </p>
            <p className="mt-2">
              Until your agent has had ten calls in the last 30 days, a few practice callers written for your business
              are added.
            </p>
            <p className="mt-2">Tests talk to what callers hear now, not to changes still waiting in your draft.</p>
            {data?.cost_note && <p className="mt-2">{data.cost_note}</p>}
          </InfoTip>
        </div>

        {data?.waiting_update && (
          <NoticeBox
            tone="warn"
            title={data.waiting_update}
            action={
              <Link href={href(`/c/${slug}/agreements`)} className="text-meta font-medium text-ink underline underline-offset-2">
                Open agreements
              </Link>
            }
          />
        )}

        {data && !data.available && <p className="text-body text-ink-muted">{data.unavailable_reason}</p>}
        <RestrictionNote reason={write.reason} />

        {data?.available && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <button
              type="button"
              className={nextIsFixing ? SECONDARY_BUTTON_SM : PRIMARY_BUTTON_SM}
              disabled={!canRun}
              title={write.reason ?? undefined}
              onClick={start}
            >
              {testing ? "Testing…" : latest ? "Test again" : "Run the tests"}
            </button>
            <label className="flex min-h-11 items-center gap-2 text-meta text-ink-muted">
              <input
                type="checkbox"
                checked={auto}
                disabled={!write.allowed || testing}
                onChange={(e) => setAuto(e.target.checked)}
              />
              Suggest fixes when a test fails
            </label>
          </div>
        )}
        {run.error && <ProblemNotice error={run.error} />}
      </div>

      {tests.isLoading && <Skeleton rows={4} />}
      {tests.error && <ProblemNotice error={tests.error} onRetry={() => void tests.refetch()} />}

      {testing && (
        <div role="status" aria-live="polite" className="space-y-2">
          <p className="text-body text-ink-muted">
            <span className="text-shimmer">Asking your agent its tests.</span> This takes a minute or two.
          </p>
          <Skeleton rows={3} />
        </div>
      )}
      {latest?.status === "failed" && !testing && (
        <NoticeBox tone="warn" title="The tests could not finish this time.">
          <p className="text-meta text-ink-muted">Test again in a minute.</p>
        </NoticeBox>
      )}

      {done && counts && !testing && (
        <>
          <Summary run={done} counts={counts} history={data?.history ?? []} />

          {failing.length > 0 && (
            <FixPanel
              count={fixable.length}
              canWrite={write.allowed}
              improving={improving}
              note={done.improve_note ?? null}
              hasProposal={proposal !== null}
              showReview={showReview}
              onImprove={() => askForFixes()}
              onReopen={() => setClosed(null)}
            />
          )}

          {showReview && proposal && (
            <ImprovementReview
              agentId={agent.id}
              run={done}
              improvement={proposal}
              onClose={() => setClosed(proposal.created_at)}
              onTestAgain={start}
            />
          )}

          {markWrong.error && <ProblemNotice error={markWrong.error} />}
          <Results
            results={done.results}
            canFix={write.allowed && !improving}
            onFix={(key) => askForFixes(key)}
            canMarkWrong={write.allowed && !markWrong.isPending}
            onMarkWrong={(key) => markWrong.mutate({ runId: done.id, key })}
            links={{
              script: href(`/c/${slug}/agents/${agent.id}?section=script`),
              handover: href(`/c/${slug}/agents/${agent.id}?section=${SETTING_LINK.handover.section}#${CALL_HANDLING_ANCHOR}`),
              agreements: href(`/c/${slug}/agreements`),
            }}
          />
        </>
      )}
    </div>
  );
}

function Summary({
  run,
  counts,
  history,
}: {
  run: TestRun;
  counts: ReturnType<typeof countsOf>;
  history: Parameters<typeof trendLine>[1];
}) {
  const trend = trendLine(run, history);
  const tiles: { label: string; value: number; tone: string }[] = [
    { label: "Passed", value: counts.passed, tone: "text-brand-strong" },
    { label: "Need a fix", value: counts.failing, tone: counts.failing > 0 ? "text-danger" : "text-ink" },
    { label: "For you to read", value: counts.unchecked, tone: "text-ink" },
  ];
  return (
    <section aria-labelledby="test-summary-heading" className="space-y-3">
      <h4 id="test-summary-heading" className="sr-only">
        Latest test
      </h4>
      <dl className="grid grid-cols-3 divide-x divide-line border-y border-line">
        {tiles.map((tile) => (
          <div key={tile.label} className="px-3 py-3 first:pl-0">
            <dt className="text-meta text-ink-muted">{tile.label}</dt>
            <dd className={`text-2xl font-semibold tabular-nums ${tile.tone}`}>{tile.value}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-1 text-meta text-ink-muted">
        {trend && <p>{trend}</p>}
        {run.round > 1 && <p>This run asked last time&apos;s failures again, beside new callers.</p>}
        {!run.is_current && <p className="text-ink">The script has changed since this run. Test again to check what callers hear now.</p>}
        {run.note && <p>{run.note}</p>}
      </div>
    </section>
  );
}

function FixPanel({
  count,
  canWrite,
  improving,
  note,
  hasProposal,
  showReview,
  onImprove,
  onReopen,
}: {
  /** Failures the script or the knowledge can fix. */
  count: number;
  canWrite: boolean;
  improving: boolean;
  note: string | null;
  hasProposal: boolean;
  showReview: boolean;
  onImprove: () => void;
  onReopen: () => void;
}) {
  if (improving) {
    return (
      <div role="status" aria-live="polite" className="space-y-2">
        <p className="text-body text-ink">
          <span className="text-shimmer">
            Working out fixes{count > 0 ? ` for ${count === 1 ? "1 test" : `${count} tests`}` : ""}…
          </span>
        </p>
        <p className="text-meta text-ink-muted">This takes up to two minutes. You can leave this screen; the fixes wait here.</p>
      </div>
    );
  }
  if (showReview) return null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {count > 0 ? (
          <p className="text-body text-ink">
            {count === 1 ? "1 test can be fixed in the script or your facts." : `${count} tests can be fixed in the script or your facts.`}{" "}
            Get suggested changes and keep the ones you want.
          </p>
        ) : (
          <p className="text-body text-ink">
            None of the failed tests can be fixed in the script. Each one below says who can fix it.
          </p>
        )}
        {canWrite && count > 0 && (
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onImprove}>
            <PipMark size={16} className="shrink-0" />
            Let {ASSISTANT_NAME} suggest fixes
          </button>
        )}
        {hasProposal && (
          <button type="button" className="text-meta font-medium text-ink underline underline-offset-2" onClick={onReopen}>
            Open the last suggestions
          </button>
        )}
      </div>
      {note && <NoticeBox tone="warn" title={note} />}
    </div>
  );
}

interface ResultLinks {
  script: string;
  handover: string;
  agreements: string;
}

interface RowActions {
  canFix: boolean;
  onFix: (key: string) => void;
  canMarkWrong: boolean;
  onMarkWrong: (key: string) => void;
  links: ResultLinks;
}

function Results({ results, ...actions }: { results: TestResult[] } & RowActions) {
  const failing = results.filter(isFailing);
  const unchecked = results.filter((r) => r.verdict === "unjudged" && !r.marked_wrong);
  const passed = results.filter((r) => r.verdict === "passed" && !r.marked_wrong);
  const wrong = results.filter((r) => r.marked_wrong);
  const readOnly = { ...actions, canFix: false, canMarkWrong: false };
  return (
    <div className="space-y-8">
      {failing.length > 0 && <ResultGroup id="needs-fix" title="Needs a fix" results={failing} actions={actions} />}
      {unchecked.length > 0 && (
        <ResultGroup id="read-yourself" title="Read these yourself" results={unchecked} actions={readOnly} />
      )}
      {[
        { label: "Passed", rows: passed },
        { label: "Marked wrong", rows: wrong },
      ]
        .filter((group) => group.rows.length > 0)
        .map((group) => (
          <details key={group.label} className="group">
            <summary className="flex min-h-11 cursor-pointer items-center text-body font-medium text-ink">
              {group.label} ({group.rows.length})
            </summary>
            <ul className="mt-2 divide-y divide-line border-y border-line">
              {group.rows.map((result) => (
                <ResultRow key={result.key} result={result} actions={readOnly} />
              ))}
            </ul>
          </details>
        ))}
    </div>
  );
}

function ResultGroup({
  id,
  title,
  results,
  actions,
}: {
  id: string;
  title: string;
  results: TestResult[];
  actions: RowActions;
}) {
  return (
    <section aria-labelledby={`${id}-heading`}>
      <h4 id={`${id}-heading`} className="text-heading text-ink">
        {title} <span className="font-normal text-ink-muted">({results.length})</span>
      </h4>
      <ul className="mt-2 divide-y divide-line border-y border-line">
        {results.map((result) => (
          <ResultRow key={result.key} result={result} actions={actions} />
        ))}
      </ul>
    </section>
  );
}

const LINK_CLASS = "min-h-11 text-meta font-medium text-ink underline underline-offset-2 sm:min-h-0";

function ResultRow({ result, actions }: { result: TestResult; actions: RowActions }) {
  const verdict = VERDICT[result.verdict];
  const before = result.before ? VERDICT[result.before] : null;
  const owner = ownerOf(result);
  const failing = isFailing(result);
  const todo = (failing || result.marked_wrong) && owner ? WHAT_TO_DO[owner] : undefined;
  const setting = owner === "setting" ? result.setting : null;
  const tags = [
    result.probe ? PROBE_TAG : null,
    result.source === "real" ? "From a real call" : null,
    result.source === "saved" ? "Saved test" : null,
    result.source === "retest" ? "Asked again" : null,
  ].filter((tag): tag is string => tag !== null);
  return (
    <li className="space-y-3 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-body font-medium text-ink">{result.title}</p>
          {tags.length > 0 && <p className="text-meta text-ink-muted">{tags.join(" · ")}</p>}
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1.5 text-meta font-medium ${verdict.tone}`}>
          {before && before.label !== verdict.label && <span className="font-normal text-ink-muted">{before.label} →</span>}
          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${verdict.dot}`} />
          {verdict.label}
        </span>
      </div>

      <Conversation turns={result.turns} />

      {(result.reason || todo) && (
        <div className="space-y-1">
          {result.reason && (
            <p className="flex flex-wrap items-center gap-x-1.5 text-body text-ink">
              <span>{result.reason}</span>
              {result.limit && (
                <InfoTip label="what a test cannot show">
                  <p>{result.limit}</p>
                </InfoTip>
              )}
            </p>
          )}
          {result.formal_words.length > 0 && (
            <p className="text-meta text-ink-muted">Textbook words it used: {result.formal_words.join(", ")}</p>
          )}
          {todo && <p className="text-meta text-ink-muted">What to do: {todo}</p>}
          <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
            {setting && setting.reason !== result.reason && <p className="w-full text-meta text-ink">{setting.reason}</p>}
            {setting && (
              <Link href={actions.links[setting.area]} className={LINK_CLASS}>
                {SETTING_LINK[setting.area].label}
              </Link>
            )}
            {failing && isFixable(result) && actions.canFix && (
              <button type="button" className={LINK_CLASS} onClick={() => actions.onFix(result.key)}>
                Let {ASSISTANT_NAME} suggest a fix
              </button>
            )}
            {failing && owner === "script" && result.fix === "script_step" && (
              <Link href={actions.links.script} className={LINK_CLASS}>
                Open the script
              </Link>
            )}
            {failing && actions.canMarkWrong && (
              <button type="button" className={LINK_CLASS} onClick={() => actions.onMarkWrong(result.key)}>
                This test is wrong
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

/** One test as the chat it was: the caller on the right, the agent on the left. */
function Conversation({ turns }: { turns: TestTurn[] }) {
  return (
    <ol className="space-y-2" aria-label="The conversation">
      {turns.map((turn, index) => (
        <li key={index} className="space-y-2">
          <Bubble who="Caller" text={turn.said} side="right" />
          <Bubble who="Agent" text={turn.reply} side="left" actions={turn.actions ?? []} />
        </li>
      ))}
    </ol>
  );
}

function Bubble({
  who,
  text,
  side,
  actions = [],
}: {
  who: "Caller" | "Agent";
  text: string;
  side: "left" | "right";
  actions?: NonNullable<TestTurn["actions"]>;
}) {
  const language = text ? languageOf(text) : null;
  const right = side === "right";
  return (
    <div className={`flex ${right ? "justify-end" : "justify-start"}`}>
      <div className={`flex min-w-0 max-w-[85%] flex-col gap-1 sm:max-w-[75%] ${right ? "items-end" : "items-start"}`}>
        <p className="px-1 text-meta text-ink-muted">
          <span className="font-medium">{who}</span>
          {language && <span> · {language}</span>}
        </p>
        <p
          className={`whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-body ${
            right ? "bg-ink/[0.05] text-ink" : "border border-line bg-surface text-ink"
          }`}
        >
          {text || <span className="text-ink-muted">(said nothing)</span>}
        </p>
        {actions.length > 0 && (
          <p className="px-1 text-meta text-ink-muted">{actions.map((a) => lookup(ACTION_LABEL, a) ?? ACTION_LABEL.other).join(" · ")}</p>
        )}
      </div>
    </div>
  );
}
