"use client";

/**
 * `/c/{slug}/inbound`: EVERY INBOUND LINE (D-997). A line says what one or more of the
 * business's numbers say when called, in one agent's voice; a draft may have no number yet.
 *
 * One row per line, in the campaigns list's form: the state mark, the name (a link stretched
 * over the row), the voice, the numbers, and an Open action in the right-hand cell. New line
 * asks only for the agent; the server names the line and the owner renames it on its page.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useCreateInboundLine, useInboundLines, type InboundLine } from "@/lib/api/inboundLines";
import { useClientRealm } from "@/lib/api/session";

import { LineStatusPill, numbersText } from "./lineStatus";

export function InboundListScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const lines = useInboundLines(session);
  const write = useWriteAccess(session, "org:manage", "set up inbound lines");
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);
  const [adding, setAdding] = useState(false);

  const newButton = (
    <button
      type="button"
      className={PRIMARY_BUTTON}
      disabled={!write.allowed}
      title={refusal}
      onClick={() => setAdding(true)}
    >
      <Plus aria-hidden className="h-4 w-4" />
      New line
    </button>
  );
  const empty = lines.data !== undefined && lines.data.length === 0;

  return (
    <div className="max-w-5xl space-y-5 pb-12">
      <PageHeader
        description="What your numbers say when someone calls."
        actions={empty || adding ? undefined : newButton}
      />
      <RestrictionNote reason={write.reason} />
      {adding && <NewLineForm slug={slug} onCancel={() => setAdding(false)} />}

      {lines.isLoading ? (
        <Skeleton rows={3} label="Loading your inbound lines" />
      ) : !lines.data ? (
        <EmptyState
          variant="error"
          message="Your inbound lines did not load."
          error={lines.error}
          onRetry={() => void lines.refetch()}
        />
      ) : empty ? (
        adding ? null : (
          <EmptyState message="No inbound lines yet." action={write.allowed ? newButton : undefined} />
        )
      ) : (
        <ul aria-label="Your inbound lines" className="divide-y divide-line border-y border-line">
          {lines.data.map((line) => (
            <LineRow key={line.id} line={line} href={href(`/c/${slug}/inbound/${line.id}`)} />
          ))}
        </ul>
      )}
    </div>
  );
}

function LineRow({ line, href }: { line: InboundLine; href: string }) {
  return (
    <li className="relative grid grid-cols-1 gap-x-6 gap-y-2 py-4 transition-colors duration-(--duration-fast) hover:bg-ink/[0.02] motion-reduce:transition-none sm:grid-cols-[minmax(0,1fr)_14rem_auto] sm:items-center">
      <div className="min-w-0 space-y-1">
        <LineStatusPill line={line} />
        <Link
          href={href}
          className="block rounded-sm text-[15px] font-semibold leading-snug text-ink [overflow-wrap:anywhere] after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          {line.name}
        </Link>
        <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">Voice: {line.agent_name}</p>
      </div>
      <p className={`text-meta tabular-nums [overflow-wrap:anywhere] ${line.numbers.length ? "text-ink" : "text-ink-muted"}`}>
        {numbersText(line)}
      </p>
      <div className="relative z-raised flex sm:min-w-28 sm:justify-end">
        <Link href={href} className={SECONDARY_BUTTON_SM} aria-label={`Open ${line.name}`}>
          Open
        </Link>
      </div>
    </li>
  );
}

/** Choose the agent whose voice the new line speaks in; the server names the line. */
function NewLineForm({ slug, onCancel }: { slug: string; onCancel: () => void }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const agents = useAgents(session);
  const create = useCreateInboundLine(session);
  useActionFeedback(create, { errorDisplay: "inline" });
  const [agentId, setAgentId] = useState("");

  if (agents.isLoading) return <Skeleton rows={1} label="Loading your agents" />;
  if (!agents.data) {
    return <ProblemNotice error={agents.error ?? new Error("Your agents did not load.")} onRetry={() => agents.refetch()} />;
  }
  const offered = agents.data.filter((agent) => agent.status !== "archived");
  if (offered.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-card border border-line p-4">
        <p className="text-body text-ink">Make an agent first. It gives the line its voice.</p>
        <Link href={href(`/c/${slug}/agents/new`)} className={PRIMARY_BUTTON_SM}>
          New agent
        </Link>
      </div>
    );
  }
  const chosen = agentId || offered[0].id;
  return (
    <form
      aria-label="New inbound line"
      noValidate
      className="space-y-3 rounded-card border border-line p-4"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(
          { agent_id: chosen },
          { onSuccess: (line) => router.push(href(`/c/${slug}/inbound/${line.id}`)) },
        );
      }}
    >
      <div>
        <label className={FIELD_LABEL} htmlFor="new-line-agent">
          Whose voice answers?
        </label>
        <select
          id="new-line-agent"
          className={`${FIELD} mt-1.5 w-full sm:w-80`}
          value={chosen}
          onChange={(event) => setAgentId(event.target.value)}
        >
          {offered.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap gap-2">
        <ActionButton
          type="submit"
          variant="primary-sm"
          status={create.isPending ? "pending" : "idle"}
          pendingLabel="Starting…"
        >
          Start the line
        </ActionButton>
        <ActionButton variant="secondary-sm" disabled={create.isPending} onClick={onCancel}>
          Cancel
        </ActionButton>
      </div>
      {create.error != null && <ProblemNotice error={create.error} />}
    </form>
  );
}
