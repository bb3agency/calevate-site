"use client";

import { FlaskConical } from "lucide-react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { RowMenu, type RowMenuItem } from "@/components/console/rowMenu";
import { CopyButton } from "@/components/interior/copy-button";
import {
  MonoValue,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
  formatIST,
} from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { API_BASE } from "@/lib/api/client";
import type { IngestActivity, LeadSource, useLeadSources } from "@/lib/api/leadSources";

import { META_SOURCE, sourceLabel } from "./sourceKinds";

/** One row's name, everywhere it is spoken: the kind plus the last eight characters of its id (uuid7 ids share their leading, time-ordered half). */
export function rowName(source: LeadSource): string {
  return `${sourceLabel(source.source)} · ${source.id.slice(-8)}`;
}

/**
 * EVERY PLACE LEADS COME FROM, one row each, with what it is doing and what can be done.
 *
 * The switch is on the row because turning a source off is frequent and cheap to undo.
 * Secret rotation, the address and Meta's setup sit in the row's menu because they are
 * set once. "Send test lead" is the row's one visible action: it is how an owner checks a
 * form is wired before trusting it with ad spend.
 *
 * §52: loading is a skeleton, a failed or paused read is a refusal and NO list. "No lead
 * sources yet" under a failed request would have a client create a second source for a
 * form already wired up.
 */
export function SourcesList({
  sources,
  agents,
  activity,
  canWrite,
  busy,
  onToggle,
  onTest,
  onRotate,
  onMeta,
}: {
  sources: ReturnType<typeof useLeadSources>;
  agents: Agent[] | undefined;
  activity: IngestActivity | undefined;
  canWrite: boolean;
  busy: boolean;
  onToggle: (source: LeadSource) => void;
  onTest: (source: LeadSource) => void;
  onRotate: (source: LeadSource) => void;
  onMeta: (source: LeadSource) => void;
}) {
  if (sources.isLoading) return <Skeleton rows={2} />;
  const items = sources.data?.items;
  if (!items) {
    return (
      <ProblemNotice
        error={sources.error ?? new Error("Your lead sources did not load.")}
        onRetry={() => sources.refetch()}
      />
    );
  }
  if (items.length === 0) {
    return (
      <EmptyState message="No lead sources yet. Add one, then point your form at the address we give you." />
    );
  }

  const agentName = (id: string | null) =>
    id === null
      ? "Saves leads, doesn't call"
      : (agents?.find((agent) => agent.id === id)?.name ?? "An agent not in your list");
  // Recoverable Meta leads per source, from the delivery log's own server-derived flag.
  const waiting = (id: string) =>
    activity?.items.filter((item) => item.lead_source_id === id && item.recoverable).length ?? 0;

  const columns: DataColumn<LeadSource>[] = [
    {
      id: "source",
      header: "Source",
      sort: { value: (row) => row.source },
      cell: (row) => (
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink">{sourceLabel(row.source)}</p>
          <p className="text-xs text-ink-faint">
            <MonoValue>{row.id.slice(-8)}</MonoValue>
            {/* The fingerprint, never the secret: enough to tell which key we hold. */}
            {" · "}key ···{row.secret_fingerprint}
          </p>
          {row.previous_secret_expires_at && (
            <p className="mt-0.5 text-xs text-warn">
              Your previous secret still works until {formatIST(row.previous_secret_expires_at)}.
            </p>
          )}
          {row.source === META_SOURCE && waiting(row.id) > 0 && (
            <p className="mt-0.5 text-xs text-warn">
              {waiting(row.id)} unread {waiting(row.id) === 1 ? "lead" : "leads"} to recover
            </p>
          )}
        </div>
      ),
    },
    {
      id: "agent",
      header: "Answered by",
      hideBelow: "md",
      cell: (row) => <span className="text-sm text-ink-muted">{agentName(row.agent_id)}</span>,
    },
    {
      id: "active",
      header: "Receiving",
      flash: (row) => String(row.active),
      cell: (row) => (
        <ToggleSwitch
          label={
            <span className="text-xs text-ink-muted">
              {row.active ? "On" : "Off"}
              <span className="sr-only"> — {rowName(row)}</span>
            </span>
          }
          checked={row.active}
          disabled={!canWrite || busy}
          onChange={() => onToggle(row)}
        />
      ),
    },
    {
      id: "actions",
      header: "Actions",
      align: "right",
      cell: (row) => {
        const menu: RowMenuItem[] = [
          ...(row.source === META_SOURCE
            ? [{ id: "meta", label: "Meta setup and recovery", onSelect: () => onMeta(row) }]
            : []),
          {
            id: "rotate",
            label: "Issue a new secret",
            onSelect: () => onRotate(row),
            disabled: !canWrite,
          },
        ];
        return (
          <div className="flex items-center justify-end gap-1">
            <button
              type="button"
              disabled={!canWrite}
              onClick={() => onTest(row)}
              aria-label={`Send test lead to ${rowName(row)}`}
              className={SECONDARY_BUTTON_SM}
            >
              <FlaskConical aria-hidden className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Send test lead</span>
            </button>
            <CopyButton
              value={`${API_BASE}${row.ingest_path}`}
              label={`Copy the address for ${rowName(row)}`}
            />
            <RowMenu label={rowName(row)} items={menu} />
          </div>
        );
      },
    },
  ];

  return <DataTable label="Your lead sources" rows={items} columns={columns} getRowId={(row) => row.id} />;
}
