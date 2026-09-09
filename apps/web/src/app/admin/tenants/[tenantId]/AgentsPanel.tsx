"use client";

import Link from "next/link";
import { ScrollText } from "lucide-react";

import { Card, EmptyState, ProblemNotice, Skeleton } from "@/components/ui";
import { useTenantAgents } from "@/lib/api/admin";

/** The tenant's agents, each linking to its prompt history, the Apply/Undo controls
 * and the call cap — the entry point those screens need, since a prompt belongs to an
 * agent, not to the tenant.
 *
 * It used to `return null` on anything but a populated list, so a failed read and a
 * client with no agents were the same blank space — and "this client has no agents" is
 * the more alarming of the two to be wrong about. */
export function AgentsPanel({ tenantId, slug }: { tenantId: string; slug: string }) {
  const agents = useTenantAgents(slug);
  return (
    <Card title="Agents" bodyClassName="px-4 pb-4 pt-2 sm:px-6">
      {agents.error ? (
        <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />
      ) : agents.isLoading || !agents.data ? (
        <Skeleton rows={2} />
      ) : agents.data.length === 0 ? (
        <EmptyState
          title="No agents yet"
          hint="Nothing answers or dials for this client until one is built."
        />
      ) : (
        <ul className="divide-y divide-line">
          {agents.data.map((agent) => (
            <li key={agent.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
              <span className="font-medium text-ink">{agent.name}</span>
              <span className="rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand-strong">
                {agent.status}
              </span>
              <span className="text-xs text-ink-muted">{agent.direction}</span>
              <Link
                href={`/admin/tenants/${tenantId}/agents/${agent.id}/prompt`}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-0.5 text-xs font-medium text-ink hover:bg-black/5 dark:hover:bg-white/5"
              >
                <ScrollText className="h-3.5 w-3.5" />
                Prompt &amp; publishing
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
