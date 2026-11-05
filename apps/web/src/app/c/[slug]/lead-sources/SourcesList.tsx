"use client";

import { FlaskConical, Webhook } from "lucide-react";
import Link from "next/link";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { IconTile } from "@/components/console/iconTile";
import { RowMenu, type RowMenuItem } from "@/components/arc/menu";
import { CopyButton } from "@/components/interior/copy-button";
import {
  MonoValue,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
  formatIST,
} from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { API_BASE } from "@/lib/api/client";
import type { IngestActivity, LeadSource, useLeadSources } from "@/lib/api/leadSources";
import { useClientRealm } from "@/lib/api/session";

import { META_SOURCE, fieldsMenuLabel, isPushSource, sourceLabel, sourceLogo } from "./sourceKinds";

/** One row's name, everywhere it is spoken: the kind plus the last eight characters of its id (uuid7 ids share their leading, time-ordered half). */
export function rowName(source: LeadSource): string {
  return `${sourceLabel(source.source)} · ${source.id.slice(-8)}`;
}

/**
 * WHO CALLS ONE SOURCE'S NEW LEADS, read from the server (`LeadSourceOut.caller`). The
 * "Call new leads" Follow-up is the one place that chooses the agent, so the row only says
 * who it is and links there.
 */
function CalledBy({ source }: { source: LeadSource }) {
  const { session, href } = useClientRealm();
  const caller = source.caller;
  const target = caller.follow_up_id
    ? `/c/${session.orgSlug}/follow-ups/${caller.follow_up_id}`
    : `/c/${session.orgSlug}/follow-ups`;
  const [line, action] = !caller.called
    ? [source.active ? "Leads arrive but nobody calls them" : "Saved, not called", "Turn on"]
    : caller.agent_name
      ? [caller.agent_name, "Change"]
      : [source.active ? "Leads arrive but nobody calls them" : "Nobody yet", "Choose an agent"];
  return (
    <div className="min-w-0">
      <p className={`text-body [overflow-wrap:anywhere] ${caller.called && caller.agent_name ? "text-ink" : "text-warn"}`}>
        {line}
      </p>
      <Link
        href={href(target)}
        className={TEXT_ACTION}
        aria-label={`${action}: who calls leads from ${rowName(source)}`}
      >
        {action}
      </Link>
    </div>
  );
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
  activity,
  canWrite,
  busy,
  onToggle,
  onTest,
  onRotate,
  onFields,
  onMeta,
  onAdd,
}: {
  sources: ReturnType<typeof useLeadSources>;
  activity: IngestActivity | undefined;
  canWrite: boolean;
  busy: boolean;
  onToggle: (source: LeadSource) => void;
  onTest: (source: LeadSource) => void;
  onRotate: (source: LeadSource) => void;
  onFields: (source: LeadSource) => void;
  onMeta: (source: LeadSource) => void;
  /** Absent for a viewer who may not add one. */
  onAdd?: () => void;
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
      <EmptyState
        illustration={<EmptySketch kind="deliveries" />}
        message="No lead sources yet."
        action={
          onAdd ? (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={onAdd}>
              Add your first source
            </button>
          ) : undefined
        }
      />
    );
  }

  // Recoverable Meta leads per source, from the delivery log's own server-derived flag.
  const waiting = (id: string) =>
    activity?.items.filter((item) => item.lead_source_id === id && item.recoverable).length ?? 0;

  const columns: DataColumn<LeadSource>[] = [
    {
      id: "source",
      header: "Source",
      sort: { value: (row) => row.source },
      cell: (row) => (
        <div className="flex min-w-0 items-start gap-3">
        <IconTile service={sourceLogo(row.source)} icon={Webhook} />
        <div className="min-w-0">
          <p className="text-body font-medium text-ink">{sourceLabel(row.source)}</p>
          {/* L3-13: the source id and key fingerprint are for whoever wires the form or
              the CRM, so they wait behind "Details" rather than sit in every row. */}
          <details className="text-meta text-ink-faint">
            <summary className="w-fit cursor-pointer select-none hover:text-ink-muted">Details</summary>
            <p>
              Source <MonoValue>{row.id.slice(-8)}</MonoValue>
              {/* The fingerprint, never the secret: enough to tell which key we hold. */}
              {" · "}key ···{row.secret_fingerprint}
            </p>
          </details>
          {row.previous_secret_expires_at && (
            <p className="mt-0.5 text-meta text-warn">
              Old secret works until {formatIST(row.previous_secret_expires_at)}
            </p>
          )}
          {row.source === META_SOURCE && waiting(row.id) > 0 && (
            <p className="mt-0.5 text-meta text-warn">
              {waiting(row.id)} unread {waiting(row.id) === 1 ? "lead" : "leads"} to recover
            </p>
          )}
          {/* The "Called by" column is hidden on a phone; the same answer sits here. */}
          <div className="mt-1 md:hidden">
            <CalledBy source={row} />
          </div>
        </div>
        </div>
      ),
    },
    {
      id: "agent",
      header: "Called by",
      hideBelow: "md",
      cell: (row) => <CalledBy source={row} />,
    },
    {
      id: "active",
      header: "Receiving",
      flash: (row) => String(row.active),
      cell: (row) => (
        <ToggleSwitch
          label={
            <span className="text-meta text-ink-muted">
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
            id: "fields",
            label: fieldsMenuLabel(row.source),
            onSelect: () => onFields(row),
            disabled: !canWrite,
          },
          {
            id: "rotate",
            // A pushed sender's secret IS its address, so a new one is a new address to paste.
            label: isPushSource(row.source) ? "Issue a new address" : "Issue a new secret",
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
            {/* A pushed sender's address carries its secret and is shown once; the bare
                path would be refused, so there is nothing to copy here. */}
            {isPushSource(row.source) ? null : (
              <CopyButton
                value={`${API_BASE}${row.ingest_path}`}
                label={`Copy the address for ${rowName(row)}`}
              />
            )}
            <RowMenu label={rowName(row)} items={menu} />
          </div>
        );
      },
    },
  ];

  return <DataTable label="Your lead sources" rows={items} columns={columns} getRowId={(row) => row.id} />;
}
