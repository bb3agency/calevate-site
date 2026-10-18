"use client";

/**
 * TRAINING — everything that teaches this agent or checks what it learnt (D-825, founder
 * 19 Oct 2026, decision 5a08c365), in the order an owner uses it:
 *
 * 1. Teach it: the business's one teach box (Pip sorts it into facts and rules; the owner
 *    keeps each before it is saved, D-821).
 * 2. What it knows: the business's knowledge, shown read-only with the way to manage it.
 *    Knowledge belongs to the business and every agent answers from it (D-689), so this
 *    tab never offers a per-agent copy.
 * 3. Try it: a chat with the live agent, and a practice call on a real phone. Phone only;
 *    there is no in-browser call.
 * 4. Where it struggled on real calls: the open questions it could not answer, each with
 *    Teach the answer and Dismiss.
 * 5. Saved tests, made from real calls.
 * 6. Practice callers (the AI-judged test run) behind a closed disclosure at the foot. Real
 *    calls come first (decision 565c8ef2); the disclosure opens by itself while a run or a
 *    set of suggested fixes is waiting, so a fix Pip prepared is never hidden.
 *
 * ONE COPILOT SURFACE. The registry answers with the newest declaration, so the tab
 * declares through the teach box: its field, plus the practice-call number on a trial and
 * this agent's facts. The practice-callers panel declares its own only while open.
 */

import Link from "next/link";
import { useState } from "react";
import { BookOpen, Pin } from "lucide-react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { SavedTests } from "@/components/improvement/SavedTests";
import { TryChat } from "@/components/improvement/TryChat";
import { Disclosure, ProblemNotice, Skeleton } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useTestConversations } from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useKnows } from "@/lib/api/teach";
import { activeTrial, useWallet } from "@/lib/api/wallet";
import { asText } from "@/lib/copilot/types";

import { KnowledgeGaps } from "../../../KnowledgeGaps";
import { TeachBox } from "../../../knowledge/TeachBox";
import { countsOf } from "../test/testCopy";
import { TestSection } from "../test/TestSection";
import { TryIt } from "./tryIt";

/** Facts shown before "and N more"; the full list is on the Knowledge page. */
const FACTS_SHOWN = 5;

export function TrainingTab({ agent, slug }: { agent: Agent; slug: string }) {
  const session = useClientSession();
  const teach = useWriteAccess(session, "kb:write", "teach your agents");
  const tryAccess = useWriteAccess(session, "org:manage", "try this agent");
  const wallet = useWallet(session);
  const trial = wallet.data ? activeTrial(wallet.data) : null;
  const onTrial = trial !== null && trial.test_calls_only === true;
  // Owned here so the one declaration (through the teach box) can offer it as a field.
  const [testNumber, setTestNumber] = useState("");

  return (
    <div className="max-w-3xl space-y-12">
      <TeachBox
        allowed={teach.allowed}
        reason={teach.reason}
        headingLevel={3}
        surface={{
          route: "/c/{slug}/agents/{id}",
          title: `Agent: training (${agent.name})`,
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
          facts: [
            { key: "agent_id", label: "Agent id", value: agent.id },
            { key: "name", label: "Agent name", value: agent.name },
            {
              key: "what_is_here",
              label: "What this tab holds",
              value:
                "a teach box for facts and rules, what the agents know, a chat and a practice call with this agent, the questions it could not answer on real calls, saved tests, and practice callers",
            },
          ],
          apply: (items) => {
            for (const item of items) {
              if (item.field_id === "agent-test-call-number")
                setTestNumber(asText(item.value));
            }
          },
        }}
      />

      <WhatItKnows slug={slug} />

      <div className="grid gap-10 lg:grid-cols-2 lg:gap-8">
        <TryChat
          agentId={agent.id}
          canWrite={tryAccess.allowed}
          headingLevel={3}
        />
        <TryIt
          agent={agent}
          slug={slug}
          onTrial={onTrial}
          number={testNumber}
          onNumber={setTestNumber}
        />
      </div>

      <KnowledgeGaps agentId={agent.id} headingLevel={3} />

      <SavedTests
        agentId={agent.id}
        canWrite={tryAccess.allowed}
        headingLevel={3}
      />

      <PracticeCallers agent={agent} slug={slug} />
    </div>
  );
}

/**
 * The business's knowledge, read-only: how much there is, the pinned facts first, and the
 * way to change it. A short read rather than the Knowledge page's searchable list, because
 * here it answers "does it know about this?" and the editing happens there.
 */
function WhatItKnows({ slug }: { slug: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const knows = useKnows(session);
  const manage = (
    <Link
      href={href(`/c/${slug}/knowledge`)}
      className={`${TEXT_ACTION} inline-flex items-center gap-1.5`}
    >
      <BookOpen aria-hidden className="h-4 w-4" />
      Manage knowledge
    </Link>
  );

  let body;
  if (knows.isLoading)
    body = <Skeleton rows={3} label="Loading what your agents know" />;
  else if (knows.error || !knows.data) {
    body = (
      <ProblemNotice
        error={
          knows.error ?? new Error("We could not load what your agents know.")
        }
        onRetry={() => void knows.refetch()}
      />
    );
  } else {
    const { facts, items } = knows.data;
    // Pinned facts first, as on the Knowledge page: they are in every call and win over
    // anything else.
    const ordered = [
      ...facts.filter((f) => f.pinned),
      ...facts.filter((f) => !f.pinned),
    ];
    const shown = ordered.slice(0, FACTS_SHOWN);
    const more = ordered.length - shown.length;
    body =
      facts.length + items.length === 0 ? (
        <p className="text-body text-ink-muted">
          Nothing yet. Teach it your prices, timings and answers above.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-meta text-ink-muted">
            {countLine(facts.length, "fact", "facts")}
            {items.length > 0
              ? ` and ${countLine(items.length, "file or page", "files and pages")}`
              : ""}
            , shared by all your agents.
          </p>
          {shown.length > 0 && (
            <ul className="divide-y divide-line border-y border-line">
              {shown.map((fact) => (
                <li
                  key={fact.id}
                  className="flex items-start gap-2 py-2.5 text-body text-ink"
                >
                  {fact.pinned ? (
                    <Pin
                      aria-label="Always said"
                      className="mt-1 h-3.5 w-3.5 shrink-0 text-brand-strong"
                    />
                  ) : (
                    <span aria-hidden className="mt-1 h-3.5 w-3.5 shrink-0" />
                  )}
                  <span className="min-w-0 [overflow-wrap:anywhere]">
                    {fact.text}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {more > 0 && (
            <p className="text-meta text-ink-muted">
              and {countLine(more, "more fact", "more facts")}
            </p>
          )}
        </div>
      );
  }

  return (
    <Section headingLevel={3} title="What it knows" action={manage}>
      {body}
    </Section>
  );
}

function countLine(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
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
    (latest.status === "queued" ||
      latest.status === "running" ||
      latest.improving === true);
  const waiting =
    latest?.status === "done" &&
    latest.improvement !== null &&
    latest.improvement !== undefined;
  // Null until the reader opens or closes it; until then it is open exactly when it opened
  // by itself.
  const [open, setOpen] = useState<boolean | null>(null);

  let fact =
    "Not run yet. Practice callers ask what real callers asked, and each answer is checked.";
  if (busy) fact = "Running now.";
  else if (latest?.status === "failed") fact = "The last test did not finish.";
  else if (latest?.status === "done") {
    const counts = countsOf(latest.results);
    fact = `Last run: ${counts.passed} of ${counts.passed + counts.failing} right every time${
      counts.unchecked > 0 ? `, ${counts.unchecked} for you to read` : ""
    }.${waiting ? " Suggested fixes are waiting." : ""}`;
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
