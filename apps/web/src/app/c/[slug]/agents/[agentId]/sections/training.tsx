"use client";

/**
 * TRAINING — checklist first, the rest folded (D-893 §6, founder 26 Oct 2026), inside the
 * seven-tab agent page (D-825, decision 5a08c365):
 *
 * 1. Questions to answer: what callers asked that it could not answer, what practice
 *    callers need and what setup leaves open, most asked first, each answered in place.
 *    Real calls first (D-826): it is the part that names something already going wrong,
 *    and the tab's badge counts it.
 * 2. Try it: one card, a chat with the live agent beside a practice call on a real phone
 *    (phone only; there is no in-browser call).
 * 3. One line each that opens on click: what it knows (with the teach box), saved tests,
 *    and practice callers (the AI-judged run, decision 565c8ef2). Practice callers open by
 *    themselves while a run or suggested fixes are waiting, so a fix Pip prepared is never
 *    hidden.
 *
 * ONE COPILOT SURFACE. The tab is a `CopilotSurfaceScope`: the teach box, the practice-call
 * number on a trial and, while open, the practice callers each declare what they own and
 * the assistant sees them merged.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { BookOpen, Pin } from "lucide-react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { QuestionsToAnswer } from "@/components/improvement/QuestionsToAnswer";
import { SavedTests } from "@/components/improvement/SavedTests";
import { TryChat } from "@/components/improvement/TryChat";
import { Disclosure, ProblemNotice, Skeleton } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useTestConversations } from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useKnows, useTestCases } from "@/lib/api/teach";
import { QUESTION_PARAM } from "@/lib/api/teachQuestions";
import { activeTrial, useWallet } from "@/lib/api/wallet";
import { CopilotSurfaceScope, useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { TeachBox } from "../../../knowledge/TeachBox";
import { countsOf } from "../test/testCopy";
import { TestSection } from "../test/TestSection";
import { TryIt } from "./tryIt";

/** Facts shown before "and N more"; the full list is on the Knowledge page. */
const FACTS_SHOWN = 5;

export function TrainingTab({ agent, slug }: { agent: Agent; slug: string }) {
  return (
    <CopilotSurfaceScope
      route="/c/{slug}/agents/{id}"
      title={`Agent: training (${agent.name})`}
      realm="client"
      facts={[
        { key: "agent_id", label: "Agent id", value: agent.id },
        { key: "name", label: "Agent name", value: agent.name },
        {
          key: "what_is_here",
          label: "What this tab holds",
          value:
            "the questions this agent needs answered, a chat and a practice call with it, what the agents know with a teach box, saved tests, and practice callers",
        },
      ]}
    >
      <Training agent={agent} slug={slug} />
    </CopilotSurfaceScope>
  );
}

function Training({ agent, slug }: { agent: Agent; slug: string }) {
  const session = useClientSession();
  const tryAccess = useWriteAccess(session, "org:manage", "try this agent");
  const wallet = useWallet(session);
  const trial = wallet.data ? activeTrial(wallet.data) : null;
  const onTrial = trial !== null && trial.test_calls_only === true;
  const [testNumber, setTestNumber] = useState("");
  const focus = useSearchParams().get(QUESTION_PARAM);

  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: "Practice call",
    realm: "client",
    fields: onTrial
      ? [
          {
            id: "agent-test-call-number",
            label: "Your phone number for a practice call",
            type: "text",
            value: testNumber,
            personal: "phone",
          },
        ]
      : [],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "agent-test-call-number") setTestNumber(asText(item.value));
      }
    },
  });

  return (
    <div className="space-y-10">
      <QuestionsToAnswer agentId={agent.id} focus={focus} headingLevel={3} />

      <Section headingLevel={3} title="Try it" description="Nothing here reaches a real caller.">
        <div className="mt-2 grid grid-cols-1 gap-8 rounded-md border border-line p-4 lg:grid-cols-2">
          <TryChat agentId={agent.id} canWrite={tryAccess.allowed} bare />
          <TryIt
            agent={agent}
            slug={slug}
            onTrial={onTrial}
            number={testNumber}
            onNumber={setTestNumber}
            bare
          />
        </div>
      </Section>

      <div className="space-y-3">
        <WhatItKnows slug={slug} />
        <SavedTestsSummary agentId={agent.id} canWrite={tryAccess.allowed} />
        <PracticeCallers agent={agent} slug={slug} />
      </div>
    </div>
  );
}

function countLine(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * What the business's agents know, folded to one line, with the teach box inside. Knowledge
 * belongs to the business and every agent answers from it (D-689), so this never offers a
 * per-agent copy; the editing happens on the Knowledge page.
 */
function WhatItKnows({ slug }: { slug: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const teach = useWriteAccess(session, "kb:write", "teach your agents");
  const knows = useKnows(session);

  let line = "Checking what your agents know…";
  let body;
  if (knows.isLoading) body = <Skeleton rows={3} label="Loading what your agents know" />;
  else if (knows.error || !knows.data) {
    line = "Could not be read.";
    body = (
      <ProblemNotice
        error={knows.error ?? new Error("We could not load what your agents know.")}
        onRetry={() => void knows.refetch()}
      />
    );
  } else {
    const { facts, items } = knows.data;
    line =
      facts.length + items.length === 0
        ? "Nothing yet."
        : `${countLine(facts.length, "fact", "facts")}${
            items.length > 0 ? `, ${countLine(items.length, "file or link", "files and links")}` : ""
          }, shared by all your agents.`;
    // Pinned facts first, as on the Knowledge page: they are in every call.
    const ordered = [...facts.filter((f) => f.pinned), ...facts.filter((f) => !f.pinned)];
    const shown = ordered.slice(0, FACTS_SHOWN);
    const more = ordered.length - shown.length;
    body = shown.length > 0 ? (
      <ul className="divide-y divide-line border-y border-line">
        {shown.map((fact) => (
          <li key={fact.id} className="flex items-start gap-2 py-2.5 text-body text-ink">
            {fact.pinned ? (
              <Pin aria-label="Always said" className="mt-1 h-3.5 w-3.5 shrink-0 text-brand-strong" />
            ) : (
              <span aria-hidden className="mt-1 h-3.5 w-3.5 shrink-0" />
            )}
            <span className="min-w-0 [overflow-wrap:anywhere]">{fact.text}</span>
          </li>
        ))}
        {more > 0 ? (
          <li className="py-2.5 text-meta text-ink-muted">and {countLine(more, "more fact", "more facts")}</li>
        ) : null}
      </ul>
    ) : null;
  }

  return (
    <Disclosure variant="card" headingLevel={3} title="What it knows" subtitle={line}>
      <div className="space-y-6">
        {body}
        <Link href={href(`/c/${slug}/knowledge`)} className={`${TEXT_ACTION} inline-flex items-center gap-1.5`}>
          <BookOpen aria-hidden className="h-4 w-4" />
          Open What your agents know
        </Link>
        <TeachBox allowed={teach.allowed} reason={teach.reason} headingLevel={3} />
      </div>
    </Disclosure>
  );
}

/** The saved tests, folded to how many there are and when they last ran. */
function SavedTestsSummary({ agentId, canWrite }: { agentId: string; canWrite: boolean }) {
  const session = useClientSession();
  const cases = useTestCases(session, agentId);
  let line = "Checking your saved tests…";
  if (cases.error) line = "Could not be read.";
  else if (cases.data) {
    const all = cases.data.cases;
    const running = all.some((c) => c.status !== "idle");
    line =
      all.length === 0
        ? "None yet. Make one from a call, or write one."
        : `${countLine(all.length, "saved test", "saved tests")}${running ? ", running now" : ""}.`;
  }
  return (
    <Disclosure variant="card" headingLevel={3} title="Saved tests" subtitle={line}>
      <SavedTests agentId={agentId} canWrite={canWrite} headingLevel={3} framed={false} />
    </Disclosure>
  );
}

/**
 * The AI-judged run, folded. Its closed row states the last result as a fact (UX-DOCTRINE
 * §3: a disclosure advertises what is inside it), and it opens by itself while a run is
 * going or suggested fixes wait for review.
 */
function PracticeCallers({ agent, slug }: { agent: Agent; slug: string }) {
  const session = useClientSession();
  const tests = useTestConversations(session, agent.id);
  const latest = tests.data?.latest ?? null;
  const busy =
    latest !== null &&
    (latest.status === "queued" || latest.status === "running" || latest.improving === true);
  const waiting =
    latest?.status === "done" && latest.improvement !== null && latest.improvement !== undefined;
  // Null until the reader opens or closes it; until then it is open exactly when it opened
  // by itself.
  const [open, setOpen] = useState<boolean | null>(null);

  let fact = "Not run yet.";
  // "Not run yet" is a claim about the agent, so it waits for the read that can make it.
  if (!tests.data) {
    fact = tests.error ? "The last run could not be read." : "Checking the last run…";
  } else if (busy) fact = "Running now.";
  else if (latest?.status === "failed") fact = "The last test did not finish.";
  else if (latest?.status === "done") {
    const counts = countsOf(latest.results);
    fact = `Last run: ${counts.passed} of ${counts.passed + counts.failing} right${
      counts.unchecked > 0 ? `, ${counts.unchecked} to read` : ""
    }.${waiting ? " Fixes are waiting." : ""}`;
  }
  const shown = open ?? (busy || waiting);

  return (
    <Disclosure
      variant="card"
      headingLevel={3}
      title="Practice callers"
      subtitle={fact}
      defaultOpen={busy || waiting}
      onToggle={setOpen}
    >
      <TestSection agent={agent} slug={slug} declare={shown} />
    </Disclosure>
  );
}
