"use client";

import { Card, ProblemNotice, SECONDARY_BUTTON_SM, PRIMARY_BUTTON_SM, Skeleton, formatIST } from "@/components/ui";
import type { HeldLeads as HeldLeadsData } from "@/lib/api/leadCalling";

import { sourceLabel } from "./sourceKinds";

/**
 * Leads that arrived after hours on a "Hold them for me" plan (D-716). "Call now" books the
 * call for now (or the plan's next opening); the compliance check runs when it is placed.
 * "Don't call" takes the lead off this list and keeps it in Leads.
 */
export function HeldLeads({
  held,
  holding,
  canWrite,
  busyId,
  actionError,
  onRelease,
  onDrop,
}: {
  held: { data?: HeldLeadsData; isLoading: boolean; error: unknown };
  holding: boolean;
  canWrite: boolean;
  busyId: string | null;
  actionError: unknown;
  onRelease: (id: string) => void;
  onDrop: (id: string) => void;
}) {
  const items = held.data?.items ?? [];
  if (!holding && items.length === 0) return null;
  return (
    <Card title="Waiting for you" info="Leads held after hours. Nothing is called until you choose.">
      {held.isLoading ? (
        <Skeleton rows={2} />
      ) : held.error ? (
        <ProblemNotice error={held.error} />
      ) : items.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No leads waiting. Leads that arrive after hours will appear here.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{item.lead_name ?? "No name given"}</p>
                <p className="text-xs text-ink-muted">
                  {sourceLabel(item.source)} · arrived {formatIST(item.held_at)}
                  {item.agent_name ? ` · ${item.agent_name} will call` : ""}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={PRIMARY_BUTTON_SM}
                  disabled={!canWrite || busyId === item.id}
                  onClick={() => onRelease(item.id)}
                >
                  Call now
                </button>
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={!canWrite || busyId === item.id}
                  onClick={() => onDrop(item.id)}
                >
                  Don&apos;t call
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {actionError != null && <ProblemNotice error={actionError} />}
    </Card>
  );
}
