"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { TaskSteps, type TaskStep } from "@/components/interior/task-steps";
import { ProblemNotice, RestrictionNote, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
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
  const [stage, setStage] = useState<Stage | null>(null);
  if (stage === null && guide.data !== undefined) setStage(stageOf(guide.data.current));

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
          <p className="mt-0.5 hidden text-meta text-ink-muted sm:block">
            Four steps from your first payment to taking real calls.
          </p>
        </div>
        <button type="button" className={`${TEXT_ACTION} shrink-0`} onClick={skip} disabled={dismiss.isPending}>
          Skip for now
        </button>
      </div>
      {dismiss.error ? <ProblemNotice error={dismiss.error} /> : null}

      <div className="grid gap-5 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-8">
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

const MOVE_COPY: Record<GoLive["move"]["state"], { title: string; hint: string }> = {
  waiting_for_account: {
    title: "Setting up your own calling account",
    hint: "Your agents move as soon as it is ready. They keep working meanwhile.",
  },
  moving: {
    title: "Moving your agents to your own account…",
    hint: "Each one keeps working while it moves. Nothing changes for your callers.",
  },
  finishing: {
    title: "We're finishing this for you",
    hint: "One of your agents needs a step on our side. We've been told, and it keeps working meanwhile. You can carry on.",
  },
  done: {
    title: "Your agents are on your own account",
    hint: "From now on, new agents are made there too.",
  },
};

function MoveStep({ guide, onNext }: { guide: GoLive; onNext: () => void }) {
  const copy = MOVE_COPY[guide.move.state];
  const list = moveChecklist(guide.move.agents);
  const more = guide.move.total - guide.move.agents.length;
  return (
    <StepScreen
      title={copy.title}
      hint={guide.move.total === 0 && guide.move.state === "done" ? "You had nothing to move." : copy.hint}
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
      {more > 0 ? <p className="text-meta text-ink-muted">and {more} more</p> : null}
    </StepScreen>
  );
}

const VERIFY_COPY: Record<GoLive["verify"], { title: string; hint: string; action: string | null }> = {
  todo: {
    title: "Verify your business",
    hint: "A short check of who you are. Your own number is bought in your business's name, so it comes first.",
    action: "Verify my business",
  },
  in_review: {
    title: "We're checking your business details",
    hint: "Nothing to do for now. This page moves on by itself once the check is done.",
    action: null,
  },
  needs_attention: {
    title: "Your business details need another look",
    hint: "The check could not be finished with what was sent. Open it to see why and send it again.",
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
      hint={copy.hint}
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
        <Link href={verifyHref} className={TEXT_ACTION}>
          See what you sent
        </Link>
      ) : null}
    </StepScreen>
  );
}

const NUMBER_COPY: Record<GoLive["number"], { title: string; hint: string; action: string | null }> = {
  locked: {
    title: "Get your number",
    hint: "Your number opens once your business is verified.",
    action: null,
  },
  waiting_approval: {
    title: "Your details are being approved for a number",
    hint: "Nothing to do for now. This page moves on by itself once they are approved.",
    action: null,
  },
  todo: {
    title: "Choose your number",
    hint: "Callers ring it to reach your agent, and your agent calls from it.",
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
      hint={copy.hint}
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
        <button type="button" className={TEXT_ACTION} onClick={onBack}>
          Back to verifying your business
        </button>
      ) : null}
    </StepScreen>
  );
}

function SwitchOnStep({
  guide,
  agentHref,
  onBack,
  onFinished,
}: {
  guide: GoLive;
  agentHref: (id: string) => string;
  onBack: () => void;
  onFinished: () => void;
}) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const finish = useFinishGoLive(session);
  // The server's word decides "you're live"; the roster read below refreshes it after a switch.
  const live = guide.switch_on === "done";
  const listed = agents.isSuccess ? agents.data.filter((agent) => !isDeleted(agent)) : [];
  return (
    <StepScreen
      title={live ? "You're live" : "Switch an agent on"}
      hint={
        live
          ? "Your agent is taking calls. Everything else is on your dashboard."
          : "Choose which agent takes calls. If something is still missing, it says what."
      }
      onBack={onBack}
      primary={live ? "Go to my dashboard" : undefined}
      pending={finish.isPending}
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
      ) : null}
      {finish.error ? <ProblemNotice error={finish.error} /> : null}
    </StepScreen>
  );
}

/** One agent and its own switch: the server's refusal is shown as it is worded. */
function SwitchRow({ agent, agentHref }: { agent: Agent; agentHref: string }) {
  const { session } = useClientRealm();
  const lifecycle = useAgentLifecycle(session, agent.id);
  const client = useQueryClient();
  const isLive = agent.status === "live";
  return (
    <li className="space-y-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link href={agentHref} className="block break-words text-body font-medium text-ink hover:underline">
            {agent.name}
          </Link>
          <p className="text-meta text-ink-muted">{isLive ? "Taking calls" : agent.status === "draft" ? "Not ready yet" : "Ready"}</p>
        </div>
        {isLive ? null : (
          <button
            type="button"
            className={`${SECONDARY_BUTTON} touch:min-h-11`}
            disabled={lifecycle.isPending}
            aria-busy={lifecycle.isPending || undefined}
            onClick={() =>
              lifecycle.mutate("activate", {
                onSuccess: () => void client.invalidateQueries({ queryKey: goLiveKey(session.orgSlug) }),
              })
            }
          >
            {lifecycle.isPending ? "Switching on…" : "Switch on"}
          </button>
        )}
      </div>
      {lifecycle.error ? <ProblemNotice error={lifecycle.error} /> : null}
    </li>
  );
}
