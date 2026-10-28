"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { TaskSteps, type TaskStep } from "@/components/interior/task-steps";
import { EmptyState } from "@/components/console/emptyState";
import { PRIMARY_BUTTON, ProblemNotice, RestrictionNote, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { isDeleted } from "@/lib/agentState";
import { useAgentLifecycle, useAgents, type Agent } from "@/lib/api/agents";
import {
  useDismissGoLive,
  useFinishGoLive,
  goLiveKey,
  useGoLive,
  type GoLive,
  type GoLiveAgentMove,
  type GoLiveStep,
} from "@/lib/api/goLive";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { StepRail, StepScreen } from "../agents/first/shell";
import { GO_LIVE } from "../setup/_ui/copy";
import { Why } from "../setup/_ui/Why";

/** The route this screen lives on, for links into it. */
export const GO_LIVE_ROUTE = "/c/{slug}/go-live";

export const GO_LIVE_STEPS = [
  { id: "move", label: "Move your agents" },
  { id: "verify", label: "Verify your business" },
  { id: "number", label: "Get your number" },
  { id: "switch_on", label: "Switch it on" },
] as const;

type Stage = (typeof GO_LIVE_STEPS)[number]["id"];

/** Where a guide that is not finished picks up: the server's first step not done. */
export function stageOf(current: GoLiveStep): Stage {
  return current === "done" ? "switch_on" : current;
}

/**
 * "GO LIVE" (D-859, founder 23 Oct 2026): the owner's guide after the first payment, on
 * "Meet your agent"'s shell (D-855): its rail, one step at a time, the action pinned in the
 * thumb's reach on a phone.
 *
 * 1. Moving your agents: the real move, agent by agent, ticked as the server records each.
 * 2. Verify your business: the existing business check.
 * 3. Get your number: the existing number purchase.
 * 4. Switch it on: each agent's own switch, refused in the server's words.
 *
 * Where the owner is comes from the server (`GET /v1/go-live`), so a reload or another device
 * lands on the same step. Nothing names a provider (D-679).
 */
export function GoLiveGuide({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const guide = useGoLive(session);
  const write = useWriteAccess(session, "org:manage", "go live");
  const dismiss = useDismissGoLive(session);
  // The skip leaves this page whatever the answer, so a failure is told in the toast stack
  // (it outlives the navigation); an inline notice here would never be seen.
  const dismissFeedback = useActionFeedback(dismiss, { errorTitle: "Could not put the guide away" });
  const [stage, setStage] = useState<Stage | null>(null);
  // The server's step as last read. When the poll moves it (the check passed, the number
  // was approved), an owner still on the step it moved from is taken on, as the waiting
  // steps promise; one who went Back to another step is left where they are.
  const [serverStage, setServerStage] = useState<Stage | null>(null);
  if (guide.data !== undefined) {
    const now = stageOf(guide.data.current);
    if (now !== serverStage) {
      if (stage === null || stage === serverStage) setStage(now);
      setServerStage(now);
    }
  }

  const skip = () => dismiss.mutate(undefined, { onSettled: () => router.push(href(`/c/${slug}`)) });
  const step = stage === null ? 0 : GO_LIVE_STEPS.findIndex((entry) => entry.id === stage);
  const go = (to: Stage) => setStage(to);

  let body: React.ReactNode;
  if (guide.isError) body = <ProblemNotice error={guide.error} onRetry={() => void guide.refetch()} />;
  else if (guide.data === undefined || stage === null || write.unknown) body = <Skeleton rows={5} label="Checking where you are…" />;
  else if (!write.allowed) body = <RestrictionNote reason={write.reason} />;
  else {
    const data = guide.data;
    switch (stage) {
      case "move":
        body = <MoveStep guide={data} onNext={() => go("verify")} />;
        break;
      case "verify":
        body = (
          <VerifyStep
            guide={data}
            verifyHref={href(`/c/${slug}/verify-business`)}
            onBack={() => go("move")}
            onNext={() => go("number")}
          />
        );
        break;
      case "number":
        body = (
          <NumberStep
            guide={data}
            numberHref={href(`/c/${slug}/phone-number`)}
            onBack={() => go("verify")}
            onNext={() => go("switch_on")}
          />
        );
        break;
      default:
        body = (
          <SwitchOnStep
            guide={data}
            agentHref={(id) => href(`/c/${slug}/agents/${id}`)}
            newAgentHref={href(`/c/${slug}/agents/new`)}
            onBack={() => go("number")}
            onFinished={() => router.push(href(`/c/${slug}`))}
          />
        );
    }
  }

  return (
    <div className="pb-8">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-title text-ink">Go live</h1>
          <p className="mt-0.5 hidden text-meta text-ink-muted sm:block">{GO_LIVE.subtitle}</p>
        </div>
        <button
          type="button"
          className={`${TEXT_ACTION} shrink-0`}
          onClick={skip}
          disabled={dismissFeedback.status === "pending"}
          aria-busy={dismissFeedback.status === "pending" || undefined}
        >
          {dismissFeedback.status === "pending" ? GO_LIVE.skipping : GO_LIVE.skip}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-8">
        <aside className="min-w-0" aria-label="Your progress">
          <StepRail steps={GO_LIVE_STEPS} current={step} onGo={(to) => to < step && go(GO_LIVE_STEPS[to].id)} />
        </aside>
        <section className="min-w-0 max-w-xl" aria-label="This step">
          {body}
        </section>
      </div>
    </div>
  );
}

const MOVE_META: Record<GoLiveAgentMove["state"], string> = {
  moved: "On your account",
  moving: "Moving",
  finishing: "We're finishing this for you",
};

const ORDER: Record<GoLiveAgentMove["state"], number> = { moved: 0, moving: 1, finishing: 2 };

/** The agents in the order the checklist ticks them: moved, then moving, then ours to finish. */
export function moveChecklist(agents: readonly GoLiveAgentMove[]): {
  steps: TaskStep[];
  current: number;
  held: boolean;
} {
  const sorted = [...agents].sort((a, b) => ORDER[a.state] - ORDER[b.state]);
  const current = sorted.filter((agent) => agent.state === "moved").length;
  return {
    steps: sorted.map((agent) => ({ id: agent.agent_id, label: agent.name, meta: MOVE_META[agent.state] })),
    current,
    // The step after the moved ones is ours to finish: shown as held, never as a spinner.
    held: sorted[current]?.state === "finishing",
  };
}

/**
 * Each step's words: a title, ONE short line (`hint`), and the longer reason behind a "Why?"
 * tap (`why`) for an owner who wants it ("buttons, not paragraphs").
 */
type StepCopy = { title: string; hint: string; why?: string };

/** The step's short line, with its reason behind a tap when it has one. */
function hintOf(copy: StepCopy) {
  return (
    <>
      {copy.hint}
      {copy.why ? <Why>{copy.why}</Why> : null}
    </>
  );
}

export const MOVE_COPY: Record<GoLive["move"]["state"], StepCopy> = {
  waiting_for_account: {
    title: "Setting up your calling account",
    hint: "Your agents keep working meanwhile.",
    why: "Your agents move to your own account as soon as it is ready.",
  },
  moving: {
    title: "Moving your agents…",
    hint: "Nothing changes for your callers.",
    why: "Each agent moves to your own account and keeps working while it moves.",
  },
  finishing: {
    title: "We're finishing this for you",
    hint: "You can carry on.",
    why: "One of your agents needs a step on our side. We've been told, and it keeps working meanwhile.",
  },
  done: {
    title: "Your agents are on your account",
    hint: "New agents are made there too.",
  },
};

function MoveStep({ guide, onNext }: { guide: GoLive; onNext: () => void }) {
  const copy = MOVE_COPY[guide.move.state];
  const list = moveChecklist(guide.move.agents);
  const more = guide.move.total - guide.move.agents.length;
  return (
    <StepScreen
      title={copy.title}
      hint={guide.move.total === 0 && guide.move.state === "done" ? "You had nothing to move." : hintOf(copy)}
      primary={
        <>
          Verify your business
          <ArrowRight aria-hidden className="h-4 w-4" />
        </>
      }
      onSubmit={onNext}
    >
      {list.steps.length > 0 ? (
        <TaskSteps
          steps={list.steps}
          current={list.current}
          hold={list.held ? "paused" : undefined}
          size="md"
          label="Moving your agents"
        />
      ) : null}
      {more > 0 ? <p className="text-meta text-ink-muted">{GO_LIVE.more(more)}</p> : null}
    </StepScreen>
  );
}

export const VERIFY_COPY: Record<GoLive["verify"], StepCopy & { action: string | null }> = {
  todo: {
    title: "Verify your business",
    hint: "A short check of who you are.",
    why: "Your own number is bought in your business's name, so this comes first.",
    action: "Verify my business",
  },
  in_review: {
    title: "We're checking your details",
    hint: "Nothing to do. This page moves on by itself.",
    action: null,
  },
  needs_attention: {
    title: "Your details need another look",
    hint: "Open it to see why, then send again.",
    why: "The check could not be finished with what was sent.",
    action: "Open my business check",
  },
  done: {
    title: "Your business is verified",
    hint: "Next, your own number.",
    action: null,
  },
};

function VerifyStep({
  guide,
  verifyHref,
  onBack,
  onNext,
}: {
  guide: GoLive;
  verifyHref: string;
  onBack: () => void;
  onNext: () => void;
}) {
  const router = useRouter();
  const copy = VERIFY_COPY[guide.verify];
  const done = guide.verify === "done";
  return (
    <StepScreen
      title={copy.title}
      hint={hintOf(copy)}
      onBack={onBack}
      primary={
        done ? (
          <>
            Get your number
            <ArrowRight aria-hidden className="h-4 w-4" />
          </>
        ) : (
          copy.action ?? undefined
        )
      }
      onSubmit={() => (done ? onNext() : router.push(verifyHref))}
    >
      {guide.verify === "in_review" ? (
        <Link href={verifyHref} className={SECONDARY_BUTTON}>
          {GO_LIVE.seeSent}
        </Link>
      ) : null}
    </StepScreen>
  );
}

export const NUMBER_COPY: Record<GoLive["number"], StepCopy & { action: string | null }> = {
  locked: {
    title: "Get your number",
    hint: "Opens once your business is verified.",
    action: null,
  },
  waiting_approval: {
    title: "Your number is being approved",
    hint: "Nothing to do. This page moves on by itself.",
    action: null,
  },
  todo: {
    title: "Choose your number",
    hint: "Callers ring it. Your agent calls from it.",
    action: "Choose my number",
  },
  done: {
    title: "You have your number",
    hint: "Last step: switch an agent on.",
    action: null,
  },
};

function NumberStep({
  guide,
  numberHref,
  onBack,
  onNext,
}: {
  guide: GoLive;
  numberHref: string;
  onBack: () => void;
  onNext: () => void;
}) {
  const router = useRouter();
  const copy = NUMBER_COPY[guide.number];
  const done = guide.number === "done";
  return (
    <StepScreen
      title={copy.title}
      hint={hintOf(copy)}
      onBack={onBack}
      primary={
        done ? (
          <>
            Switch it on
            <ArrowRight aria-hidden className="h-4 w-4" />
          </>
        ) : (
          copy.action ?? undefined
        )
      }
      onSubmit={() => (done ? onNext() : router.push(numberHref))}
    >
      {guide.number === "locked" ? (
        <button type="button" className={PRIMARY_BUTTON} onClick={onBack}>
          {GO_LIVE.backToVerify}
        </button>
      ) : null}
    </StepScreen>
  );
}

function SwitchOnStep({
  guide,
  agentHref,
  newAgentHref,
  onBack,
  onFinished,
}: {
  guide: GoLive;
  agentHref: (id: string) => string;
  /** Where an account with no agent makes one. */
  newAgentHref: string;
  onBack: () => void;
  onFinished: () => void;
}) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const finish = useFinishGoLive(session);
  const finishFeedback = useActionFeedback(finish, { errorDisplay: "inline" });
  // The server's word decides "you're live"; the roster read below refreshes it after a switch.
  const live = guide.switch_on === "done";
  const listed = agents.isSuccess ? agents.data.filter((agent) => !isDeleted(agent)) : [];
  return (
    <StepScreen
      title={live ? GO_LIVE.liveTitle : GO_LIVE.switchTitle}
      hint={live ? GO_LIVE.liveHint : GO_LIVE.switchHint}
      onBack={onBack}
      primary={live ? GO_LIVE.dashboard : undefined}
      status={finishFeedback.status}
      successLabel="Done"
      onSubmit={() => finish.mutate(undefined, { onSuccess: onFinished })}
    >
      {agents.isError ? <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} /> : null}
      {agents.isPending ? <Skeleton rows={2} label="Getting your agents…" /> : null}
      {listed.length > 0 ? (
        <ul className="divide-y divide-line rounded-card border border-line bg-surface">
          {listed.map((agent) => (
            <SwitchRow key={agent.id} agent={agent} agentHref={agentHref(agent.id)} />
          ))}
        </ul>
      ) : agents.isSuccess ? (
        // Every agent deleted, or none made yet: the step has nothing to switch on, so it
        // says so and points at the one thing that gives it something.
        <EmptyState
          className="rounded-card border border-line"
          message={GO_LIVE.noAgent}
          action={
            <Link href={newAgentHref} className={PRIMARY_BUTTON}>
              {GO_LIVE.makeAgent}
            </Link>
          }
        />
      ) : null}
      {finish.error ? <ProblemNotice error={finish.error} /> : null}
    </StepScreen>
  );
}

/** One agent and its own switch: the server's refusal is shown as it is worded. */
function SwitchRow({ agent, agentHref }: { agent: Agent; agentHref: string }) {
  const { session } = useClientRealm();
  const lifecycle = useAgentLifecycle(session, agent.id);
  const lifecycleFeedback = useActionFeedback(lifecycle, { errorDisplay: "inline" });
  const client = useQueryClient();
  const isLive = agent.status === "live";
  return (
    <li className="space-y-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link href={agentHref} className="block break-words text-body font-medium text-ink hover:underline">
            {agent.name}
          </Link>
          <p className="text-meta text-ink-muted">{isLive ? GO_LIVE.taking : agent.status === "draft" ? GO_LIVE.notReady : GO_LIVE.ready}</p>
        </div>
        {isLive ? null : (
          <ActionButton
            variant="primary"
            status={lifecycleFeedback.status}
            pendingLabel="Switching on…"
            successLabel="Switched on"
            onClick={() =>
              lifecycle.mutate("activate", {
                onSuccess: () => void client.invalidateQueries({ queryKey: goLiveKey(session.orgSlug) }),
              })
            }
          >
            Switch on
          </ActionButton>
        )}
      </div>
      {lifecycle.error ? <ProblemNotice error={lifecycle.error} /> : null}
    </li>
  );
}
