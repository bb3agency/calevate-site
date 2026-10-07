"use client";

/**
 * THE ROSTER — every working-roster agent in one list, working ones first, one row you can
 * open; and the deleted ones behind a closed disclosure.
 *
 * The "is it live" test exists ONCE, in `@/lib/agentState.ts`, which the campaign picker and
 * the detail screen also read. The count of working agents is the page header's status
 * (see `page.tsx`), so the list carries no group headings of its own.
 *
 * Each row is ONE link (doctrine §4: one target per row) and a ⋯ menu as the deliberate
 * second target. Delete in that menu opens a confirm dialog that states the four
 * consequences before it does anything; on a working agent it explains the one thing to do
 * first and offers that instead, because the server refuses to delete a live agent
 * (`agent_is_live`, D-527).
 */

import Link from "next/link";
import { useState } from "react";
import { Plus } from "lucide-react";

import {
  Disclosure,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  formatCount,
  formatIST,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { RowMenu } from "@/components/console/rowMenu";
import {
  useAgentLifecycle,
  useAgentStats,
  useArchivedAgents,
  type Agent,
  type AgentStats,
} from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { agentOwnTier } from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { DIRECTION_COPY, LANGUAGE_NAMES, agentGroup, humanise } from "@/lib/agentState";

import { LiveBadge, VoiceTierBadge } from "./AgentBadge";
import { MOVE_COPY } from "./AgentLifecycle";

export function Roster({ agents, slug }: { agents: Agent[]; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  // A separate request over `calls`, the biggest table a tenant owns: the list paints first
  // and a row simply carries no activity line until its figures exist — never a zero.
  const stats = useAgentStats(session);

  if (agents.length === 0) {
    return (
      <EmptyState
        message="No agents yet. Build one and it shows up here before it takes a call."
        action={
          <Link href={href(`/c/${slug}/agents/new`)} className={PRIMARY_BUTTON}>
            <Plus aria-hidden className="h-4 w-4" />
            Build your first agent
          </Link>
        }
      />
    );
  }

  const ordered = [
    ...agents.filter((agent) => agentGroup(agent) === "active"),
    ...agents.filter((agent) => agentGroup(agent) !== "active"),
  ];
  return <AgentList rows={ordered} slug={slug} stats={stats.data} label="Your agents" />;
}

/**
 * The deleted agents — a second request, because `GET /v1/agents` deliberately excludes
 * them (history grows without limit while the working roster does not).
 */
export function Archive({ slug }: { slug: string }) {
  const session = useClientSession();
  const archived = useArchivedAgents(session);
  const stats = useAgentStats(session);

  if (archived.error) {
    return <ProblemNotice error={archived.error} onRetry={() => void archived.refetch()} />;
  }
  if (!archived.data?.length) return null;
  return (
    <Disclosure
      title={`Deleted (${archived.data.length})`}
      subtitle="They take no calls. Their call history stays in your call log, and you can bring one back."
    >
      <AgentList rows={archived.data} slug={slug} stats={stats.data} label="Deleted agents" archived />
    </Disclosure>
  );
}

function AgentList({
  rows,
  slug,
  stats,
  label,
  archived = false,
}: {
  rows: Agent[];
  slug: string;
  stats: AgentStats[] | undefined;
  label: string;
  archived?: boolean;
}) {
  return (
    <ul
      aria-label={label}
      className={archived ? "divide-y divide-line" : "divide-y divide-line rounded-card border border-line bg-surface shadow-card"}
    >
      {rows.map((agent, index) => (
        <AgentRow
          key={agent.id}
          agent={agent}
          slug={slug}
          archived={archived}
          index={index}
          // `find`, not an index keyed by server ids: a keyed object inherits
          // `Object.prototype` (src/lib/lookup.ts), and the roster is bounded at 200 rows.
          stats={stats?.find((row) => row.agent_id === agent.id)}
        />
      ))}
    </ul>
  );
}

function AgentRow({
  agent,
  slug,
  archived,
  stats,
  index,
}: {
  agent: Agent;
  slug: string;
  archived: boolean;
  stats: AgentStats | undefined;
  index: number;
}) {
  const { href } = useClientRealm();
  const [deleting, setDeleting] = useState(false);
  const direction = lookup(DIRECTION_COPY, agent.direction);
  const language = lookup(LANGUAGE_NAMES, agent.language_primary) ?? agent.language_primary;
  const ownTier = agentOwnTier(agent);
  const open = href(`/c/${slug}/agents/${agent.id}`);

  return (
    <li
      // First paint only: `settings-enter` animates from `@starting-style`, which applies on
      // insertion, so a refetch that keeps the row does not replay it.
      className="settings-enter flex items-center gap-2 pr-2 sm:pr-4"
      style={{ transitionDelay: `${Math.min(index, 8) * 40}ms` }}
    >
      <Link
        href={open}
        className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1.5 rounded-card px-4 py-3.5 transition-colors duration-(--duration-fast) ease-out hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand sm:px-5"
      >
        <span className="min-w-0 flex-1 basis-56">
          <span title={agent.name} className="block truncate text-sm font-semibold text-ink">
            {agent.name}
          </span>
          <span className="block text-xs text-ink-muted">
            {direction?.label ?? humanise(agent.direction)} · Speaks {language}
            {/* Inbound is a per-number binding, so this is the honest per-agent count of
                calls it can answer at once; outbound concurrency is account-wide. */}
            {agent.direction !== "outbound" && (
              <>
                {" · "}
                {agent.inbound_number_count === 1
                  ? "Answers 1 number"
                  : `Answers ${formatCount(agent.inbound_number_count)} numbers`}
              </>
            )}
            {/* The server's identifier, as the invoice line prints it. */}
            {ownTier !== null && (
              <>
                {" · "}Its own AI model: {ownTier}
              </>
            )}
          </span>
          {stats && (
            <span className="block text-xs text-ink-faint">
              {formatCount(stats.calls_total)} {stats.calls_total === 1 ? "call" : "calls"} handled
              {stats.last_call_at !== null && <> · last used {formatIST(stats.last_call_at)}</>}
            </span>
          )}
          {agent.archived_at !== null && (
            <span className="block text-xs text-ink-faint">Deleted {formatIST(agent.archived_at)}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <VoiceTierBadge agent={agent} />
          <LiveBadge agent={agent} />
        </span>
      </Link>
      {!archived && (
        <RowMenu
          label={agent.name}
          items={[
            { id: "open", label: "Open", href: open },
            { id: "script", label: "Edit its script", href: href(`/c/${slug}/agents/${agent.id}/script`) },
            { id: "delete", label: "Delete…", tone: "danger", onSelect: () => setDeleting(true) },
          ]}
        />
      )}
      {deleting && <DeleteDialog agent={agent} onClose={() => setDeleting(false)} />}
    </li>
  );
}

/**
 * Delete, with its consequences stated before anything is sent. On a working agent it
 * offers Switch off instead — the server refuses to delete a live agent.
 */
function DeleteDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const session = useClientSession();
  const move = useAgentLifecycle(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "delete an agent");
  const working = agentGroup(agent) === "active";
  const copy = MOVE_COPY.archive.confirm;

  if (working) {
    return (
      <ConfirmDialog
        title={`${agent.name} is working right now`}
        confirmLabel="Switch it off"
        pendingLabel="Switching off…"
        cancelLabel="Keep it"
        pending={move.isPending}
        error={move.error}
        onCancel={onClose}
        onConfirm={() => {
          if (write.allowed) move.mutate("deactivate", { onSuccess: onClose });
        }}
      >
        <p>
          It has to be switched off before it can be deleted. Switching it off stops it
          answering and dialling, and releases the numbers it picks up.
        </p>
        <RestrictionNote reason={write.reason} />
      </ConfirmDialog>
    );
  }
  return (
    <ConfirmDialog
      title={`Delete ${agent.name}?`}
      confirmLabel={`Delete ${agent.name}`}
      pendingLabel="Deleting…"
      cancelLabel="Keep it"
      pending={move.isPending}
      error={move.error}
      onCancel={onClose}
      onConfirm={() => {
        if (write.allowed) move.mutate("archive", { onSuccess: onClose });
      }}
    >
      <ul className="list-inside list-disc space-y-1">
        {copy?.points.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
      <RestrictionNote reason={write.reason} />
    </ConfirmDialog>
  );
}
