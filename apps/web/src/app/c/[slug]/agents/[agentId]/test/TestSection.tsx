"use client";

/**
 * PRACTICE TESTS — the agent callers hear now is asked the questions real callers asked, the
 * owner's saved tests and the four rules every agent keeps, each test tried several times
 * (D-724, rebuilt by D-823 and D-828, redesigned by D-844). It sits behind the "Practice
 * callers" disclosure at the foot of the Training tab and declares its copilot surface only
 * while open (`declare`).
 *
 * The screen's job: show the owner what is wrong and the one thing to do about it.
 * 1. How is my agent doing? (`Standing`) One headline, the score as countable blocks, and the
 *    same tests on earlier runs.
 * 2. What do I do next? (`NextStepBlock`) One sentence, one primary action, "Test again"
 *    beside it.
 * 3. Which tests? (`Results`) The failures grouped by what fixes them (the script, a missing
 *    answer, a setting), each row showing the judge's reason before it is opened.
 *
 * What is ours to fix (a rule we keep for every agent, how replies sounded) is one quiet note,
 * outside the score: the owner cannot change it, so it never sinks their result (D-828).
 */

import Link from "next/link";
import { useState } from "react";

import { NoticeBox, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { ApiProblem } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useMarkTestWrong,
  useRestoreVersion,
  useRunTestConversations,
  useTestConversations,
  type RunTestsBody,
} from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { openAssistant } from "@/lib/copilot/launcher";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { ImprovementReview } from "../script/ImprovementReview";
import { CALL_HANDLING_ANCHOR } from "../sections/settingsTab";
import { Results } from "./TestResults";
import { FirstRun, NextStepBlock, Running, Standing, Stopped } from "./TestSummary";
import { NOTHING_CHANGED_CODE, SETTING_LINK, countsOf, isFixable } from "./testCopy";

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
  const restore = useRestoreVersion(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "test and improve this agent");
  const [closed, setClosed] = useState<string | null>(null);

  const data = tests.data;
  const latest = data?.latest ?? null;
  const testing = latest?.status === "queued" || latest?.status === "running" || run.isPending;
  const done = latest?.status === "done" ? latest : null;
  const fixable = done ? done.results.filter(isFixable) : [];
  const counts = done ? countsOf(done.results) : null;
  const improving = done?.improving === true;
  const proposal = done?.improvement ?? null;
  const showReview = done !== null && proposal !== null && !improving && closed !== proposal.created_at;
  // "Test again" with nothing changed is guidance, not a failure: shown calmly in the
  // next-step block, in the server's words. Every other refusal stays a ProblemNotice.
  const refusal = run.error instanceof ApiProblem && run.error.code === NOTHING_CHANGED_CODE ? run.error : null;
  const unchanged = refusal ? { said: refusal.message, next: refusal.remediation ?? null } : null;

  useCopilotSurface(
    declare
      ? {
          route: "/c/{slug}/agents/{id}",
          title: "Agent: practice tests",
          realm: "client",
          fields: [],
          facts: [
            { key: "agent_id", label: "Agent id", value: agent.id },
            {
              key: "state",
              label: "What is on screen",
              value: counts
                ? `the latest test: ${counts.passed} right every time, ${counts.failing} not yet (${counts.unreliable} of them right only sometimes), ${counts.unchecked} for the owner to read, ${counts.ours} on our side`
                : testing
                  ? "a test is running"
                  : "no finished test yet",
            },
            {
              key: "what_is_here",
              label: "What this section does",
              value:
                "each test is tried several times against the agent callers hear now; 'Test again' asks the same tests so before and after compare; failures the script or knowledge can fix become suggested fixes",
            },
            // Pip's `agent_tests_fix` names the failures to fix by these keys: only those the
            // script or the knowledge owns and that failed on most of their tries.
            ...(fixable.length > 0
              ? [
                  {
                    key: "failed_tests",
                    label: "Tests the script can fix (key: title)",
                    value: fixable.map((r) => `${r.key}: ${r.title}`).join("; "),
                  },
                ]
              : []),
          ],
          apply: noFill,
        }
      : null,
  );

  const start = (body: RunTestsBody) => run.mutate(body);
  const testAgain = () => done && start({ retest_of: done.id, auto_improve: done.auto_improve });
  const askForFixes = (key?: string) => {
    setClosed(null);
    const title = key ? fixable.find((r) => r.key === key)?.title : undefined;
    openAssistant({ prompt: title ? fixOneRequest(title) : FIX_ALL_REQUEST });
  };

  const links = {
    script: href(`/c/${slug}/agents/${agent.id}?section=script`),
    handover: href(`/c/${slug}/agents/${agent.id}?section=${SETTING_LINK.handover.section}#${CALL_HANDLING_ANCHOR}`),
    agreements: href(`/c/${slug}/agreements`),
  };
  const canRun = data?.available === true && write.allowed && !testing;

  return (
    <div className="space-y-6">
      {data?.waiting_update && (
        <NoticeBox
          tone="warn"
          title={data.waiting_update}
          action={
            <Link href={links.agreements} className="text-meta font-medium text-ink underline underline-offset-2">
              Open agreements
            </Link>
          }
        />
      )}
      {data && !data.available && <p className="text-body text-ink-muted">{data.unavailable_reason}</p>}
      <RestrictionNote reason={write.reason} />

      {tests.isLoading && <Skeleton rows={4} />}
      {tests.error && <ProblemNotice error={tests.error} onRetry={() => void tests.refetch()} />}

      {data &&
        (testing ? (
          <Running run={latest} trials={data.trials ?? 3} />
        ) : latest?.status === "failed" ? (
          <Stopped
            run={latest}
            canRun={canRun}
            onRetry={() => start(latest.retest_of ? { retest_of: latest.retest_of } : {})}
          />
        ) : done ? (
          <>
            <Standing run={done} data={data} />
            <NextStepBlock
              run={done}
              data={data}
              canRun={canRun}
              canWrite={write.allowed}
              fixable={fixable.length}
              improving={improving}
              hasProposal={proposal !== null}
              showingReview={showReview}
              restoring={restore.isPending}
              restored={restore.isSuccess}
              links={links}
              unchanged={unchanged}
              onTestAgain={testAgain}
              onNewSet={(practice) => start({ practice_callers: practice })}
              onFix={() => askForFixes()}
              onReopen={() => setClosed(null)}
              onUndo={(version) => restore.mutate(version)}
            />
          </>
        ) : (
          <FirstRun
            data={data}
            canRun={canRun}
            onRun={() => start({})}
            knowledgeHref={href(`/c/${slug}/knowledge`)}
          />
        ))}
      {run.error && !refusal && <ProblemNotice error={run.error} />}
      {restore.error && <ProblemNotice error={restore.error} />}

      {done && !testing && (
        <>
          {showReview && proposal && (
            <ImprovementReview
              agentId={agent.id}
              run={done}
              improvement={proposal}
              onClose={() => {
                setClosed(proposal.created_at);
                void tests.refetch();
              }}
              onTestAgain={testAgain}
            />
          )}
          {markWrong.error && <ProblemNotice error={markWrong.error} />}
          <Results
            run={done}
            actions={{
              canFix: write.allowed && !improving,
              onFix: (key) => askForFixes(key),
              canMarkWrong: write.allowed && !markWrong.isPending,
              onMarkWrong: (key) => markWrong.mutate({ runId: done.id, key }),
              links,
            }}
          />
        </>
      )}
    </div>
  );
}
