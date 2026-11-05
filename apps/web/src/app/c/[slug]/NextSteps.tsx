"use client";

import Link from "next/link";
import type { UseQueryResult } from "@tanstack/react-query";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Gauge,
  MessageCircleQuestion,
  PhoneMissed,
  Rocket,
  Store,
  Target,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { READINESS_BANDS, type GaugeBand } from "@/components/arc/gauge";
import { useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { useEnterClass } from "@/components/live/arrivals";
import {
  PRIMARY_BUTTON_SM,
  QUIET_ICON_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  TONE_INK,
  formatCount,
  type NoticeTone,
} from "@/components/ui";
import type { useAttention } from "@/lib/api/attention";
import {
  STEPS,
  setupHref,
  stepStates,
  useSetupAction,
  type BusinessProfile,
} from "@/lib/api/businessProfile";
import type { Dashboard, Session } from "@/lib/api/client";
import type { GoLive } from "@/lib/api/goLive";
import type { useKnowledgeGaps } from "@/lib/api/knowledgeGaps";
import type { AccountReadiness, ReadinessFix } from "@/lib/api/readiness";
import { QUESTION_PARAM, QUESTIONS_TAB } from "@/lib/api/teachQuestions";
import { activeTrial, walletState, type useWallet } from "@/lib/api/wallet";
import { callersWord, useBusinessCapabilities } from "@/lib/businessCapabilities";

import { readinessBand } from "./agents/AgentReadiness";
import { HOME, READINESS_WHY } from "./_ui/copy";

/**
 * Most urgent first: what has stopped, then getting the account working, then what needs a
 * look, then opportunities, then improvements. The tone is also the row's glyph colour, and
 * each kind has its own glyph, so the order and the kind read before the words (colour,
 * shape and label together, never colour alone).
 */
type Rank = "stopped" | "onboarding" | "look" | "opportunity" | "improve";
const RANK: Record<Rank, number> = { stopped: 0, onboarding: 1, look: 2, opportunity: 3, improve: 4 };

/** The most readiness fixes shown here; the rest are on each agent's own page. */
const MAX_FIXES = 2;

/** The icon chip of the top step: the tone's soft ground under the tone's ink. */
const TONE_CHIP: Record<NoticeTone, string> = {
  ok: "bg-success-soft",
  info: "bg-info-soft",
  warn: "bg-warn-soft",
  stop: "bg-danger-soft",
  neutral: "bg-surface-muted",
};

/** The meter's fill, the same colour per band as the ring on each agent's page. */
const BAND_FILL: Record<GaugeBand["tone"], string> = {
  danger: "bg-danger",
  warn: "bg-chart-warn",
  good: "bg-brand",
};
const BAND_INK: Record<GaugeBand["tone"], string> = {
  danger: "text-danger",
  warn: "text-warn",
  good: "text-brand-strong",
};

type Step = {
  key: string;
  rank: Rank;
  tone: NoticeTone;
  icon: LucideIcon;
  text: ReactNode;
  /** One short line under the text. */
  detail?: ReactNode;
  /** Where the step is done, realm-relative ("/leads"). */
  to?: string;
  /**
   * The problem the step fixes, when two sources can report the same one under different
   * links (an unanswered caller question is a gap, a readiness fix and a setup reason).
   * Steps without one are told apart by where they lead.
   */
  problem?: string;
  label: string;
  /** A failed read's retry, in place of a link. */
  retry?: () => void;
  /** A quiet control after the action (hiding the setup step). */
  extra?: ReactNode;
};

/** Two steps that send the owner to the same place are one step: the page and tab they
 *  open, ignoring which question or filter is pre-selected. */
function destination(to: string): string {
  const [path, query = ""] = to.split("?");
  const section = new URLSearchParams(query).get("section");
  return section ? `${path}#${section}` : path;
}

/** The go-live guide is offered from the first payment until the owner finishes it;
 *  putting it aside keeps it here (D-859). */
export function goLiveOffered(guide: GoLive | undefined): boolean {
  return (
    guide !== undefined &&
    guide.owed_at !== null &&
    (guide.finished_at ?? null) === null &&
    guide.current !== "done"
  );
}
const GO_LIVE_ORDER: readonly GoLive["current"][] = ["verify", "number", "switch_on"];

/** Setup steps whose answers are the "what it knows" the readiness score counts (D-968). */
const KNOWLEDGE_STEPS: ReadonlySet<string> = new Set(["services", "faqs"]);

/** A readiness fix's problem and button. The server's sentence says why; the button says
 *  what it opens, so no two rows share a "Fix" that tells the owner nothing. */
function fixShape(fix: ReadinessFix, agentId: string | undefined): { problem?: string; label: string } {
  const training = destination(fix.href).endsWith("#training");
  switch (fix.component) {
    case "missed":
      return { problem: "unanswered", label: HOME.readinessAction.missed };
    case "knowledge":
      // With too little on file it opens Knowledge to add more; with enough, the agent's
      // Training tab, to answer what it was asked (`agents/readiness.score`).
      return training
        ? { problem: "unanswered", label: HOME.readinessAction.answerQuestions }
        : { problem: "knowledge", label: HOME.readinessAction.addKnowledge };
    case "opening":
      return { problem: `opening:${agentId ?? fix.href}`, label: HOME.readinessAction.opening };
    case "live":
      return { problem: `live:${agentId ?? fix.href}`, label: HOME.readinessAction.live };
  }
}

/**
 * NEXT STEPS: the one ranked list on the dashboard of what to do now. It folds what used to
 * be five stacked cards (the first agent, go live, business setup, what needs you, and the
 * readiness fixes), so a problem that two of them both report is shown once, and the owner
 * reads one list with one primary button: the top step's.
 *
 * Three layers, in the order an owner asks: how ready am I (the meter, with how far is
 * left), what do I do first (the top step, set apart), and what else (the rest, split
 * into what needs them now and what makes the agents better).
 *
 * Built only from reads the dashboard already makes; nothing here is inferred beyond what
 * those say. A read that FAILED is a row with a retry, never an all-clear (§52). The
 * attention queue keeps its own page, Needs attention, which is the full list.
 */
export function NextSteps({
  data,
  attention,
  wallet,
  gaps,
  readiness,
  profile,
  guide,
  firstAgent,
  canHideSetup,
  session,
  href,
  folded = false,
}: {
  data: Dashboard;
  attention: ReturnType<typeof useAttention>;
  wallet: ReturnType<typeof useWallet>;
  gaps: ReturnType<typeof useKnowledgeGaps>;
  readiness: UseQueryResult<AccountReadiness>;
  profile: BusinessProfile | undefined;
  guide: GoLive | undefined;
  /** `null` when the account has an agent or this person may not create one. */
  firstAgent: { started: boolean } | null;
  canHideSetup: boolean;
  session: Session;
  href: (path: string) => string;
  /**
   * Once the account is set up the dashboard leads with its figures, so the list starts
   * folded to one line (how many things, how ready) and opens on a tap. It opens by itself
   * when calls have stopped, the one step that cannot wait.
   */
  folded?: boolean;
}) {
  const [opened, setOpened] = useState<boolean | null>(null);
  const caps = useBusinessCapabilities();
  const steps: Step[] = [];
  const hide = useSetupAction(session);
  // On success the step leaves with the button that hid it, so the toast is the only place
  // the result can be said, with where to find the questions again.
  const hideFeedback = useActionFeedback(hide, {
    errorTitle: "Could not hide the setup step",
    successToast: "Setup step hidden",
    successDescription: "It is always under Settings, Business profile.",
  });

  if (wallet.data && activeTrial(wallet.data) === null) {
    const state = walletState(wallet.data);
    if (state === "low" || state === "stopped") {
      steps.push({
        key: "credit",
        rank: state === "stopped" ? "stopped" : "look",
        tone: state === "stopped" ? "stop" : "warn",
        icon: Wallet,
        // The minutes left are on the credit tile; this row says only what to do.
        text: state === "stopped" ? HOME.creditStopped : HOME.creditLow,
        to: "/billing?tab=credits",
        label: HOME.creditAction,
      });
    }
  }

  if (firstAgent) {
    steps.push({
      key: "first-agent",
      rank: "onboarding",
      tone: "info",
      icon: Bot,
      text: HOME.meetTitle,
      detail: HOME.meetSteps.join(", "),
      to: "/agents/first",
      label: firstAgent.started ? HOME.meetContinue : HOME.meetStart,
    });
  }

  if (goLiveOffered(guide) && !(firstAgent && guide!.current === "switch_on")) {
    const at = GO_LIVE_ORDER.indexOf(guide!.current);
    steps.push({
      key: "go-live",
      rank: "onboarding",
      tone: "info",
      icon: Rocket,
      text: at >= 0 ? HOME.goLiveStepOf(at + 1, GO_LIVE_ORDER.length) : HOME.goLiveTitle,
      to: "/go-live",
      label: HOME.goLiveAction[guide!.current],
    });
  }

  const unanswered = gaps.data?.open_count ?? 0;

  // The business's facts, while the server says they belong on the dashboard: the first
  // day, or later when calls show a missing step cost something (`setup.nudges`). It waits
  // while the first agent is still to meet: the owner's first job is the agent.
  if (profile && profile.setup.on_dashboard && !firstAgent?.started) {
    const states = stepStates(profile);
    const left = STEPS.filter((step) => states[step.id] !== "done");
    const blocking = new Set(profile.blockers.map((blocker) => blocker.step));
    // An unanswered question is listed below as its own step, and answering it there also
    // closes this reason; saying it here too is the same problem twice.
    const nudges = profile.setup.nudges.filter(
      (nudge) => !(unanswered > 0 && nudge.cause === "unanswered_questions"),
    );
    const onlyForCoveredReasons = profile.setup.nudges.length > 0 && nudges.length === 0 && blocking.size === 0;
    const nudge = nudges[0];
    const next = nudge?.step ?? left.find((step) => blocking.has(step.id))?.id ?? left[0]?.id;
    if (next !== undefined && !onlyForCoveredReasons) {
      const needed = blocking.size > 0;
      steps.push({
        key: "setup",
        rank: needed || nudge ? "look" : "onboarding",
        tone: needed || nudge ? "warn" : "info",
        icon: Store,
        text: nudge ? nudge.message : HOME.setupTitle,
        detail: needed ? HOME.setupNeeded : HOME.setupLeft(left.length, STEPS.length),
        to: setupHref((path) => path, next),
        // While what the business offers or is often asked is still to answer, this list
        // is where it gets added, so it stands for the readiness fix that asks for both.
        problem: left.some((step) => KNOWLEDGE_STEPS.has(step.id)) ? "knowledge" : undefined,
        label: HOME.setupAction[next],
        extra: canHideSetup ? (
          <HideSetup onHide={() => hideFeedback.run({ action: "dismiss" })} pending={hide.isPending} />
        ) : null,
      });
    }
  }

  if (attention.isError) {
    steps.push({
      key: "queue",
      rank: "look",
      tone: "neutral",
      icon: CircleAlert,
      text: HOME.queueFailed,
      label: HOME.tryAgain,
      retry: () => void attention.refetch(),
    });
  } else if (attention.data && attention.data.total > 0) {
    steps.push({
      key: "queue",
      rank: "look",
      tone: "warn",
      icon: Target,
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(attention.data.total)}</span>{" "}
          {HOME.queue(attention.data.total)}
        </>
      ),
      to: "/attention",
      label: HOME.queueAction,
    });
  }

  const today = data.daily_7d.at(-1);
  const missed = today ? today.failed + today.no_answer : 0;
  if (today && missed > 0) {
    // The calls list filters on one status, so link to the one that holds every missed call,
    // and to the unfiltered list when they are split between failed and no answer.
    steps.push({
      key: "missed",
      rank: "look",
      tone: "warn",
      icon: PhoneMissed,
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(missed)}</span> {HOME.missed(missed)}
        </>
      ),
      to:
        today.no_answer === 0 ? "/calls?status=failed"
        : today.failed === 0 ? "/calls?status=no_answer"
        : "/calls",
      label: HOME.missedAction,
    });
  }

  if (data.hot_leads_open > 0) {
    steps.push({
      key: "hot",
      rank: "opportunity",
      // Green, as on the call log: a goal reached is good news that wants a follow-up.
      tone: "ok",
      icon: Target,
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(data.hot_leads_open)}</span>{" "}
          {HOME.goalReached(data.hot_leads_open, caps.callerNoun ?? "person", callersWord(caps, "people"))}
        </>
      ),
      to: "/leads",
      label: HOME.goalReachedAction,
    });
  }

  if (unanswered > 0) {
    // One agent's gaps open on its Training tab, which leads with its Questions to answer
    // (D-826, D-893); several agents' open the same list, account-wide, on Knowledge. One
    // topic opens on that question, never on a blank page.
    const complete = gaps.data?.items.length === unanswered;
    const agentIds = new Set(gaps.data?.items.map((gap) => gap.agent_id));
    const topics = new Set(gaps.data?.items.map((gap) => gap.topic_key));
    const [only] = agentIds;
    const [topic] = topics;
    const oneAgent = only !== undefined && agentIds.size === 1 && complete;
    const focus =
      complete && topic !== undefined && topics.size === 1
        ? `${QUESTION_PARAM}=${encodeURIComponent(topic)}`
        : null;
    const agentName = oneAgent ? gaps.data?.items[0]?.agent_name : undefined;
    steps.push({
      key: "gaps",
      rank: "improve",
      tone: "info",
      icon: MessageCircleQuestion,
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(unanswered)}</span> {HOME.gaps(unanswered)}
        </>
      ),
      detail: agentName ? HOME.forAgent(agentName) : undefined,
      to: oneAgent
        ? `/agents/${only}?section=training${focus ? `&${focus}` : ""}`
        : `/knowledge?${focus ?? QUESTIONS_TAB}`,
      problem: "unanswered",
      label: HOME.gapsAction(unanswered),
    });
  } else if (gaps.error) {
    steps.push({
      key: "gaps",
      rank: "improve",
      tone: "neutral",
      icon: CircleAlert,
      text: HOME.gapsFailed,
      label: HOME.tryAgain,
      retry: () => void gaps.refetch(),
    });
  }

  // How ready the agents are for real calls (D-870): the server's biggest fixes, each
  // naming the agent it is for, matched on the id its link carries.
  const scored = readiness.data;
  if (readiness.error) {
    steps.push({
      key: "readiness",
      rank: "improve",
      tone: "neutral",
      icon: CircleAlert,
      text: HOME.readinessFailed,
      label: HOME.tryAgain,
      retry: () => void readiness.refetch(),
    });
  } else if (scored && scored.agents.length > 0) {
    const names = new Map(scored.agents.map((agent) => [agent.agent_id, agent.agent_name]));
    for (const fix of scored.top_fixes) {
      const agentId = /^\/agents\/([^/?#]+)/.exec(fix.href)?.[1];
      const agentName = agentId === undefined ? undefined : names.get(agentId);
      steps.push({
        key: `fix:${fix.component}:${fix.href}`,
        rank: "improve",
        tone: "info",
        icon: Gauge,
        text: fix.action,
        detail: agentName ? HOME.forAgent(agentName) : undefined,
        to: fix.href,
        ...fixShape(fix, agentId),
      });
    }
  }

  const ranked = dedupe(steps.sort((a, b) => RANK[a.rank] - RANK[b.rank]));
  // A row that appears while the dashboard is open (a lead turned hot, credit ran low)
  // enters softly (D-774); the rows present on load do not.
  const enter = useEnterClass(ranked.map((step) => step.key));
  const allClear =
    ranked.length === 0 && attention.data !== undefined && gaps.data !== undefined && readiness.data !== undefined;
  const score = scored && scored.agents.length > 0 && scored.score !== null ? scored.score : null;
  // Every fix across every agent, not only the few listed here, so "to reach 100%" counts
  // what is really left.
  const fixesLeft = scored ? scored.agents.reduce((sum, agent) => sum + agent.fixes.length, 0) : 0;

  const [top, ...rest] = ranked;
  const now = rest.filter((step) => step.rank !== "improve");
  const better = rest.filter((step) => step.rank === "improve");
  // A heading over the only group left says nothing the section title does not.
  const headed = now.length > 0 && better.length > 0;

  const open = !folded || (opened ?? ranked.some((step) => step.rank === "stopped"));
  const toggle = folded ? (
    <button
      type="button"
      aria-expanded={open}
      aria-controls="next-steps-list"
      onClick={() => setOpened(!open)}
      className={TEXT_ACTION}
    >
      {open ? HOME.nextHide : HOME.nextShow}
    </button>
  ) : null;

  if (!open) {
    return (
      <Section title={HOME.nextTitle} action={toggle}>
        <p className="-mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-body text-ink-muted">
          <span>{HOME.nextSummary(ranked.length)}</span>
          {score !== null ? (
            <>
              <span aria-hidden className="text-ink-faint">·</span>
              <span className="tabular-nums">{HOME.nextReady(Math.round(score))}</span>
            </>
          ) : null}
        </p>
      </Section>
    );
  }

  return (
    <Section
      title={HOME.nextTitle}
      action={
        <>
          {/* Only when the attention queue holds something: it is the full list of problems,
              not of these steps, so offering it with an empty queue would contradict this list. */}
          {attention.data && attention.data.total > 0 ? (
            <Link href={href("/attention")} className={TEXT_ACTION}>
              {HOME.seeAll}
            </Link>
          ) : null}
          {toggle}
        </>
      }
    >
      <div id="next-steps-list" className="space-y-5">
        {score !== null ? (
          <ReadinessMeter score={score} fixesLeft={fixesLeft} />
        ) : readiness.isLoading ? (
          <Skeleton rows={1} label={HOME.readinessLoading} />
        ) : null}

        {top ? <TopStep step={top} href={href} className={enter(top.key)} /> : null}

        {now.length > 0 ? (
          <StepGroup title={headed ? HOME.groupNow : undefined} steps={now} href={href} enter={enter} />
        ) : null}
        {better.length > 0 ? (
          <StepGroup title={headed ? HOME.groupBetter : undefined} steps={better} href={href} enter={enter} />
        ) : null}

        {allClear ? (
          <p className="flex items-center gap-2 text-body text-ink-muted">
            <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
            {HOME.allClear}
          </p>
        ) : null}
      </div>
    </Section>
  );
}

/**
 * How ready the agents are, as a reading with its meaning beside it: the share, the band
 * in words (the same bands as the ring on each agent), a bar, and how many fixes are left.
 * The band's word travels with its colour, so colour is never the only signal.
 */
function ReadinessMeter({ score, fixesLeft }: { score: number; fixesLeft: number }) {
  const value = Math.max(0, Math.min(100, Math.round(score)));
  const band = readinessBand(value, READINESS_BANDS);
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex items-center gap-1">
          <p className="text-body font-medium text-ink">{HOME.readinessTitle}</p>
          <InfoTip label={HOME.readinessHow}>
            <p>{READINESS_WHY}</p>
          </InfoTip>
        </div>
        <p className="flex items-baseline gap-2">
          <span className="text-figure tabular-nums text-ink">{HOME.readinessScore(value)}</span>
          {band ? <span className={`text-meta font-medium ${BAND_INK[band.tone]}`}>{band.label}</span> : null}
        </p>
      </div>
      <div
        role="meter"
        aria-label={HOME.readinessTitle}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-valuetext={`${value} out of 100${band ? `, ${band.label}` : ""}`}
        className="mt-2 h-2 overflow-hidden rounded-full bg-surface-muted"
      >
        <div
          className={`h-full rounded-full ${band ? BAND_FILL[band.tone] : "bg-brand"} motion-safe:transition-[width] motion-safe:duration-(--duration-slow) motion-safe:ease-out`}
          style={{ width: `${value}%` }}
        />
      </div>
      {fixesLeft > 0 ? (
        <p className="mt-2 text-meta text-ink-muted">{HOME.readinessLeft(fixesLeft)}</p>
      ) : value >= 100 ? (
        <p className="mt-2 text-meta text-ink-muted">{HOME.readinessDone}</p>
      ) : null}
    </div>
  );
}

function StepAction({ step, primary, href }: { step: Step; primary: boolean; href: (path: string) => string }) {
  const look = primary ? PRIMARY_BUTTON_SM : SECONDARY_BUTTON_SM;
  return (
    <span className="flex shrink-0 items-center gap-1">
      {step.retry ? (
        <button type="button" onClick={step.retry} className={look}>
          {step.label}
        </button>
      ) : (
        <Link href={href(step.to!)} className={look}>
          {step.label}
        </Link>
      )}
      {step.extra}
    </span>
  );
}

/** The one step to do first, set apart with the list's only filled button. */
function TopStep({ step, href, className }: { step: Step; href: (path: string) => string; className: string }) {
  return (
    <div
      data-step={step.key}
      className={`flex flex-wrap items-center gap-x-4 gap-y-3 rounded-card border border-line bg-surface p-4 ${className}`}
    >
      <span aria-hidden className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${TONE_CHIP[step.tone]}`}>
        <step.icon className={`h-[18px] w-[18px] ${TONE_INK[step.tone]}`} />
      </span>
      <div className="min-w-0 flex-1 basis-48">
        <p className="text-body font-medium text-ink [text-wrap:pretty]">{step.text}</p>
        {step.detail ? <p className="text-meta text-ink-muted">{step.detail}</p> : null}
      </div>
      <StepAction step={step} primary={!step.retry} href={href} />
    </div>
  );
}

function StepGroup({
  title,
  steps,
  href,
  enter,
}: {
  title: string | undefined;
  steps: Step[];
  href: (path: string) => string;
  enter: (key: string) => string;
}) {
  return (
    <div>
      {title ? <h3 className="mb-1 text-meta font-medium text-ink-muted">{title}</h3> : null}
      <ul className="divide-y divide-line">
        {steps.map((step) => (
          <li
            key={step.key}
            data-step={step.key}
            className={`flex flex-wrap items-center gap-x-3 gap-y-2 py-3 ${enter(step.key)}`}
          >
            <step.icon aria-hidden className={`h-4 w-4 shrink-0 ${TONE_INK[step.tone]}`} />
            <div className="min-w-0 flex-1 basis-48">
              <p className="text-body text-ink [text-wrap:pretty]">{step.text}</p>
              {step.detail ? <p className="text-meta text-ink-muted">{step.detail}</p> : null}
            </div>
            <StepAction step={step} primary={false} href={href} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The first step for each problem (or, without one, each destination), and at most
 *  `MAX_FIXES` readiness fixes. */
function dedupe(steps: Step[]): Step[] {
  const seen = new Set<string>();
  let fixes = 0;
  return steps.filter((step) => {
    const isFix = step.key.startsWith("fix:");
    if (isFix && fixes >= MAX_FIXES) return false;
    const id =
      step.problem !== undefined ? `problem:${step.problem}`
      : step.to !== undefined ? `to:${destination(step.to)}`
      : undefined;
    if (id !== undefined) {
      if (seen.has(id)) return false;
      seen.add(id);
    }
    if (isFix) fixes += 1;
    return true;
  });
}

function HideSetup({ onHide, pending }: { onHide: () => void; pending: boolean }) {
  return (
    <button
      type="button"
      onClick={onHide}
      disabled={pending}
      aria-label={HOME.setupHide}
      title={HOME.setupHide}
      className={QUIET_ICON_BUTTON}
    >
      <X aria-hidden className="h-4 w-4" />
    </button>
  );
}
