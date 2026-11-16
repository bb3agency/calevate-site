"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ArrowLeft, X } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { focusMain } from "@/components/copilot/workspace/AssistantWorkspace";
import { ProgressBar } from "@/components/interior/progress-bar";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { agentKeys, useAgents, type Agent } from "@/lib/api/agents";
import { useBusinessProfile } from "@/lib/api/businessProfile";
import type { CallSummary } from "@/lib/api/client";
import { useDismissFirstRun, useFirstRun, type FirstRunDocument } from "@/lib/api/firstRun";
import { useCalls, useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { pipLocked, usePipConsent } from "@/lib/copilot/conversation";
import { fallbackSurface } from "@/lib/copilot/fallback";
import { resolveDestination } from "@/lib/copilot/navigate";
import { useCopilotSurface, useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { useCampaignWorkspace } from "@/lib/api/campaignWorkspace";
import { useInboundLine } from "@/lib/api/inboundLines";
import {
  STEPS,
  defaultLanguage,
  documentLine,
  firstAgentOf,
  firstWorkOf,
  introFor,
  piecesOf,
  quickRepliesFor,
  resumeStage,
  stepIndexOf,
  voicePickNote,
  type FirstWork,
  type Piece,
  type Stage,
} from "@/lib/firstAgent";

import { AgentStep } from "./AgentStep";
import { AgentTakingShape } from "./AgentTakingShape";
import { BriefStep } from "./BriefStep";
import { HearItStep } from "./HearItStep";
import { QuestionsStep } from "./QuestionsStep";
import { ResultStep, TeamStep } from "./ResultStep";
import { StepRail } from "./shell";
import { WorkStep } from "./WorkStep";

/** The route this screen declares to Pip; the server's first-agent guide is keyed on it. */
export const FIRST_AGENT_ROUTE = "/c/{slug}/agents/first";

/** Where a finished step on the rail goes back to, by its index in `STEPS`. */
const RAIL_STAGES: readonly Stage[] = ["brief", "agent", "work", "hear"];

/**
 * "MEET YOUR AGENT" (D-855, founder 23 Oct 2026): a new owner's first run.
 *
 * Four steps on a rail (Phase 3b, founder 16 Nov 2026): About your business → Name and voice
 * → What first? → Hear it, then the result and going live, with the agent taking shape beside
 * them. The agent is staff, a name and a voice; what it says belongs to the first work it is
 * given, a draft inbound line or a draft campaign, which Pip writes. It replaces the business
 * setup wizard as the first thing after sign-up; the wizard stays on the dashboard checklist
 * and in Settings.
 *
 * WHERE THE OWNER IS COMES FROM THE SERVER (`GET /v1/first-run`, the agents, the line or
 * campaign it drafted, the agent's calls), so a reload, another device or a return next week
 * lands on the same step. Moving
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
  const write = useWriteAccess(session, "org:manage", "build an agent");
  // The first run is the owner's (`org:manage`): a colleague is told so rather than shown
  // the 403 the read would have met.
  const run = useFirstRun(session, write.allowed);
  const agents = useAgents(session);
  const profile = useBusinessProfile(session);
  const consent = usePipConsent(session);
  const dismiss = useDismissFirstRun(session);
  // Skipping leaves this screen whatever the answer (onSettled below), so a refusal goes to
  // the toast stack, which outlives the navigation; an inline notice would vanish with it.
  const dismissFeedback = useActionFeedback(dismiss, { errorTitle: "Could not put this away" });
  const agent = firstAgentOf(agents.data, run.data);
  const calls = useCalls(session, { agent_id: agent?.id, limit: 1 }, agent !== null);
  // The first work's own read, for its script and Pip's progress on it; each polls while
  // Pip is writing.
  const lineId = run.data?.line_id ?? null;
  const campaignId = run.data?.campaign_id ?? null;
  const line = useInboundLine(session, lineId ?? "", lineId !== null);
  const campaign = useCampaignWorkspace(session, campaignId ?? "", campaignId !== null);
  const work = firstWorkOf(run.data, { line: line.data, campaign: campaign.data });
  const [stage, setStage] = useState<Stage | null>(null);
  const [pip, setPip] = useState(false);
  const [lastCall, setLastCall] = useState<CallSummary | null>(null);
  // The brief typed or spoken but not yet saved: kept here because the brief step unmounts on
  // Back and on "Talk it through with Pip", and each spoken piece used a recording.
  const [briefDraft, setBriefDraft] = useState<string | null>(null);

  const workLoaded = (lineId === null || line.data !== undefined) && (campaignId === null || campaign.data !== undefined);
  const loaded =
    run.data !== undefined &&
    agents.data !== undefined &&
    (agent === null || calls.data !== undefined) &&
    (workLoaded || line.isError || campaign.isError);
  const pieces = piecesOf({ run: run.data, agent, calls: calls.data, work });
  if (stage === null && loaded) setStage(resumeStage({ run: run.data, agent, calls: calls.data, work }));

  // The agent's row learns its AI notice from a job after "Name and voice", and its voice
  // from the picker; reading the roster again when the work's script lands keeps the card true.
  const workReady = work?.ready === true;
  useEffect(() => {
    if (workReady) void queries.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) });
  }, [workReady, queries, session.orgSlug]);

  const pipOff = session.impersonateOrg
    ? `${ASSISTANT_NAME} isn't available while you view this account.`
    : consent.data && pipLocked(consent.data) && !consent.data.can_accept
      ? `${ASSISTANT_NAME} is off for this account until its owner turns it on.`
      : null;

  const skip = () => dismiss.mutate(null, { onSettled: () => router.push(href(`/c/${slug}`)) });

  const step = stage === null ? 0 : stepIndexOf(stage);
  const call = lastCall ?? calls.data?.[0] ?? null;

  // The name step seeds its language from the profile once, on mount; drawn before the
  // profile arrives it would keep Telugu for an account that chose another language. A
  // failed profile read falls back to Telugu rather than holding the step.
  const agentWaitsForProfile = stage === "agent" && profile.isPending;

  let body: React.ReactNode;
  if (!write.unknown && !write.allowed) body = <RestrictionNote reason={write.reason} />;
  else if (run.isError) body = <ProblemNotice error={run.error} onRetry={() => void run.refetch()} />;
  else if (agents.isError) body = <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />;
  // `loaded` waits on the agent's calls, so a failed read would otherwise hold the skeleton for good.
  else if (agent !== null && calls.isError)
    body = <ProblemNotice error={calls.error} onRetry={() => void calls.refetch()} />;
  else if (!loaded || stage === null || write.unknown || agentWaitsForProfile)
    body = <Skeleton rows={6} label="Getting your agent ready…" />;
  else if (pip)
    body = (
      <PipPanel
        slug={slug}
        agent={agent}
        pieces={pieces}
        documents={run.data?.documents ?? []}
        defaultName={run.data?.default_agent.name ?? ""}
        work={work}
        onClose={() => setPip(false)}
      />
    );
  else {
    const data = run.data!;
    // A step that needs what an earlier one makes goes back to that one when it is missing.
    const lost = (label: string) => <Skeleton rows={4} label={label} />;
    switch (stage) {
      case "brief":
        body = (
          <BriefStep
            run={data}
            draft={briefDraft}
            onDraft={setBriefDraft}
            onDone={() => setStage("questions")}
            onPip={() => setPip(true)}
            pipOff={pipOff}
          />
        );
        break;
      case "questions":
        body = <QuestionsStep run={data} onBack={() => setStage("brief")} onDone={() => setStage("agent")} />;
        break;
      case "agent":
        body = (
          <AgentStep
            run={data}
            agent={agent}
            defaultLanguage={defaultLanguage(profile.data?.languages)}
            onBack={() => setStage("questions")}
            onDone={() => setStage(work?.ready ? "hear" : "work")}
          />
        );
        break;
      case "work":
        body = agent ? (
          <WorkStep
            run={data}
            agent={agent}
            work={work}
            onBack={() => setStage("agent")}
            onDone={() => setStage("hear")}
          />
        ) : (
          lost("Getting your agent ready…")
        );
        break;
      case "hear":
        body =
          agent && work?.ready ? (
            <HearItStep
              agent={agent}
              work={work}
              jobs={data.jobs}
              calls={calls.data}
              onBack={() => setStage("work")}
              onEnded={(ended) => {
                setLastCall(ended);
                setStage("result");
              }}
            />
          ) : (
            lost("Getting its work ready…")
          );
        break;
      case "result":
        body =
          agent && call && work ? (
            <ResultStep
              agent={agent}
              work={work}
              call={call}
              onCallAgain={() => setStage("hear")}
              onNext={() => setStage("team")}
            />
          ) : (
            lost("Getting your call")
          );
        break;
      default:
        body = agent ? (
          <TeamStep agent={agent} run={data} work={work} onBack={() => setStage(call ? "result" : "hear")} />
        ) : null;
    }
  }

  const voiceStep = run.data?.build.steps.find((entry) => entry.step === "voice");
  const voiceNote = voicePickNote(voiceStep?.fallback, voiceStep?.not_female);
  const card = (compact: boolean) => (
    <AgentTakingShape
      agent={agent}
      jobs={work ? (run.data?.jobs ?? []) : []}
      language={run.data?.language_primary ?? null}
      brief={run.data?.brief ?? null}
      pieces={pieces}
      loaded={loaded}
      compact={compact}
      voiceNote={voiceNote}
      documents={run.data?.documents ?? []}
      work={work}
    />
  );

  return (
    <div className="pb-8">
      {/* One row from `lg`: the screen's name, the four steps, and the way out, so the step
          itself starts high enough to fit a laptop screen. */}
      <div className="mb-5 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-3 lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:gap-x-8">
        <h1 className="text-title text-ink">Meet your agent</h1>
        <div
          className="col-span-2 row-start-2 min-w-0 lg:col-span-1 lg:col-start-2 lg:row-start-1"
          role="group"
          aria-label="Your progress"
        >
          <StepRail
            steps={STEPS}
            current={step}
            layout="row"
            onGo={(to) => to < step && setStage(RAIL_STAGES[to] ?? "brief")}
          />
        </div>
        {write.allowed && (
          <ActionButton
            variant="secondary-sm"
            className="shrink-0 justify-self-end"
            status={dismissFeedback.status}
            successLabel="Skipped"
            onClick={skip}
          >
            <X aria-hidden className="h-3.5 w-3.5" />
            Skip for now
          </ActionButton>
        )}
      </div>

      {/* Two columns from `lg` while the agent is being made: the step, as wide as its cards
          need, and the agent taking shape beside it. Once it is made (its first call and
          after) the card only restates steps 1 and 2 and competes with the call being read,
          so the step stands alone. The rail sits above both, so the step is not squeezed. */}
      {stage === "result" || stage === "team" ? (
        // The team step is two columns from `lg` (the agent, then what is next), so it takes
        // the width the call read-back does not need.
        <section className={`min-w-0 ${stage === "team" ? "max-w-5xl" : "max-w-2xl"}`} aria-label="This step">
          {body}
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,20rem)] lg:gap-8 xl:gap-12">
          <div className="min-w-0 lg:hidden">{card(true)}</div>
          <section className="min-w-0 max-w-2xl" aria-label="This step">
            {body}
          </section>
          <aside className="hidden min-w-0 lg:block" aria-label="Your agent as it takes shape">
            <div className="space-y-3 lg:sticky lg:top-4">
              <Meter pieces={pieces} loaded={loaded} />
              {card(false)}
            </div>
          </aside>
        </div>
      )}
    </div>
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
  documents,
  defaultName,
  work,
  onClose,
}: {
  slug: string;
  agent: Agent | null;
  pieces: readonly Piece[];
  documents: readonly FirstRunDocument[];
  defaultName: string;
  work: FirstWork | null;
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
    facts: surfaceFacts(agent, pieces, documents, defaultName, work),
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
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Back to the steps
      </button>
    </div>
  );
}

/** What Pip is told about this screen: the pieces and the agent's current values, by name
 *  (the screen guide skips any piece marked done). The agent has no script of its own, so
 *  what it says is the work's (Phase 3b). */
function surfaceFacts(
  agent: Agent | null,
  pieces: readonly Piece[],
  documents: readonly FirstRunDocument[],
  defaultName: string,
  work: FirstWork | null,
) {
  const facts = [
    { key: "default_name", label: "The default agent's name", value: defaultName },
    {
      key: "first_work",
      label: "Its first work",
      value: work ? (work.kind === "line" ? "Answering the business's calls" : "Calling people") : "not chosen yet",
    },
    {
      key: "pieces",
      label: "Pieces of the first agent (done or to do)",
      value: pieces.map((piece) => `${piece.label}: ${piece.done ? "done" : "to do"}`).join("; "),
    },
    {
      key: "documents",
      label: "Files the owner added for the agent to read",
      value: documents.map((document) => `${document.name}: ${documentLine(document)}`).join("; ") || "none",
    },
  ];
  if (agent === null) return [...facts, { key: "agent", label: "The agent being set up", value: "none yet" }];
  return [
    ...facts,
    { key: "agent_id", label: "The agent's id", value: agent.id },
    { key: "agent_name", label: "Its name", value: agent.name },
    {
      key: "agent_language",
      label: "Its main language",
      value: agent.language_primary,
    },
    {
      key: "agent_voice",
      label: "Its voice id",
      value: agent.engine_voice_id ?? "none chosen yet",
    },
  ];
}
