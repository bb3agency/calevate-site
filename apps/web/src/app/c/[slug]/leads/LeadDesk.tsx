"use client";

import Link from "next/link";
import { useState, type DragEvent } from "react";
import { LoaderCircle } from "lucide-react";

import { FIELD_INLINE, ProblemNotice, ScrollRegion, Skeleton, StageDot, formatCount, formatPhone } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import type { Session } from "@/lib/api/client";
import { useLeadsUnderLens, type Lead, type LeadLens, type LeadStatus, type RowEditing } from "@/lib/api/leads";
import { useLeadNouns } from "@/lib/businessCapabilities";
import { outcomeWords } from "@/lib/callReview";
import { leadNextStep } from "@/lib/leadLabels";
import { useMediaQuery } from "@/lib/useMediaQuery";

import { RowFailure } from "./RowFailure";
import { STATUSES, StatusSelect, stageLabel } from "./StatusSelect";
import { cellValue } from "./leadsTable";

/** How many people each stage lists before "See all in the table". */
export const DESK_COLUMN_SIZE = 20;

/** Below `sm` the desk is one stage at a time, picked above its cards. */
const PHONE = "(max-width: 639px)";

/** The drag payload: a lead id, under our own type so a dropped file or link is ignored. */
const DRAG_TYPE = "application/x-calevate-lead";

export type DeskProps = {
  session: Session;
  /** The table's lens WITHOUT its stage: on the desk the stages are the columns. */
  lens: LeadLens;
  /** The same per-row status edit the table uses, so a move is the table's own write. */
  rows: RowEditing;
  readOnly: boolean;
  readOnlyReason?: string | null;
  /** The captured field the business treats as "what they want", and its label. */
  needKey: string;
  needLabel: string | null;
  hrefFor: (lead: Lead) => string;
  /** Opens the table on one stage. */
  onOpenStage: (stage: LeadStatus) => void;
};

/**
 * THE DESK (W7.1): the people in each stage, stage by stage, in pipeline order.
 *
 * Each column is its own read of the table's lens with that stage, so a column holds the
 * server's newest matches and its count is the server's, never a slice of one page. A card
 * moves with its "Stage" select, the same control and the same write as the table's row,
 * which keeps it usable by keyboard and screen reader; dragging a card onto another column
 * is a mouse shortcut for the same write, never the only way. On a phone, one stage shows
 * at a time under a stage picker, because six columns do not fit 375px.
 */
export function LeadDesk(props: DeskProps) {
  const phone = useMediaQuery(PHONE);
  const [stage, setStage] = useState<LeadStatus>("new");
  const nouns = useLeadNouns();

  if (phone) {
    return (
      <div className="space-y-3">
        <label className="flex items-center gap-2 text-meta text-ink-muted">
          Stage
          <select
            value={stage}
            onChange={(event) => setStage(event.target.value as LeadStatus)}
            className={FIELD_INLINE}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {stageLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <DeskColumn {...props} stage={stage} />
      </div>
    );
  }

  return (
    <ScrollRegion label={`${nouns.Leads} by stage`} className="-mx-1 overscroll-x-contain px-1 pb-2">
      <div className="grid min-w-max auto-cols-[minmax(15rem,1fr)] grid-flow-col gap-3">
        {STATUSES.map((s) => (
          <DeskColumn key={s} {...props} stage={s} />
        ))}
      </div>
    </ScrollRegion>
  );
}

function DeskColumn({
  session,
  lens,
  rows,
  readOnly,
  readOnlyReason,
  needKey,
  needLabel,
  hrefFor,
  onOpenStage,
  stage,
}: DeskProps & { stage: LeadStatus }) {
  const column = useLeadsUnderLens(session, { ...lens, status: stage }, { limit: DESK_COLUMN_SIZE });
  const [over, setOver] = useState(false);
  // Rows of another stage held over while this one loads are not this stage's rows.
  const answer = column.isPlaceholderData ? undefined : column.data;
  const total = answer?.total;
  const headingId = `desk-${stage}`;

  const onDrop = (event: DragEvent<HTMLElement>) => {
    setOver(false);
    const leadId = event.dataTransfer.getData(DRAG_TYPE);
    if (!leadId || readOnly) return;
    event.preventDefault();
    rows.edit(leadId, { status: stage });
  };

  return (
    <section
      aria-labelledby={headingId}
      onDragOver={(event) => {
        if (readOnly || !event.dataTransfer.types.includes(DRAG_TYPE)) return;
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`flex min-w-0 flex-col rounded-lg border bg-surface ${over ? "border-action" : "border-line"}`}
    >
      <header className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 id={headingId} className="flex min-w-0 items-center gap-2 text-body font-semibold text-ink">
          <StageDot stage={stage} />
          {stageLabel(stage)}
        </h3>
        {total !== undefined && <span className="text-meta tabular-nums text-ink-muted">{formatCount(total)}</span>}
      </header>
      <div className="min-h-24 flex-1 space-y-2 p-2">
        {column.error ? (
          <ProblemNotice error={column.error} onRetry={() => void column.refetch()} />
        ) : !answer ? (
          <Skeleton rows={2} label={`Loading ${stageLabel(stage)}`} />
        ) : answer.items.length === 0 ? (
          <p className="px-1 py-3 text-meta text-ink-faint">Nobody here.</p>
        ) : (
          <ul className="space-y-2">
            {answer.items.map((lead) => (
              <DeskCard
                key={lead.id}
                lead={lead}
                rows={rows}
                readOnly={readOnly}
                readOnlyReason={readOnlyReason}
                needKey={needKey}
                needLabel={needLabel}
                href={hrefFor(lead)}
              />
            ))}
          </ul>
        )}
        {answer && total !== undefined && total > answer.items.length && answer.items.length > 0 && (
          <button type="button" className={`${TEXT_ACTION} mx-1`} onClick={() => onOpenStage(stage)}>
            See all {formatCount(total)} in the table
          </button>
        )}
      </div>
    </section>
  );
}

function DeskCard({
  lead,
  rows,
  readOnly,
  readOnlyReason,
  needKey,
  needLabel,
  href,
}: {
  lead: Lead;
  rows: RowEditing;
  readOnly: boolean;
  readOnlyReason?: string | null;
  needKey: string;
  needLabel: string | null;
  href: string;
}) {
  const name = lead.name ?? formatPhone(lead.phone_e164);
  const outcome = lead.last_call_id
    ? outcomeWords({ outcome_tag: lead.last_call_outcome ?? null, business_outcome_label: lead.last_call_business_outcome_label })
    : null;
  const need = cellValue(lead, needKey);
  const next = leadNextStep(lead);
  const saving = rows.pendingFor(lead.id);
  return (
    <li
      draggable={!readOnly && !saving}
      onDragStart={(event) => {
        event.dataTransfer.setData(DRAG_TYPE, lead.id);
        event.dataTransfer.effectAllowed = "move";
      }}
      className={`rounded-md border border-line bg-surface px-3 py-2 shadow-[0_1px_2px_rgba(28,25,23,0.06)] ${saving ? "opacity-60" : ""} ${readOnly ? "" : "cursor-grab active:cursor-grabbing"}`}
    >
      <Link
        href={href}
        className="block rounded-sm font-medium text-ink [overflow-wrap:anywhere] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        {name}
      </Link>
      <dl className="mt-1 space-y-0.5 text-meta">
        {outcome && (
          <div className="flex gap-1">
            <dt className="sr-only">Last call</dt>
            <dd className="text-ink-muted">{outcome}</dd>
          </div>
        )}
        {need !== "—" && (
          <div className="flex min-w-0 gap-1">
            <dt className="shrink-0 text-ink-faint">{needLabel ?? "Wants"}:</dt>
            <dd className="min-w-0 truncate text-ink" title={need}>
              {need}
            </dd>
          </div>
        )}
        {next && (
          <div className="flex gap-1">
            <dt className="sr-only">Next</dt>
            <dd className={lead.next_callback_at ? "text-ink" : "text-ink-muted"}>{next}</dd>
          </div>
        )}
      </dl>
      <div className="mt-2 flex items-center gap-2">
        <StatusSelect
          value={lead.status}
          label={`Move ${name} to another stage`}
          disabled={saving || readOnly}
          onChange={(next) => rows.edit(lead.id, { status: next })}
          className={`${FIELD_INLINE} py-1 text-meta`}
        />
        {saving && (
          <span className="inline-flex items-center gap-1 text-meta text-ink-faint">
            <LoaderCircle aria-hidden className="size-3.5 motion-safe:animate-spin" />
            Moving…
          </span>
        )}
      </div>
      {readOnly && readOnlyReason ? <p className="sr-only">{readOnlyReason}</p> : null}
      <RowFailure error={rows.errorFor(lead.id)} />
    </li>
  );
}
