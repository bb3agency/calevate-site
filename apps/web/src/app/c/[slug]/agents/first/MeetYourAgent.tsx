"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Check } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { focusMain } from "@/components/copilot/workspace/AssistantWorkspace";
import { ProgressBar } from "@/components/interior/progress-bar";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { agentKeys, useAgents, type Agent } from "@/lib/api/agents";
import { useBusinessProfile } from "@/lib/api/businessProfile";
import type { CallSummary } from "@/lib/api/client";
import { useDismissFirstRun, useFirstRun } from "@/lib/api/firstRun";
import { useCalls, useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { pipLocked, usePipConsent } from "@/lib/copilot/conversation";
import { fallbackSurface } from "@/lib/copilot/fallback";
import { resolveDestination } from "@/lib/copilot/navigate";
import { useCopilotSurface, useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import {
  STEPS,
  STEP_OF_STAGE,
  charCount,
  defaultLanguage,
  firstAgentOf,
  introFor,
  piecesOf,
  quickRepliesFor,
  resumeStage,
  type Piece,
  type Stage,
} from "@/lib/firstAgent";

import { AgentTakingShape } from "./AgentTakingShape";
import { BriefStep } from "./BriefStep";
import { BuildStep } from "./BuildStep";
import { HearItStep } from "./HearItStep";
import { JobStep } from "./JobStep";
import { QuestionsStep } from "./QuestionsStep";
import { ResultStep, TeamStep } from "./ResultStep";

/** The route this screen declares to Pip; the server's first-agent guide is keyed on it. */
export const FIRST_AGENT_ROUTE = "/c/{slug}/agents/first";

/**
 * "MEET YOUR AGENT" (D-855, founder 23 Oct 2026): a new owner's first run.
 *
 * Four steps on a rail, Its job → Tell it about you → Hear it → Make it yours, with the agent
 * taking shape beside them. It replaces the business setup wizard as the first thing after
 * sign-up; the wizard stays on the dashboard checklist and in Settings.
 *
 * WHERE THE OWNER IS COMES FROM THE SERVER (`GET /v1/first-run`, the agents, the agent's
 * calls), so a reload, another device or a return next week lands on the same step. Moving
 * between steps on the screen is local; the server only learns what the owner decided.
 *
 * Phone first: the rail is a row of four, the card a single line that opens, and each step's
 * one action is pinned in the thumb's reach. From `lg` the rail sits on the left, the step in
 * the middle and the card on the right.
 *
 * Pip (D-854's chat) is offered as "Talk it through with Pip instead" inside the same screen;
 * its owner consent (D-788) is unchanged.
 */
export function MeetYourAgent({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const queries = useQueryClient();
  const run = useFirstRun(session);
  const agents = useAgents(session);
  const profile = useBusinessProfile(session);
  const write = useWriteAccess(session, "org:manage", "build an agent");
  const consent = usePipConsent(session);
  const dismiss = useDismissFirstRun(session);
  const agent = firstAgentOf(agents.data, run.data);
  const calls = useCalls(session, { agent_id: agent?.id, limit: 1 }, agent !== null);
  const [stage, setStage] = useState<Stage | null>(null);
  const [pip, setPip] = useState(false);
  const [lastCall, setLastCall] = useState<CallSummary | null>(null);

  const loaded = run.data !== undefined && agents.data !== undefined && (agent === null || calls.data !== undefined);
  const pieces = piecesOf({ run: run.data, agent, calls: calls.data });
  if (stage === null && loaded) setStage(resumeStage({ run: run.data, agent, calls: calls.data }));

  // The roster read learns of the agent when the build makes it, and again as each step
  // changes it, so the card fills in while the steps tick.
  const buildStatus = run.data?.build.status;
  const ticked = run.data?.build.steps.filter((entry) => entry.state !== "waiting").length ?? 0;
  useEffect(() => {
    if (ticked > 0) void queries.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) });
  }, [ticked, buildStatus, queries, session.orgSlug]);

  const pipOff = session.impersonateOrg
    ? `${ASSISTANT_NAME} isn't available while you view this account.`
    : consent.data && pipLocked(consent.data) && !consent.data.can_accept
      ? `${ASSISTANT_NAME} is off for this account until its owner turns it on.`
      : null;

  const skip = () => dismiss.mutate(null, { onSettled: () => router.push(href(`/c/${slug}`)) });

  const step = stage === null ? 0 : STEPS.findIndex((entry) => entry.id === STEP_OF_STAGE[stage]);
  const call = lastCall ?? calls.data?.[0] ?? null;

  let body: React.ReactNode;
  if (run.isError) body = <ProblemNotice error={run.error} onRetry={() => void run.refetch()} />;
  else if (agents.isError) body = <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />;
  else if (!loaded || stage === null || write.unknown) body = <Skeleton rows={6} label="Getting your agent ready…" />;
  else if (!write.allowed) body = <RestrictionNote reason={write.reason} />;
  else if (pip) body = <PipPanel slug={slug} agent={agent} pieces={pieces} onClose={() => setPip(false)} />;
  else {
    const data = run.data!;
    switch (stage) {
      case "job":
        body = <JobStep run={data} defaultLanguage={defaultLanguage(profile.data?.languages)} onDone={() => setStage("brief")} />;
        break;
      case "brief":
        body = (
          <BriefStep run={data} onBack={() => setStage("job")} onDone={() => setStage("questions")} onPip={() => setPip(true)} pipOff={pipOff} />
        );
        break;
      case "questions":
        body = <QuestionsStep run={data} onBack={() => setStage("brief")} onBuilding={() => setStage("build")} />;
        break;
      case "build":
        body = <BuildStep run={data} agent={agent} onBack={() => setStage("brief")} onDone={() => setStage("hear")} />;
        break;
      case "hear":
        body = agent ? (
          <HearItStep
            agent={agent}
            job={data.job}
            calls={calls.data}
            onBack={() => setStage("build")}
            onEnded={(ended) => {
              setLastCall(ended);
              setStage("result");
            }}
          />
        ) : (
          <Skeleton rows={4} label="Getting your agent ready…" />
        );
        break;
      case "result":
        body =
          agent && call ? (
            <ResultStep
              agent={agent}
              call={call}
              placedAt={Date.parse(call.started_at ?? "") || Date.now()}
              onCallAgain={() => setStage("hear")}
              onNext={() => setStage("team")}
            />
          ) : (
            <Skeleton rows={4} label="Getting your call" />
          );
        break;
      default:
        body = agent ? <TeamStep agent={agent} run={data} onBack={() => setStage(call ? "result" : "hear")} /> : null;
    }
  }

  const card = (compact: boolean) => (
    <AgentTakingShape
      agent={agent}
      job={run.data?.job ?? null}
      language={run.data?.language_primary ?? null}
      brief={run.data?.brief ?? null}
      pieces={pieces}
      loaded={loaded}
      compact={compact}
      voiceFallback={run.data?.build.steps.find((entry) => entry.step === "voice")?.fallback ?? null}
    />
  );

  return (
    <div className="pb-8">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-title text-ink">Meet your agent</h1>
          <p className="mt-0.5 hidden text-meta text-ink-muted sm:block">
            A few minutes to build, then it rings your phone so you hear it.
          </p>
        </div>
        <button type="button" className={`${TEXT_ACTION} shrink-0`} onClick={skip} disabled={dismiss.isPending}>
          Skip for now
        </button>
      </div>
      {dismiss.error ? <ProblemNotice error={dismiss.error} /> : null}

      <div className="grid gap-5 lg:grid-cols-[13rem_minmax(0,1fr)_minmax(18rem,22rem)] lg:gap-8">
        <aside className="min-w-0 space-y-4" aria-label="Your progress">
          <Rail current={step} onGo={(to) => to < step && setStage(to === 0 ? "job" : to === 1 ? "brief" : "hear")} />
          <Meter pieces={pieces} loaded={loaded} />
        </aside>
        <div className="min-w-0 lg:hidden">{card(true)}</div>
        <section className="min-w-0 max-w-xl" aria-label="This step">
          {body}
        </section>
        <aside className="hidden min-w-0 lg:block" aria-label="Your agent as it takes shape">
          <div className="lg:sticky lg:top-4">{card(false)}</div>
        </aside>
      </div>
    </div>
  );
}

/**
 * The four steps. A row of four on a phone (the current one named under it), a column with
 * every name from `lg`. A finished step can be gone back to.
 */
function Rail({ current, onGo }: { current: number; onGo: (step: number) => void }) {
  return (
    <nav aria-label="Steps">
      <ol className="grid grid-cols-4 gap-1.5 lg:grid-cols-1 lg:gap-1">
        {STEPS.map((entry, index) => {
          const done = index < current;
          const here = index === current;
          const tile = (
            <>
              <span
                aria-hidden
                className={`grid h-7 w-7 shrink-0 place-items-center rounded-[8px] border text-[12px] font-medium tabular-nums ${
                  done ? "border-brand-strong bg-brand-strong text-white" : here ? "border-ink/40 text-ink" : "border-line text-ink-faint"
                }`}
              >
                {done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : index + 1}
              </span>
              <span
                className={`hidden text-body lg:inline ${here ? "font-medium text-ink" : done ? "text-ink-muted" : "text-ink-faint"}`}
              >
                {entry.label}
              </span>
              <span className="sr-only lg:hidden">{entry.label}</span>
            </>
          );
          const bar = <span aria-hidden className={`h-1 rounded-full lg:hidden ${done || here ? "bg-brand-strong" : "bg-line"}`} />;
          return (
            <li key={entry.id} aria-current={here ? "step" : undefined} className="flex min-w-0 flex-col gap-1.5 lg:block">
              {bar}
              {done ? (
                <button
                  type="button"
                  onClick={() => onGo(index)}
                  className="press hidden w-full items-center gap-3 rounded-md px-1 py-1 text-left hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand lg:flex"
                >
                  {tile}
                  <span className="sr-only">, done. Go back to it</span>
                </button>
              ) : (
                <span className="hidden items-center gap-3 px-1 py-1 lg:flex">{tile}</span>
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-meta text-ink-muted lg:hidden">
        Step {current + 1} of {STEPS.length}: <span className="font-medium text-ink">{STEPS[current]?.label}</span>
      </p>
    </nav>
  );
}

/** Pieces of the agent done, starting above zero: the account is done already. */
function Meter({ pieces, loaded }: { pieces: readonly Piece[]; loaded: boolean }) {
  const done = pieces.filter((piece) => piece.done).length;
  return (
    <div className="hidden lg:block">
      <ProgressBar
        value={loaded ? done : null}
        max={pieces.length}
        label={loaded ? `${done} of ${pieces.length} ready` : "Your agent"}
        pendingLabel="Checking"
        completeLabel="Your agent is ready"
      />
    </div>
  );
}

/** D-854's chat with Pip, in place of the steps, beside the same card. */
function PipPanel({
  slug,
  agent,
  pieces,
  onClose,
}: {
  slug: string;
  agent: Agent | null;
  pieces: readonly Piece[];
  onClose: () => void;
}) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const agentName = agent?.name ?? null;
  useCopilotSurface({
    route: FIRST_AGENT_ROUTE,
    title: "Meet your agent",
    realm: "client",
    fields: [],
    facts: surfaceFacts(agent, pieces),
    apply: noFill,
  });
  const declared = useCopilotSurfaceHolder();
  const holder = useMemo<SurfaceHolder>(() => {
    const surface = fallbackSurface(FIRST_AGENT_ROUTE, "client");
    return { read: () => surface };
  }, []);
  const onNavigate = useCallback(
    (destination: { route: string }) => {
      const path = resolveDestination(destination.route, slug);
      if (path === null) return;
      router.push(href(path));
      focusMain();
    },
    [href, router, slug],
  );
  return (
    <div className="space-y-3">
      <CopilotPanel
        session={session}
        holder={declared ?? holder}
        realm="client"
        labelledBy="first-agent-pip"
        placement="page"
        onNavigate={onNavigate}
        quickReplies={quickRepliesFor(agent !== null)}
        intro={introFor(agentName)}
      />
      <span id="first-agent-pip" className="sr-only">
        {ASSISTANT_NAME}, building your first agent with you
      </span>
      <button type="button" className={TEXT_ACTION} onClick={onClose}>
        Back to the steps
      </button>
    </div>
  );
}

/** What Pip is told about this screen: the pieces and the agent's current values, by name
 *  (the screen guide skips any piece marked done). */
function surfaceFacts(agent: Agent | null, pieces: readonly Piece[]) {
  const facts = [
    {
      key: "pieces",
      label: "Pieces of the first agent (done or to do)",
      value: pieces.map((piece) => `${piece.label}: ${piece.done ? "done" : "to do"}`).join("; "),
    },
  ];
  if (agent === null) return [...facts, { key: "agent", label: "The agent being built", value: "none yet" }];
  const opening = agent.script_opening_line.trim();
  return [
    ...facts,
    { key: "agent_id", label: "The agent's id", value: agent.id },
    { key: "agent_name", label: "Its name", value: agent.name },
    { key: "agent_language", label: "Its main language", value: agent.language_primary },
    { key: "agent_voice", label: "Its voice id", value: agent.engine_voice_id ?? "none chosen yet" },
    {
      key: "opening_line",
      label: `Its opening line (${charCount(opening)} characters)`,
      value: opening || "none written yet",
    },
    {
      key: "notes_down",
      label: "What it notes down",
      value: agent.extraction_fields.map((field) => field.label).join(", ") || "nothing yet",
    },
  ];
}
