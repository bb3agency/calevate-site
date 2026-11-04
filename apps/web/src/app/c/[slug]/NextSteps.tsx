"use client";

import Link from "next/link";
import type { UseQueryResult } from "@tanstack/react-query";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Flame,
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
import type { ReactNode } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { useEnterClass } from "@/components/live/arrivals";
import {
  PRIMARY_BUTTON_SM,
  QUIET_ICON_BUTTON,
  SECONDARY_BUTTON_SM,
  TONE_INK,
  formatCount,
  type NoticeTone,
} from "@/components/ui";
import type { useAttention } from "@/lib/api/attention";
import {
  STEPS,
  setupHref,
  stepCopy,
  stepStates,
  useSetupAction,
  type BusinessProfile,
} from "@/lib/api/businessProfile";
import type { Dashboard, Session } from "@/lib/api/client";
import type { GoLive } from "@/lib/api/goLive";
import type { useKnowledgeGaps } from "@/lib/api/knowledgeGaps";
import type { AccountReadiness } from "@/lib/api/readiness";
import { QUESTION_PARAM, QUESTIONS_TAB } from "@/lib/api/teachQuestions";
import { activeTrial, walletState, type useWallet } from "@/lib/api/wallet";

import { HOME } from "./_ui/copy";

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

type Step = {
  key: string;
  rank: Rank;
  tone: NoticeTone;
  icon: LucideIcon;
  text: ReactNode;
  /** One short line under the text. */
  detail?: ReactNode;
  /** Where the step is done, realm-relative ("/leads"). Also its identity for de-duplication. */
  to?: string;
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
const GO_LIVE_ORDER: readonly GoLive["current"][] = ["move", "verify", "number", "switch_on"];

/**
 * NEXT STEPS: the one ranked list on the dashboard of what to do now. It folds what used to
 * be five stacked cards (the first agent, go live, business setup, what needs you, and the
 * readiness fixes), so a step that two of them both suggested is shown once, and the owner
 * reads one list with one primary button: the top step's.
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
}) {
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
      detail: HOME.meetSteps.join(" · "),
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
      detail: HOME.goLiveStep[guide!.current],
      to: "/go-live",
      label: HOME.goLiveContinue,
    });
  }

  // The business's facts, while the server says they belong on the dashboard: the first
  // day, or later when calls show a missing step cost something (`setup.nudges`). It waits
  // while the first agent is still to meet: the owner's first job is the agent.
  if (profile && profile.setup.on_dashboard && !firstAgent?.started) {
    const states = stepStates(profile);
    const left = STEPS.filter((step) => states[step.id] !== "done");
    const blocking = new Set(profile.blockers.map((blocker) => blocker.step));
    const nudge = profile.setup.nudges[0];
    const next = nudge?.step ?? left.find((step) => blocking.has(step.id))?.id ?? left[0]?.id;
    if (next !== undefined) {
      const needed = blocking.size > 0;
      steps.push({
        key: "setup",
        rank: needed || nudge ? "look" : "onboarding",
        tone: needed || nudge ? "warn" : "info",
        icon: Store,
        text: nudge ? nudge.message : HOME.setupTitle,
        detail: needed ? HOME.setupNeeded : HOME.setupLeft(left.length, stepCopy(next).short),
        to: setupHref((path) => path, next),
        label: HOME.setupAction,
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
      // Green, as on the call log: a lead ready to act is good news that wants a call.
      tone: "ok",
      icon: Flame,
      text: (
        <>
          <span className="font-semibold tabular-nums">{formatCount(data.hot_leads_open)}</span>{" "}
          {HOME.hotLeads(data.hot_leads_open)}
        </>
      ),
      to: "/leads",
      label: HOME.hotLeadsAction,
    });
  }

  const unanswered = gaps.data?.open_count ?? 0;
  if (unanswered > 0) {
    // One agent's gaps open on its Training tab, which leads with its Questions to answer
    // (D-826, D-893); several agents' open the same list, account-wide, on Knowledge. One
    // topic opens on that question, never on a blank page.
    const complete = gaps.data?.items.length === unanswered;
    const agentIds = new Set(gaps.data?.items.map((gap) => gap.agent_id));
    const topics = new Set(gaps.data?.items.map((gap) => gap.topic_key));
    const [only] = agentIds;
    const [topic] = topics;
    const focus =
      complete && topic !== undefined && topics.size === 1
        ? `${QUESTION_PARAM}=${encodeURIComponent(topic)}`
        : null;
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
      to:
        only !== undefined && agentIds.size === 1 && complete
          ? `/agents/${only}?section=training${focus ? `&${focus}` : ""}`
          : `/knowledge?${focus ?? QUESTIONS_TAB}`,
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

  // How ready the agents are for real calls (D-870): the server's biggest fixes. With more
  // than one agent a fix names the agent it is for, matched on the id its link carries.
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
        detail: scored.agents.length > 1 && agentName ? agentName : undefined,
        to: fix.href,
        label: HOME.readinessFix,
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

  return (
    <Section
      title={HOME.nextTitle}
      description={score !== null ? HOME.readinessScore(score) : undefined}
      action={
        // Only when the attention queue holds something: it is the full list of problems,
        // not of these steps, so offering it with an empty queue would contradict this list.
        attention.data && attention.data.total > 0 ? (
          <Link href={href("/attention")} className={TEXT_ACTION}>
            {HOME.seeAll}
          </Link>
        ) : undefined
      }
    >
      {ranked.length > 0 ? (
        <ol className="divide-y divide-line border-y border-line">
          {ranked.map((step, index) => (
            <li key={step.key} className={`flex items-center gap-x-3 py-3 ${enter(step.key)}`}>
              <step.icon aria-hidden className={`h-4 w-4 shrink-0 ${TONE_INK[step.tone]}`} />
              <div className="min-w-0 flex-1">
                <p className="text-body text-ink">{step.text}</p>
                {step.detail ? <p className="truncate text-meta text-ink-muted">{step.detail}</p> : null}
              </div>
              {step.retry ? (
                <button type="button" onClick={step.retry} className={`${SECONDARY_BUTTON_SM} shrink-0`}>
                  {step.label}
                </button>
              ) : (
                <Link
                  href={href(step.to!)}
                  // The top step is the one primary action on the list.
                  className={`${index === 0 ? PRIMARY_BUTTON_SM : SECONDARY_BUTTON_SM} shrink-0`}
                >
                  {step.label}
                </Link>
              )}
              {step.extra}
            </li>
          ))}
        </ol>
      ) : null}
      {allClear ? (
        <p className="flex items-center gap-2 text-body text-ink-muted">
          <CheckCircle2 aria-hidden className="h-4 w-4 text-brand-strong" />
          {HOME.allClear}
        </p>
      ) : null}
    </Section>
  );
}

/** The first step for each destination, and at most `MAX_FIXES` readiness fixes. */
function dedupe(steps: Step[]): Step[] {
  const seen = new Set<string>();
  let fixes = 0;
  return steps.filter((step) => {
    const isFix = step.key.startsWith("fix:");
    if (isFix && fixes >= MAX_FIXES) return false;
    if (step.to !== undefined) {
      const where = destination(step.to);
      if (seen.has(where)) return false;
      seen.add(where);
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

