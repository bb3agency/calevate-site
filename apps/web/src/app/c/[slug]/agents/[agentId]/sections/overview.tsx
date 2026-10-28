"use client";

/**
 * OVERVIEW — how ready this agent is (the readiness score and what would raise it, first at
 * every width, D-873), what is left before its first call, anything waiting to go live, the
 * opening notices, and its latest calls (the old Calls entry, D-825).
 *
 * The notices are HERE and nowhere else: this is the tab that opens first, so the
 * truthful-answer guarantee and the two switches under it are never behind a tab switch
 * (doctrine §8 rule 7). On a phone the checklist folds to its "N of M done" summary so the
 * notices stay near the top. Hearing the agent for yourself is in Training.
 */

import { RotateCw } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, Skeleton, formatINR } from "@/components/ui";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { TEXT_ACTION } from "@/components/console/section";
import { movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent, type LifecycleMove } from "@/lib/api/agents";
import { useAgreementsReadiness, type LegalReadiness } from "@/lib/api/agreements";
import { usePendingChanges, type PendingState } from "@/lib/api/publishing";
import { useScript, type ScriptOut } from "@/lib/api/script";
import { useTrialPanel } from "@/lib/api/trialCalls";
import { activeTrial, trialEndsAt, useWallet, walletState, type Wallet } from "@/lib/api/wallet";
import { useCalls, useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { useMediaQuery } from "@/lib/useMediaQuery";

import { LatestCalls } from "../../../LatestCalls";
import { LifecycleError, MOVE_COPY } from "../../AgentLifecycle";
import { AgentReadinessPanel } from "../../AgentReadiness";
import { OpeningNotices } from "../../panels/openingNotices";
import { PendingBanner } from "../../panels/publishing";

const PHONE = "(max-width: 639px)";

/** True on a phone-width viewport; false on the server and in a browser without matchMedia. */
function useIsPhone(): boolean {
  return useMediaQuery(PHONE);
}

export function Overview({ agent, slug }: { agent: Agent; slug: string }) {
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);
  const script = useScript(session, agent.id);
  // Switching on is a publish, and publish refuses an account with unaccepted agreements
  // (`legal/service.assert_agreements_accepted`), so it is on the list.
  const agreements = useAgreementsReadiness(session);
  // Credit is the wallet's own answer — the same read and the same `walletState` the
  // dashboard's credit tile uses — never inferred from the voice tier rates.
  const wallet = useWallet(session);
  // On a free trial "switched on" means ready for test calls from the shared trial number:
  // the switch gets it ready (`/prepare`), and calls are placed from the dashboard.
  const trial = useTrialPanel(session, agent.status !== "live");
  const onTrial = trial.data?.on_trial === true;
  const { href } = useClientRealm();
  // ITS LAST CALLS (founder, REDESIGN-2): what this agent has actually been doing, the
  // first thing an owner checks after "is it live".
  const recent = useCalls(session, { agent_id: agent.id, limit: 5 });

  // OVERVIEW, DECLARED TO THE ASSISTANT. It is the section that opens first, so this is
  // what the assistant sees on an agent unless another section is open.
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: `Agent: ${agent.name}`,
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      { key: "name", label: "Agent name", value: agent.name },
      { key: "status", label: "Status", value: agent.status },
      { key: "published", label: "Callers hear the latest version", value: agent.published ? "yes" : "no" },
      { key: "direction", label: "Calls it handles", value: agent.direction },
      { key: "ai_disclosure_enabled", label: "Says it is an AI at the start", value: agent.ai_disclosure_enabled ? "yes" : "no" },
      { key: "recording_notice_enabled", label: "Says the call is recorded at the start", value: agent.recording_notice_enabled ? "yes" : "no" },
      { key: "script_opening_line", label: "Opening line (its greeting, from the script)", value: agent.script_opening_line.trim() || "none written" },
      { key: "first_words", label: "What callers hear first", value: agent.first_words.trim() || "nothing yet" },
      {
        key: "pending",
        label: "Changes waiting to go live",
        value: pending.data ? (pending.data.has_pending ? "yes" : "none") : pending.error ? "could not be read" : "still loading",
      },
    ],
    apply: noFill,
  });

  return (
    <div className="space-y-10">
      <AgentReadinessPanel agentId={agent.id} slug={slug} />
      <SetupChecklist
        agent={agent}
        slug={slug}
        pending={pending}
        script={script}
        agreements={agreements}
        wallet={wallet}
        onTrial={onTrial}
      />
      {pending.error && (
        <ProblemNotice error={pending.error} onRetry={() => void pending.refetch()} />
      )}
      {pending.data && <PendingBanner state={pending.data} />}
      <OpeningNotices agent={agent} />
      <LatestCalls
        recent={recent}
        allHref={href(`/c/${slug}/calls?agent_id=${agent.id}`)}
        callHref={(id) => href(`/c/${slug}/calls/${id}`)}
      />
    </div>
  );
}

/** One read's three answers, as the checklist needs them. */
type Read<T> = {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  refetch: () => unknown;
};

/**
 * The row for a read that did not arrive: unknown, said as unknown, never "to do" — and
 * the retry is a button on the row rather than a sentence asking for a reload
 * (error-handling-ux: the way out sits where the failure is).
 */
function unknown(id: string, label: string, read: Pick<Read<unknown>, "refetch">): ChecklistItem {
  return {
    id,
    label,
    state: "waiting",
    detail: "Couldn't check this.",
    action: (
      <button type="button" className={TEXT_ACTION} onClick={() => void read.refetch()}>
        <RotateCw aria-hidden className="h-4 w-4" />
        Try again
      </button>
    ),
  };
}

/**
 * What is left before the first call. Each item is stated from a read that ARRIVED; a read
 * that failed makes its row say so, because a failed read is not evidence about the
 * account either way.
 */
function SetupChecklist({
  agent,
  slug,
  pending,
  script,
  agreements,
  wallet,
  onTrial,
}: {
  agent: Agent;
  slug: string;
  pending: Read<PendingState>;
  script: Read<ScriptOut>;
  agreements: Read<LegalReadiness>;
  wallet: Read<Wallet>;
  onTrial: boolean;
}) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const phone = useIsPhone();
  const move = useAgentLifecycle(session, agent.id);
  // The row's button turns into "done" when the agent reads back as working; a refusal
  // stays inline under the list, in the same words the header's switch uses.
  const moveFeedback = useActionFeedback(move, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change whether this agent is working");
  const base = `/c/${slug}/agents/${agent.id}`;
  const working =
    agent.published && (agent.status === "live" || (onTrial && agent.status === "paused"));

  if (pending.isLoading || script.isLoading || agreements.isLoading || wallet.isLoading) {
    return <Skeleton rows={4} label="Checking what is left to set up" />;
  }

  const items: ChecklistItem[] = [];

  const scriptDone = script.data ? script.data.version !== null : undefined;
  if (script.data) {
    items.push({
      id: "script",
      label: "Write its script",
      state: scriptDone ? "done" : "todo",
      link: scriptDone ? undefined : { href: href(`${base}?section=script`), label: "Write" },
    });
  } else {
    items.push(unknown("script", "Write its script", script));
  }

  // The greeting is the script's own line, never a notice (D-708): an agent whose script has
  // none opens on nothing once its notices are off, and cannot make calls on some platforms.
  if (script.data && scriptDone && !script.data.is_freeform) {
    const greets = script.data.script.opening_line.trim() !== "";
    items.push({
      id: "opening",
      label: "Give it an opening line",
      state: greets ? "done" : "todo",
      ...(greets
        ? {}
        : {
            detail: "Its first words on every call.",
            link: { href: href(`${base}?section=script`), label: "Write" },
          }),
    });
  }

  if (pending.data?.voice) {
    const chosen = pending.data.voice.configured !== null;
    items.push({
      id: "voice",
      label: "Choose a voice",
      state: chosen ? "done" : "todo",
      link: chosen ? undefined : { href: href(`${base}?section=voice`), label: "Choose" },
    });
  } else if (pending.isError) {
    items.push(unknown("voice", "Choose a voice", pending));
  }

  if (agent.direction !== "outbound") {
    // The count is the agent row's own (`inbound_number_count`). One pricing model for
    // every client (D-707): the client buys its own number from Numbers once it has paid
    // and its business is verified, so a test-calls-only trial is pointed at Billing first.
    const numbered = agent.inbound_number_count > 0;
    const onTrial = wallet.data ? activeTrial(wallet.data)?.test_calls_only === true : false;
    items.push({
      id: "number",
      label: "Give it a phone number to answer",
      state: numbered ? "done" : onTrial ? "waiting" : "todo",
      ...(numbered
        ? {}
        : onTrial
          ? {
              detail: "Add credit and verify your business first.",
              link: { href: href(`/c/${slug}/billing`), label: "Add credit" },
            }
          : {
              detail: "Needs a verified business.",
              link: { href: href(`/c/${slug}/phone-number`), label: "Get a number" },
            }),
    });
  }

  if (wallet.data) {
    const credit = walletState(wallet.data);
    // An account that is not prepaid is billed by invoice, so credit is not its step.
    if (credit !== "not-prepaid") {
      const stopped = credit === "stopped";
      const trial = activeTrial(wallet.data);
      items.push({
        id: "credit",
        label: "Add calling credit",
        state: stopped ? "todo" : "done",
        detail: stopped
          ? "Calls stopped. No credit left."
          : trial !== null
            ? `Free until ${trialEndsAt(trial)}`
            : `${formatINR(wallet.data.balance_inr)} left`,
        link: stopped ? { href: href(`/c/${slug}/billing`), label: "Top up" } : undefined,
      });
    }
  } else {
    items.push(unknown("credit", "Add calling credit", wallet));
  }

  if (agreements.data) {
    // `outstanding_documents` is counted by the same `outstanding_slugs` the publish
    // refusal reads, so this item and the refusal cannot disagree.
    const accepted = agreements.data.outstanding_documents === 0;
    items.push({
      id: "agreements",
      label: "Accept the agreements",
      state: accepted ? "done" : "todo",
      link: accepted ? undefined : { href: href(`/c/${slug}/agreements`), label: "Review" },
    });
  } else {
    items.push(unknown("agreements", "Accept the agreements", agreements));
  }

  const agreementsOutstanding =
    agreements.data !== undefined && agreements.data.outstanding_documents > 0;
  // The step does the move itself (the header's switch, as a button here) rather than
  // pointing at the switch: on a trial "on" is `prepare`, test calls only (D-853).
  const switchOn: LifecycleMove | null = movesFor(agent.status).includes("activate")
    ? onTrial
      ? "prepare"
      : "activate"
    : null;
  items.push({
    id: "live",
    label: onTrial ? "Switch it on for test calls" : "Switch it on",
    state: working ? "done" : "todo",
    ...(!working && switchOn
      ? {
          action: (
            <ActionButton
              variant="primary-sm"
              status={move.variables === switchOn ? moveFeedback.status : "idle"}
              pendingLabel={MOVE_COPY[switchOn].busy}
              successLabel="Done"
              disabled={!write.allowed || move.isPending}
              title={write.reason ?? undefined}
              onClick={() => moveFeedback.run(switchOn)}
            >
              {MOVE_COPY[switchOn].label}
            </ActionButton>
          ),
        }
      : {}),
    ...(scriptDone === false && !working
      ? { disabledReason: "Write its script first." }
      : agreementsOutstanding && !working
        ? { disabledReason: "Accept the agreements first." }
        : {}),
  });

  const allDone = items.every((item) => item.state === "done");
  return (
    <div className="space-y-3">
      {/* One next step, drawn as the primary button (critique-visual-hierarchy: one
          entry point), so an owner never has to choose where to start. */}
      <Checklist
        label={allDone ? "Ready for calls" : working ? "Still to set up" : "Before its first call"}
        items={items}
        collapsible={phone || allDone}
        defaultOpen={!phone && !allDone}
        emphasizeNext
        nextLabel="Do this next"
      />
      <LifecycleError error={move.error} />
    </div>
  );
}
