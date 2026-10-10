"use client";

/**
 * THE WORKSPACE HEADER — who the agent is, whether it is taking calls, and the one action
 * that moves it forward.
 *
 * - **The On/Off switch** is the agent's lifecycle: on is `POST .../activate` (which puts it
 *   on the calling system, and is refused with the server's reason while there is no
 *   script or the agreements are outstanding); off is `POST .../deactivate`. No confirm
 *   step: the consequence is in the ⓘ beside it, and switching back is the same switch.
 * - **Try it** opens a side panel: ring my phone where the account can, and the test
 *   conversations, which test what callers hear now.
 * - **Put it live** is the one filled button, and only while the script's draft differs
 *   from what callers hear. It is the same step as the builder's (`script/PutLive.tsx`).
 * - A deleted agent has one move: **Bring it back**.
 *
 * Delete is in the ⋯ menu and only points at Settings, where its consequences are stated
 * above the button that does it.
 */

import { useState } from "react";
import { FlaskConical } from "lucide-react";

import { formatINR, ProblemNotice, PRIMARY_BUTTON, RestrictionNote, SECONDARY_BUTTON, ToggleSwitch } from "@/components/ui";
import { Drawer } from "@/components/console/drawer";
import { SavedTests } from "@/components/improvement/SavedTests";
import { TryChat } from "@/components/improvement/TryChat";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { RowMenu, type RowMenuItem } from "@/components/console/rowMenu";
import { STATUS_COPY, isDeleted, movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent, type LifecycleMove } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { usePendingChanges } from "@/lib/api/publishing";
import { useScript, useUndoScript } from "@/lib/api/script";
import { type Spend, useSpend } from "@/lib/api/spend";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { activeTrial, useWallet } from "@/lib/api/wallet";
import { lookup } from "@/lib/lookup";

import { LiveBadge, liveState } from "../../AgentBadge";
import { MOVE_COPY } from "../../AgentLifecycle";
import { stagedScript, voiceTierLine } from "../../panels/publishing";
import { PutLiveDialog, usePutLive } from "../script/PutLive";
import { TestConversationsPanel } from "../script/TestConversationsPanel";
import { hasUnpublished, workingCopy } from "../script/scriptDraft";
import { TryIt } from "./tryIt";

export function AgentHeader({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);
  const move = useAgentLifecycle(session, agent.id);
  const undo = useUndoScript(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change whether this agent is working");
  // Owners see what this agent spent this month; staff without billing:read see nothing,
  // and a failed read shows nothing rather than a guessed figure.
  const billing = useWriteAccess(session, "billing:read", "see what this agent spent");
  const spend = useSpend(session, undefined, { enabled: billing.allowed });
  const deleted = isDeleted(agent);

  const live = liveState(agent);
  const moves = movesFor(agent.status);
  const staged = pending.data ? stagedScript(pending.data) : undefined;
  const base = `/c/${slug}/agents/${agent.id}`;
  const [trying, setTrying] = useState(false);

  const items: RowMenuItem[] = deleted
    ? []
    : [
        { id: "script", label: "Open the script builder", href: href(`${base}/script`) },
        ...(staged
          ? [
              {
                id: "undo",
                label: "Undo waiting changes",
                onSelect: () => undo.mutate(),
                disabled: !write.allowed || undo.isPending,
                hint: write.reason ?? undefined,
              },
            ]
          : []),
        { id: "delete", label: "Delete…", tone: "danger" as const, href: href(`${base}?section=advanced`) },
      ];

  const status = lookup(STATUS_COPY, agent.status);
  const stateLine =
    status && !deleted && agent.published !== (agent.status === "live")
      ? `${live.detail} Status: ${status.label}.`
      : live.detail;
  // The tier it speaks in, and that tier's rate, beside the state (Clear or Studio only).
  const tierLine = deleted ? null : voiceTierLine(pending.data);
  const spendLine = spend.isSuccess && !deleted ? agentMonthLine(spend.data, agent.id) : null;
  const detail = [stateLine, tierLine, spendLine].filter(Boolean).join(" · ");

  const restoreButton = deleted && moves.includes("restore") && (
    <button
      type="button"
      onClick={() => move.mutate("restore")}
      disabled={!write.allowed || move.isPending}
      title={write.reason ?? undefined}
      className={`${PRIMARY_BUTTON} flex-1 sm:flex-none`}
    >
      {move.isPending ? MOVE_COPY.restore.busy : MOVE_COPY.restore.label}
    </button>
  );

  return (
    <div className="space-y-3">
      <PageHeader
        back={{ href: href(`/c/${slug}/agents`), label: "All agents" }}
        title={agent.name}
        status={<LiveBadge agent={agent} />}
        description={detail}
        actions={
          <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
            {restoreButton}
            {!deleted && (
              <>
                <OnOffSwitch agent={agent} canWrite={write.allowed} move={move} />
                <button type="button" className={`${SECONDARY_BUTTON} flex-1 sm:flex-none`} onClick={() => setTrying(true)}>
                  <FlaskConical aria-hidden className="h-4 w-4" />
                  Try it
                </button>
                <PutLiveButton agent={agent} canWrite={write.allowed} reason={write.reason} voiceLine={tierLine} />
              </>
            )}
            {items.length > 0 && <RowMenu label={agent.name} items={items} />}
          </div>
        }
      />
      <RestrictionNote reason={write.reason} />
      {move.error && <ProblemNotice error={move.error} />}
      {undo.error && <ProblemNotice error={undo.error} />}
      {trying && <TryItPanel agent={agent} slug={slug} onClose={() => setTrying(false)} />}
    </div>
  );
}

function OnOffSwitch({
  agent,
  canWrite,
  move,
}: {
  agent: Agent;
  canWrite: boolean;
  move: ReturnType<typeof useAgentLifecycle>;
}) {
  const moves = movesFor(agent.status);
  const next: LifecycleMove | null = moves.includes("deactivate")
    ? "deactivate"
    : moves.includes("activate")
      ? "activate"
      : null;
  const on = next === "deactivate";
  const busy = move.isPending && (move.variables === "activate" || move.variables === "deactivate");
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
      <button
        type="button"
        className={`${PRIMARY_BUTTON} flex-1 sm:flex-none`}
        disabled={!canWrite || putLive.pending}
        title={reason ?? undefined}
        onClick={() => setAsking(true)}
      >
        {putLive.pending ? "Putting it live…" : "Put it live"}
      </button>
      {asking && (
        <PutLiveDialog
          live={out.script}
          draft={local}
          agentOn={agent.published && agent.status === "live"}
          voiceLine={voiceLine}
          pending={putLive.pending}
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

/** "Try it": ring my phone where the account can, and the test conversations. */
function TryItPanel({ agent, slug, onClose }: { agent: Agent; slug: string; onClose: () => void }) {
  const session = useClientSession();
  const wallet = useWallet(session);
  const [number, setNumber] = useState("");
  const write = useWriteAccess(session, "org:manage", "test this agent");
  const trial = wallet.data ? activeTrial(wallet.data) : null;
  const onTrial = trial !== null && trial.test_calls_only === true;
  return (
    <Drawer open onClose={onClose} title="Try it" description="Hear and test what callers hear now.">
      <div className="space-y-8">
        <TryIt agent={agent} slug={slug} onTrial={onTrial} number={number} onNumber={setNumber} />
        <TryChat agentId={agent.id} canWrite={write.allowed} />
        <TestConversationsPanel agentId={agent.id} />
        <SavedTests agentId={agent.id} canWrite={write.allowed} />
      </div>
    </Drawer>
  );
}
