"use client";

/**
 * THE WORKSPACE HEADER — who the agent is, whether it is taking calls, and the one action
 * that moves it forward.
 *
 * - **The On/Off switch** is the agent's lifecycle: on is `POST .../activate` (which puts it
 *   on the calling system, and is refused with the server's reason while there is no
 *   script or the agreements are outstanding); off is `POST .../deactivate`. No confirm
 *   step: the consequence is in the ⓘ beside it, and switching back is the same switch.
 *   On a free trial the switch means "on for test calls": it gets the agent ready
 *   (`/prepare`) instead of `activate`, which a trial refuses, and test calls are then
 *   placed from the dashboard through the shared trial number (D-853, founder 23 Oct 2026).
 * - **Get it ready** (a draft only) publishes it without taking calls, so the chat can try it
 *   (D-838); a refused move shows its reason, with setup links when it is missing facts.
 * - **Try it** opens the Training tab, where the chat and the practice call are (D-825),
 *   through the tabs' own unsaved-edits guard (D-826) like the ⋯ menu's Delete.
 * - **Put it live** is the one filled button, and only while the script's draft differs
 *   from what callers hear. It is the same step as the builder's (`script/PutLive.tsx`), so
 *   on the Script tab, where the builder shows its own, the header leaves it out.
 * - A deleted agent has one move: **Bring it back**.
 * - **Show me around** (`tour`, live agents only) sits under the header line rather than
 *   among the actions, so it never competes with them (D-855).
 *
 * Delete is in the ⋯ menu and only points at Settings, where its consequences are stated
 * above the button that does it.
 */

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { MessageSquareText } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { formatINR, ProblemNotice, RestrictionNote, SECONDARY_BUTTON, ToggleSwitch } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useSectionLink } from "@/components/console/settingsLayout";
import { RowMenu, type RowMenuItem } from "@/components/arc/menu";
import { STATUS_COPY, isDeleted, movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent, type LifecycleMove } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { usePendingChanges } from "@/lib/api/publishing";
import { useScript, useUndoScript } from "@/lib/api/script";
import { useTrialPanel } from "@/lib/api/trialCalls";
import { type Spend, useSpend } from "@/lib/api/spend";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { LiveBadge, liveState } from "../../AgentBadge";
import { LifecycleError, MOVE_COPY } from "../../AgentLifecycle";
import { stagedScript, voiceTierLine } from "../../panels/publishing";
import { PutLiveDialog, usePutLive } from "../script/PutLive";
import { TRY_IT_ANCHOR } from "../tour/tourModel";
import { hasUnpublished, workingCopy } from "../script/scriptDraft";

export function AgentHeader({
  agent,
  slug,
  onScriptTab = false,
  tour,
}: {
  agent: Agent;
  slug: string;
  /** The Script tab is open, and the builder there carries its own Put it live. */
  onScriptTab?: boolean;
  /** The page tour's trigger, which also holds the tour. */
  tour?: ReactNode;
}) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);
  const move = useAgentLifecycle(session, agent.id);
  const undo = useUndoScript(session, agent.id);
  /* Bringing an agent back or getting it ready changes which buttons are offered, so the one
     pressed is gone when it succeeds: those say so in a toast. The switch is its own success.
     A refusal stays inline (`LifecycleError`). */
  const moveFeedback = useActionFeedback(move, {
    errorDisplay: "inline",
    successToast: (_, key) => (key === "restore" || key === "prepare" ? MOVE_COPY[key].done : null),
  });
  // Started from the ⋯ menu, which closes: the result is said in a toast.
  const undoFeedback = useActionFeedback(undo, {
    errorDisplay: "inline",
    successToast: "Changes undone. Callers hear the same as before.",
  });
  const write = useWriteAccess(session, "org:manage", "change whether this agent is working");
  // Owners see what this agent spent this month; staff without billing:read see nothing,
  // and a failed read shows nothing rather than a guessed figure.
  const billing = useWriteAccess(session, "billing:read", "see what this agent spent");
  const spend = useSpend(session, undefined, { enabled: billing.allowed });
  const deleted = isDeleted(agent);

  const moves = movesFor(agent.status);
  const trial = useTrialPanel(session, !deleted && agent.status !== "live");
  const onTrial = trial.data?.on_trial === true;
  const live = liveState(agent, onTrial);
  const staged = pending.data ? stagedScript(pending.data) : undefined;
  const base = `/c/${slug}/agents/${agent.id}`;
  // Guarded by the layout when the header is drawn inside it; a plain link otherwise.
  const training = useSectionLink("training");
  const settings = useSectionLink("settings");

  const items: RowMenuItem[] = deleted
    ? []
    : [
        ...(staged
          ? [
              {
                id: "undo",
                label: "Undo waiting changes",
                onSelect: () => undoFeedback.run(),
                disabled: !write.allowed || undo.isPending,
                hint: write.reason ?? undefined,
              },
            ]
          : []),
        settings
          ? { id: "delete", label: "Delete…", tone: "danger" as const, onSelect: settings.go }
          : { id: "delete", label: "Delete…", tone: "danger" as const, href: href(`${base}?section=settings`) },
      ];

  const status = lookup(STATUS_COPY, agent.status);
  // The status column is named only when it disagrees with the badge in a way the badge
  // does not already say: "switched off" is the badge's own word for a paused agent.
  const stateLine =
    status &&
    !deleted &&
    !onTrial &&
    agent.status !== "paused" &&
    agent.published !== (agent.status === "live")
      ? `${live.detail} Status: ${status.label}.`
      : live.detail;
  // The tier it speaks in, and that tier's rate, beside the state (Clear or Studio only).
  const tierLine = deleted ? null : voiceTierLine(pending.data);
  const spendLine = spend.isSuccess && !deleted ? agentMonthLine(spend.data, agent.id) : null;
  // Three short facts, each on its own wrap unit, so a phone breaks between facts rather
  // than mid-sentence (responsive-layout-patterns).
  const detail = (
    <span className="flex flex-wrap gap-x-3 gap-y-0.5">
      {[stateLine, tierLine, spendLine]
        .filter((part): part is string => Boolean(part))
        .map((part, index) => (
          <span key={part} className={index === 0 ? undefined : "whitespace-nowrap"}>
            {index > 0 && <span aria-hidden className="mr-3 text-ink-faint">·</span>}
            {part}
          </span>
        ))}
    </span>
  );

  const restoreButton = deleted && moves.includes("restore") && (
    <ActionButton
      status={move.variables === "restore" ? moveFeedback.status : "idle"}
      pendingLabel={MOVE_COPY.restore.busy}
      successLabel="Done"
      onClick={() => moveFeedback.run("restore")}
      disabled={!write.allowed}
      title={write.reason ?? undefined}
      className="flex-1 whitespace-nowrap sm:flex-none"
    >
      {MOVE_COPY.restore.label}
    </ActionButton>
  );

  return (
    <div className="space-y-3">
      <PageHeader
        back={{ href: href(`/c/${slug}/agents`), label: "All agents" }}
        title={agent.name}
        status={<LiveBadge agent={agent} />}
        description={detail}
        actions={
          // On a phone: the switch and the ⋯ menu share the first row, the buttons fill the
          // second at full width (mobile-native: 44px targets, no orphaned menu). From `sm`
          // the pair dissolves into one row and the menu goes last.
          <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
            {restoreButton}
            {deleted && items.length > 0 && <RowMenu label={agent.name} items={items} />}
            {!deleted && (
              <>
                <div className="flex w-full items-center justify-between gap-2 sm:contents">
                  <OnOffSwitch agent={agent} canWrite={write.allowed} onTrial={onTrial} move={move} />
                  {items.length > 0 && (
                    <span className="sm:order-last">
                      <RowMenu label={agent.name} items={items} />
                    </span>
                  )}
                </div>
                {moves.includes("prepare") && (
                  <ActionButton
                    variant="secondary"
                    status={move.variables === "prepare" ? moveFeedback.status : "idle"}
                    pendingLabel={MOVE_COPY.prepare.busy}
                    successLabel="Done"
                    onClick={() => moveFeedback.run("prepare")}
                    disabled={!write.allowed || (move.isPending && move.variables !== "prepare")}
                    title={write.reason ?? MOVE_COPY.prepare.hint}
                    className="flex-1 whitespace-nowrap sm:flex-none"
                  >
                    {MOVE_COPY.prepare.label}
                  </ActionButton>
                )}
                <Link
                  href={training?.href ?? href(`${base}?section=training`)}
                  onClick={training?.onClick}
                  scroll={false}
                  data-tour={TRY_IT_ANCHOR}
                  className={`${SECONDARY_BUTTON} flex-1 justify-center whitespace-nowrap sm:flex-none`}
                >
                  <MessageSquareText aria-hidden className="h-4 w-4" />
                  Try it
                </Link>
                {!onScriptTab && (
                  <PutLiveButton agent={agent} canWrite={write.allowed} reason={write.reason} voiceLine={tierLine} />
                )}
              </>
            )}
          </div>
        }
      />
      {/* The state is said once, in the header line above; on a trial this row only adds
          the place a test call is made from. */}
      {!deleted && (tour || (onTrial && agent.published && agent.status === "paused")) && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
          {tour}
          {onTrial && agent.published && agent.status === "paused" && (
            <Link
              href={href(`/c/${slug}`)}
              className="inline-flex items-center text-body font-medium text-brand-strong underline-offset-2 hover:underline touch:min-h-11"
            >
              Make a test call
            </Link>
          )}
        </div>
      )}
      <RestrictionNote reason={write.reason} />

      <LifecycleError error={move.error} />
      {undo.error && <ProblemNotice error={undo.error} />}
    </div>
  );
}

function OnOffSwitch({
  agent,
  canWrite,
  onTrial,
  move,
}: {
  agent: Agent;
  canWrite: boolean;
  /** On a free trial "on" means ready for test calls, reached by `prepare`. */
  onTrial: boolean;
  move: ReturnType<typeof useAgentLifecycle>;
}) {
  const moves = movesFor(agent.status);
  const readyForTests = onTrial && agent.published && agent.status === "paused";
  const next: LifecycleMove | null = readyForTests
    ? null
    : moves.includes("deactivate")
      ? "deactivate"
      : onTrial && moves.includes("activate")
        ? "prepare"
        : moves.includes("activate")
          ? "activate"
          : null;
  const on = readyForTests || next === "deactivate";
  const busy =
    move.isPending &&
    (move.variables === "activate" || move.variables === "deactivate" || move.variables === "prepare");
  return (
    <span className="flex items-center gap-1">
      <ToggleSwitch
        className="touch:min-h-11 flex items-center px-1"
        label={busy ? MOVE_COPY[next ?? "activate"].busy : "Taking calls"}
        checked={on}
        disabled={!canWrite || next === null || move.isPending}
        onChange={() => {
          if (next !== null) move.mutate(next);
        }}
      />
      {next && (
        <InfoTip label={MOVE_COPY[next].label} align="end">
          <p>{MOVE_COPY[next].hint}</p>
        </InfoTip>
      )}
    </span>
  );
}

/** Shown only while callers hear something different from the draft. */
function PutLiveButton({
  agent,
  canWrite,
  reason,
  voiceLine,
}: {
  agent: Agent;
  canWrite: boolean;
  reason: string | null;
  voiceLine: string | null;
}) {
  const session = useClientSession();
  const script = useScript(session, agent.id);
  const putLive = usePutLive(session, agent.id);
  const [asking, setAsking] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  if (!script.data) return null;
  const out = script.data;
  const local = workingCopy(out).script;
  if (!hasUnpublished(out, local)) {
    return done ? (
      <span role="status" className="text-meta text-ink-muted">
        {done}
      </span>
    ) : null;
  }
  return (
    <>
      <ActionButton
        status={putLive.pending ? "pending" : "idle"}
        pendingLabel="Putting it live…"
        disabled={!canWrite}
        title={reason ?? undefined}
        onClick={() => setAsking(true)}
        className="flex-1 whitespace-nowrap sm:flex-none"
      >
        Put it live
      </ActionButton>
      {asking && (
        <PutLiveDialog
          agentId={agent.id}
          live={out.script}
          draft={local}
          agentOn={agent.published && agent.status === "live"}
          voiceLine={voiceLine}
          pending={putLive.pending}
          status={putLive.status}
          error={putLive.error}
          onCancel={() => {
            setAsking(false);
            putLive.reset();
          }}
          onConfirm={(summary) =>
            putLive.run(out, local, summary, (r) => {
              setAsking(false);
              setDone(r.live ? "Live from the next call" : "Saved; callers hear it once it is on");
            })
          }
        />
      )}
    </>
  );
}

/**
 * One agent's charge this month, as the header line reads it, or null when there is no
 * figure to show. An agent with no row in `by_agent` made no charged call this month, which
 * is a real zero rather than a missing read.
 */
function agentMonthLine(spend: Spend, agentId: string): string {
  const row = spend.by_agent.find((entry) => entry.agent_id === agentId);
  return row ? `${formatINR(row.charged_inr)} this month` : "Nothing spent this month";
}
