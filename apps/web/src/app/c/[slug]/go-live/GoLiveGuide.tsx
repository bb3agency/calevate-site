"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, Check } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { EmptyState } from "@/components/console/emptyState";
import { PRIMARY_BUTTON, ProblemNotice, RestrictionNote, SECONDARY_BUTTON, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { isDeleted } from "@/lib/agentState";
import { useAgentLifecycle, useAgents, type Agent } from "@/lib/api/agents";
import { LifecycleError } from "../agents/AgentLifecycle";
import {
  useDismissGoLive,
  useFinishGoLive,
  goLiveKey,
  useGoLive,
  type GoLive,
  type GoLiveStep,
} from "@/lib/api/goLive";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { StepRail, StepScreen } from "../agents/first/shell";
import { GO_LIVE } from "../_ui/copy";
import { Why } from "@/components/why";

/** The route this screen lives on, for links into it. */
export const GO_LIVE_ROUTE = "/c/{slug}/go-live";

/**
 * The owner's steps. Moving the agents into the account's own calling set-up is ours and
 * runs beside them (one quiet line while it does), never a step the owner is asked to take.
 */
export const GO_LIVE_STEPS = [
  { id: "verify", label: "Verify your business" },
  { id: "number", label: "Get your number" },
  { id: "switch_on", label: "Switch it on" },
] as const;

type Stage = (typeof GO_LIVE_STEPS)[number]["id"];

/** Where a guide that is not finished picks up: the server's first step not done. */
export function stageOf(current: GoLiveStep): Stage {
  return current === "done" ? "switch_on" : current === "move" ? "verify" : current;
}

/**
 * "GO LIVE" (D-859, founder 23 Oct 2026): the owner's guide after the first payment, on
 * "Meet your agent"'s shell (D-855): its rail, one step at a time, the action pinned in the
 * thumb's reach on a phone.
 *
 * 1. Verify your business: the business check, the agreements and the no-cold-calls pledge,
 *    each with its own button, so the list matches every gate an agent's switch asks.
 * 2. Get your number: the true reason a number cannot be bought yet, one state per gate.
 * 3. Switch it on: each agent's own switch, refused in the server's words.
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
  const to = (path: string) => href(`/c/${slug}${path}`);

  let body: React.ReactNode;
  if (guide.isError) body = <ProblemNotice error={guide.error} onRetry={() => void guide.refetch()} />;
  else if (guide.data === undefined || stage === null || write.unknown) body = <Skeleton rows={5} label="Checking where you are…" />;
  else if (!write.allowed) body = <RestrictionNote reason={write.reason} />;
  else {
    const data = guide.data;
    switch (stage) {
      case "verify":
        body = <VerifyStep guide={data} to={to} onNext={() => go("number")} />;
        break;
      case "number":
        body = <NumberStep guide={data} to={to} onBack={() => go("verify")} onNext={() => go("switch_on")} />;
        break;
      default:
        body = (
          <SwitchOnStep
            guide={data}
            agentHref={(id) => to(`/agents/${id}`)}
            newAgentHref={to("/agents/new")}
            onBack={() => go("number")}
            onFinished={() => router.push(to(""))}
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
        <ActionButton
          variant="text"
          className="shrink-0"
          onClick={skip}
          status={dismissFeedback.status}
          pendingLabel={GO_LIVE.skipping}
        >
          {GO_LIVE.skip}
        </ActionButton>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-8">
        <aside className="min-w-0" aria-label="Your progress">
          <StepRail steps={GO_LIVE_STEPS} current={step} onGo={(at) => at < step && go(GO_LIVE_STEPS[at].id)} />
        </aside>
        <section className="min-w-0 max-w-xl space-y-4" aria-label="This step">
          {guide.data !== undefined && movingNow(guide.data) ? (
            <p role="status" className="text-meta text-ink-muted">
              {GO_LIVE.gettingReady}
            </p>
          ) : null}
          {body}
        </section>
      </div>
    </div>
  );
}

/** Our move is still under way: the owner is told once, quietly, and carries on. */
export function movingNow(guide: GoLive): boolean {
  return guide.move.state === "waiting_for_account" || guide.move.state === "moving";
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

/** The three things the first step holds, as the rows the owner ticks off. */
export const VERIFY_ITEMS = {
  business: { label: "Business check", done: "Verified", review: "Being checked", todo: "To do" },
  agreements: { label: "Agreements", done: "Accepted", todo: "To do", action: "Read and accept" },
  pledge: {
    label: "No-cold-calls pledge",
    done: "Accepted",
    todo: "Needed before your agent calls out",
    action: "Accept the pledge",
  },
} as const;

function VerifyStep({ guide, to, onNext }: { guide: GoLive; to: (path: string) => string; onNext: () => void }) {
  const router = useRouter();
  const kycDone = guide.verify === "done";
  const agreementsDone = guide.agreements === "done";
  const done = kycDone && agreementsDone;
  // The business check's own words while it is the open item; once it is through, the
  // step speaks for the agreements that still hold it.
  const copy: StepCopy & { action: string | null } = kycDone
    ? agreementsDone
      ? VERIFY_COPY.done
      : { title: GO_LIVE.agreementsTitle, hint: GO_LIVE.agreementsHint, action: VERIFY_ITEMS.agreements.action }
    : VERIFY_COPY[guide.verify];
  const primaryHref = kycDone ? to("/agreements") : to("/verify-business");
  return (
    <StepScreen
      title={copy.title}
      hint={hintOf(copy)}
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
      onSubmit={() => (done ? onNext() : router.push(primaryHref))}
    >
      <ul className="divide-y divide-line rounded-card border border-line bg-surface">
        <ItemRow
          label={VERIFY_ITEMS.business.label}
          done={kycDone}
          state={
            kycDone ? VERIFY_ITEMS.business.done : guide.verify === "in_review" ? VERIFY_ITEMS.business.review : VERIFY_ITEMS.business.todo
          }
          action={guide.verify === "in_review" ? { href: to("/verify-business"), label: GO_LIVE.seeSent } : null}
        />
        <ItemRow
          label={VERIFY_ITEMS.agreements.label}
          done={agreementsDone}
          state={agreementsDone ? VERIFY_ITEMS.agreements.done : VERIFY_ITEMS.agreements.todo}
          action={agreementsDone ? null : { href: to("/agreements"), label: VERIFY_ITEMS.agreements.action }}
        />
        <ItemRow
          label={VERIFY_ITEMS.pledge.label}
          done={guide.pledge === "done"}
          state={guide.pledge === "done" ? VERIFY_ITEMS.pledge.done : VERIFY_ITEMS.pledge.todo}
          action={guide.pledge === "done" ? null : { href: to("/verify-business#step-pledge"), label: VERIFY_ITEMS.pledge.action }}
        />
      </ul>
    </StepScreen>
  );
}

/** One thing the step needs: its name, where it stands, and the button that does it. */
function ItemRow({
  label,
  done,
  state,
  action,
}: {
  label: string;
  done: boolean;
  state: string;
  action: { href: string; label: string } | null;
}) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 p-4">
      <div className="flex min-w-0 items-start gap-2.5">
        <span
          aria-hidden
          className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border ${done ? "border-brand-strong bg-brand-strong text-white" : "border-line"}`}
        >
          {done ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
        </span>
        <div className="min-w-0">
          <p className="text-body font-medium text-ink">{label}</p>
          <p className="text-meta text-ink-muted">{state}</p>
        </div>
      </div>
      {action ? (
        <Link href={action.href} className={SECONDARY_BUTTON_SM}>
          {action.label}
        </Link>
      ) : null}
    </li>
  );
}

type NumberCopy = StepCopy & {
  action: string | null;
  /** Where the action goes, as a path inside the account; null with no action. */
  path: string | null;
};

export const NUMBER_COPY: Record<GoLive["number"], NumberCopy> = {
  locked: {
    title: "Get your number",
    hint: "Opens once your business is verified.",
    action: null,
    path: null,
  },
  add_credit: {
    title: "Get your number",
    hint: "Opens once you add credit.",
    why: "Numbers are for paying accounts. Your free trial uses our shared test line.",
    action: "Add credit",
    path: "/billing?tab=credits",
  },
  setting_up: {
    title: "We're setting up your calling account",
    hint: "Nothing to do. This page moves on by itself.",
    why: "Your number is bought in your business's name, in its own calling account.",
    action: null,
    path: null,
  },
  send_details: {
    title: "Send your business details",
    hint: "Needed once, to buy a number in your name.",
    action: "Send my details",
    path: "/phone-number",
  },
  waiting_approval: {
    title: "Your details are being approved",
    hint: "Nothing to do. This page moves on by itself.",
    why: "The phone network checks the business a number is registered to.",
    action: null,
    path: null,
  },
  needs_attention: {
    title: "Your details need a fix",
    hint: "See what to change, then send them again.",
    action: "Fix and send again",
    path: "/phone-number",
  },
  not_on_sale: {
    title: "Numbers open soon",
    hint: "We'll tell you when you can choose one.",
    action: null,
    path: null,
  },
  todo: {
    title: "Choose your number",
    hint: "Callers ring it. Your agent calls from it.",
    action: "Choose my number",
    path: "/phone-number",
  },
  done: {
    title: "You have your number",
    hint: "Last step: switch an agent on.",
    action: null,
    path: null,
  },
};

function NumberStep({
  guide,
  to,
  onBack,
  onNext,
}: {
  guide: GoLive;
  to: (path: string) => string;
  onBack: () => void;
  onNext: () => void;
}) {
  const router = useRouter();
  const copy = NUMBER_COPY[guide.number];
  const done = guide.number === "done";
  const note = guide.number === "needs_attention" ? guide.business_review_note : null;
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
      onSubmit={() => (done ? onNext() : copy.path !== null ? router.push(to(copy.path)) : undefined)}
    >
      {note ? (
        <p className="rounded-card border border-line bg-surface-muted px-4 py-3 text-body text-ink">
          <span className="font-medium">{GO_LIVE.reviewNote}</span> {note}
        </p>
      ) : null}
      {guide.number === "locked" ? (
        <button type="button" className={PRIMARY_BUTTON} onClick={onBack}>
          {GO_LIVE.backToVerify}
        </button>
      ) : null}
      {guide.number === "waiting_approval" ? (
        <Link href={to("/phone-number")} className={SECONDARY_BUTTON}>
          {GO_LIVE.seeSent}
        </Link>
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
      <LifecycleError error={lifecycle.error} />
    </li>
  );
}
