"use client";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { Card, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
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
  statusOf,
  actionError,
  onRelease,
  onDrop,
}: {
  held: { data?: HeldLeadsData; isLoading: boolean; error: unknown };
  holding: boolean;
  canWrite: boolean;
  /** One row's state for one of its two actions, from the screen's `useActionFeedback`. */
  statusOf: (id: string, action: "release" | "drop") => FeedbackStatus;
  actionError: unknown;
  onRelease: (id: string) => void;
  onDrop: (id: string) => void;
}) {
  const items = held.data?.items ?? [];
  // A failed read still shows: leads held before the plan changed would otherwise vanish.
  if (!holding && !held.error && items.length === 0) return null;
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
                <ActionButton
                  variant="primary-sm"
                  status={statusOf(item.id, "release")}
                  successLabel="Booked"
                  disabled={!canWrite || statusOf(item.id, "drop") === "pending"}
                  onClick={() => onRelease(item.id)}
                >
                  Call now
                </ActionButton>
                <ActionButton
                  variant="secondary-sm"
                  status={statusOf(item.id, "drop")}
                  disabled={!canWrite || statusOf(item.id, "release") === "pending"}
                  onClick={() => onDrop(item.id)}
                >
                  Don&apos;t call
                </ActionButton>
              </div>
            </li>
          ))}
        </ul>
      )}
      {actionError != null && <ProblemNotice error={actionError} />}
    </Card>
  );
}
