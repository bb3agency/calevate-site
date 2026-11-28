"use client";

/**
 * THE ROSTER — every working-roster agent in one list, working ones first, one row you can
 * open; and the deleted ones behind a closed disclosure.
 *
 * The "is it live" test exists ONCE, in `@/lib/agentState.ts`, which the campaign picker and
 * the detail screen also read. The count of working agents is the page header's status
 * (see `page.tsx`), so the list carries no group headings of its own.
 *
 * Each row is ONE link (doctrine §4: one target per row), a "Try it" text action that opens
 * the agent's practice chat, and a ⋯ menu. Delete in that menu opens a confirm dialog that states the four
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
import { useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { ChipGroup } from "@/components/arc/chip-group";
import { RowMenu } from "@/components/arc/menu";
import { SearchField } from "@/components/arc/search-field";
import {
  useAgentLifecycle,
  useAgentStats,
  useArchivedAgents,
  type Agent,
  type AgentStats,
} from "@/lib/api/agents";
import { useAgentsToday, type AgentToday } from "@/lib/api/analytics";
import { useWriteAccess } from "@/lib/api/hooks";
import { useAccountReadiness, type AccountReadiness } from "@/lib/api/readiness";
import { agentOwnTier } from "@/lib/api/llmModels";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { DIRECTION_COPY, LANGUAGE_NAMES, agentGroup, humanise } from "@/lib/agentState";

import { LiveBadge, VoiceTierBadge } from "./AgentBadge";
import { MOVE_COPY } from "./AgentLifecycle";
import { ReadinessScore } from "./AgentReadiness";

/** The roster limit (`agents/roster.AGENT_ROSTER_LIMIT`): every listed agent gets its score. */
const ROSTER_LIMIT = 200;

/** Above this many agents the list gets a search box and the state chips. */
export const FIND_FROM = 5;

export type RosterState = "working" | "off" | "not_live";

/** Working: live on the calling system. Off: published once, switched off now. Not live yet:
 *  never published. The "is it live" test itself stays `agentGroup`'s. */
export function rosterState(agent: Agent): RosterState {
  if (agentGroup(agent) === "active") return "working";
  return agent.published ? "off" : "not_live";
}

const STATE_LABELS: Record<RosterState, string> = {
  working: "Working",
  off: "Off",
  not_live: "Not live yet",
};

/** "just now", "4 min ago", "2 h ago" today; the IST time and day further back. */
export function sinceWords(at: string, now: number = Date.now()): string {
  const minutes = Math.floor((now - new Date(at).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return formatIST(at);
}

/** "Today: 12 calls · 3 interested", IST. An agent absent from the read had none today. */
export function todayWords(row: AgentToday | undefined): string {
  const calls = row?.calls ?? 0;
  const interested = row?.interested ?? 0;
  return `Today: ${formatCount(calls)} ${calls === 1 ? "call" : "calls"} · ${formatCount(interested)} interested`;
}

export function Roster({ agents, slug }: { agents: Agent[]; slug: string }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  // A separate request over `calls`, the biggest table a tenant owns: the list paints first
  // and a row simply carries no activity line until its figures exist — never a zero.
  const stats = useAgentStats(session);
  // Today's line is a third read; until it arrives, or if it fails, a row shows the lifetime
  // line instead, never a "Today: 0" it does not know.
  const today = useAgentsToday(session);
  const [query, setQuery] = useState("");
  const [state, setState] = useState<RosterState | null>(null);
  // Like the figures: a row whose score has not arrived (or failed) shows none, never a 0.
  const readiness = useAccountReadiness(session, ROSTER_LIMIT);
  // The list, not the row or its dialog, holds the delete: the move's refresh is awaited, so
  // the deleted agent's row has already left the list when the move succeeds, and a feedback
  // hook unmounted with it would never say it worked. `target` outlives the dialog so the
  // toast can name the agent.
  const [target, setTarget] = useState<Agent | null>(null);
  const [asking, setAsking] = useState(false);
  const move = useAgentLifecycle(session, target?.id ?? "");
  const moveFeedback = useActionFeedback(move, {
    errorDisplay: "inline",
    successToast: (_data, step) =>
      target === null ? null : step === "archive" ? `${target.name} deleted` : `${target.name} switched off`,
  });
  const askToDelete = (agent: Agent) => {
    move.reset();
    setTarget(agent);
    setAsking(true);
  };

  if (agents.length === 0) {
    return (
      <EmptyState illustration={<EmptySketch kind="actions" />}
        message="No agents yet."
        action={
          <Link href={href(`/c/${slug}/agents/first`)} className={PRIMARY_BUTTON}>
            <Plus aria-hidden className="h-4 w-4" />
            Meet your agent
          </Link>
        }
      />
    );
  }

  const ordered = [
    ...agents.filter((agent) => agentGroup(agent) === "active"),
    ...agents.filter((agent) => agentGroup(agent) !== "active"),
  ];
  const finding = agents.length > FIND_FROM;
  const needle = query.trim().toLocaleLowerCase();
  const shown = finding
    ? ordered.filter(
        (agent) =>
          (state === null || rosterState(agent) === state) &&
          (needle === "" || agent.name.toLocaleLowerCase().includes(needle)),
      )
    : ordered;
  const counts = (Object.keys(STATE_LABELS) as RosterState[]).map((key) => ({
    value: key,
    label: `${STATE_LABELS[key]} ${formatCount(agents.filter((agent) => rosterState(agent) === key).length)}`,
  }));
  return (
    <>
      {finding && (
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <SearchField
            label="Find an agent"
            hideLabel
            placeholder="Find an agent"
            value={query}
            onValueChange={setQuery}
            className="w-full sm:w-64"
          />
          <ChipGroup
            mode="single"
            label="Show agents by state"
            allLabel="All"
            chips={counts}
            value={state}
            onChange={(next) => setState((next as RosterState | null) ?? null)}
          />
        </div>
      )}
      {shown.length === 0 ? (
        <EmptyState
          variant="filtered"
          message="No agent matches."
          onClear={() => {
            setQuery("");
            setState(null);
          }}
        />
      ) : (
        <AgentList
          rows={shown}
          slug={slug}
          stats={stats.data}
          today={today.data?.agents}
          readiness={readiness.data}
          label="Your agents"
          onDelete={askToDelete}
        />
      )}
      {asking && target !== null && (
        <DeleteDialog
          // The roster's current copy of the agent, so a refetch while the dialog is open
          // (it was switched on elsewhere) changes which question it asks.
          agent={agents.find((agent) => agent.id === target.id) ?? target}
          move={move}
          status={moveFeedback.status}
          onClose={() => setAsking(false)}
        />
      )}
    </>
  );
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
      subtitle="No calls. Open one to bring it back."
    >
      <AgentList rows={archived.data} slug={slug} stats={stats.data} label="Deleted agents" archived />
    </Disclosure>
  );
}

function AgentList({
  rows,
  slug,
  stats,
  today,
  readiness,
  label,
  archived = false,
  onDelete,
}: {
  rows: Agent[];
  slug: string;
  stats: AgentStats[] | undefined;
  /** Absent on the deleted list, and until (or unless) today's read arrives. */
  today?: AgentToday[];
  /** Absent on the deleted list, which is not being made ready. */
  readiness?: AccountReadiness;
  label: string;
  archived?: boolean;
  /** Absent on the deleted list, whose rows offer no delete. */
  onDelete?: (agent: Agent) => void;
}) {
  return (
    <ul
      aria-label={label}
      className={archived ? "divide-y divide-line" : "divide-y divide-line border-y border-line"}
    >
      {rows.map((agent, index) => (
        <AgentRow
          key={agent.id}
          agent={agent}
          slug={slug}
          index={index}
          onDelete={archived ? undefined : onDelete}
          // `find`, not an index keyed by server ids: a keyed object inherits
          // `Object.prototype` (src/lib/lookup.ts), and the roster is bounded at 200 rows.
          stats={stats?.find((row) => row.agent_id === agent.id)}
          today={today === undefined ? undefined : { row: today.find((row) => row.agent_id === agent.id) }}
          score={readiness?.agents.find((row) => row.agent_id === agent.id)?.score}
        />
      ))}
    </ul>
  );
}

function AgentRow({
  agent,
  slug,
  stats,
  today,
  score,
  index,
  onDelete,
}: {
  agent: Agent;
  slug: string;
  stats: AgentStats | undefined;
  /** Present once today's read has arrived; `row` is absent for an agent with no call today. */
  today?: { row: AgentToday | undefined };
  score?: number;
  index: number;
  onDelete?: (agent: Agent) => void;
}) {
  const { href } = useClientRealm();
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
          {/* Short facts joined by dots, one line each: what it does, the language, how
              many numbers it answers, and its own model when it has one. */}
          <span className="block text-meta text-ink-muted">
            {direction?.label ?? humanise(agent.direction)} · {language}
            {/* Inbound is a per-number binding, so this is the honest per-agent count of
                calls it can answer at once; outbound concurrency is account-wide. */}
            {agent.direction !== "outbound" && (
              <>
                {" · "}
                {agent.inbound_number_count === 1
                  ? "1 number"
                  : `${formatCount(agent.inbound_number_count)} numbers`}
              </>
            )}
            {/* The server's identifier, as the invoice line prints it. */}
            {ownTier !== null && (
              <>
                {" · "}AI model: {ownTier}
              </>
            )}
          </span>
          {today ? (
            <span className="block text-meta text-ink-muted">
              {todayWords(today.row)}
              {stats?.last_call_at ? <> · last {sinceWords(stats.last_call_at)}</> : null}
            </span>
          ) : (
            stats && (
              <span className="block text-meta text-ink-faint">
                {formatCount(stats.calls_total)} {stats.calls_total === 1 ? "call" : "calls"}
                {stats.last_call_at !== null && <> · last {formatIST(stats.last_call_at)}</>}
              </span>
            )
          )}
          {agent.archived_at !== null && (
            <span className="block text-xs text-ink-faint">Deleted {formatIST(agent.archived_at)}</span>
          )}
        </span>
        <span className="flex shrink-0 flex-wrap items-center gap-2">
          <ReadinessScore score={score} />
          <VoiceTierBadge agent={agent} />
          <LiveBadge agent={agent} />
        </span>
      </Link>
      {onDelete && (
        <Link
          href={href(`/c/${slug}/agents/${agent.id}?section=training`)}
          className="shrink-0 rounded-md px-2 py-1 text-meta font-medium text-ink underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          Try it
        </Link>
      )}
      {onDelete && (
        <RowMenu
          label={agent.name}
          items={[
            { id: "open", label: "Open", href: open },
            { id: "settings", label: "Open its settings", href: href(`/c/${slug}/agents/${agent.id}?section=settings`) },
            { id: "delete", label: "Delete…", tone: "danger", onSelect: () => onDelete(agent) },
          ]}
        />
      )}
    </li>
  );
}

/**
 * Delete, with its consequences stated before anything is sent. On a working agent it
 * offers Switch off instead — the server refuses to delete a live agent.
 */
function DeleteDialog({
  agent,
  move,
  status,
  onClose,
}: {
  agent: Agent;
  move: ReturnType<typeof useAgentLifecycle>;
  status: FeedbackStatus;
  onClose: () => void;
}) {
  const session = useClientSession();
  const write = useWriteAccess(session, "org:manage", "delete an agent");
  const working = agentGroup(agent) === "active";
  const copy = MOVE_COPY.archive.confirm;

  if (working) {
    return (
      <ConfirmDialog
        title={`${agent.name} is taking calls`}
        confirmLabel="Switch it off"
        pendingLabel="Switching off…"
        cancelLabel="Keep it"
        status={status}
        successLabel="Switched off"
        error={move.error}
        onCancel={onClose}
        onConfirm={() => {
          if (write.allowed) move.mutate("deactivate", { onSuccess: onClose });
        }}
      >
        <p className="font-medium text-ink">Switch it off first.</p>
        <p>{MOVE_COPY.deactivate.hint}</p>
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
      status={status}
      successLabel="Deleted"
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
