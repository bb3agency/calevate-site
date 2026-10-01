"use client";

/**
 * THE WORKSPACE HEADER — who the agent is, whether it is working, and the ONE action that
 * moves it forward (D-657).
 *
 * The primary is chosen by state, because "publish" means a different request at each
 * stage of an agent's life:
 *
 * - switched off or never published → **Switch on** (`POST /v1/agents/{id}/activate`),
 *   which is the client's publish: it puts the agent on the calling system;
 * - live with a staged script → **Apply changes** (`POST /v1/agents/{id}/script/apply`,
 *   `org:manage`), CAS on the staged version the owner can see in the banner below;
 * - live with nothing waiting → no primary at all, since there is nothing to publish;
 * - deleted → **Bring it back**.
 *
 * Everything else that moves the agent (switch off, undo, delete) is in the row menu, and
 * Delete only points at the Advanced section, where its consequences are stated above the
 * button that does it (doctrine §4).
 */

import { ProblemNotice, PRIMARY_BUTTON, RestrictionNote } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { RowMenu, type RowMenuItem } from "@/components/console/rowMenu";
import { STATUS_COPY, isDeleted, movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent, type LifecycleMove } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { usePendingChanges } from "@/lib/api/publishing";
import { useApplyScript, useUndoScript } from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { LiveBadge, liveState } from "../../AgentBadge";
import { MOVE_COPY } from "../../AgentLifecycle";
import { stagedScript } from "../../panels/publishing";

export function AgentHeader({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);
  const move = useAgentLifecycle(session, agent.id);
  const apply = useApplyScript(session, agent.id);
  const undo = useUndoScript(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change whether this agent is working");

  const live = liveState(agent);
  const moves = movesFor(agent.status);
  const staged = pending.data ? stagedScript(pending.data) : undefined;
  const deleted = isDeleted(agent);
  const base = `/c/${slug}/agents/${agent.id}`;

  const lifecycleButton = (key: LifecycleMove) => (
    <span className="flex flex-1 items-center gap-1 sm:flex-none">
      <button
        type="button"
        onClick={() => move.mutate(key)}
        disabled={!write.allowed || move.isPending}
        title={write.reason ?? undefined}
        className={`${PRIMARY_BUTTON} flex-1 sm:flex-none`}
      >
        {move.isPending && move.variables === key ? MOVE_COPY[key].busy : MOVE_COPY[key].label}
      </button>
      <InfoTip label={MOVE_COPY[key].label} align="end">
        <p>{MOVE_COPY[key].hint}</p>
      </InfoTip>
    </span>
  );

  let primary = null;
  if (deleted && moves.includes("restore")) primary = lifecycleButton("restore");
  else if (moves.includes("activate")) primary = lifecycleButton("activate");
  else if (staged) {
    primary = (
      <button
        type="button"
        onClick={() => apply.mutate({ expected_version: staged.staged_version })}
        disabled={!write.allowed || apply.isPending}
        title={write.reason ?? undefined}
        className={`${PRIMARY_BUTTON} flex-1 sm:flex-none`}
      >
        {apply.isPending ? "Applying…" : "Apply changes"}
      </button>
    );
  }

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
        ...(moves.includes("deactivate")
          ? [
              {
                id: "deactivate",
                label: MOVE_COPY.deactivate.label,
                onSelect: () => move.mutate("deactivate"),
                disabled: !write.allowed || move.isPending,
                hint: write.reason ?? undefined,
              },
            ]
          : []),
        {
          id: "delete",
          label: "Delete…",
          tone: "danger" as const,
          href: href(`${base}?section=advanced`),
        },
      ];

  // `status` and "on the calling system" are two facts that can disagree; the pill says the
  // second, and the line names the first only when it adds something.
  const status = lookup(STATUS_COPY, agent.status);
  const detail =
    status && !deleted && agent.published !== (agent.status === "live")
      ? `${live.detail} Status: ${status.label}.`
      : live.detail;

  return (
    <div className="space-y-3">
      <PageHeader
        back={{ href: href(`/c/${slug}/agents`), label: "All agents" }}
        title={agent.name}
        status={
          <>
            <LiveBadge agent={agent} />
            {/* With no primary the menu sits on the title line, so a phone does not spend
                a whole row on one ⋯ button. */}
            {!primary && items.length > 0 && (
              <span className="ml-auto">
                <RowMenu label={agent.name} items={items} />
              </span>
            )}
          </>
        }
        description={detail}
        actions={
          primary ? (
            <div className="flex w-full items-center justify-end gap-2 sm:w-auto">
              {primary}
              {items.length > 0 && <RowMenu label={agent.name} items={items} />}
            </div>
          ) : undefined
        }
      />
      <RestrictionNote reason={write.reason} />
      {/* Apply is offered only on the server's word that a script is staged; a failed read
          says so here rather than silently offering nothing. */}
      {pending.isError && !deleted && (
        <p className="text-xs text-ink-muted">
          Whether a script change is waiting could not be read just now, so Apply is not
          offered. Reload to try again.
        </p>
      )}
      {move.error && <ProblemNotice error={move.error} />}
      {apply.error && <ProblemNotice error={apply.error} />}
      {undo.error && <ProblemNotice error={undo.error} />}
    </div>
  );
}
